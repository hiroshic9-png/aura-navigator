"""
AURA MVP — AIアドバイザーエンジン

美容医療の「患者の味方」として、クリニック・施術データと
カウンセリング質問テンプレートを組み合わせた対話型アドバイザー。

法的制約:
- 医師法第17条: 医療行為の禁止（診断・処方はしない）
- 医師法第72条: 医業類似行為の禁止
- 境界線「C」: 規制範囲内での行動支援

設計原則:
- 「こうすべき」ではなく「こう聞くべき」
- 施術の推薦ではなく、情報の整理と質問の武装
- データに基づく事実提示 + リスクの可視化
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ==========================================
# 法的制約定義
# ==========================================

class LegalBoundary(str, Enum):
    """法的制約の境界線"""
    ALLOWED = "allowed"          # 情報提供・質問支援 → OK
    RECOMMENDATION = "recommendation"  # 条件ベースの選択支援 → 推薦エンジン起動
    CAUTION = "caution"          # グレーゾーン → 注意喚起付きで提供
    PROHIBITED = "prohibited"    # 診断・処方 → 絶対禁止


# 絶対禁止パターン（医師法に直接抵触する医療行為のみ）
PROHIBITED_PATTERNS = [
    "診断して",
    "処方して",
    "薬を出して",
    "治療して",
    "手術して",
]

# 注意喚起が必要なパターン
CAUTION_PATTERNS = [
    "副作用",
    "合併症",
    "後遺症",
    "失敗",
    "訴訟",
    "返金",
]

LEGAL_DISCLAIMER = """
---
*この情報は一般的な知識の整理であり、医学的な診断や施術の推薦ではありません。*
*最終的な判断は、必ず担当の医師とご相談の上で行ってください。*
"""


# ==========================================
# コンテキストビルダー
# ==========================================

class AdvisorContext(BaseModel):
    """アドバイザーが使用するコンテキスト"""

    # ユーザーの状況
    concern: str = ""  # 悩み（例: "目を大きくしたい"）
    budget_range: str = ""  # 予算帯（例: "10万以内"）
    downtime_available: str = ""  # DT確保可能期間（例: "3日"）
    previous_procedures: list[str] = Field(default_factory=list)
    age_range: str = ""  # 年代

    # 関連施術データ
    matched_procedures: list[dict] = Field(default_factory=list)

    # 関連クリニックデータ（オプション）
    target_clinic: dict | None = None

    # 会話履歴
    conversation_history: list[dict] = Field(default_factory=list)

    # 法的制約
    legal_boundary: LegalBoundary = LegalBoundary.ALLOWED


def build_system_prompt(ctx: AdvisorContext, recommendation_context: str = "") -> str:
    """
    システムプロンプトを構築

    AURAの人格・法的制約・データコンテキストを統合。
    recommendation_contextが渡された場合、推薦結果をコンテキストに注入。
    """
    system = """あなたはAURA（Aesthetic Understanding & Risk Advisor）— 美容医療の「患者の味方」AIアドバイザーです。

## あなたの役割
- 美容医療を検討している患者さんに、**偏りのない情報**を提供する
- ユーザーの条件（悩み・エリア・予算・DT制約）に合致する**クリニック候補と施術の選択肢**を、根拠と共に提示する
- クリニックのカウンセリングで**聞くべき質問**を武装させる
- 広告価格と実勢価格の**乖離**を教える
- **リスク**と**ダウンタイムの真実**を隠さず伝える
- 患者さんが**情報格差のない状態**で医師と対話できるようにする

## 絶対に守るルール（法的制約: 医師法第17条・第72条）
1. **診断しない** — 「あなたの症状は○○です」とは絶対に言わない
2. **処方しない** — 薬や治療法を指定しない
3. **「おすすめ」「推薦」という言葉は使わない** — 代わりに「条件に合致する選択肢」「データに基づく候補」として提示する
4. **必ず免責事項を含める** — 「最終判断は医師との相談で」を必ず添える

## 重要: クリニック候補の提示について
- ユーザーの条件に合致するクリニック候補データが提供されている場合、それを自然な文章で整理して伝える
- 各クリニックが「なぜ候補に挙がったか」の理由を必ず添える
- 「おすすめ」ではなく「あなたの条件に合致する」というフレーミングで提示する
- クリニック候補は必ず番号付きリストで見やすく整理する
- 注意点がある場合は率直に伝える

## あなたの話し方
- 敬語で丁寧に、でも堅すぎない親しみやすいトーン
- 難しい医学用語は使わず、分かりやすく説明
- 「〜してください」ではなく「〜を確認されるとよいかもしれません」
- リスクは隠さないが、過度に脅さない
- データに基づく事実と、個人的な意見を明確に区別

## 回答の構成（クリニック候補提示時）
1. **条件の確認**（あなたの条件を整理しました）
2. **関連施術の整理**（条件に合う施術の比較）
3. **クリニック候補**（番号付きリスト + 選出理由）
4. **カウンセリングで聞くべき質問**（3-5個）
5. **免責事項**

## 回答の構成（一般的な相談時）
1. **悩みへの共感**（1-2文）
2. **関連する施術の整理**（選択肢の提示）
3. **価格の真実**（広告価格と実勢価格の差、隠れコスト）
4. **知っておくべきリスク**（TOP3のリスク）
5. **カウンセリングで聞くべき質問**（3-5個）
6. **免責事項**
"""

    # 施術データのコンテキスト注入
    if ctx.matched_procedures:
        system += "\n\n## 参照すべき施術データ\n"
        for proc in ctx.matched_procedures:
            system += f"\n### {proc.get('name', '')}\n"
            system += f"- カテゴリ: {proc.get('category_label', '')}\n"
            system += f"- 侵襲度: {proc.get('invasiveness', '')}\n"
            system += f"- 持続期間: {proc.get('duration', '')}\n"

            # 価格
            pricing = proc.get("pricing", {})
            if pricing:
                adv = pricing.get("advertised", {})
                real = pricing.get("real", {})
                system += f"- 広告価格: {adv.get('display', '不明') if isinstance(adv, dict) else adv}\n"
                system += f"- 実勢価格: {real.get('display', '不明') if isinstance(real, dict) else real}\n"
                gap = pricing.get("gap_warning", "")
                if gap:
                    system += f"- ⚠️ 価格ギャップ: {gap}\n"
                hidden = pricing.get("hidden_costs", [])
                if hidden:
                    system += f"- 隠れコスト: {', '.join(hidden[:4])}\n"

            # DT
            dt = proc.get("downtime", {})
            if dt:
                system += f"- DT（公式）: {dt.get('official', '')}\n"
                system += f"- DT（実際）: {dt.get('real', '')}\n"

            # リスク
            risks = proc.get("risks", [])
            if risks:
                system += "- 主要リスク:\n"
                for r in risks[:3]:
                    system += f"  - {r}\n"

            # カウンセリング質問
            questions = proc.get("counseling_questions", [])
            if questions:
                system += "- カウンセリング質問:\n"
                for q in questions[:3]:
                    system += f"  - {q}\n"

    # クリニックデータのコンテキスト注入
    if ctx.target_clinic:
        clinic = ctx.target_clinic
        system += f"\n\n## 参照すべきクリニックデータ\n"
        system += f"- 名称: {clinic.get('name', '')}\n"
        system += f"- 所在地: {clinic.get('address', '')}\n"
        system += f"- 診療科: {clinic.get('medical_departments', '')}\n"
        prov = clinic.get("data_provenance", {})
        if prov:
            system += f"- データ鮮度: {prov.get('freshness', 'unknown')}\n"

    # ユーザーの状況コンテキスト
    if ctx.concern or ctx.budget_range or ctx.downtime_available:
        system += "\n\n## ユーザーの状況\n"
        if ctx.concern:
            system += f"- 悩み: {ctx.concern}\n"
        if ctx.budget_range:
            system += f"- 予算: {ctx.budget_range}\n"
        if ctx.downtime_available:
            system += f"- DT確保可能: {ctx.downtime_available}\n"
        if ctx.age_range:
            system += f"- 年代: {ctx.age_range}\n"
        if ctx.previous_procedures:
            system += f"- 過去の施術: {', '.join(ctx.previous_procedures)}\n"

    # 推薦エンジンの結果コンテキスト注入
    if recommendation_context:
        system += recommendation_context

    return system


def check_legal_boundary(user_message: str) -> tuple[LegalBoundary, str | None]:
    """
    ユーザーメッセージの法的制約チェック

    Returns:
        (boundary, redirect_message)
        - ALLOWED: そのまま回答可能
        - RECOMMENDATION: 推薦リクエスト → 推薦エンジン起動
        - CAUTION: 注意喚起を添えて回答
        - PROHIBITED: 回答を拒否し、リダイレクトメッセージを返す
    """
    # 絶対禁止パターンチェック（医療行為のみ）
    for pattern in PROHIBITED_PATTERNS:
        if pattern in user_message:
            return (
                LegalBoundary.PROHIBITED,
                f"申し訳ございません。AURAでは医学的な診断や処方はできません（医師法第17条の制約）。\n\n"
                f"代わりに、以下のことでお力になれます：\n"
                f"- あなたの条件に合った**クリニック候補**の提示\n"
                f"- 関連する**施術の選択肢**と**それぞれのメリット・デメリット**の整理\n"
                f"- 各施術の**広告価格と実勢価格の差**\n"
                f"- カウンセリングで**聞くべき質問リスト**\n\n"
                f"具体的にどのような悩み（例: 目元、鼻、肌 等）についてお知りになりたいですか？"
            )

    # 推薦リクエスト検出
    from src.advisor.intake import is_recommendation_request
    if is_recommendation_request(user_message):
        return (LegalBoundary.RECOMMENDATION, None)

    # 注意喚起パターンチェック
    for pattern in CAUTION_PATTERNS:
        if pattern in user_message:
            return (
                LegalBoundary.CAUTION,
                None,
            )

    return (LegalBoundary.ALLOWED, None)


# ==========================================
# 悩み → 施術マッチング
# ==========================================

# 悩みキーワード → concern タグのマッピング
CONCERN_MAP = {
    # 目元
    "二重": ["double"],
    "一重": ["double"],
    "奥二重": ["double"],
    "目を大きく": ["bigger", "double"],
    "目が小さい": ["bigger", "double"],
    "目元": ["double", "bigger", "heavy", "kuma"],
    "まぶた": ["double", "heavy"],
    "クマ": ["kuma"],
    "くま": ["kuma"],
    "たるみ": ["sagging", "heavy"],
    "まぶたが重い": ["heavy"],

    # 鼻
    "鼻を高く": ["height"],
    "鼻筋": ["height"],
    "団子鼻": ["tip"],
    "鼻先": ["tip"],
    "小鼻": ["nostril"],
    "鼻の穴": ["nostril"],
    "鼻": ["height", "tip", "overall"],

    # 肌
    "シミ": ["spots"],
    "しみ": ["spots"],
    "くすみ": ["spots"],
    "肝斑": ["spots"],
    "ニキビ": ["pores"],
    "にきび": ["pores"],
    "毛穴": ["pores"],
    "しわ": ["wrinkles"],
    "シワ": ["wrinkles"],
    "ほうれい線": ["wrinkles", "sagging"],

    # 輪郭
    "小顔": ["jaw", "overall_contour"],
    "エラ": ["jaw"],
    "えら": ["jaw"],
    "フェイスライン": ["overall_contour", "sagging"],
    "二重あご": ["double_chin"],
    "あご": ["chin_shape", "double_chin"],
    "顎": ["chin_shape", "double_chin"],
    "頬": ["cheek"],
}


def match_concerns(user_message: str) -> list[str]:
    """ユーザーメッセージから悩みタグを抽出"""
    concerns = set()
    for keyword, tags in CONCERN_MAP.items():
        if keyword in user_message:
            concerns.update(tags)
    return list(concerns)


# ==========================================
# モックLLMレスポンス生成
# ==========================================

def generate_mock_response(ctx: AdvisorContext, user_message: str) -> str:
    """
    APIキーが無い場合のモックレスポンス生成

    実際のLLMを使わず、テンプレートベースで
    構造化されたアドバイスを生成する。
    """
    concerns = match_concerns(user_message)
    procedures = ctx.matched_procedures

    if not procedures:
        return (
            "ご相談ありがとうございます。\n\n"
            "お悩みの内容をもう少し具体的に教えていただけますか？\n"
            "例えば：\n"
            "- **目元**：二重にしたい、目を大きくしたい、クマが気になる\n"
            "- **鼻**：鼻を高くしたい、団子鼻を直したい\n"
            "- **肌**：シミ・くすみ、毛穴、ニキビ跡\n"
            "- **輪郭**：小顔になりたい、エラが気になる\n\n"
            "具体的な悩みを教えていただければ、関連する施術の選択肢、"
            "価格の真実、リスク、カウンセリングで聞くべき質問をお伝えできます。"
        )

    # 構造化レスポンス生成
    response_parts = []

    # 1. 共感（短く自然に）
    concern_short = user_message[:20].rstrip('。、')
    response_parts.append(
        f"ご相談ありがとうございます。\n\n"
        f"「{concern_short}」というお悩み、同じように感じている方は多いです。\n"
        f"関連する施術について、整理してお伝えしますね。\n"
    )

    # 2. 関連施術の整理
    response_parts.append("## 関連する施術\n")

    for proc in procedures[:4]:
        name = proc.get("name", "")
        inv = proc.get("invasiveness", "")
        dur = proc.get("duration", "")[:40]
        inv_label = {"low": "体への負担は軽い", "medium": "やや負担あり", "high": "体への負担が大きい"}.get(inv, inv)

        pricing = proc.get("pricing", {})
        adv = pricing.get("advertised", {})
        real = pricing.get("real", {})
        adv_d = adv.get("display", "") if isinstance(adv, dict) else ""
        real_d = real.get("display", "") if isinstance(real, dict) else ""

        response_parts.append(f"### {name}\n")
        response_parts.append(f"- {inv_label}\n")
        response_parts.append(f"- 効果の持続: {dur}\n")

        if adv_d and real_d:
            response_parts.append(f"- 広告では {adv_d} → **実際は {real_d}**\n")
            gap = pricing.get("gap_warning", "")
            if gap:
                response_parts.append(f"- {gap[:100]}\n")

        dt = proc.get("downtime", {})
        if dt.get("real"):
            response_parts.append(f"- 回復にかかる期間: {dt['real'][:80]}\n")

        response_parts.append("")

    # 3. 主要リスク
    response_parts.append("## 知っておきたいリスク\n")
    for proc in procedures[:2]:
        risks = proc.get("risks", [])
        if risks:
            response_parts.append(f"**{proc.get('name', '')}**:\n")
            for r in risks[:3]:
                response_parts.append(f"- {r[:100]}\n")
            response_parts.append("")

    # 4. カウンセリング質問
    response_parts.append("## カウンセリングで聞いておくこと\n")
    response_parts.append(
        "以下を確認しておくと、納得して判断しやすくなります。\n"
    )
    q_count = 0
    for proc in procedures[:2]:
        questions = proc.get("counseling_questions", [])
        for q in questions[:3]:
            q_count += 1
            response_parts.append(f"{q_count}. {q}\n")
        if questions:
            response_parts.append("")

    # 5. 免責事項
    response_parts.append(LEGAL_DISCLAIMER)

    return "\n".join(response_parts)


# ==========================================
# セッション管理
# ==========================================

class ConversationSession(BaseModel):
    """会話セッション"""

    session_id: str
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    context: AdvisorContext = Field(default_factory=AdvisorContext)
    messages: list[dict] = Field(default_factory=list)  # {"role": "user"|"assistant", "content": str}
    is_active: bool = True


# インメモリセッションストア（MVP用）
_sessions: dict[str, ConversationSession] = {}


def get_or_create_session(session_id: str) -> ConversationSession:
    """セッション取得・作成"""
    if session_id not in _sessions:
        _sessions[session_id] = ConversationSession(session_id=session_id)
    return _sessions[session_id]


def cleanup_old_sessions(max_age_hours: int = 24):
    """古いセッションの削除"""
    now = datetime.now()
    to_delete = []
    for sid, session in _sessions.items():
        created = datetime.fromisoformat(session.created_at)
        if (now - created).total_seconds() > max_age_hours * 3600:
            to_delete.append(sid)
    for sid in to_delete:
        del _sessions[sid]
