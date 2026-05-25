"""
AURA MVP — Google口コミテキスト取得スクリプト（レガシーAPI版）

Place Details API（レガシー）のreviewsフィールドを使って、
各クリニックの口コミテキスト（最大5件/クリニック）を取得してDBに保存する。

使い方:
    uv run python -m src.collectors.review_fetcher          # ドライラン
    uv run python -m src.collectors.review_fetcher --execute # 実行
"""

import asyncio
import json
import sys
from datetime import datetime, timezone

import httpx

from src.config import settings


async def fetch_reviews():
    """全place_id付きクリニックの口コミテキストを取得してDBに保存"""
    from sqlalchemy import text
    from src.db.database import AsyncSessionLocal

    execute = "--execute" in sys.argv
    key = settings.google_maps_api_key

    if not key:
        print("❌ AURA_GOOGLE_MAPS_API_KEY が設定されていません")
        return

    async with AsyncSessionLocal() as db:
        # place_idがあり、まだ口コミテキストを取得していないクリニック
        result = await db.execute(text("""
            SELECT id, google_place_id, name
            FROM clinics
            WHERE google_place_id IS NOT NULL
            AND google_place_id != ''
            AND id NOT IN (SELECT DISTINCT clinic_id FROM reviews)
            ORDER BY google_review_count DESC
        """))
        clinics = result.fetchall()
        print(f"対象クリニック: {len(clinics)}件")

        if not execute:
            print("（ドライラン。--execute で実行）")
            return

        success = 0
        total_reviews = 0
        errors = 0

        async with httpx.AsyncClient(timeout=10.0) as client:
            for i, (clinic_id, place_id, name) in enumerate(clinics, 1):
                try:
                    url = (
                        f"https://maps.googleapis.com/maps/api/place/details/json"
                        f"?place_id={place_id}"
                        f"&fields=reviews"
                        f"&language=ja"
                        f"&key={key}"
                    )
                    r = await client.get(url)
                    data = r.json()

                    if data.get("status") != "OK":
                        errors += 1
                        if i % 50 == 0:
                            print(f"  [{i}/{len(clinics)}] {name}: {data.get('status')}")
                        continue

                    reviews = data.get("result", {}).get("reviews", [])
                    if not reviews:
                        if i % 50 == 0:
                            print(f"  [{i}/{len(clinics)}] {name}: 口コミなし")
                        continue

                    # DB保存
                    for rev in reviews:
                        review_text = rev.get("text", "")
                        if not review_text.strip():
                            continue

                        import ulid
                        review_id = str(ulid.ULID())
                        await db.execute(text("""
                            INSERT OR IGNORE INTO reviews (id, clinic_id, source, author_name, text, rating, created_at)
                            VALUES (:id, :clinic_id, 'google_legacy', :author, :text, :rating, :created_at)
                        """), {
                            "id": review_id,
                            "clinic_id": clinic_id,
                            "author": rev.get("author_name", ""),
                            "text": review_text,
                            "rating": rev.get("rating"),
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        })
                        total_reviews += 1

                    success += 1
                    if i % 20 == 0:
                        await db.commit()
                        print(f"  [{i}/{len(clinics)}] {success}件成功 / {total_reviews}件口コミ")

                    # レート制限（0.5秒間隔 — Place Details APIは比較的寛容）
                    await asyncio.sleep(0.5)

                except Exception as e:
                    errors += 1
                    if i % 50 == 0:
                        print(f"  [{i}/{len(clinics)}] エラー: {e}")

        await db.commit()
        print(f"\n{'='*60}")
        print(f"  口コミ取得完了")
        print(f"{'='*60}")
        print(f"  成功: {success}件")
        print(f"  取得口コミ: {total_reviews}件")
        print(f"  エラー: {errors}件")
        print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(fetch_reviews())
