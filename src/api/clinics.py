"""
AURA MVP — クリニック検索API

東京の美容クリニックを検索・比較するためのAPIエンドポイント。
"""

import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import ClinicTable, get_db

router = APIRouter()


@router.get("/")
async def search_clinics(
    q: str | None = Query(None, description="フリーワード検索（クリニック名、住所等）"),
    city: str | None = Query(None, description="市区町村フィルタ（例: 新宿区）"),
    department: str | None = Query(None, description="診療科目フィルタ（美容外科/形成外科/美容皮膚科）"),
    min_rating: float | None = Query(None, ge=1.0, le=5.0, description="最低Google評価"),
    has_website: bool | None = Query(None, description="Webサイトの有無"),
    sort_by: str = Query("name", description="ソート基準（name/rating/review_count）"),
    page: int = Query(1, ge=1, description="ページ番号"),
    per_page: int = Query(20, ge=1, le=100, description="1ページあたりの件数"),
    db: AsyncSession = Depends(get_db),
):
    """
    クリニック検索

    東京都内の美容クリニックを条件指定で検索。
    厚労省オープンデータ + Google Maps APIの統合データから結果を返却。
    """
    query = select(ClinicTable).where(ClinicTable.is_active == True)

    # フリーワード検索
    if q:
        query = query.where(
            or_(
                ClinicTable.name.contains(q),
                ClinicTable.address.contains(q),
                ClinicTable.chain_name.contains(q),
            )
        )

    # 市区町村フィルタ
    if city:
        query = query.where(ClinicTable.city == city)

    # 診療科目フィルタ
    if department:
        query = query.where(ClinicTable.medical_departments.contains(department))

    # Google評価フィルタ
    if min_rating is not None:
        query = query.where(ClinicTable.google_rating >= min_rating)

    # Webサイト有無
    if has_website is not None:
        if has_website:
            query = query.where(ClinicTable.website != "", ClinicTable.website.isnot(None))
        else:
            query = query.where(
                or_(ClinicTable.website == "", ClinicTable.website.is_(None))
            )

    # ソート
    if sort_by == "rating":
        query = query.order_by(ClinicTable.google_rating.desc().nullslast())
    elif sort_by == "review_count":
        query = query.order_by(ClinicTable.google_review_count.desc().nullslast())
    else:
        query = query.order_by(ClinicTable.name)

    # 総数取得
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)

    # ページング
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)

    result = await db.execute(query)
    clinics = result.scalars().all()

    return {
        "clinics": [_format_clinic(c) for c in clinics],
        "total": total or 0,
        "page": page,
        "per_page": per_page,
        "total_pages": ((total or 0) + per_page - 1) // per_page,
        "data_freshness": {
            "source": "mhlw",
            "source_version": "20251201",
            "note": "厚労省医療情報ネット 2025年12月1日時点データ",
        },
    }


@router.get("/stats")
async def clinic_stats(db: AsyncSession = Depends(get_db)):
    """
    クリニックDB統計情報

    区別・診療科別の集計データを返却。
    """
    # 総数
    total = await db.scalar(select(func.count(ClinicTable.id)))

    # 区別集計
    city_result = await db.execute(
        select(ClinicTable.city, func.count(ClinicTable.id))
        .where(ClinicTable.city != "", ClinicTable.city.isnot(None))
        .group_by(ClinicTable.city)
        .order_by(func.count(ClinicTable.id).desc())
        .limit(25)
    )
    by_city = [{"city": row[0], "count": row[1]} for row in city_result.all()]

    # Webサイト有無
    with_website = await db.scalar(
        select(func.count(ClinicTable.id)).where(
            ClinicTable.website != "", ClinicTable.website.isnot(None)
        )
    )

    # 座標有無
    with_coords = await db.scalar(
        select(func.count(ClinicTable.id)).where(
            ClinicTable.lat != 0, ClinicTable.lng != 0
        )
    )

    # Google評価あり
    with_rating = await db.scalar(
        select(func.count(ClinicTable.id)).where(ClinicTable.google_rating.isnot(None))
    )

    # 鮮度チェック
    from src.analyzers.freshness import FreshnessChecker
    checker = FreshnessChecker(db)
    freshness_report = await checker.check_clinic_freshness()

    return {
        "total": total or 0,
        "with_website": with_website or 0,
        "with_coordinates": with_coords or 0,
        "with_google_rating": with_rating or 0,
        "by_city": by_city,
        "data_source": "mhlw_opendata_20251201",
        "freshness": freshness_report,
    }


@router.get("/{clinic_id}")
async def get_clinic(clinic_id: str, db: AsyncSession = Depends(get_db)):
    """
    クリニック詳細取得

    指定IDのクリニック詳細情報を返却。医師情報・施術データも含む。
    """
    result = await db.execute(select(ClinicTable).where(ClinicTable.id == clinic_id))
    clinic = result.scalar_one_or_none()

    if not clinic:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="クリニックが見つかりません")

    data = _format_clinic(clinic, detail=True)

    # 医師情報を取得
    from src.db.database import DoctorTable
    doc_result = await db.execute(
        select(DoctorTable)
        .where(DoctorTable.clinic_id == clinic_id)
        .order_by(DoctorTable.title.desc())
    )
    doctors = doc_result.scalars().all()
    data["doctors"] = [
        {
            "name": d.name,
            "title": d.title or "",
            "specialties": json.loads(d.specialties) if d.specialties else [],
            "certifications": json.loads(d.board_certifications) if d.board_certifications else [],
        }
        for d in doctors
    ]

    # 施術データを取得
    from src.db.database import ClinicProcedure, ProcedureTable
    cp_result = await db.execute(
        select(ClinicProcedure, ProcedureTable.name, ProcedureTable.category)
        .join(ProcedureTable, ClinicProcedure.procedure_id == ProcedureTable.id)
        .where(ClinicProcedure.clinic_id == clinic_id)
        .where(ClinicProcedure.is_active == True)
    )
    procedures = cp_result.all()
    data["procedures"] = [
        {
            "name": row[1],
            "category": row[2],
            "source": row[0].source,
            "price_advertised": row[0].price_advertised,
        }
        for row in procedures
    ]

    # 口コミを取得（最新5件、スパムを除外）
    from src.db.database import ReviewTable
    rev_result = await db.execute(
        select(ReviewTable)
        .where(ReviewTable.clinic_id == clinic_id)
        .where(ReviewTable.is_spam != True)
        .order_by(ReviewTable.created_at.desc())
        .limit(5)
    )
    reviews = rev_result.scalars().all()
    data["reviews"] = [
        {
            "text": r.text[:200] + ("…" if len(r.text or "") > 200 else ""),
            "rating": r.rating,
            "author": r.author_name or "",
            "sentiment": r.sentiment_score,
        }
        for r in reviews
    ]

    return data


def _format_clinic(clinic: ClinicTable, detail: bool = False) -> dict:
    """クリニックデータのフォーマット"""
    data = {
        "id": clinic.id,
        "name": clinic.name,
        "branch_name": clinic.branch_name,
        "chain_name": clinic.chain_name,
        "address": clinic.address,
        "city": clinic.city,
        "lat": clinic.lat,
        "lng": clinic.lng,
        "website": clinic.website,
        "google_rating": clinic.google_rating,
        "google_review_count": clinic.google_review_count,
        "transparency_score": clinic.transparency_score,
        "departments": json.loads(clinic.medical_departments) if clinic.medical_departments else [],
        "data_quality": {
            "source": "厚生労働省 医療情報ネット" if (clinic.source or "") == "mhlw" else (clinic.source or "不明"),
            "data_date": "2025-12-01",
            "publish_status": getattr(clinic, "publish_status", "verified") or "verified",
        },
    }

    # 一覧表示用のサムネイル（写真がある場合、1枚目の参照キーを返す）
    photos_raw = json.loads(clinic.google_photos) if clinic.google_photos else []
    if photos_raw and len(photos_raw) > 0:
        data["thumbnail_ref"] = photos_raw[0]

    if detail:
        from src.analyzers.freshness import build_freshness_metadata
        freshness = build_freshness_metadata(
            source=clinic.source,
            fetched_at=getattr(clinic, 'fetched_at', None) or clinic.created_at,
            source_version=getattr(clinic, 'source_version', '') or '',
        )
        data.update({
            "phone": clinic.phone,
            "mhlw_code": clinic.mhlw_code,
            "medical_corp_name": clinic.medical_corp_name,
            "doctor_count": clinic.doctor_count,
            "google_place_id": clinic.google_place_id,
            "opening_hours": json.loads(clinic.opening_hours) if clinic.opening_hours else None,
            "editorial_summary": clinic.editorial_summary,
            "photos": json.loads(clinic.google_photos) if clinic.google_photos else [],
            "data_provenance": {
                "source": clinic.source,
                "source_version": getattr(clinic, 'source_version', ''),
                "fetched_at": (getattr(clinic, 'fetched_at', None) or clinic.created_at).isoformat() if (getattr(clinic, 'fetched_at', None) or clinic.created_at) else None,
                "verified_at": clinic.verified_at.isoformat() if getattr(clinic, 'verified_at', None) else None,
                "confidence": getattr(clinic, 'confidence', 1.0),
                "publish_status": getattr(clinic, 'publish_status', 'verified'),
                "freshness": freshness.freshness,
                "days_old": freshness.days_old,
            },
        })

    return data


@router.get("/{clinic_id}/photo")
async def get_clinic_photo(
    clinic_id: str,
    ref: str = Query(..., description="Google Photosの参照キー"),
    maxwidth: int = Query(600, ge=100, le=1600, description="最大幅"),
):
    """
    クリニック写真プロキシ

    Google Places Photo APIのphoto_referenceを使って画像を取得し、
    バイナリとして返却する。APIキーをフロントエンドに露出させない。
    """
    import httpx
    from fastapi.responses import Response

    from src.config import settings

    if not settings.google_maps_api_key:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Google Maps APIキー未設定")

    # Google Places Photo API（レガシー）
    photo_url = (
        f"https://maps.googleapis.com/maps/api/place/photo"
        f"?maxwidth={maxwidth}"
        f"&photo_reference={ref}"
        f"&key={settings.google_maps_api_key}"
    )

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
            resp = await client.get(photo_url)
            if resp.status_code == 200:
                content_type = resp.headers.get("content-type", "image/jpeg")
                return Response(
                    content=resp.content,
                    media_type=content_type,
                    headers={
                        "Cache-Control": "public, max-age=86400",  # 24時間キャッシュ
                    },
                )
            else:
                from fastapi import HTTPException
                raise HTTPException(status_code=resp.status_code, detail="写真取得に失敗")
    except httpx.TimeoutException:
        from fastapi import HTTPException
        raise HTTPException(status_code=504, detail="写真取得タイムアウト")

