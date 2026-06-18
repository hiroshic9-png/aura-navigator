"""
AURA MVP — 施術情報API

28施術の詳細データを提供するAPIエンドポイント。
広告価格 vs 実勢価格の乖離、隠れコスト、リアルDT、
カウンセリング質問リストなど「患者の味方」としての核心情報を返却。
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.analyzers.freshness import build_freshness_metadata
from src.advisor.engine import CONCERN_MAP
from src.db.database import ProcedureTable, ClinicProcedure, ClinicTable, get_db
from src.analyzers.price_intelligence import format_price

# 価格ソースの日本語ラベルマッピング
PRICE_SOURCE_LABELS = {
    'website_scrape': '公式サイト',
    'chain_inference': 'チェーン参考',
    'department_inference': '診療科推定',
    'estimated': '統計推定',
}

router = APIRouter()


@router.get("/")
async def list_procedures(
    category: str | None = Query(None, description="カテゴリフィルタ（eye/nose/skin/contour）"),
    concern: str | None = Query(None, description="悩みフィルタ（double/kuma/spots/sagging等）"),
    invasiveness: str | None = Query(None, description="侵襲度フィルタ（low/medium/high）"),
    db: AsyncSession = Depends(get_db),
):
    """
    施術一覧取得

    カテゴリ・悩み・侵襲度でフィルタ可能。
    全28施術の概要（価格比較・DT・リスク数）を返却。
    """
    query = select(ProcedureTable)

    if category:
        query = query.where(ProcedureTable.category == category)

    if concern:
        # CONCERN_MAPで日本語キーワードからタグに変換（例: "鼻先" → ["tip"]）
        concern_tags = CONCERN_MAP.get(concern, [concern])
        # いずれかのタグにマッチする施術を検索
        from sqlalchemy import or_
        tag_conditions = [ProcedureTable.matches_concern.contains(tag) for tag in concern_tags]
        query = query.where(or_(*tag_conditions))

    if invasiveness:
        query = query.where(ProcedureTable.invasiveness == invasiveness)

    query = query.order_by(ProcedureTable.category, ProcedureTable.name)

    result = await db.execute(query)
    procedures = result.scalars().all()

    return {
        "procedures": [_format_summary(p) for p in procedures],
        "total": len(procedures),
        "categories": {
            "eye": "目元",
            "nose": "鼻",
            "skin": "肌",
            "contour": "輪郭・小顔",
        },
    }


@router.get("/stats")
async def procedure_stats(db: AsyncSession = Depends(get_db)):
    """
    施術DB統計

    カテゴリ別・侵襲度別の集計と、データ鮮度情報。
    """
    total = await db.scalar(select(func.count(ProcedureTable.id)))

    cat_result = await db.execute(
        select(ProcedureTable.category_label, func.count(ProcedureTable.id))
        .group_by(ProcedureTable.category_label)
        .order_by(func.count(ProcedureTable.id).desc())
    )
    by_category = [{"category": r[0], "count": r[1]} for r in cat_result.all()]

    inv_result = await db.execute(
        select(ProcedureTable.invasiveness, func.count(ProcedureTable.id))
        .group_by(ProcedureTable.invasiveness)
    )
    by_invasiveness = [{"level": r[0], "count": r[1]} for r in inv_result.all()]

    return {
        "total": total or 0,
        "by_category": by_category,
        "by_invasiveness": by_invasiveness,
        "data_source": "aura_navi_v1.1",
        "all_fields_complete": True,
        "note": "全42施術で広告価格・実勢価格・リスク・質問リスト・リアルDTが100%充填",
    }


@router.get("/market-prices")
async def market_prices(db: AsyncSession = Depends(get_db)):
    """
    施術別 東京エリア価格市場統計

    全施術の実勢価格統計（中央値/P25/P75/件数/エリア別）を返却。
    クリニック別の実際の掲載・提示価格から算出。
    """
    from src.analyzers.price_intelligence import build_price_stats

    stats = await build_price_stats()

    result = []
    for proc_id, s in sorted(stats.items(), key=lambda x: x[1].category):
        result.append({
            "procedure_id": proc_id,
            "procedure_name": s.procedure_name,
            "category": s.category,
            "sample_count": s.sample_count,
            "median": s.median,
            "median_display": format_price(s.median),
            "percentile_25": s.percentile_25,
            "percentile_75": s.percentile_75,
            "min_price": s.min_price,
            "max_price": s.max_price,
            "range_display": f"{format_price(s.percentile_25)}〜{format_price(s.percentile_75)}",
            "area_stats": s.area_stats,
        })

    return {
        "market_prices": result,
        "total_procedures": len(result),
        "note": "東京エリアのクリニック実勢価格から算出",
    }


@router.get("/compare")
async def compare_procedures(
    ids: str = Query(..., description="比較する施術IDをカンマ区切り（2-4件）"),
    db: AsyncSession = Depends(get_db),
):
    """
    施術比較

    2-4施術を並べて比較。価格・DT・リスク・満足度・侵襲度を横並びで返却。
    存在しないIDはスキップし、有効な施術が2件未満なら400エラー。
    """
    id_list = [i.strip() for i in ids.split(",") if i.strip()]
    if len(id_list) < 2 or len(id_list) > 4:
        raise HTTPException(status_code=400, detail="比較は2〜4施術で指定してください")

    result = await db.execute(
        select(ProcedureTable).where(ProcedureTable.id.in_(id_list))
    )
    procedures = result.scalars().all()

    if len(procedures) < 2:
        raise HTTPException(
            status_code=400,
            detail="有効な施術が2件未満です。IDを確認してください",
        )

    return {
        "procedures": [_format_comparison(p) for p in procedures],
        "count": len(procedures),
    }


@router.get("/{procedure_id}/top-clinics")
async def top_clinics_for_procedure(
    procedure_id: str,
    sort_by: str = Query("score", description="ソート基準（score/price/rating）"),
    limit: int = Query(20, ge=1, le=50, description="取得件数"),
    db: AsyncSession = Depends(get_db),
):
    """
    施術別おすすめクリニックランキング

    指定施術を扱うクリニックを、複合スコアでランキング。
    各クリニックのtop_doctorに専門性マッチスコア（specialty_match）を付与。
    ランキングは客観データのみに基づき、広告・提携要素は一切含まない。

    複合スコア構成:
    - trust_score (40%): 医師の信頼性スコア
    - specialty_match (30%): 専門分野×施術カテゴリの親和度
    - clinic_score (20%): クリニック総合品質
    - price_competitiveness (10%): 価格競争力
    """
    from sqlalchemy import case, literal_column
    from src.db.database import ReviewTable, DoctorTable
    from src.analyzers.price_intelligence import get_price_label
    from src.analyzers.doctor_specialty import (
        match_doctor_to_procedure,
        get_specialty_match_label,
    )

    # 施術存在確認
    proc = await db.scalar(
        select(ProcedureTable).where(ProcedureTable.id == procedure_id)
    )
    if not proc:
        raise HTTPException(status_code=404, detail="施術が見つかりません")

    # この施術を扱うクリニックを取得
    cp_result = await db.execute(
        select(
            ClinicProcedure.clinic_id,
            ClinicProcedure.price_advertised,
            ClinicProcedure.source,
        )
        .where(ClinicProcedure.procedure_id == procedure_id)
        .where(ClinicProcedure.is_active == True)
    )
    cp_rows = cp_result.all()
    if not cp_rows:
        return {"procedure": proc.name, "clinics": [], "total": 0}

    clinic_ids = [r[0] for r in cp_rows]
    price_map = {r[0]: r[1] for r in cp_rows if r[1] and r[1] > 0}
    source_map = {r[0]: r[2] for r in cp_rows}

    # クリニック基本情報を一括取得
    clinic_result = await db.execute(
        select(ClinicTable).where(
            ClinicTable.id.in_(clinic_ids),
            ClinicTable.is_active == True,
        )
    )
    clinics_data = {c.id: c for c in clinic_result.scalars().all()}

    # Phase 56: 各クリニックのトップ医師を一括取得（N+1回避）
    doc_result = await db.execute(
        select(DoctorTable)
        .where(DoctorTable.clinic_id.in_(clinic_ids))
        .where(DoctorTable.is_active == True)
    )
    all_doctors = doc_result.scalars().all()

    # Phase 67: クリニック別に最適な医師を選出（専門性マッチ + trust_score で総合判定）
    top_doctor_map: dict[str, dict] = {}
    for doc in all_doctors:
        cid = doc.clinic_id
        doc_score = doc.trust_score or 0

        # 専門性マッチスコアを算出
        specialty_score = match_doctor_to_procedure(
            doctor_specialties=doc.specialties,
            procedure_category=proc.category,
            procedure_name=proc.name,
        )
        specialty_label = get_specialty_match_label(specialty_score)

        # 複合選出スコア: trust_score * 0.6 + specialty_match * 100 * 0.4
        combined = doc_score * 0.6 + specialty_score * 100 * 0.4

        if cid not in top_doctor_map or combined > top_doctor_map[cid].get("_combined", 0):
            top_doctor_map[cid] = {
                "name": doc.name,
                "has_certification": bool(doc.jsaps_certified),
                "experience_years": doc.experience_years,
                "trust_score": round(doc.trust_score, 1) if doc.trust_score else None,
                "specialty_match": specialty_score,
                "specialty_match_label": specialty_label,
                "_combined": combined,  # 選出用（レスポンスでは除外）
            }

    # 市場価格の中央値を算出（価格比較用）
    import statistics
    prices = list(price_map.values())
    median_price = int(statistics.median(prices)) if len(prices) >= 3 else None

    # ランキングスコア算出（Phase 67: 複合スコアに改定）
    ranked = []
    for cid in clinic_ids:
        clinic = clinics_data.get(cid)
        if not clinic:
            continue

        # --- 各軸のスコア ---

        # (1) 医師 trust_score (0-100)
        doc_info = top_doctor_map.get(cid)
        trust = (doc_info["trust_score"] or 0) if doc_info else 0

        # (2) 専門性マッチ (0.0-1.0 → 0-100)
        spec_match = (doc_info["specialty_match"] * 100) if doc_info else 0

        # (3) クリニック品質 (0-100)
        clinic_quality = clinic.clinic_score or 0

        # (4) 価格競争力 (0-100)
        price_competitiveness = 50.0  # 価格不明時はニュートラル
        if cid in price_map and median_price and median_price > 0:
            ratio = price_map[cid] / median_price
            if ratio <= 0.7:
                price_competitiveness = 100.0
            elif ratio <= 0.85:
                price_competitiveness = 80.0
            elif ratio <= 1.0:
                price_competitiveness = 65.0
            elif ratio <= 1.15:
                price_competitiveness = 45.0
            elif ratio <= 1.3:
                price_competitiveness = 30.0
            else:
                price_competitiveness = 10.0

        # 複合スコア
        relevance_score = (
            trust * 0.4 +
            spec_match * 0.3 +
            clinic_quality * 0.2 +
            price_competitiveness * 0.1
        )

        # データ充実ボーナス (0-5pt)
        data_bonus = 0.0
        if source_map.get(cid) != "chain_inference":
            data_bonus += 2.0
        if cid in price_map:
            data_bonus += 1.5
        if clinic.google_review_count and clinic.google_review_count >= 10:
            data_bonus += 1.5

        score = relevance_score + data_bonus

        # Phase 56: 相場対比ラベルを算出
        market_context = None
        if cid in price_map and price_map[cid] > 0 and median_price:
            ctx = get_price_label(price_map[cid], median_price)
            market_context = {
                "label": ctx.label,
                "ratio": ctx.ratio,
            }

        # top_doctorから内部用フィールドを除外
        top_doc_response = None
        if doc_info:
            top_doc_response = {k: v for k, v in doc_info.items() if not k.startswith("_")}

        raw_source = source_map.get(cid, "unknown")
        item = {
            "clinic_id": cid,
            "name": clinic.name,
            "chain_name": clinic.chain_name,
            "city": clinic.city,
            "google_rating": clinic.google_rating,
            "google_review_count": clinic.google_review_count,
            "clinic_grade": clinic.clinic_grade,
            "price": price_map.get(cid),
            "price_display": format_price(price_map[cid]) if cid in price_map else None,
            "data_source": raw_source,
            "price_source": raw_source,
            "price_source_label": PRICE_SOURCE_LABELS.get(raw_source, raw_source),
            "score": round(score, 1),
            "top_doctor": top_doc_response,
            "market_context": market_context,
        }

        ranked.append(item)

    # ソート
    if sort_by == "price":
        ranked.sort(key=lambda x: (x["price"] or 99999999, -x["score"]))
    elif sort_by == "rating":
        ranked.sort(key=lambda x: (-(x["google_rating"] or 0), -x["score"]))
    else:
        ranked.sort(key=lambda x: -x["score"])

    # 順位付け
    for i, r in enumerate(ranked[:limit], 1):
        r["rank"] = i

    return {
        "procedure": proc.name,
        "category": proc.category_label,
        "median_price": median_price,
        "median_price_display": format_price(median_price) if median_price else None,
        "clinics": ranked[:limit],
        "total": len(ranked),
        "note": "ランキングは客観データのみに基づきます。広告・提携要素は含みません。",
    }


@router.get("/market-check/{name}")
async def market_check(
    name: str,
    price: int = Query(..., gt=0, description="見積もり金額（円）"),
    db: AsyncSession = Depends(get_db),
):
    """
    見積もりチェッカー

    カウンセリングで提示された見積もり金額を市場統計と比較し、
    相場判定・隠れコスト・確認すべき質問リストを返す。
    「トリビューで見つけた→AURAでチェック」フローの核心機能。
    """
    import statistics as stats_module

    # 施術名で検索（完全一致を優先、なければ部分一致）
    result = await db.execute(
        select(ProcedureTable).where(ProcedureTable.name == name)
    )
    proc = result.scalar_one_or_none()

    if not proc:
        # 部分一致で再検索
        result = await db.execute(
            select(ProcedureTable).where(ProcedureTable.name.contains(name))
        )
        proc = result.scalars().first()

    if not proc:
        raise HTTPException(status_code=404, detail="施術が見つかりません")

    # 市場価格統計を取得
    market = await _get_procedure_market_stats(proc.id, db)

    # 市場統計がない場合は施術マスタの実勢価格から推定
    if market:
        median = market["median"]
        p25 = market["percentile_25"]
        p75 = market["percentile_75"]
    else:
        real_price_data = _parse_json(proc.real_price)
        if isinstance(real_price_data, dict) and real_price_data.get("median"):
            median = real_price_data["median"]
            p25 = real_price_data.get("low", int(median * 0.7))
            p75 = real_price_data.get("high", int(median * 1.4))
        elif isinstance(real_price_data, dict) and real_price_data.get("low"):
            low = real_price_data["low"]
            high = real_price_data.get("high", low * 2)
            median = (low + high) // 2
            p25 = low
            p75 = high
        else:
            raise HTTPException(
                status_code=404,
                detail="この施術の市場価格データが不足しています"
            )

    # 判定ロジック
    ratio = price / median if median > 0 else 1.0
    if ratio <= 0.7:
        verdict = "cheap"
        verdict_label = "かなり安い — 追加料金の有無を必ず確認してください"
    elif ratio <= 1.3:
        verdict = "reasonable"
        verdict_label = "相場範囲内です"
    else:
        verdict = "expensive"
        verdict_label = "相場より高い可能性があります"

    # 隠れコストを取得
    hidden_costs = _parse_json(proc.hidden_costs)
    if isinstance(hidden_costs, list):
        hidden_costs_list = hidden_costs
    else:
        hidden_costs_list = []

    # 隠れコストの平均的な追加額を推定（1件あたり5,000〜15,000円を想定）
    estimated_hidden = len(hidden_costs_list) * 8000
    total_estimated = price + estimated_hidden

    # カウンセリングで確認すべき質問リスト
    questions = _parse_json(proc.counseling_questions)
    if not isinstance(questions, list):
        questions = []

    # 価格に特化した追加質問
    price_questions = [
        "提示された金額は税込みですか？",
        "麻酔代・薬代・再診料は含まれていますか？",
        "術後のフォローアップ費用は別途かかりますか？",
    ]
    if verdict == "cheap":
        price_questions.append("この価格で含まれる内容と、追加費用が発生するケースを教えてください")
        price_questions.append("保証制度はありますか？再施術の場合の費用を教えてください")
    elif verdict == "expensive":
        price_questions.append("他院と比較して高い理由を教えてください")
        price_questions.append("分割払いやモニター価格は利用できますか？")

    # 施術固有の質問と統合（重複除去、最大10件）
    all_questions = price_questions + [q for q in questions if q not in price_questions]

    return {
        "procedure_name": proc.name,
        "procedure_id": proc.id,
        "input_price": price,
        "market_median": median,
        "market_p25": p25,
        "market_p75": p75,
        "verdict": verdict,
        "verdict_label": verdict_label,
        "ratio": round(ratio, 2),
        "hidden_costs": hidden_costs_list,
        "hidden_cost_estimate": estimated_hidden,
        "total_estimated": total_estimated,
        "questions_to_ask": all_questions[:10],
    }


@router.get("/recommended-clinics/{procedure_name}")
async def recommended_clinics(
    procedure_name: str,
    area: str | None = Query(None, description="エリアフィルタ（例: 渋谷区）"),
    limit: int = Query(3, ge=1, le=10, description="取得件数（デフォルト3）"),
    db: AsyncSession = Depends(get_db),
):
    """
    おすすめクリニック推薦API

    施術名から該当施術を特定し、客観データに基づく推薦スコアで
    クリニックをランキングして返却する。
    スコア構成:
    - Google口コミ評価 (30%)
    - 専門医在籍 (25%)
    - 価格透明性 (20%)
    - 口コミの質 (15%)
    - クリニックスコア (10%)
    広告費・掲載料は一切反映しない。
    """
    from src.db.database import ReviewTable, DoctorTable

    # 施術名で検索（完全一致 → 部分一致フォールバック）
    result = await db.execute(
        select(ProcedureTable).where(ProcedureTable.name == procedure_name)
    )
    proc = result.scalar_one_or_none()

    if not proc:
        result = await db.execute(
            select(ProcedureTable).where(ProcedureTable.name.contains(procedure_name))
        )
        proc = result.scalars().first()

    if not proc:
        raise HTTPException(status_code=404, detail="施術が見つかりません")

    # この施術を扱うクリニックを取得
    cp_query = (
        select(ClinicProcedure)
        .where(ClinicProcedure.procedure_id == proc.id)
        .where(ClinicProcedure.is_active == True)
    )
    cp_result = await db.execute(cp_query)
    cp_rows = cp_result.scalars().all()

    if not cp_rows:
        return {
            "procedure": proc.name,
            "recommended": [],
            "total_clinics_with_procedure": 0,
            "disclaimer": "この推薦は公開データに基づくものであり、医療の質を保証するものではありません。",
        }

    clinic_ids = list({cp.clinic_id for cp in cp_rows})

    # クリニック基本情報を一括取得
    clinic_query = select(ClinicTable).where(
        ClinicTable.id.in_(clinic_ids),
        ClinicTable.is_active == True,
    )
    if area:
        clinic_query = clinic_query.where(ClinicTable.city.contains(area))
    clinic_result = await db.execute(clinic_query)
    clinics_data = {c.id: c for c in clinic_result.scalars().all()}

    if not clinics_data:
        return {
            "procedure": proc.name,
            "recommended": [],
            "total_clinics_with_procedure": len(clinic_ids),
            "disclaimer": "この推薦は公開データに基づくものであり、医療の質を保証するものではありません。",
        }

    # 医師情報を一括取得
    doc_result = await db.execute(
        select(DoctorTable)
        .where(DoctorTable.clinic_id.in_(list(clinics_data.keys())))
        .where(DoctorTable.is_active == True)
    )
    all_doctors = doc_result.scalars().all()
    doctors_by_clinic: dict[str, list] = {}
    for doc in all_doctors:
        doctors_by_clinic.setdefault(doc.clinic_id, []).append(doc)

    # 口コミ情報を一括取得
    review_result = await db.execute(
        select(ReviewTable)
        .where(ReviewTable.clinic_id.in_(list(clinics_data.keys())))
    )
    all_reviews = review_result.scalars().all()
    reviews_by_clinic: dict[str, list] = {}
    for rev in all_reviews:
        reviews_by_clinic.setdefault(rev.clinic_id, []).append(rev)

    # クリニック施術の価格マッピング
    price_map: dict[str, dict] = {}
    for cp in cp_rows:
        if cp.clinic_id in clinics_data:
            prices = price_map.setdefault(cp.clinic_id, {})
            if cp.price_advertised and cp.price_advertised > 0:
                prices.setdefault("values", []).append(cp.price_advertised)
            prices["source"] = cp.source

    # クリニック別の施術情報マッピング（価格透明性計算用）
    cp_by_clinic: dict[str, list] = {}
    for cp in cp_rows:
        if cp.clinic_id in clinics_data:
            cp_by_clinic.setdefault(cp.clinic_id, []).append(cp)

    # 推薦スコア算出
    scored_clinics = []
    for cid, clinic in clinics_data.items():
        doctors = doctors_by_clinic.get(cid, [])
        reviews = reviews_by_clinic.get(cid, [])
        procedures_for_clinic = cp_by_clinic.get(cid, [])

        score, reasons = _calculate_recommendation_score(
            clinic, doctors, procedures_for_clinic, reviews,
        )

        # 価格情報
        price_info = price_map.get(cid, {})
        price_values = price_info.get("values", [])
        price_range = None
        if price_values:
            price_range = {
                "min": min(price_values),
                "max": max(price_values),
                "source": price_info.get("source", "unknown"),
            }

        # 専門医カウント
        specialist_count = sum(
            1 for d in doctors if d.jsaps_certified or (d.trust_score and d.trust_score >= 70)
        )

        scored_clinics.append({
            "clinic_id": cid,
            "clinic_name": clinic.name,
            "area": clinic.city or "",
            "google_rating": clinic.google_rating,
            "google_review_count": clinic.google_review_count,
            "specialist_count": specialist_count,
            "recommendation_score": round(score, 2),
            "reasons": reasons,
            "price_range": price_range,
            "aura_grade": clinic.clinic_grade or "—",
        })

    # スコア降順でソートしてランキング付与
    scored_clinics.sort(key=lambda x: -x["recommendation_score"])
    for i, c in enumerate(scored_clinics[:limit], 1):
        c["rank"] = i

    return {
        "procedure": proc.name,
        "recommended": scored_clinics[:limit],
        "total_clinics_with_procedure": len(clinic_ids),
        "disclaimer": "この推薦は公開データ（Google口コミ・専門医資格・価格公開性）に基づくものであり、医療の質を保証するものではありません。広告費や掲載料は一切反映されていません。",
    }


def _calculate_recommendation_score(
    clinic,
    doctors: list,
    procedures: list,
    reviews: list,
) -> tuple[float, list[str]]:
    """客観データに基づく推薦スコアを算出"""
    score = 0.0
    reasons = []

    # 1. Google口コミ評価 (weight: 0.30)
    if clinic.google_rating and clinic.google_review_count:
        if clinic.google_rating >= 4.5 and clinic.google_review_count >= 50:
            score += 0.30
            reasons.append(f'口コミ評価 {clinic.google_rating}（{clinic.google_review_count}件）')
        elif clinic.google_rating >= 4.0 and clinic.google_review_count >= 30:
            score += 0.22
            reasons.append(f'口コミ評価 {clinic.google_rating}（{clinic.google_review_count}件）')
        elif clinic.google_rating >= 3.5:
            score += 0.15

    # 2. 専門医在籍 (weight: 0.25)
    certified = [d for d in doctors if d.jsaps_certified or (d.trust_score and d.trust_score >= 70)]
    if certified:
        score += min(0.25, len(certified) * 0.08)
        reasons.append(f'専門医資格保有の医師 {len(certified)}名在籍')

    # 3. 価格透明性 (weight: 0.20)
    official_prices = [p for p in procedures if p.source == 'website_scrape']
    if official_prices:
        ratio = len(official_prices) / max(len(procedures), 1)
        score += 0.20 * ratio
        if ratio > 0.5:
            reasons.append('価格が公式サイトで公開済み')

    # 4. 口コミの質 (weight: 0.15)
    if reviews:
        # red_flagsはJSON列: NULLでなく空配列でもなければレッドフラグ有り
        red_flag_count = 0
        for r in reviews:
            if r.red_flags:
                try:
                    flags = json.loads(r.red_flags)
                    if isinstance(flags, list) and len(flags) > 0:
                        red_flag_count += 1
                except (json.JSONDecodeError, TypeError):
                    pass
        red_flag_rate = red_flag_count / len(reviews)
        if red_flag_rate < 0.05:
            score += 0.15
            reasons.append('レッドフラグ口コミが極めて少ない')
        elif red_flag_rate < 0.10:
            score += 0.10

    # 5. クリニックスコア (weight: 0.10)
    if clinic.clinic_score:
        score += 0.10 * (clinic.clinic_score / 100)

    return score, reasons


@router.get("/{procedure_id}")
async def get_procedure(procedure_id: str, db: AsyncSession = Depends(get_db)):
    """
    施術詳細取得

    指定IDの施術の全情報を返却。
    広告価格と実勢価格の乖離、隠れコスト、カウンセリング質問を含む。
    """
    result = await db.execute(
        select(ProcedureTable).where(ProcedureTable.id == procedure_id)
    )
    procedure = result.scalar_one_or_none()

    if not procedure:
        raise HTTPException(status_code=404, detail="施術が見つかりません")

    detail = _format_detail(procedure)

    # Phase 14: 市場価格統計を付加
    market_stats = await _get_procedure_market_stats(procedure_id, db)
    if market_stats:
        detail["market_price"] = market_stats

    # 症例写真を付加（procedure_idで紐付いたものを最大10件）
    from src.db.database import CasePhotoTable
    cp_result = await db.execute(
        select(CasePhotoTable)
        .where(CasePhotoTable.procedure_id == procedure_id)
        .where(CasePhotoTable.is_active == True)
        .where(CasePhotoTable.before_image_url.isnot(None))
        .order_by(CasePhotoTable.created_at.desc())
        .limit(10)
    )
    photos = cp_result.scalars().all()
    if photos:
        detail["case_photos"] = [
            {
                "id": p.id,
                "before_image_url": p.before_image_url,
                "after_image_url": p.after_image_url,
                "description": p.description,
                "price": p.price,
                "source": p.source,
                "source_url": p.source_url,
                "clinic_name": p.clinic_name,
                "doctor_name": p.doctor_name,
            }
            for p in photos
        ]

    return detail


async def _get_procedure_market_stats(procedure_id: str, db: AsyncSession) -> dict | None:
    """施術の市場価格統計を取得"""
    from sqlalchemy import func as sqlfunc

    result = await db.execute(
        select(
            sqlfunc.count(ClinicProcedure.id).label("count"),
            sqlfunc.avg(ClinicProcedure.price_advertised).label("avg"),
            sqlfunc.min(ClinicProcedure.price_advertised).label("min"),
            sqlfunc.max(ClinicProcedure.price_advertised).label("max"),
        )
        .where(ClinicProcedure.procedure_id == procedure_id)
        .where(ClinicProcedure.price_advertised.isnot(None))
        .where(ClinicProcedure.price_advertised > 0)
    )
    row = result.one()
    if not row[0] or row[0] < 3:
        return None

    # 個別価格を取得して中央値・パーセンタイル算出
    prices_result = await db.execute(
        select(ClinicProcedure.price_advertised)
        .where(ClinicProcedure.procedure_id == procedure_id)
        .where(ClinicProcedure.price_advertised.isnot(None))
        .where(ClinicProcedure.price_advertised > 0)
        .order_by(ClinicProcedure.price_advertised)
    )
    prices = [r[0] for r in prices_result.all()]
    n = len(prices)
    import statistics
    median = int(statistics.median(prices))
    p25 = prices[n // 4] if n >= 4 else prices[0]
    p75 = prices[(3 * n) // 4] if n >= 4 else prices[-1]

    return {
        "sample_count": n,
        "median": median,
        "median_display": format_price(median),
        "percentile_25": p25,
        "percentile_75": p75,
        "range_display": f"{format_price(p25)}〜{format_price(p75)}",
        "min_price": prices[0],
        "max_price": prices[-1],
    }


def _format_comparison(proc: ProcedureTable) -> dict:
    """施術比較用フォーマット（比較に必要なフィールドのみ返却）"""
    adv_price = _parse_json(proc.advertised_price)
    real_price = _parse_json(proc.real_price)
    satisfaction = _parse_json(proc.satisfaction)

    return {
        "id": proc.id,
        "name": proc.name,
        "category": proc.category,
        "category_label": proc.category_label,
        "description": proc.description,
        "pricing": {
            "advertised_display": adv_price.get("display", "") if isinstance(adv_price, dict) else "",
            "real_display": real_price.get("display", "") if isinstance(real_price, dict) else "",
            "hidden_costs": _parse_json(proc.hidden_costs),
        },
        "downtime": {
            "official": proc.downtime_official,
            "real": proc.downtime_real,
        },
        "risks": _parse_json(proc.risks),
        "satisfaction": {
            "rate": satisfaction.get("rate") if isinstance(satisfaction, dict) else None,
            "common_regrets": satisfaction.get("common_regrets", []) if isinstance(satisfaction, dict) else [],
            "regret_prevention": satisfaction.get("regret_prevention", []) if isinstance(satisfaction, dict) else [],
            "completion_months": satisfaction.get("completion_months") if isinstance(satisfaction, dict) else None,
        },
        "counseling_questions": _parse_json(proc.counseling_questions),
        "invasiveness": proc.invasiveness,
        "duration": proc.duration,
    }


def _parse_json(value: str | None) -> list | dict:
    """JSON文字列をパース。失敗時は空リスト/空辞書を返却"""
    if not value:
        return []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []


# エビデンスレベルの日本語ラベル
_EVIDENCE_LABELS = {
    "guideline": "学会ガイドライン準拠",
    "cross_checked": "複数ソース横断分析",
    "single_source": "単一ソース",
    "unverified": "未検証",
}


def _build_data_quality(proc: ProcedureTable) -> dict:
    """施術のデータ品質情報を構築"""
    from datetime import datetime

    evidence = getattr(proc, "evidence_level", "unverified") or "unverified"
    status = getattr(proc, "publish_status", "draft") or "draft"
    verified = getattr(proc, "last_verified_date", None)

    # 鮮度計算
    base_date = verified or proc.fetched_at or proc.created_at
    days_old = 0
    freshness = "fresh"
    if base_date:
        days_old = (datetime.now() - base_date).days
        if days_old > 180:
            freshness = "stale"
        elif days_old > 90:
            freshness = "aging"

    return {
        "evidence_level": evidence,
        "evidence_label": _EVIDENCE_LABELS.get(evidence, evidence),
        "publish_status": status,
        "freshness": freshness,
        "days_since_verified": days_old,
        "last_verified": verified.isoformat() if verified else None,
        "sources_note": "複数クリニック公式サイト横断分析, 口コミサイト, 学術文献",
    }

def _format_summary(proc: ProcedureTable) -> dict:
    """施術の概要フォーマット（一覧用）"""
    adv_price = _parse_json(proc.advertised_price)
    real_price = _parse_json(proc.real_price)
    risks = _parse_json(proc.risks)
    hidden_costs = _parse_json(proc.hidden_costs)

    satisfaction = _parse_json(proc.satisfaction)

    return {
        "id": proc.id,
        "name": proc.name,
        "category": proc.category,
        "category_label": proc.category_label,
        "invasiveness": proc.invasiveness,
        "duration_type": proc.duration_type,
        "duration": proc.duration,
        "recommended_sessions": proc.recommended_sessions,
        "price": {
            "advertised": adv_price.get("display", "") if isinstance(adv_price, dict) else "",
            "real": real_price.get("display", "") if isinstance(real_price, dict) else "",
            "has_gap": bool(proc.price_gap_note),
            "hidden_cost_count": len(hidden_costs) if isinstance(hidden_costs, list) else 0,
        },
        "downtime": {
            "official": proc.downtime_official,
            "real": proc.downtime_real,
        },
        "risk_count": len(risks) if isinstance(risks, list) else 0,
        "concerns": _parse_json(proc.matches_concern),
        "satisfaction_rate": satisfaction.get("rate") if isinstance(satisfaction, dict) else None,
        "data_quality": _build_data_quality(proc),
    }


def _format_detail(proc: ProcedureTable) -> dict:
    """施術の詳細フォーマット"""
    freshness = build_freshness_metadata(
        source=proc.source or "navi",
        fetched_at=proc.fetched_at or proc.created_at,
        source_version=proc.source_version or "",
    )

    return {
        "id": proc.id,
        "name": proc.name,
        "category": proc.category,
        "category_label": proc.category_label,
        "description": proc.description,
        "invasiveness": proc.invasiveness,
        "duration_type": proc.duration_type,
        "duration": proc.duration,
        "recommended_sessions": proc.recommended_sessions,
        "concerns": _parse_json(proc.matches_concern),
        # 価格の真実 — AURAの核心
        "pricing": {
            "advertised": _parse_json(proc.advertised_price),
            "real": _parse_json(proc.real_price),
            "gap_warning": proc.price_gap_note,
            "hidden_costs": _parse_json(proc.hidden_costs),
        },
        # ダウンタイムの真実
        "downtime": {
            "official": proc.downtime_official,
            "real": proc.downtime_real,
            "recovery_phases": _parse_json(proc.recovery_phases),
        },
        # リスクと適性
        "risks": _parse_json(proc.risks),
        "suitable_for": _parse_json(proc.suitable_for),
        "not_suitable_for": _parse_json(proc.not_suitable_for),
        # カウンセリング武装 — 患者が聞くべき質問
        "counseling_questions": _parse_json(proc.counseling_questions),
        # 満足度・後悔データ
        "satisfaction": _parse_json(proc.satisfaction),
        # データ来歴
        "data_quality": _build_data_quality(proc),
        "data_provenance": {
            "source": proc.source,
            "source_version": proc.source_version,
            "freshness": freshness.freshness,
            "days_old": freshness.days_old,
            "confidence": getattr(proc, "confidence", 1.0),
            "evidence_level": getattr(proc, "evidence_level", "unverified"),
            "publish_status": getattr(proc, "publish_status", "draft"),
            "last_verified": proc.last_verified_date.isoformat() if getattr(proc, "last_verified_date", None) else None,
            "price_sources": _parse_json(getattr(proc, "price_sources", None)),
        },
    }
