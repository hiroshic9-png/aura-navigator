"""
AURA MVP — お気に入り・比較API

ユーザーのクリニック/施術のお気に入り管理と比較機能を提供する。
本番ではJWT認証と紐付けるが、MVP段階ではセッションベースで動作。
"""

import json
import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import get_db, ClinicTable

logger = logging.getLogger(__name__)
router = APIRouter()


# ==========================================
# スキーマ
# ==========================================


class FavoriteRequest(BaseModel):
    """お気に入り追加/削除リクエスト"""
    clinic_id: str = Field(..., description="クリニックID")


class FavoriteResponse(BaseModel):
    """お気に入り操作レスポンス"""
    session_id: str
    clinic_id: str
    action: str  # "added" or "removed"
    total_favorites: int


class CompareRequest(BaseModel):
    """比較リクエスト"""
    clinic_ids: list[str] = Field(..., min_length=2, max_length=5, description="比較するクリニックID（2〜5件）")
    procedure_id: str | None = Field(None, description="特定施術で比較する場合の施術ID")


class CompareResult(BaseModel):
    """比較結果"""
    clinics: list[dict]
    comparison_matrix: dict
    insights: list[str]


# ==========================================
# セッションストア（MVP用インメモリ）
# ==========================================

# 本番ではRedis or DB。MVP段階ではインメモリで十分。
_favorites_store: dict[str, set[str]] = {}


def _get_or_create_session(session_id: str | None) -> tuple[str, set[str]]:
    """セッションのお気に入りセットを取得（なければ作成）"""
    if not session_id:
        session_id = str(uuid4())
    if session_id not in _favorites_store:
        _favorites_store[session_id] = set()
    return session_id, _favorites_store[session_id]


# ==========================================
# お気に入りエンドポイント
# ==========================================


@router.post("/favorites")
async def toggle_favorite(
    req: FavoriteRequest,
    session_id: str = Query(None, description="セッションID"),
    db: AsyncSession = Depends(get_db),
):
    """お気に入りを追加/削除（トグル）"""
    # クリニックの存在確認
    clinic = await db.execute(
        select(ClinicTable).where(ClinicTable.id == req.clinic_id)
    )
    if clinic.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="クリニックが見つかりません")

    sid, favs = _get_or_create_session(session_id)

    if req.clinic_id in favs:
        favs.discard(req.clinic_id)
        action = "removed"
    else:
        if len(favs) >= 50:
            raise HTTPException(
                status_code=400,
                detail="お気に入りは50件までです",
            )
        favs.add(req.clinic_id)
        action = "added"

    return FavoriteResponse(
        session_id=sid,
        clinic_id=req.clinic_id,
        action=action,
        total_favorites=len(favs),
    )


@router.get("/favorites")
async def get_favorites(
    session_id: str = Query(None, description="セッションID"),
    db: AsyncSession = Depends(get_db),
):
    """お気に入り一覧を取得"""
    if not session_id or session_id not in _favorites_store:
        return {"session_id": session_id, "favorites": [], "total": 0}

    favs = _favorites_store[session_id]

    if not favs:
        return {"session_id": session_id, "favorites": [], "total": 0}

    # クリニック情報を取得
    result = await db.execute(
        select(ClinicTable).where(ClinicTable.id.in_(list(favs)))
    )
    clinics = result.scalars().all()

    favorites = []
    for c in clinics:
        favorites.append({
            "id": c.id,
            "name": c.name,
            "branch_name": c.branch_name,
            "address": c.address,
            "google_rating": c.google_rating,
            "google_review_count": c.google_review_count,
            "phone": c.phone,
            "website": c.website,
            "transparency_score": c.transparency_score,
        })

    return {
        "session_id": session_id,
        "favorites": favorites,
        "total": len(favorites),
    }


@router.delete("/favorites/{clinic_id}")
async def remove_favorite(
    clinic_id: str,
    session_id: str = Query(None, description="セッションID"),
):
    """お気に入りから削除"""
    if session_id and session_id in _favorites_store:
        _favorites_store[session_id].discard(clinic_id)

    total = len(_favorites_store.get(session_id, set()))
    return {"session_id": session_id, "removed": clinic_id, "total_favorites": total}


# ==========================================
# 比較エンドポイント
# ==========================================


@router.post("/compare")
async def compare_clinics(
    req: CompareRequest,
    db: AsyncSession = Depends(get_db),
):
    """複数クリニックを比較する"""
    # クリニック情報取得
    result = await db.execute(
        select(ClinicTable).where(ClinicTable.id.in_(req.clinic_ids))
    )
    clinics = result.scalars().all()

    if len(clinics) < 2:
        raise HTTPException(
            status_code=400,
            detail="比較には2つ以上の有効なクリニックIDが必要です",
        )

    # 基本比較データ構築
    clinic_data = []
    for c in clinics:
        data = {
            "id": c.id,
            "name": c.name,
            "branch_name": c.branch_name,
            "address": c.address,
            "google_rating": c.google_rating,
            "google_review_count": c.google_review_count,
            "phone": c.phone,
            "website": c.website,
            "transparency_score": c.transparency_score,
            "opening_hours": c.opening_hours,
            "doctor_count": c.doctor_count,
        }
        clinic_data.append(data)

    # 施術別価格比較（procedure_idが指定されている場合）
    price_comparison = {}
    if req.procedure_id:
        price_rows = await db.execute(
            text("""
                SELECT cp.clinic_id, cp.price_advertised, cp.price_display,
                       p.name as procedure_name
                FROM clinic_procedures cp
                JOIN procedures p ON cp.procedure_id = p.id
                WHERE cp.clinic_id IN :clinic_ids
                  AND cp.procedure_id = :proc_id
                  AND cp.price_advertised > 0
            """),
            {
                "clinic_ids": tuple(req.clinic_ids),
                "proc_id": req.procedure_id,
            },
        )
        for row in price_rows:
            price_comparison[row.clinic_id] = {
                "price": row.price_advertised,
                "display": row.price_display,
                "procedure": row.procedure_name,
            }

    # 比較マトリクス
    comparison_matrix = {
        "ratings": {c["id"]: c["google_rating"] for c in clinic_data},
        "review_counts": {c["id"]: c["google_review_count"] for c in clinic_data},
        "transparency_scores": {c["id"]: c["transparency_score"] for c in clinic_data},
        "has_phone": {c["id"]: bool(c["phone"]) for c in clinic_data},
        "has_website": {c["id"]: bool(c["website"]) for c in clinic_data},
        "doctor_counts": {c["id"]: c["doctor_count"] for c in clinic_data},
    }

    if price_comparison:
        comparison_matrix["prices"] = price_comparison

    # インサイト生成
    insights = _generate_comparison_insights(clinic_data, price_comparison)

    return {
        "clinics": clinic_data,
        "comparison_matrix": comparison_matrix,
        "insights": insights,
    }


def _generate_comparison_insights(
    clinics: list[dict],
    prices: dict,
) -> list[str]:
    """比較結果からインサイトを生成する"""
    insights = []

    # 評価の比較
    rated = [c for c in clinics if c.get("google_rating")]
    if rated:
        best = max(rated, key=lambda c: c["google_rating"])
        worst = min(rated, key=lambda c: c["google_rating"])
        if best["google_rating"] != worst["google_rating"]:
            diff = best["google_rating"] - worst["google_rating"]
            insights.append(
                f"Google評価は{best['name']}が最も高く（★{best['google_rating']}）、"
                f"最低の{worst['name']}（★{worst['google_rating']}）との差は{diff:.1f}です。"
            )

    # 口コミ数の比較
    reviewed = [c for c in clinics if c.get("google_review_count")]
    if reviewed:
        most_reviewed = max(reviewed, key=lambda c: c["google_review_count"])
        insights.append(
            f"口コミ数は{most_reviewed['name']}が最多（{most_reviewed['google_review_count']}件）です。"
        )

    # 透明性スコア
    scored = [c for c in clinics if c.get("transparency_score") is not None]
    if scored:
        best_t = max(scored, key=lambda c: c["transparency_score"])
        insights.append(
            f"透明性スコアは{best_t['name']}が最も高い（{best_t['transparency_score']:.1f}点）です。"
        )

    # 価格比較
    if prices and len(prices) >= 2:
        price_list = sorted(prices.items(), key=lambda x: x[1]["price"])
        cheapest_id = price_list[0][0]
        expensive_id = price_list[-1][0]
        cheapest_name = next(c["name"] for c in clinics if c["id"] == cheapest_id)
        expensive_name = next(c["name"] for c in clinics if c["id"] == expensive_id)
        diff_pct = (price_list[-1][1]["price"] - price_list[0][1]["price"]) / price_list[0][1]["price"] * 100

        insights.append(
            f"{prices[cheapest_id]['procedure']}の価格は{cheapest_name}が最安"
            f"（¥{price_list[0][1]['price']:,.0f}）。"
            f"{expensive_name}は{diff_pct:.0f}%高い（¥{price_list[-1][1]['price']:,.0f}）です。"
        )

    # 電話番号の有無
    no_phone = [c["name"] for c in clinics if not c.get("phone")]
    if no_phone and len(no_phone) < len(clinics):
        insights.append(
            f"注意: {', '.join(no_phone)}は電話番号が未登録です。"
        )

    return insights
