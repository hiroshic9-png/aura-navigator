"""
AURA MVP — データベース管理API

整合性チェック、データバージョン確認、バックアップ・エクスポート等の
管理用エンドポイント。
"""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import (
    AuditLog, ClinicTable, DataVersion, ProcedureTable,
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
