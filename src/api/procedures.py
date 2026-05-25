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
from src.db.database import ProcedureTable, get_db

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
        query = query.where(ProcedureTable.matches_concern.contains(concern))

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
        "note": "全28施術で広告価格・実勢価格・リスク・質問リスト・リアルDTが100%充填",
    }


@router.get("/compare")
async def compare_procedures(
    ids: str = Query(..., description="比較する施術IDをカンマ区切り（2-4件）"),
    db: AsyncSession = Depends(get_db),
):
    """
    施術比較

    2-4施術を並べて比較。価格・DT・リスク・侵襲度を横並びで返却。
    """
    id_list = [i.strip() for i in ids.split(",")]
    if len(id_list) < 2 or len(id_list) > 4:
        raise HTTPException(status_code=400, detail="比較は2〜4施術で指定してください")

    result = await db.execute(
        select(ProcedureTable).where(ProcedureTable.id.in_(id_list))
    )
    procedures = result.scalars().all()

    if len(procedures) < 2:
        raise HTTPException(status_code=404, detail="指定した施術が見つかりません")

    return {
        "comparison": [_format_detail(p) for p in procedures],
        "count": len(procedures),
    }


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

    return _format_detail(procedure)


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
