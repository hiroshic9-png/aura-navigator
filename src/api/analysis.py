"""
AURA MVP — 分析API

価格乖離分析、透明性スコア、クリニック×施術マッチングを提供。
「患者の味方」としてのAURAの核心機能。
"""

import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.analyzers.pricing import (
    analyze_procedure_price,
    calculate_transparency_score,
    classify_gap,
    GAP_LABELS,
    PriceGapAnalysis,
)
from src.db.database import ClinicTable, ProcedureTable, get_db

router = APIRouter()


@router.get("/price-gaps")
async def price_gap_ranking(
    category: str | None = Query(None, description="カテゴリフィルタ"),
    sort_by: str = Query("gap_ratio", description="ソート基準（gap_ratio/hidden_costs/annual_cost）"),
    db: AsyncSession = Depends(get_db),
):
    """
    価格乖離ランキング

    全28施術の「広告価格の盛り度」をランキング形式で返却。
    乖離倍率・隠れコスト・年間維持費を可視化。
    """
    query = select(ProcedureTable)
    if category:
        query = query.where(ProcedureTable.category == category)

    result = await db.execute(query)
    procedures = result.scalars().all()

    analyses = []
    for proc in procedures:
        data = {
            "name": proc.name,
            "category": proc.category,
            "advertised_price": proc.advertised_price,
            "real_price": proc.real_price,
            "price_gap_note": proc.price_gap_note,
            "hidden_costs": proc.hidden_costs,
            "duration_type": proc.duration_type,
            "recommended_sessions": proc.recommended_sessions,
        }
        analysis = analyze_procedure_price(data)
        analyses.append(analysis)

    # ソート
    if sort_by == "hidden_costs":
        analyses.sort(key=lambda x: x.estimated_hidden_total or 0, reverse=True)
    elif sort_by == "annual_cost":
        analyses.sort(key=lambda x: x.annual_maintenance_cost or 0, reverse=True)
    else:
        analyses.sort(key=lambda x: x.gap_ratio or 0, reverse=True)

    # 統計サマリー
    ratios = [a.gap_ratio for a in analyses if a.gap_ratio]
    categories = {}
    for a in analyses:
        cat = a.gap_category
        categories[cat] = categories.get(cat, 0) + 1

    return {
        "rankings": [a.model_dump() for a in analyses],
        "total": len(analyses),
        "summary": {
            "average_gap_ratio": round(sum(ratios) / len(ratios), 1) if ratios else None,
            "max_gap_ratio": max(ratios) if ratios else None,
            "by_severity": {
                label: categories.get(key, 0)
                for key, label in GAP_LABELS.items()
            },
        },
        "methodology": {
            "description": "広告最低価格に対する実勢最低価格の倍率で乖離度を算出",
            "categories": GAP_LABELS,
        },
    }


@router.get("/price-gaps/{procedure_id}")
async def price_gap_detail(
    procedure_id: str,
    db: AsyncSession = Depends(get_db),
):
    """特定施術の価格乖離詳細"""
    result = await db.execute(
        select(ProcedureTable).where(ProcedureTable.id == procedure_id)
    )
    proc = result.scalar_one_or_none()
    if not proc:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="施術が見つかりません")

    data = {
        "name": proc.name,
        "category": proc.category,
        "advertised_price": proc.advertised_price,
        "real_price": proc.real_price,
        "price_gap_note": proc.price_gap_note,
        "hidden_costs": proc.hidden_costs,
        "duration_type": proc.duration_type,
        "recommended_sessions": proc.recommended_sessions,
    }
    analysis = analyze_procedure_price(data)
    return analysis.model_dump()


@router.get("/transparency")
async def transparency_ranking(
    city: str | None = Query(None, description="市区町村フィルタ"),
    grade: str | None = Query(None, description="グレードフィルタ（A/B/C/D/F）"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """
    クリニック透明性ランキング

    6軸100点でクリニックの情報開示度をスコアリング。
    """
    query = select(ClinicTable).where(ClinicTable.is_active == True)
    if city:
        query = query.where(ClinicTable.city == city)

    result = await db.execute(query)
    clinics = result.scalars().all()

    scores = []
    for clinic in clinics:
        data = {
            "id": clinic.id,
            "name": clinic.name,
            "address": clinic.address,
            "city": clinic.city,
            "phone": clinic.phone,
            "website": clinic.website,
            "lat": clinic.lat,
            "lng": clinic.lng,
            "medical_departments": clinic.medical_departments,
            "mhlw_code": clinic.mhlw_code,
            "google_rating": clinic.google_rating,
            "google_review_count": clinic.google_review_count,
        }
        score = calculate_transparency_score(data)
        scores.append(score)

    # グレードフィルタ
    if grade:
        scores = [s for s in scores if s.grade == grade.upper()]

    # スコア順ソート
    scores.sort(key=lambda x: x.score, reverse=True)

    # 統計
    total = len(scores)
    grade_dist = {}
    for s in scores:
        grade_dist[s.grade] = grade_dist.get(s.grade, 0) + 1

    avg_score = sum(s.score for s in scores) / total if total else 0

    # ページング
    start = (page - 1) * per_page
    paged = scores[start:start + per_page]

    return {
        "rankings": [s.model_dump() for s in paged],
        "total": total,
        "page": page,
        "per_page": per_page,
        "summary": {
            "average_score": round(avg_score, 1),
            "grade_distribution": grade_dist,
            "score_components": {
                "website": "Webサイトの有無（20点）",
                "data_completeness": "データ充填率（20点）",
                "department_diversity": "診療科の多様性（15点）",
                "mhlw_registered": "厚労省登録（15点）",
                "google_presence": "Google Maps存在（15点）",
                "coordinate_accuracy": "座標精度（15点）",
            },
        },
    }


@router.get("/transparency/{clinic_id}")
async def transparency_detail(
    clinic_id: str,
    db: AsyncSession = Depends(get_db),
):
    """特定クリニックの透明性スコア詳細"""
    result = await db.execute(
        select(ClinicTable).where(ClinicTable.id == clinic_id)
    )
    clinic = result.scalar_one_or_none()
    if not clinic:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="クリニックが見つかりません")

    data = {
        "id": clinic.id,
        "name": clinic.name,
        "address": clinic.address,
        "city": clinic.city,
        "phone": clinic.phone,
        "website": clinic.website,
        "lat": clinic.lat,
        "lng": clinic.lng,
        "medical_departments": clinic.medical_departments,
        "mhlw_code": clinic.mhlw_code,
        "google_rating": clinic.google_rating,
        "google_review_count": clinic.google_review_count,
    }
    score = calculate_transparency_score(data)
    return score.model_dump()


@router.get("/dashboard")
async def analysis_dashboard(db: AsyncSession = Depends(get_db)):
    """
    分析ダッシュボード

    価格乖離 + 透明性 + DB統計の統合ビュー。
    """
    # クリニック統計
    total_clinics = await db.scalar(select(func.count(ClinicTable.id)))

    # 施術の価格乖離集計
    result = await db.execute(select(ProcedureTable))
    procedures = result.scalars().all()

    gap_analyses = []
    for proc in procedures:
        data = {
            "name": proc.name,
            "category": proc.category,
            "advertised_price": proc.advertised_price,
            "real_price": proc.real_price,
            "price_gap_note": proc.price_gap_note,
            "hidden_costs": proc.hidden_costs,
            "duration_type": proc.duration_type,
            "recommended_sessions": proc.recommended_sessions,
        }
        gap_analyses.append(analyze_procedure_price(data))

    # TOP5 乖離施術
    gap_sorted = sorted(gap_analyses, key=lambda x: x.gap_ratio or 0, reverse=True)
    top5_gaps = [
        {
            "name": a.procedure_name,
            "advertised": a.advertised_display,
            "real": a.real_display,
            "gap_ratio": a.gap_ratio,
            "gap_category": a.gap_category,
        }
        for a in gap_sorted[:5]
    ]

    # 透明性サンプル（渋谷区TOP5）
    shibuya = await db.execute(
        select(ClinicTable).where(
            ClinicTable.city == "渋谷区",
            ClinicTable.is_active == True,
        ).limit(50)
    )
    shibuya_clinics = shibuya.scalars().all()
    shibuya_scores = []
    for c in shibuya_clinics:
        data = {
            "id": c.id, "name": c.name, "address": c.address,
            "city": c.city, "phone": c.phone, "website": c.website,
            "lat": c.lat, "lng": c.lng,
            "medical_departments": c.medical_departments,
            "mhlw_code": c.mhlw_code,
            "google_rating": c.google_rating,
            "google_review_count": c.google_review_count,
        }
        shibuya_scores.append(calculate_transparency_score(data))

    shibuya_scores.sort(key=lambda x: x.score, reverse=True)

    return {
        "overview": {
            "total_clinics": total_clinics or 0,
            "total_procedures": len(procedures),
            "data_source": "mhlw_20251201 + aura_navi_v1.1",
        },
        "price_gap_analysis": {
            "top5_inflated": top5_gaps,
            "severity_counts": {
                category: sum(1 for a in gap_analyses if a.gap_category == category)
                for category in ["mild", "moderate", "severe", "extreme"]
            },
        },
        "transparency_sample": {
            "area": "渋谷区",
            "sample_size": len(shibuya_scores),
            "average_score": round(
                sum(s.score for s in shibuya_scores) / len(shibuya_scores), 1
            ) if shibuya_scores else 0,
            "top5": [
                {"name": s.clinic_name, "score": s.score, "grade": s.grade}
                for s in shibuya_scores[:5]
            ],
        },
    }
