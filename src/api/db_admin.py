"""
AURA MVP — データベース管理API

整合性チェック、データバージョン確認、バックアップ・エクスポート等の
管理用エンドポイント。
"""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import (
    AuditLog, ClinicProcedure, ClinicTable, DataVersion,
    DoctorTable, ProcedureTable, ReviewTable,
    get_db,
)
from src.db.operations import check_db_integrity, export_table_json, get_latest_version

router = APIRouter()


@router.get("/health")
async def db_health(db: AsyncSession = Depends(get_db)):
    """DB整合性チェック"""
    report = await check_db_integrity(db)
    return report


@router.get("/versions")
async def data_versions(db: AsyncSession = Depends(get_db)):
    """データバージョン一覧"""
    result = await db.execute(
        select(DataVersion).order_by(DataVersion.completed_at.desc())
    )
    versions = result.scalars().all()

    return {
        "versions": [
            {
                "source": v.source,
                "version_key": v.version_key,
                "record_count": v.record_count,
                "status": v.status,
                "completed_at": v.completed_at.isoformat() if v.completed_at else None,
            }
            for v in versions
        ],
        "total": len(versions),
    }


@router.get("/audit")
async def audit_log(
    table: str = "",
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """監査ログ閲覧"""
    query = select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit)
    if table:
        query = query.where(AuditLog.table_name == table)

    result = await db.execute(query)
    logs = result.scalars().all()

    return {
        "logs": [
            {
                "id": log.id,
                "table": log.table_name,
                "record_id": log.record_id,
                "action": log.action,
                "changed_fields": json.loads(log.changed_fields) if log.changed_fields else None,
                "changed_by": log.changed_by,
                "source": log.source,
                "timestamp": log.timestamp.isoformat() if log.timestamp else None,
            }
            for log in logs
        ],
        "total": len(logs),
    }


@router.get("/export/{table}")
async def export_data(
    table: str,
    db: AsyncSession = Depends(get_db),
):
    """テーブルデータをJSONエクスポート"""
    valid_tables = {"clinics", "procedures"}
    if table not in valid_tables:
        raise HTTPException(400, f"エクスポート可能なテーブル: {valid_tables}")

    data = await export_table_json(db, table)
    return {
        "table": table,
        "exported_at": datetime.now().isoformat(),
        "record_count": len(data),
        "data": data,
    }


@router.get("/stats")
async def db_stats(db: AsyncSession = Depends(get_db)):
    """DB統計情報（詳細版）"""
    clinic_count = await db.scalar(select(func.count(ClinicTable.id)))
    proc_count = await db.scalar(select(func.count(ProcedureTable.id)))
    audit_count = await db.scalar(select(func.count(AuditLog.id)))
    version_count = await db.scalar(select(func.count(DataVersion.id)))

    # クリニック都市分布
    city_result = await db.execute(
        select(ClinicTable.city, func.count(ClinicTable.id))
        .where(ClinicTable.is_active == True)
        .group_by(ClinicTable.city)
        .order_by(func.count(ClinicTable.id).desc())
        .limit(10)
    )
    top_cities = city_result.all()

    # 施術カテゴリ分布
    cat_result = await db.execute(
        select(ProcedureTable.category, func.count(ProcedureTable.id))
        .group_by(ProcedureTable.category)
    )
    categories = cat_result.all()

    # 最新の来歴情報
    latest_mhlw = await get_latest_version(db, "mhlw")
    latest_navi = await get_latest_version(db, "navi")

    return {
        "counts": {
            "clinics": clinic_count or 0,
            "procedures": proc_count or 0,
            "audit_logs": audit_count or 0,
            "data_versions": version_count or 0,
        },
        "clinic_distribution": [
            {"city": c[0], "count": c[1]} for c in top_cities
        ],
        "procedure_categories": [
            {"category": c[0], "count": c[1]} for c in categories
        ],
        "latest_versions": {
            "mhlw": {
                "version": latest_mhlw.version_key if latest_mhlw else None,
                "records": latest_mhlw.record_count if latest_mhlw else 0,
                "at": latest_mhlw.completed_at.isoformat() if latest_mhlw and latest_mhlw.completed_at else None,
            },
            "navi": {
                "version": latest_navi.version_key if latest_navi else None,
                "records": latest_navi.record_count if latest_navi else 0,
                "at": latest_navi.completed_at.isoformat() if latest_navi and latest_navi.completed_at else None,
            },
        },
    }


@router.get("/data-quality")
async def data_quality_dashboard(db: AsyncSession = Depends(get_db)):
    """データ品質ダッシュボード — 管理者向けデータ充実度・品質指標の一括取得"""

    # --- 概要 ---
    total_clinics = await db.scalar(
        select(func.count(ClinicTable.id)).where(ClinicTable.is_active == True)
    ) or 0
    total_doctors = await db.scalar(
        select(func.count(DoctorTable.id)).where(DoctorTable.is_active == True)
    ) or 0
    total_reviews = await db.scalar(select(func.count(ReviewTable.id))) or 0
    total_procedures = await db.scalar(select(func.count(ProcedureTable.id))) or 0
    total_clinic_procedures = await db.scalar(select(func.count(ClinicProcedure.id))) or 0

    # --- 価格カバー率（カテゴリ別） ---
    # clinic_proceduresのうち price_advertised が入っているものの割合
    price_rows = await db.execute(
        select(
            ProcedureTable.category,
            func.count(ClinicProcedure.id).label("total"),
            func.count(
                case(
                    (ClinicProcedure.price_advertised.isnot(None), ClinicProcedure.id),
                    else_=None,
                )
            ).label("with_price"),
        )
        .join(ProcedureTable, ClinicProcedure.procedure_id == ProcedureTable.id)
        .group_by(ProcedureTable.category)
        .order_by(ProcedureTable.category)
    )
    by_category = []
    price_total_count = 0
    price_total_all = 0
    cat_labels = {
        "eye": "目元",
        "nose": "鼻",
        "skin": "肌",
        "contour": "輪郭",
        "anti_aging": "エイジング",
        "body": "痩身",
        "breast": "バスト",
        "hair_removal": "脱毛",
    }
    for row in price_rows:
        cat, total, with_price = row[0], row[1], row[2]
        pct = round(with_price / total * 100, 1) if total > 0 else 0
        by_category.append({
            "category": cat_labels.get(cat, cat or "その他"),
            "category_key": cat,
            "count": with_price,
            "total": total,
            "pct": pct,
        })
        price_total_count += with_price
        price_total_all += total

    price_coverage = {
        "total": {
            "count": price_total_count,
            "total": price_total_all,
            "pct": round(price_total_count / price_total_all * 100, 1) if price_total_all > 0 else 0,
        },
        "by_category": by_category,
    }

    # --- グレード分布 ---
    grade_rows = await db.execute(
        select(ClinicTable.clinic_grade, func.count(ClinicTable.id))
        .where(ClinicTable.is_active == True, ClinicTable.clinic_grade.isnot(None))
        .group_by(ClinicTable.clinic_grade)
        .order_by(ClinicTable.clinic_grade)
    )
    grade_distribution = [
        {"grade": g[0], "count": g[1]} for g in grade_rows
    ]

    # --- 口コミ品質 ---
    avg_rating = await db.scalar(
        select(func.avg(ReviewTable.rating)).where(ReviewTable.rating.isnot(None))
    )
    with_sentiment = await db.scalar(
        select(func.count(ReviewTable.id)).where(ReviewTable.sentiment_score.isnot(None))
    ) or 0
    with_aspects = await db.scalar(
        select(func.count(ReviewTable.id)).where(ReviewTable.aspects.isnot(None))
    ) or 0

    # 感情分布（sentiment_score を positive/neutral/negative に分類）
    pos_count = await db.scalar(
        select(func.count(ReviewTable.id)).where(ReviewTable.sentiment_score > 0.3)
    ) or 0
    neg_count = await db.scalar(
        select(func.count(ReviewTable.id)).where(ReviewTable.sentiment_score < -0.3)
    ) or 0
    neutral_count = total_reviews - pos_count - neg_count if total_reviews > 0 else 0

    sentiment_distribution = {}
    if total_reviews > 0:
        sentiment_distribution = {
            "positive": round(pos_count / total_reviews * 100, 1),
            "neutral": round(neutral_count / total_reviews * 100, 1),
            "negative": round(neg_count / total_reviews * 100, 1),
        }

    review_quality = {
        "total": total_reviews,
        "with_sentiment": with_sentiment,
        "with_aspects": with_aspects,
        "avg_rating": round(avg_rating, 2) if avg_rating else 0,
        "sentiment_distribution": sentiment_distribution,
    }

    # --- データ鮮度 ---
    last_clinic_update = await db.scalar(
        select(func.max(ClinicTable.updated_at))
    )
    last_review_update = await db.scalar(
        select(func.max(ReviewTable.created_at))
    )

    data_freshness = {
        "last_clinic_update": last_clinic_update.isoformat().split("T")[0] if last_clinic_update else None,
        "last_review_update": last_review_update.isoformat().split("T")[0] if last_review_update else None,
    }

    return {
        "overview": {
            "total_clinics": total_clinics,
            "total_doctors": total_doctors,
            "total_reviews": total_reviews,
            "total_procedures": total_procedures,
            "total_clinic_procedures": total_clinic_procedures,
        },
        "price_coverage": price_coverage,
        "grade_distribution": grade_distribution,
        "review_quality": review_quality,
        "data_freshness": data_freshness,
    }

