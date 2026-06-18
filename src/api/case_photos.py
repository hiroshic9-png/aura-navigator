"""
AURA MVP — 症例写真検索API

美容クリニックの施術Before/After写真を検索・フィルタリングするAPIエンドポイント。
カテゴリ（目元/鼻/肌/輪郭/体/その他）やソース（SBC/TCB等）で絞り込み可能。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import CasePhotoTable, get_db

router = APIRouter()


@router.get("/")
async def search_case_photos(
    category: str | None = Query(
        None,
        description="カテゴリフィルタ（eyes/nose/skin/jawline/body/other）",
    ),
    procedure_id: str | None = Query(None, description="施術IDフィルタ"),
    clinic_id: str | None = Query(None, description="クリニックIDフィルタ"),
    source: str | None = Query(
        None,
        description="ソースフィルタ（sbc/tcb/shinagawa/tribeau）",
    ),
    page: int = Query(1, ge=1, description="ページ番号"),
    per_page: int = Query(20, ge=1, le=50, description="1ページあたりの件数"),
    db: AsyncSession = Depends(get_db),
):
    """
    症例写真検索

    Before/After写真をカテゴリ・施術・クリニック・ソースで絞り込み検索。
    ページネーション対応。before_image_urlがNULLのレコードは除外する。
    """
    # ベースクエリ: アクティブかつbefore画像があるもの
    query = (
        select(CasePhotoTable)
        .where(CasePhotoTable.is_active == True)
        .where(CasePhotoTable.before_image_url.isnot(None))
    )

    # カテゴリフィルタ
    if category:
        query = query.where(CasePhotoTable.category == category)

    # 施術IDフィルタ
    if procedure_id:
        query = query.where(CasePhotoTable.procedure_id == procedure_id)

    # クリニックIDフィルタ
    if clinic_id:
        query = query.where(CasePhotoTable.clinic_id == clinic_id)

    # ソースフィルタ
    if source:
        query = query.where(CasePhotoTable.source == source)

    # 新着順ソート
    query = query.order_by(CasePhotoTable.created_at.desc())

    # 総数取得
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)

    # ページネーション
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)

    result = await db.execute(query)
    photos = result.scalars().all()

    return {
        "case_photos": [_format_case_photo(p) for p in photos],
        "total": total or 0,
        "page": page,
        "total_pages": ((total or 0) + per_page - 1) // per_page,
    }


@router.get("/stats")
async def case_photo_stats(db: AsyncSession = Depends(get_db)):
    """
    症例写真統計

    カテゴリ別・ソース別の件数統計を返却。
    アクティブかつbefore画像があるレコードのみ集計対象。
    """
    # ベース条件
    base_condition = (
        (CasePhotoTable.is_active == True)
        & (CasePhotoTable.before_image_url.isnot(None))
    )

    # 総数
    total = await db.scalar(
        select(func.count(CasePhotoTable.id)).where(base_condition)
    )

    # カテゴリ別集計
    cat_result = await db.execute(
        select(
            CasePhotoTable.category,
            func.count(CasePhotoTable.id),
        )
        .where(base_condition)
        .group_by(CasePhotoTable.category)
        .order_by(func.count(CasePhotoTable.id).desc())
    )
    by_category = [
        {"category": row[0], "count": row[1]} for row in cat_result.all()
    ]

    # ソース別集計
    source_result = await db.execute(
        select(
            CasePhotoTable.source,
            func.count(CasePhotoTable.id),
        )
        .where(base_condition)
        .group_by(CasePhotoTable.source)
        .order_by(func.count(CasePhotoTable.id).desc())
    )
    by_source = [
        {"source": row[0], "count": row[1]} for row in source_result.all()
    ]

    return {
        "total": total or 0,
        "by_category": by_category,
        "by_source": by_source,
    }


def _format_case_photo(photo: CasePhotoTable) -> dict:
    """症例写真をAPIレスポンス用の辞書に変換"""
    return {
        "id": photo.id,
        "clinic_id": photo.clinic_id,
        "doctor_id": photo.doctor_id,
        "procedure_id": photo.procedure_id,
        "before_image_url": photo.before_image_url,
        "after_image_url": photo.after_image_url,
        "procedure_name": photo.procedure_name,
        "category": photo.category,
        "price": photo.price,
        "source": photo.source,
        "source_url": photo.source_url,
        "clinic_name": photo.clinic_name,
        "doctor_name": photo.doctor_name,
    }
