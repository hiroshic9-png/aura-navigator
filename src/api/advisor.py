"""
AURA MVP — AIアドバイザーAPI

対話型アドバイザーのRESTエンドポイント。
セッション管理、コンテキスト自動構築、法的制約チェックを統合。
"""

import json
import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from starlette.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.advisor.engine import (
    AdvisorContext,
    ConversationSession,
    LegalBoundary,
    LEGAL_DISCLAIMER,
    build_system_prompt,
    check_legal_boundary,
    generate_mock_response,
    get_or_create_session,
    match_concerns,
)
from src.advisor.llm_client import call_llm, is_llm_available, stream_llm
from src.db.database import ProcedureTable, ClinicTable, get_db

logger = logging.getLogger(__name__)

router = APIRouter()


class ChatRequest(BaseModel):
    """チャットリクエスト"""
    message: str = Field(..., min_length=1, max_length=2000, description="ユーザーメッセージ")
    session_id: str | None = Field(None, description="セッションID（継続会話用）")

    # オプション: ユーザーの状況
    budget_range: str | None = Field(None, description="予算帯（例: '10万以内'）")
    downtime_available: str | None = Field(None, description="DT確保可能期間（例: '3日'）")
    age_range: str | None = Field(None, description="年代（例: '20代後半'）")
    clinic_id: str | None = Field(None, description="対象クリニックID")


class ChatResponse(BaseModel):
    """チャットレスポンス"""
    session_id: str
    message: str
    legal_boundary: str
    matched_procedures: list[str] = Field(default_factory=list)
    matched_clinics: list[dict] = Field(default_factory=list)  # 推薦されたクリニック
    response_source: str = "mock"  # "claude" or "mock"
    model: str | None = None  # 使用モデル（claude時のみ）


@router.post("/chat")
async def chat(
    req: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    """
    アドバイザーとチャット

    フロー:
    1. 法的制約チェック
    2. 推薦リクエスト判定 → インテーク → 推薦エンジン
    3. 通常の相談 → 施術マッチング → 回答生成
    """
    from src.advisor.intake import (
        IntakeSession, IntakeState,
        extract_conditions_from_message,
        assess_intake_state,
        generate_followup_question,
    )
    from src.advisor.recommendation_engine import (
        UserConditions, recommend_clinics, build_recommendation_context,
    )

    # セッション取得・作成
    session_id = req.session_id or str(uuid4())
    session = get_or_create_session(session_id)

    # インテークセッション管理（セッションに紐付け）
    if not hasattr(session, '_intake'):
        session._intake = IntakeSession()
    intake = session._intake

    # 1. 法的制約チェック
    boundary, redirect_msg = check_legal_boundary(req.message)
    if boundary == LegalBoundary.PROHIBITED:
        session.messages.append({"role": "user", "content": req.message})
        session.messages.append({"role": "assistant", "content": redirect_msg})
        return ChatResponse(
            session_id=session_id,
            message=redirect_msg,
            legal_boundary=boundary.value,
        )

    # 2. 推薦モード判定
    recommendation_context = ""
    matched_clinics_response = []

    if boundary == LegalBoundary.RECOMMENDATION or intake.state in (
        IntakeState.CONCERN_IDENTIFIED, IntakeState.READY
    ):
        # メッセージから条件を抽出し蓄積
        intake.conditions = extract_conditions_from_message(
            req.message, intake.conditions
        )

        # 過去の会話からも条件を蓄積
        for prev_msg in session.messages:
            if prev_msg["role"] == "user":
                intake.conditions = extract_conditions_from_message(
                    prev_msg["content"], intake.conditions
                )

        # リクエストのオプション条件を反映
        if req.budget_range:
            from src.advisor.recommendation_engine import parse_budget
            budget = parse_budget(req.budget_range)
            if budget:
                intake.conditions.budget = budget
        if req.downtime_available:
            from src.advisor.recommendation_engine import parse_downtime_days
            dt = parse_downtime_days(req.downtime_available)
            if dt is not None:
                intake.conditions.downtime_days = dt
        if req.age_range:
            intake.conditions.age_range = req.age_range

        # 条件の充足度を評価
        state, missing = assess_intake_state(intake.conditions)
        intake.state = state
        intake.missing_fields = missing

        if state == IntakeState.INITIAL:
            # 悩みが特定できていない → 通常モードへフォールバック
            boundary = LegalBoundary.ALLOWED

        elif state == IntakeState.CONCERN_IDENTIFIED and intake.asked_count < 2:
            # 悩みは特定できたが、追加条件が不足 → ヒアリング
            followup = generate_followup_question(
                intake.conditions, missing, intake.asked_count
            )
            if followup:
                intake.asked_count += 1
                session.messages.append({"role": "user", "content": req.message})
                session.messages.append({"role": "assistant", "content": followup})
                return ChatResponse(
                    session_id=session_id,
                    message=followup,
                    legal_boundary=LegalBoundary.RECOMMENDATION.value,
                    response_source="intake",
                )

        # READY or ヒアリング済み → 推薦エンジン実行
        if state == IntakeState.READY or intake.asked_count >= 2:
            rec_result = await recommend_clinics(db, intake.conditions, max_results=5)
            recommendation_context = build_recommendation_context(rec_result)
            intake.state = IntakeState.COMPLETED

            # レスポンス用のクリニック候補
            for match in rec_result.clinic_matches[:5]:
                matched_clinics_response.append({
                    "clinic_id": match.clinic_id,
                    "name": match.name,
                    "city": match.city,
                    "google_rating": match.google_rating,
                    "google_review_count": match.google_review_count,
                    "match_score": match.match_score,
                    "match_reasons": match.match_reasons,
                    "procedures": [p.name for p in match.procedures],
                })

    # 3. 施術マッチング（通常モード + 推薦モード共通）
    concerns = match_concerns(req.message)
    for prev_msg in session.messages:
        if prev_msg["role"] == "user":
            concerns.extend(match_concerns(prev_msg["content"]))
    concerns = list(set(concerns))

    matched_procs = []
    if concerns:
        result = await db.execute(select(ProcedureTable))
        all_procs = result.scalars().all()
        for proc in all_procs:
            try:
                proc_concerns = json.loads(proc.matches_concern or "[]")
            except (json.JSONDecodeError, TypeError):
                proc_concerns = []

            if any(c in proc_concerns for c in concerns):
                pricing = {}
                try:
                    adv = json.loads(proc.advertised_price or "{}")
                    real = json.loads(proc.real_price or "{}")
                    hidden = json.loads(proc.hidden_costs or "[]")
                    pricing = {
                        "advertised": adv,
                        "real": real,
                        "gap_warning": proc.price_gap_note or "",
                        "hidden_costs": hidden,
                    }
                except (json.JSONDecodeError, TypeError):
                    pass

                dt = {
                    "official": proc.downtime_official or "",
                    "real": proc.downtime_real or "",
                }

                risks = []
                try:
                    risks = json.loads(proc.risks or "[]")
                except (json.JSONDecodeError, TypeError):
                    pass

                questions = []
                try:
                    questions = json.loads(proc.counseling_questions or "[]")
                except (json.JSONDecodeError, TypeError):
                    pass

                matched_procs.append({
                    "id": proc.id,
                    "name": proc.name,
                    "category": proc.category,
                    "category_label": proc.category_label or "",
                    "invasiveness": proc.invasiveness or "",
                    "duration": proc.duration or "",
                    "duration_type": proc.duration_type or "",
                    "pricing": pricing,
                    "downtime": dt,
                    "risks": risks,
                    "counseling_questions": questions,
                })

    # 4. クリニックデータ取得（個別指定時）
    clinic_data = None
    if req.clinic_id:
        result = await db.execute(
            select(ClinicTable).where(ClinicTable.id == req.clinic_id)
        )
        clinic = result.scalar_one_or_none()
        if clinic:
            clinic_data = {
                "name": clinic.name,
                "address": clinic.address,
                "medical_departments": clinic.medical_departments,
                "website": clinic.website,
                "google_rating": clinic.google_rating,
            }

    # 5. コンテキスト構築
    ctx = AdvisorContext(
        concern=req.message,
        budget_range=req.budget_range or session.context.budget_range,
        downtime_available=req.downtime_available or session.context.downtime_available,
        age_range=req.age_range or session.context.age_range,
        matched_procedures=matched_procs,
        target_clinic=clinic_data,
        conversation_history=session.messages[-10:],
        legal_boundary=boundary,
    )
    session.context = ctx

    # 6. レスポンス生成
    system_prompt = build_system_prompt(ctx, recommendation_context)

    llm_result = await call_llm(
        system_prompt=system_prompt,
        user_message=req.message,
        conversation_history=session.messages[-8:],
    )

    if llm_result["source"] == "claude" and llm_result["content"]:
        response_text = llm_result["content"]
    elif llm_result["source"] == "error":
        response_text = generate_mock_response(ctx, req.message)
    else:
        # モック時で推薦コンテキストがある場合は専用モックを生成
        if recommendation_context:
            response_text = _generate_recommendation_mock(
                intake.conditions if hasattr(session, '_intake') else None,
                matched_clinics_response,
                matched_procs,
            )
        else:
            response_text = generate_mock_response(ctx, req.message)

    # 注意喚起の追加（CAUTION時）
    if boundary == LegalBoundary.CAUTION:
        response_text = (
            "*以下は一般的な情報の整理です。個別の医学的判断は担当医にご相談ください。*\n\n"
            + response_text
        )

    # 会話履歴に追加
    session.messages.append({"role": "user", "content": req.message})
    session.messages.append({"role": "assistant", "content": response_text})

    return ChatResponse(
        session_id=session_id,
        message=response_text,
        legal_boundary=boundary.value,
        matched_procedures=[p["name"] for p in matched_procs],
        matched_clinics=matched_clinics_response,
        response_source=llm_result["source"] if not recommendation_context else "recommendation",
        model=llm_result.get("model"),
    )


# ==========================================
# ストリーミングチャットエンドポイント
# ==========================================


async def _prepare_chat_context(
    req: ChatRequest,
    db: AsyncSession,
) -> dict:
    """
    チャットのコンテキスト準備（/chat と /chat/stream で共有するDRYロジック）

    法的制約チェック、インテーク、施術マッチング、推薦エンジン、
    コンテキスト構築までを一括で行い、結果を辞書で返す。

    Returns:
        {
            "session": ConversationSession,
            "session_id": str,
            "boundary": LegalBoundary,
            "redirect_msg": str | None,
            "matched_procs": list[dict],
            "matched_clinics_response": list[dict],
            "recommendation_context": str,
            "system_prompt": str,
            "ctx": AdvisorContext,
            "intake": IntakeSession | None,
            "followup": str | None,   # ヒアリング中のフォローアップ質問
        }
    """
    from src.advisor.intake import (
        IntakeSession, IntakeState,
        extract_conditions_from_message,
        assess_intake_state,
        generate_followup_question,
    )
    from src.advisor.recommendation_engine import (
        UserConditions, recommend_clinics, build_recommendation_context,
    )

    # セッション取得・作成
    session_id = req.session_id or str(uuid4())
    session = get_or_create_session(session_id)

    # インテークセッション管理
    if not hasattr(session, '_intake'):
        session._intake = IntakeSession()
    intake = session._intake

    # 1. 法的制約チェック
    boundary, redirect_msg = check_legal_boundary(req.message)
    if boundary == LegalBoundary.PROHIBITED:
        return {
            "session": session,
            "session_id": session_id,
            "boundary": boundary,
            "redirect_msg": redirect_msg,
            "matched_procs": [],
            "matched_clinics_response": [],
            "recommendation_context": "",
            "system_prompt": "",
            "ctx": None,
            "intake": intake,
            "followup": None,
        }

    # 2. 推薦モード判定
    recommendation_context = ""
    matched_clinics_response = []

    if boundary == LegalBoundary.RECOMMENDATION or intake.state in (
        IntakeState.CONCERN_IDENTIFIED, IntakeState.READY
    ):
        intake.conditions = extract_conditions_from_message(
            req.message, intake.conditions
        )
        for prev_msg in session.messages:
            if prev_msg["role"] == "user":
                intake.conditions = extract_conditions_from_message(
                    prev_msg["content"], intake.conditions
                )

        if req.budget_range:
            from src.advisor.recommendation_engine import parse_budget
            budget = parse_budget(req.budget_range)
            if budget:
                intake.conditions.budget = budget
        if req.downtime_available:
            from src.advisor.recommendation_engine import parse_downtime_days
            dt = parse_downtime_days(req.downtime_available)
            if dt is not None:
                intake.conditions.downtime_days = dt
        if req.age_range:
            intake.conditions.age_range = req.age_range

        state, missing = assess_intake_state(intake.conditions)
        intake.state = state
        intake.missing_fields = missing

        if state == IntakeState.INITIAL:
            boundary = LegalBoundary.ALLOWED

        elif state == IntakeState.CONCERN_IDENTIFIED and intake.asked_count < 2:
            followup = generate_followup_question(
                intake.conditions, missing, intake.asked_count
            )
            if followup:
                intake.asked_count += 1
                return {
                    "session": session,
                    "session_id": session_id,
                    "boundary": LegalBoundary.RECOMMENDATION,
                    "redirect_msg": None,
                    "matched_procs": [],
                    "matched_clinics_response": [],
                    "recommendation_context": "",
                    "system_prompt": "",
                    "ctx": None,
                    "intake": intake,
                    "followup": followup,
                }

        if state == IntakeState.READY or intake.asked_count >= 2:
            rec_result = await recommend_clinics(db, intake.conditions, max_results=5)
            recommendation_context = build_recommendation_context(rec_result)
            intake.state = IntakeState.COMPLETED

            for match in rec_result.clinic_matches[:5]:
                matched_clinics_response.append({
                    "clinic_id": match.clinic_id,
                    "name": match.name,
                    "city": match.city,
                    "google_rating": match.google_rating,
                    "google_review_count": match.google_review_count,
                    "match_score": match.match_score,
                    "match_reasons": match.match_reasons,
                    "procedures": [p.name for p in match.procedures],
                })

    # 3. 施術マッチング
    concerns = match_concerns(req.message)
    for prev_msg in session.messages:
        if prev_msg["role"] == "user":
            concerns.extend(match_concerns(prev_msg["content"]))
    concerns = list(set(concerns))

    matched_procs = []
    if concerns:
        result = await db.execute(select(ProcedureTable))
        all_procs = result.scalars().all()
        for proc in all_procs:
            try:
                proc_concerns = json.loads(proc.matches_concern or "[]")
            except (json.JSONDecodeError, TypeError):
                proc_concerns = []

            if any(c in proc_concerns for c in concerns):
                pricing = {}
                try:
                    adv = json.loads(proc.advertised_price or "{}")
                    real = json.loads(proc.real_price or "{}")
                    hidden = json.loads(proc.hidden_costs or "[]")
                    pricing = {
                        "advertised": adv,
                        "real": real,
                        "gap_warning": proc.price_gap_note or "",
                        "hidden_costs": hidden,
                    }
                except (json.JSONDecodeError, TypeError):
                    pass

                dt = {
                    "official": proc.downtime_official or "",
                    "real": proc.downtime_real or "",
                }

                risks = []
                try:
                    risks = json.loads(proc.risks or "[]")
                except (json.JSONDecodeError, TypeError):
                    pass

                questions = []
                try:
                    questions = json.loads(proc.counseling_questions or "[]")
                except (json.JSONDecodeError, TypeError):
                    pass

                matched_procs.append({
                    "id": proc.id,
                    "name": proc.name,
                    "category": proc.category,
                    "category_label": proc.category_label or "",
                    "invasiveness": proc.invasiveness or "",
                    "duration": proc.duration or "",
                    "duration_type": proc.duration_type or "",
                    "pricing": pricing,
                    "downtime": dt,
                    "risks": risks,
                    "counseling_questions": questions,
                })

    # 4. クリニックデータ取得（個別指定時）
    clinic_data = None
    if req.clinic_id:
        result = await db.execute(
            select(ClinicTable).where(ClinicTable.id == req.clinic_id)
        )
        clinic = result.scalar_one_or_none()
        if clinic:
            clinic_data = {
                "name": clinic.name,
                "address": clinic.address,
                "medical_departments": clinic.medical_departments,
                "website": clinic.website,
                "google_rating": clinic.google_rating,
            }

    # 5. コンテキスト構築
    ctx = AdvisorContext(
        concern=req.message,
        budget_range=req.budget_range or session.context.budget_range,
        downtime_available=req.downtime_available or session.context.downtime_available,
        age_range=req.age_range or session.context.age_range,
        matched_procedures=matched_procs,
        target_clinic=clinic_data,
        conversation_history=session.messages[-10:],
        legal_boundary=boundary,
    )
    session.context = ctx

    # 6. システムプロンプト構築
    system_prompt = build_system_prompt(ctx, recommendation_context)

    return {
        "session": session,
        "session_id": session_id,
        "boundary": boundary,
        "redirect_msg": None,
        "matched_procs": matched_procs,
        "matched_clinics_response": matched_clinics_response,
        "recommendation_context": recommendation_context,
        "system_prompt": system_prompt,
        "ctx": ctx,
        "intake": intake,
        "followup": None,
    }


@router.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    ストリーミングチャットエンドポイント（SSE）

    Server-Sent Events形式でレスポンスをストリーミング送信する。
    法的制約チェック、施術マッチング、推薦エンジンは既存の/chatと同じロジック。

    SSEイベント:
        data: {"type": "start", "session_id": "..."}
        data: {"type": "delta", "content": "テキスト断片"}
        data: {"type": "done", "matched_procedures": [...], "matched_clinics": [...]}
        data: {"type": "error", "message": "..."}
    """
    # コンテキスト準備（DRY — /chatと同じロジック）
    prepared = await _prepare_chat_context(req, db)

    session = prepared["session"]
    session_id = prepared["session_id"]
    boundary = prepared["boundary"]
    matched_procs = prepared["matched_procs"]
    matched_clinics_response = prepared["matched_clinics_response"]
    recommendation_context = prepared["recommendation_context"]
    system_prompt = prepared["system_prompt"]
    ctx = prepared["ctx"]
    intake = prepared["intake"]

    async def event_generator():
        """SSEイベントジェネレーター"""

        # 開始イベント
        yield f"data: {json.dumps({'type': 'start', 'session_id': session_id}, ensure_ascii=False)}\n\n"

        # --- 即座に返すパターン（禁止 / フォローアップ） ---
        if prepared["redirect_msg"]:
            # 法的制約で禁止
            msg = prepared["redirect_msg"]
            session.messages.append({"role": "user", "content": req.message})
            session.messages.append({"role": "assistant", "content": msg})
            yield f"data: {json.dumps({'type': 'delta', 'content': msg}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'matched_procedures': [], 'matched_clinics': []}, ensure_ascii=False)}\n\n"
            return

        if prepared["followup"]:
            # インテーク中のフォローアップ質問
            msg = prepared["followup"]
            session.messages.append({"role": "user", "content": req.message})
            session.messages.append({"role": "assistant", "content": msg})
            yield f"data: {json.dumps({'type': 'delta', 'content': msg}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'matched_procedures': [], 'matched_clinics': []}, ensure_ascii=False)}\n\n"
            return

        # --- モックテキストの事前生成（LLM未接続時用） ---
        mock_text = None
        if not is_llm_available():
            if recommendation_context and intake:
                mock_text = _generate_recommendation_mock(
                    intake.conditions if hasattr(intake, 'conditions') else None,
                    matched_clinics_response,
                    matched_procs,
                )
            elif ctx:
                mock_text = generate_mock_response(ctx, req.message)

        # --- 注意喚起の接頭辞（CAUTION時） ---
        caution_prefix = ""
        if boundary == LegalBoundary.CAUTION:
            caution_prefix = "*以下は一般的な情報の整理です。個別の医学的判断は担当医にご相談ください。*\n\n"

        # --- ストリーミングLLM呼び出し ---
        full_content = ""
        source = "mock"

        # 注意喚起の接頭辞をまず送信
        if caution_prefix:
            yield f"data: {json.dumps({'type': 'delta', 'content': caution_prefix}, ensure_ascii=False)}\n\n"
            full_content += caution_prefix

        try:
            async for event in stream_llm(
                system_prompt=system_prompt,
                user_message=req.message,
                conversation_history=session.messages[-8:],
                mock_text=mock_text,
            ):
                if event["type"] == "delta":
                    full_content += event["content"]
                    yield f"data: {json.dumps({'type': 'delta', 'content': event['content']}, ensure_ascii=False)}\n\n"
                elif event["type"] == "done":
                    source = event.get("source", "mock")
                    # 完了イベント
                    done_data = {
                        "type": "done",
                        "matched_procedures": [p["name"] for p in matched_procs],
                        "matched_clinics": matched_clinics_response,
                        "response_source": source if not recommendation_context else "recommendation",
                        "model": event.get("model"),
                    }
                    yield f"data: {json.dumps(done_data, ensure_ascii=False)}\n\n"
                elif event["type"] == "error":
                    yield f"data: {json.dumps({'type': 'error', 'message': event['message']}, ensure_ascii=False)}\n\n"
                    return

        except Exception as e:
            logger.error(f"ストリーミングエラー: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': f'ストリーミングエラー: {str(e)[:200]}'}, ensure_ascii=False)}\n\n"
            return

        # --- 会話履歴に追加（ストリーミング完了後） ---
        if full_content:
            session.messages.append({"role": "user", "content": req.message})
            session.messages.append({"role": "assistant", "content": full_content})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # nginx対応
        },
    )


def _generate_recommendation_mock(
    conditions,
    clinics: list[dict],
    procedures: list[dict],
) -> str:
    """推薦結果のモックレスポンス生成（Claude API未接続時）"""
    parts = []

    # 条件サマリー
    if conditions:
        cond_parts = []
        if conditions.concern_text:
            cond_parts.append(f"お悩み: {conditions.concern_text}")
        if conditions.area:
            cond_parts.append(f"エリア: {conditions.area}")
        if conditions.budget:
            budget_text = f"{conditions.budget // 10000}万円" if conditions.budget >= 10000 else f"{conditions.budget:,}円"
            cond_parts.append(f"ご予算: {budget_text}")
        if conditions.downtime_days is not None:
            cond_parts.append(f"ダウンタイム: {conditions.downtime_days}日")

        if cond_parts:
            parts.append("あなたの条件を整理しました。\n")
            parts.append(f"**【条件】** {' / '.join(cond_parts)}\n")

    # 関連施術
    if procedures:
        parts.append("\n## 関連する施術\n")
        for proc in procedures[:3]:
            name = proc.get("name", "")
            dt = proc.get("downtime", {}).get("real", "")
            pricing = proc.get("pricing", {})
            adv = pricing.get("advertised", {})
            real = pricing.get("real", {})
            adv_d = adv.get("display", "") if isinstance(adv, dict) else ""
            real_d = real.get("display", "") if isinstance(real, dict) else ""

            parts.append(f"**{name}**\n")
            if adv_d and real_d:
                parts.append(f"- 広告では {adv_d} → 実際は {real_d}\n")
            if dt:
                parts.append(f"- 回復期間: {dt[:60]}\n")
            parts.append("")

    # クリニック候補
    if clinics:
        parts.append("\n## あなたの条件に合致するクリニック\n")
        for i, c in enumerate(clinics[:5], 1):
            name = c.get("name", "")
            rating = c.get("google_rating")
            reviews = c.get("google_review_count")
            reasons = c.get("match_reasons", [])
            procs = c.get("procedures", [])

            rating_text = f"★{rating:.1f}" if rating else ""
            review_text = f"（{reviews}件の口コミ）" if reviews else ""

            parts.append(f"### {i}. {name}\n")
            if rating_text:
                parts.append(f"- {rating_text}{review_text}\n")
            if procs:
                parts.append(f"- 対応施術: {', '.join(procs[:3])}\n")
            if reasons:
                parts.append(f"- 選出理由: {' / '.join(reasons[:3])}\n")
            parts.append("")
    else:
        parts.append("\n現在、クリニックデータの紐付けを拡充中です。")
        parts.append("施術の一般情報と、カウンセリングで聞くべき質問をお伝えします。\n")

    # カウンセリング質問
    if procedures:
        all_questions = []
        for proc in procedures[:2]:
            all_questions.extend(proc.get("counseling_questions", [])[:3])
        if all_questions:
            parts.append("\n## カウンセリングで聞いておくこと\n")
            for i, q in enumerate(all_questions[:5], 1):
                parts.append(f"{i}. {q}\n")

    # 免責事項
    parts.append("\n---")
    parts.append("*この情報は条件に基づくデータの整理であり、特定のクリニックや施術の推薦ではありません。*")
    parts.append("*最終的な判断は、必ず担当の医師とご相談の上で行ってください。*")

    return "\n".join(parts)




@router.get("/session/{session_id}")
async def get_session(session_id: str):
    """セッション情報取得"""
    session = get_or_create_session(session_id)
    return {
        "session_id": session.session_id,
        "created_at": session.created_at,
        "message_count": len(session.messages),
        "messages": session.messages[-20:],
        "context": {
            "concern": session.context.concern,
            "budget_range": session.context.budget_range,
            "matched_procedure_count": len(session.context.matched_procedures),
        },
    }


@router.get("/concerns")
async def list_concerns():
    """対応可能な悩み一覧"""
    from src.advisor.engine import CONCERN_MAP

    categories = {
        "eye": {"label": "目元", "concerns": []},
        "nose": {"label": "鼻", "concerns": []},
        "skin": {"label": "肌", "concerns": []},
        "contour": {"label": "輪郭・小顔", "concerns": []},
    }

    # 悩みキーワードをカテゴリ別に整理
    eye_keys = ["二重", "一重", "奥二重", "目を大きく", "目元", "まぶた", "クマ", "まぶたが重い"]
    nose_keys = ["鼻を高く", "鼻筋", "団子鼻", "鼻先", "小鼻", "鼻"]
    skin_keys = ["シミ", "くすみ", "肝斑", "ニキビ", "毛穴", "しわ", "ほうれい線"]
    contour_keys = ["小顔", "エラ", "フェイスライン", "二重あご", "あご", "頬"]

    for k in eye_keys:
        if k in CONCERN_MAP:
            categories["eye"]["concerns"].append(k)
    for k in nose_keys:
        if k in CONCERN_MAP:
            categories["nose"]["concerns"].append(k)
    for k in skin_keys:
        if k in CONCERN_MAP:
            categories["skin"]["concerns"].append(k)
    for k in contour_keys:
        if k in CONCERN_MAP:
            categories["contour"]["concerns"].append(k)

    return {
        "categories": categories,
        "usage": "POST /api/advisor/chat にメッセージを送信してください。悩みキーワードが自動的にマッチングされます。",
        "example": {
            "message": "二重にしたいんですが、埋没と切開どちらがいいか分からなくて...",
            "note": "→ 二重埋没法・二重切開法の価格比較、リスク、質問リストを返却",
        },
    }


@router.get("/status")
async def advisor_status():
    """アドバイザーのステータス確認"""
    return {
        "llm_available": is_llm_available(),
        "llm_provider": "anthropic" if is_llm_available() else "mock",
        "model": "claude-sonnet-4-20250514" if is_llm_available() else "template",
        "note": "APIキー未設定時はテンプレートベースで回答します。"
                if not is_llm_available()
                else "Claude APIに接続中。",
        "setup": {
            "env_var": "AURA_ANTHROPIC_API_KEY",
            "file": ".env",
            "example": "AURA_ANTHROPIC_API_KEY=sk-ant-...",
        } if not is_llm_available() else None,
    }


# ==========================================
# 法的行動支援ツール
# ==========================================


@router.get("/tools")
async def list_legal_tools():
    """利用可能な法的行動支援ツール一覧"""
    from src.advisor.legal_tools import get_tools_list
    return {
        "tools": get_tools_list(),
        "description": "美容医療の患者さんが自分で行動を起こすためのテンプレートとチェックリスト。",
        "legal_note": "情報とツールの提供であり、法律相談や医療相談ではありません。",
    }


class ToolRequest(BaseModel):
    """ツール実行リクエスト"""
    params: dict = Field(default_factory=dict, description="ツール固有のパラメータ")


@router.post("/tools/{tool_id}")
async def execute_legal_tool(tool_id: str, request: ToolRequest):
    """法的行動支援ツールを実行"""
    from src.advisor.legal_tools import execute_tool

    result = execute_tool(tool_id, request.params)
    if result is None:
        raise HTTPException(status_code=404, detail=f"ツール '{tool_id}' は存在しません")

    return {
        "tool_id": tool_id,
        "result": result,
        "legal_note": "この情報は一般的な知識の整理であり、法律相談ではありません。具体的な法的問題については弁護士にご相談ください。",
    }

