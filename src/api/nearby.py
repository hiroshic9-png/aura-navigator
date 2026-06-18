"""AURA MVP — 近隣クリニック検索API"""
import math
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.database import ClinicTable, get_db
from src.utils.normalize import normalize_query

router = APIRouter()


def haversine_distance(lat1, lng1, lat2, lng2):
    """2点間の距離をキロメートルで計算（Haversine公式）"""
    R = 6371  # 地球の半径（km）
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlng/2)**2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


@router.get("/nearby")
async def nearby_clinics(
    lat: float = Query(..., description="緯度"),
    lng: float = Query(..., description="経度"),
    radius_km: float = Query(3.0, ge=0.1, le=50, description="検索半径(km)"),
    limit: int = Query(20, ge=1, le=50, description="最大件数"),
    db: AsyncSession = Depends(get_db),
):
    """指定座標の近隣クリニックを検索（Haversine距離でソート）"""
    # バウンディングボックスで事前フィルタ（緯度1度≒111km）
    lat_delta = radius_km / 111.0
    lng_delta = radius_km / (111.0 * math.cos(math.radians(lat)))
    result = await db.execute(
        select(ClinicTable).where(
            ClinicTable.is_active == True,
            ClinicTable.lat.isnot(None),
            ClinicTable.lng.isnot(None),
            ClinicTable.lat != 0,
            ClinicTable.lng != 0,
            ClinicTable.lat.between(lat - lat_delta, lat + lat_delta),
            ClinicTable.lng.between(lng - lng_delta, lng + lng_delta),
        )
    )
    all_clinics = result.scalars().all()

    # Haversine距離でフィルタ・ソート
    nearby = []
    for c in all_clinics:
        dist = haversine_distance(lat, lng, c.lat, c.lng)
        if dist <= radius_km:
            nearby.append({
                "id": c.id,
                "name": c.name,
                "address": c.address,
                "city": c.city,
                "lat": c.lat,
                "lng": c.lng,
                "distance_km": round(dist, 2),
                "google_rating": c.google_rating,
                "google_review_count": c.google_review_count,
                "departments": c.medical_departments.split(',') if c.medical_departments else [],
                "transparency_score": c.transparency_score,
            })

    nearby.sort(key=lambda x: x["distance_km"])

    return {
        "center": {"lat": lat, "lng": lng},
        "radius_km": radius_km,
        "total": len(nearby),
        "clinics": nearby[:limit],
    }


@router.get("/suggest")
async def suggest_clinics(
    q: str = "",
    db: AsyncSession = Depends(get_db),
):
    """クリニック名のサジェスト（オートコンプリート）

    2文字以上の入力で、クリニック名の部分一致検索を行い
    最大8件のサジェスト候補を返却する。
    """
    if not q or len(q) < 2:
        return {"suggestions": []}

    q = normalize_query(q)

    stmt = (
        select(ClinicTable.id, ClinicTable.name, ClinicTable.address)
        .where(ClinicTable.is_active == True)
        .where(ClinicTable.name.contains(q))
        .limit(8)
    )
    result = await db.execute(stmt)
    rows = result.all()

    return {
        "suggestions": [
            {"id": r.id, "name": r.name, "address": r.address}
            for r in rows
        ]
    }

