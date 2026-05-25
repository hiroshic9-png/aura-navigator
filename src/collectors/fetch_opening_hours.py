"""
AURA MVP — Google Place Details で営業時間を取得

Google マッチ済みクリニック（google_place_id あり）に対して
Place Details API (New) を呼び出し、opening_hours を取得・DB更新する。

使い方:
    python -m src.collectors.fetch_opening_hours
    python -m src.collectors.fetch_opening_hours --limit 50  # テスト用
"""

import argparse
import asyncio
import json
import logging
import time

import httpx
from sqlalchemy import select, update

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def fetch_opening_hours(limit: int | None = None, dry_run: bool = False):
    """Googleマッチ済みクリニックの営業時間を取得"""
    from src.config import settings
    from src.db.database import AsyncSessionLocal, ClinicTable

    api_key = settings.google_maps_api_key
    if not api_key:
        logger.error("APIキーが設定されていません")
        return

    # 営業時間が空のGoogleマッチ済みクリニックを取得
    async with AsyncSessionLocal() as s:
        query = (
            select(ClinicTable)
            .where(
                ClinicTable.google_place_id.isnot(None),
                # 空のweekday_textを持つもの or NULLのもの
            )
        )
        if limit:
            query = query.limit(limit)
        result = await s.execute(query)
        clinics = result.scalars().all()

    # 実際に営業時間がない（空配列）のものだけをフィルタ
    targets = []
    for c in clinics:
        if not c.opening_hours:
            targets.append(c)
            continue
        try:
            hours = json.loads(c.opening_hours)
            wt = hours.get("weekday_text", [])
            if not wt or len(wt) == 0:
                targets.append(c)
        except (json.JSONDecodeError, AttributeError):
            targets.append(c)

    logger.info(f"営業時間取得対象: {len(targets)}件 / Googleマッチ済み: {len(clinics)}件")

    if dry_run:
        for c in targets[:10]:
            logger.info(f"  [DRY] {c.name} (place_id={c.google_place_id[:20]}...)")
        return

    # Place Details APIで営業時間を取得
    stats = {"fetched": 0, "updated": 0, "empty": 0, "error": 0}
    batch_size = 10

    async with httpx.AsyncClient(timeout=15) as client:
        for i, clinic in enumerate(targets):
            try:
                # Place Details (Legacy) API
                resp = await client.get(
                    "https://maps.googleapis.com/maps/api/place/details/json",
                    params={
                        "place_id": clinic.google_place_id,
                        "fields": "opening_hours,current_opening_hours",
                        "key": api_key,
                        "language": "ja",
                    },
                )
                data = resp.json()
                stats["fetched"] += 1

                if data.get("status") != "OK":
                    logger.warning(f"  API応答異常: {clinic.name} → {data.get('status')}")
                    stats["error"] += 1
                    continue

                place = data.get("result", {})
                hours = place.get("opening_hours") or place.get("current_opening_hours")

                if hours and hours.get("weekday_text"):
                    # 営業時間あり → DB更新
                    hours_json = json.dumps(
                        {"weekday_text": hours["weekday_text"]},
                        ensure_ascii=False,
                    )
                    async with AsyncSessionLocal() as s:
                        await s.execute(
                            update(ClinicTable)
                            .where(ClinicTable.id == clinic.id)
                            .values(opening_hours=hours_json)
                        )
                        await s.commit()
                    stats["updated"] += 1

                    if stats["updated"] <= 5:
                        logger.info(f"  ✅ {clinic.name}: {hours['weekday_text'][0]}...")
                else:
                    stats["empty"] += 1

                # レート制限回避（100ms間隔 = 最大10 QPS）
                await asyncio.sleep(0.12)

                # 進捗報告（50件ごと）
                if (i + 1) % 50 == 0:
                    logger.info(
                        f"  進捗: {i+1}/{len(targets)} "
                        f"(更新: {stats['updated']}, 空: {stats['empty']})"
                    )

            except Exception as e:
                logger.error(f"  ❌ {clinic.name}: {e}")
                stats["error"] += 1
                await asyncio.sleep(0.5)

    # 結果表示
    logger.info(f"\n{'='*50}")
    logger.info(f"営業時間取得完了")
    logger.info(f"{'='*50}")
    logger.info(f"API呼出: {stats['fetched']}件")
    logger.info(f"DB更新:  {stats['updated']}件")
    logger.info(f"営業時間なし: {stats['empty']}件")
    logger.info(f"エラー:  {stats['error']}件")


def main():
    parser = argparse.ArgumentParser(description="Google Place Detailsで営業時間を取得")
    parser.add_argument("--limit", type=int, help="処理件数制限（テスト用）")
    parser.add_argument("--dry-run", action="store_true", help="API呼出なしで対象を表示")
    args = parser.parse_args()

    asyncio.run(fetch_opening_hours(limit=args.limit, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
