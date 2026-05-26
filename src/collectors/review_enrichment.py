"""
AURA MVP -- Google口コミテキスト取得スクリプト（Legacy API版）

Place IDが設定済みで口コミが未取得のクリニックについて、
Legacy Place Details APIで口コミテキストを取得しDBに格納する。

使い方:
    python -m src.collectors.review_enrichment --dry-run --limit 5
    python -m src.collectors.review_enrichment --limit 100
    python -m src.collectors.review_enrichment
"""

import argparse
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv
from ulid import ULID

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "aura.db"

# Legacy Place Details API
PLACE_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"

# API呼び出し間隔
API_CALL_INTERVAL = 1.0
PROGRESS_LOG_INTERVAL = 20


def get_api_key() -> str:
    """APIキー取得"""
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.environ.get("AURA_GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        logger.error("AURA_GOOGLE_MAPS_API_KEY を設定してください。")
        sys.exit(1)
    return api_key


def get_db_connection() -> sqlite3.Connection:
    """DB接続取得"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def fetch_target_clinics(conn: sqlite3.Connection, limit: int | None = None) -> list[dict]:
    """Place IDありで口コミ未取得のクリニックを取得する"""
    query = """
        SELECT c.id, c.name, c.google_place_id
        FROM clinics c
        WHERE c.google_place_id IS NOT NULL
          AND c.google_place_id != ''
          AND c.id NOT IN (
              SELECT DISTINCT clinic_id FROM reviews WHERE source IN ('google', 'google_legacy')
          )
        ORDER BY c.google_review_count DESC NULLS LAST
    """
    if limit:
        query += f" LIMIT {limit}"
    rows = conn.execute(query).fetchall()
    return [dict(row) for row in rows]


def fetch_reviews(client: httpx.Client, api_key: str, place_id: str) -> list[dict] | None:
    """Legacy Place Details APIで口コミを取得する"""
    params = {
        "place_id": place_id,
        "fields": "reviews",
        "key": api_key,
        "language": "ja",
        "reviews_sort": "newest",
    }

    try:
        response = client.get(PLACE_DETAILS_URL, params=params)
        if response.status_code != 200:
            logger.warning(f"  API error ({response.status_code})")
            return None

        data = response.json()
        if data.get("status") != "OK":
            if data.get("status") == "ZERO_RESULTS":
                return []
            logger.warning(f"  API status: {data.get('status')}")
            return None

        reviews = data.get("result", {}).get("reviews", [])
        return [
            {
                "author": r.get("author_name", ""),
                "rating": r.get("rating"),
                "text": r.get("text", "").strip(),
                "time": r.get("time"),  # Unix timestamp
            }
            for r in reviews
            if r.get("text", "").strip()
        ]

    except Exception as e:
        logger.warning(f"  Error: {e}")
        return None


def insert_reviews(conn: sqlite3.Connection, clinic_id: str, reviews: list[dict], dry_run: bool = False) -> int:
    """口コミをDBに挿入する"""
    count = 0
    for rev in reviews:
        if dry_run:
            logger.info(f"  [DRY-RUN] [{rev.get('rating')}★] {rev.get('text', '')[:50]}...")
            count += 1
            continue

        review_id = str(ULID())
        # Unix timestampからISO形式に変換
        created_at = None
        if rev.get("time"):
            try:
                created_at = datetime.utcfromtimestamp(rev["time"]).isoformat()
            except (ValueError, OSError):
                pass

        try:
            conn.execute(
                """
                INSERT INTO reviews (id, clinic_id, procedure_id, source, author_name, text, rating, created_at)
                VALUES (?, ?, NULL, 'google_legacy', ?, ?, ?, ?)
                """,
                (review_id, clinic_id, rev.get("author", ""), rev.get("text", ""), rev.get("rating"), created_at),
            )
            count += 1
        except sqlite3.Error as e:
            logger.error(f"  INSERT error: {e}")

    return count


def run_collector(dry_run: bool = False, limit: int | None = None):
    """口コミ取得メインループ"""
    mode = "DRY-RUN" if dry_run else "本番実行"
    logger.info(f"\n{'='*60}")
    logger.info(f"AURA MVP -- 口コミテキスト取得 (Legacy API)")
    logger.info(f"モード: {mode}")
    logger.info(f"{'='*60}")

    api_key = get_api_key()
    conn = get_db_connection()

    clinics = fetch_target_clinics(conn, limit=limit)
    total = len(clinics)

    if total == 0:
        logger.info("対象クリニックなし（全て取得済みまたはPlace IDなし）")
        conn.close()
        return

    logger.info(f"対象: {total}件")

    success = 0
    empty = 0
    failed = 0
    total_reviews = 0
    start_time = time.time()

    with httpx.Client(timeout=30.0) as client:
        for idx, clinic in enumerate(clinics, 1):
            logger.info(f"[{idx}/{total}] {clinic['name']}")

            reviews = fetch_reviews(client, api_key, clinic["google_place_id"])

            if reviews is None:
                failed += 1
            elif len(reviews) == 0:
                empty += 1
                success += 1
            else:
                inserted = insert_reviews(conn, clinic["id"], reviews, dry_run=dry_run)
                total_reviews += inserted
                success += 1
                logger.info(f"  -> {inserted}件の口コミを{'表示' if dry_run else '保存'}")

            if idx % PROGRESS_LOG_INTERVAL == 0:
                elapsed = time.time() - start_time
                rate = idx / elapsed if elapsed > 0 else 0
                remaining = (total - idx) / rate if rate > 0 else 0
                logger.info(
                    f"--- 進捗: {idx}/{total} ({idx/total*100:.1f}%) | "
                    f"口コミ累計: {total_reviews} | 残り約{remaining:.0f}秒 ---"
                )

            if idx < total:
                time.sleep(API_CALL_INTERVAL)

    if not dry_run:
        conn.commit()
        logger.info("DBコミット完了")

    elapsed = time.time() - start_time
    logger.info(f"\n{'='*60}")
    logger.info(f"最終結果")
    logger.info(f"{'='*60}")
    logger.info(f"  処理: {total}件")
    logger.info(f"  成功: {success}件 (口コミなし: {empty}件)")
    logger.info(f"  失敗: {failed}件")
    logger.info(f"  口コミ総数: {total_reviews}件")
    logger.info(f"  所要時間: {elapsed:.1f}秒")

    total_rev = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    logger.info(f"\n  DB: reviews テーブル総数: {total_rev}件")

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Google口コミテキストを取得しDBに格納する")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    run_collector(dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    main()
