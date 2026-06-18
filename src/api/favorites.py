"""
AURA MVP — お気に入り・比較API

ユーザーのクリニック/施術のお気に入り管理と比較機能を提供する。
本番ではJWT認証と紐付けるが、MVP段階ではセッションベースで動作。
"""

import json
import logging
from collections import Counter
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import (
    get_db, ClinicTable, ClinicProcedure, ProcedureTable, ReviewTable,
)

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
    """
    複数クリニックを比較する

    各クリニックの基本情報に加え、施術価格・口コミセンチメント分布・
    強み/懸念点・共通施術の価格比較を返却する。
    N+1回避のため一括クエリを使用。
    """
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

    clinic_ids = [c.id for c in clinics]

    # === 施術データを一括取得（N+1回避） ===
    proc_result = await db.execute(
        select(ClinicProcedure, ProcedureTable)
        .join(ProcedureTable, ClinicProcedure.procedure_id == ProcedureTable.id)
        .where(ClinicProcedure.clinic_id.in_(clinic_ids))
        .where(ClinicProcedure.is_active == True)
    )
    proc_rows = proc_result.all()

    # クリニックごとの施術マップ: {clinic_id: [(proc_name, price, proc_id), ...]}
    clinic_procs: dict[str, list[tuple[str, int | None, str]]] = {}
    # 施術ごとのクリニック価格マップ: {proc_name: {clinic_id: price}}
    procedure_clinic_prices: dict[str, dict[str, int | None]] = {}
    # 施術ごとのクリニック価格ソースマップ: {proc_name: {clinic_id: source}}
    procedure_clinic_sources: dict[str, dict[str, str]] = {}
    for cp, proc in proc_rows:
        clinic_procs.setdefault(cp.clinic_id, []).append(
            (proc.name, cp.price_advertised, proc.id)
        )
        procedure_clinic_prices.setdefault(proc.name, {})[cp.clinic_id] = cp.price_advertised
        procedure_clinic_sources.setdefault(proc.name, {})[cp.clinic_id] = cp.source or 'unknown'

    # === 口コミデータを一括取得 ===
    reviews_result = await db.execute(
        select(ReviewTable)
        .where(ReviewTable.clinic_id.in_(clinic_ids))
        .where(ReviewTable.is_spam != True)
    )
    all_reviews = reviews_result.scalars().all()

    # クリニックごとの口コミリスト
    clinic_reviews: dict[str, list] = {}
    for r in all_reviews:
        clinic_reviews.setdefault(r.clinic_id, []).append(r)

    # === 各クリニックの比較データ構築 ===
    clinic_data = []
    for c in clinics:
        # 施術上位3件（価格降順、価格nullは末尾）
        procs = clinic_procs.get(c.id, [])
        procs_sorted = sorted(
            procs,
            key=lambda x: x[1] if x[1] is not None else 0,
            reverse=True,
        )[:3]
        top_procedures = []
        for name, price, pid in procs_sorted:
            top_procedures.append({
                "name": name,
                "price": price,
                "price_display": f"\u00a5{price:,}" if price else None,
            })

        # 口コミセンチメント分布
        reviews = clinic_reviews.get(c.id, [])
        pos_count = 0
        neu_count = 0
        neg_count = 0
        for r in reviews:
            if r.sentiment_score is not None:
                if r.sentiment_score > 0.2:
                    pos_count += 1
                elif r.sentiment_score < -0.2:
                    neg_count += 1
                else:
                    neu_count += 1
        scored_total = pos_count + neu_count + neg_count
        if scored_total > 0:
            review_sentiment = {
                "positive": round(pos_count / scored_total * 100),
                "neutral": round(neu_count / scored_total * 100),
                "negative": round(neg_count / scored_total * 100),
            }
        else:
            review_sentiment = {"positive": 0, "neutral": 0, "negative": 0}

        # 強み/懸念点の抽出
        strengths = _extract_compare_highlights(reviews, positive=True)
        concerns = _extract_compare_highlights(reviews, positive=False)

        data = {
            "id": c.id,
            "name": c.name,
            "city": c.city,
            "clinic_grade": c.clinic_grade,
            "clinic_score": c.clinic_score,
            "google_rating": c.google_rating,
            "google_review_count": c.google_review_count,
            "transparency_score": c.transparency_score,
            "editorial_summary": c.editorial_summary,
            "top_procedures": top_procedures,
            "review_sentiment": review_sentiment,
            "strengths": strengths,
            "concerns": concerns,
        }
        clinic_data.append(data)

    # === 共通施術の価格比較を生成 ===
    common_procedures = []
    clinic_id_set = set(clinic_ids)
    for proc_name, prices_map in procedure_clinic_prices.items():
        # 全比較クリニックがこの施術を提供しているか
        if set(prices_map.keys()) >= clinic_id_set:
            sources_map = procedure_clinic_sources.get(proc_name, {})
            common_procedures.append({
                "name": proc_name,
                "prices": {cid: prices_map.get(cid) for cid in clinic_ids},
                "sources": {cid: sources_map.get(cid, 'unknown') for cid in clinic_ids},
            })
    # 施術名でソート
    common_procedures.sort(key=lambda x: x["name"])

    # 比較マトリクス（後方互換性維持）
    comparison_matrix = {
        "ratings": {c["id"]: c["google_rating"] for c in clinic_data},
        "review_counts": {c["id"]: c["google_review_count"] for c in clinic_data},
        "transparency_scores": {c["id"]: c["transparency_score"] for c in clinic_data},
    }

    # インサイト生成
    insights = _generate_comparison_insights(clinic_data, {})

    return {
        "clinics": clinic_data,
        "common_procedures": common_procedures,
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


# ハイライト抽出用キーワード（比較モーダル用）
_COMPARE_POSITIVE_KEYWORDS: list[str] = [
    "カウンセリングが丁寧", "説明が丁寧", "清潔", "きれい",
    "仕上がりが自然", "痛みが少ない", "スタッフが親切",
    "親切", "丁寧", "安心", "コスパ", "リーズナブル",
    "アフターケアが充実", "予約が取りやすい", "個室",
]

_COMPARE_NEGATIVE_KEYWORDS: list[str] = [
    "待ち時間が長い", "待たされ", "予約が取れない",
    "追加料金", "強引な勧誘", "押し売り",
    "態度が悪い", "冷たい", "不自然", "左右差",
    "説明不足", "狭い",
]


def _extract_compare_highlights(reviews: list, positive: bool = True) -> list[str]:
    """
    比較用ハイライト（強み / 懸念点）を抽出する

    sentiment_scoreが高い/低い口コミからキーワードマッチで頻出フレーズを抽出。
    上位3件を返す。
    """
    keywords = _COMPARE_POSITIVE_KEYWORDS if positive else _COMPARE_NEGATIVE_KEYWORDS
    threshold = 0.1 if positive else -0.1

    matched: list[str] = []
    for r in reviews:
        if r.sentiment_score is None or not r.text:
            continue
        if positive and r.sentiment_score < threshold:
            continue
        if not positive and r.sentiment_score > threshold:
            continue
        for kw in keywords:
            if kw in r.text:
                matched.append(kw)

    # 頻出順に上位3件（重複なし）
    counter = Counter(matched)
    result = []
    for kw, _ in counter.most_common():
        if kw not in result and len(result) < 3:
            result.append(kw)
    return result
