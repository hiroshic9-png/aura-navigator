"""
AURA MVP — 通知API（Phase 30）

お気に入りクリニックの口コミ変動・レッドフラグを検知して通知を生成する。
favorite_idsはフロントエンドのlocalStorageからカンマ区切りで送信される。
"""

import json
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import ClinicTable, ReviewTable, get_db

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/notifications")
async def get_notifications(
    request: Request,
    favorite_ids: str = Query("", description="お気に入りクリニックID（カンマ区切り）"),
    db: AsyncSession = Depends(get_db),
):
    """
    通知API

    お気に入りクリニックについて以下の変動を検知して通知を返す:
    1. 新しいレッドフラグ口コミ（直近7日以内）
    2. 注意すべき口コミの傾向（直近の口コミのsentiment_scoreが低い場合）
    3. Google評価の変動（reviewsの最新日時と比較）

    favorite_idsが空の場合は空配列を返す。
    """
    # お気に入りIDをパース
    if not favorite_ids or not favorite_ids.strip():
        return {"notifications": [], "unread_count": 0}

    id_list = [fid.strip() for fid in favorite_ids.split(",") if fid.strip()]

    if not id_list:
        return {"notifications": [], "unread_count": 0}

    # お気に入りクリニックの情報を取得
    clinic_result = await db.execute(
        select(ClinicTable).where(ClinicTable.id.in_(id_list))
    )
    clinics = clinic_result.scalars().all()

    if not clinics:
        return {"notifications": [], "unread_count": 0}

    # クリニックIDから名前への逆引きマップ
    clinic_map = {c.id: c for c in clinics}

    notifications = []
    seven_days_ago = datetime.now() - timedelta(days=7)

    for clinic in clinics:
        # === 1. 新しいレッドフラグ口コミ（直近7日以内） ===
        red_flag_notifications = await _check_red_flags(
            db, clinic, seven_days_ago
        )
        notifications.extend(red_flag_notifications)

        # === 2. 注意すべき口コミの傾向 ===
        sentiment_notification = await _check_sentiment_trend(
            db, clinic, seven_days_ago
        )
        if sentiment_notification:
            notifications.append(sentiment_notification)

        # === 3. Google評価の変動 ===
        rating_notification = await _check_rating_change(
            db, clinic
        )
        if rating_notification:
            notifications.append(rating_notification)

    # 作成日時の降順でソート
    notifications.sort(
        key=lambda n: n.get("created_at", ""),
        reverse=True,
    )

    return {
        "notifications": notifications,
        "unread_count": len(notifications),
    }


async def _check_red_flags(
    db: AsyncSession,
    clinic: ClinicTable,
    since: datetime,
) -> list[dict]:
    """
    直近7日以内のレッドフラグ付き口コミを検出する

    red_flagsカラムがNULLでなく、空配列でもないものをカウント。
    """
    result = await db.execute(
        select(ReviewTable)
        .where(ReviewTable.clinic_id == clinic.id)
        .where(ReviewTable.is_spam != True)
        .where(ReviewTable.red_flags.isnot(None))
        .where(ReviewTable.red_flags != "[]")
        .where(ReviewTable.created_at >= since)
    )
    flagged_reviews = result.scalars().all()

    if not flagged_reviews:
        return []

    # レッドフラグのカテゴリを集計
    categories: dict[str, int] = {}
    for r in flagged_reviews:
        try:
            flags = json.loads(r.red_flags)
            for f in flags:
                cat = f.get("category", "unknown") if isinstance(f, dict) else str(f)
                categories[cat] = categories.get(cat, 0) + 1
        except (json.JSONDecodeError, TypeError):
            pass

    count = len(flagged_reviews)

    # 最新の口コミ日時を通知日時とする
    latest_date = max(
        (r.created_at for r in flagged_reviews if r.created_at),
        default=datetime.now(),
    )

    return [{
        "type": "red_flag",
        "clinic_id": clinic.id,
        "clinic_name": clinic.name,
        "message": f"新しい注意口コミが{count}件追加されました",
        "severity": "warning",
        "details": {"categories": categories, "count": count},
        "created_at": latest_date.isoformat(),
    }]


async def _check_sentiment_trend(
    db: AsyncSession,
    clinic: ClinicTable,
    since: datetime,
) -> dict | None:
    """
    直近の口コミの感情スコアが低下傾向にないか確認する

    直近7日間の平均sentiment_scoreが-0.2以下の場合に通知を生成。
    """
    result = await db.execute(
        select(
            func.count(ReviewTable.id),
            func.avg(ReviewTable.sentiment_score),
        )
        .where(ReviewTable.clinic_id == clinic.id)
        .where(ReviewTable.is_spam != True)
        .where(ReviewTable.sentiment_score.isnot(None))
        .where(ReviewTable.created_at >= since)
    )
    row = result.one()
    recent_count = row[0] or 0
    recent_avg = row[1]

    # データが少ない場合はスキップ
    if recent_count < 2 or recent_avg is None:
        return None

    # 平均感情スコアが-0.2以下で「注意」通知
    if recent_avg <= -0.2:
        return {
            "type": "sentiment_alert",
            "clinic_id": clinic.id,
            "clinic_name": clinic.name,
            "message": f"直近の口コミ{recent_count}件でネガティブな傾向が見られます（平均スコア: {recent_avg:.2f}）",
            "severity": "caution",
            "details": {
                "recent_count": recent_count,
                "avg_sentiment": round(recent_avg, 3),
            },
            "created_at": datetime.now().isoformat(),
        }

    return None


async def _check_rating_change(
    db: AsyncSession,
    clinic: ClinicTable,
) -> dict | None:
    """
    Google評価の変動を検知する

    直近の口コミの平均ratingとgoogle_ratingに乖離がある場合に通知。
    google_ratingが記録されている場合のみ判定する。
    """
    if clinic.google_rating is None:
        return None

    # 直近30日間の口コミの平均ratingを取得
    thirty_days_ago = datetime.now() - timedelta(days=30)
    result = await db.execute(
        select(
            func.count(ReviewTable.id),
            func.avg(ReviewTable.rating),
        )
        .where(ReviewTable.clinic_id == clinic.id)
        .where(ReviewTable.is_spam != True)
        .where(ReviewTable.rating.isnot(None))
        .where(ReviewTable.created_at >= thirty_days_ago)
    )
    row = result.one()
    recent_count = row[0] or 0
    recent_avg_rating = row[1]

    # データが少ない場合はスキップ
    if recent_count < 3 or recent_avg_rating is None:
        return None

    # 乖離判定（Google評価より0.5以上低い場合）
    diff = clinic.google_rating - recent_avg_rating
    if diff >= 0.5:
        return {
            "type": "rating_change",
            "clinic_id": clinic.id,
            "clinic_name": clinic.name,
            "message": (
                f"直近の口コミ評価（{recent_avg_rating:.1f}）が"
                f"Google評価（{clinic.google_rating:.1f}）を下回っています"
            ),
            "severity": "info",
            "details": {
                "google_rating": clinic.google_rating,
                "recent_avg_rating": round(recent_avg_rating, 1),
                "recent_review_count": recent_count,
                "difference": round(diff, 1),
            },
            "created_at": datetime.now().isoformat(),
        }

    return None
