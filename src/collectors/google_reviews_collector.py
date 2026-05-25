"""
AURA MVP — Google口コミテキスト取得スクリプト

DBのclinicsテーブルに google_place_id が存在するクリニックについて、
Google Places API (New) の Place Details エンドポイントで口コミテキストを取得し、
reviews テーブルに格納するバッチスクリプト。

使い方:
    # ドライラン（3件のみテスト）
    python -m src.collectors.google_reviews_collector --dry-run --limit 3

    # 全件実行
    python -m src.collectors.google_reviews_collector

    # 件数制限付き
    python -m src.collectors.google_reviews_collector --limit 50
"""

import argparse
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv
from ulid import ULID

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# プロジェクトルートを基準にDBパスを解決
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "aura.db"

# Google Places API (New) エンドポイント
PLACES_API_BASE = "https://places.googleapis.com/v1/places"

# Place Details で口コミのみ要求するフィールドマスク
REVIEW_FIELD_MASK = "reviews"

# レート制限（秒/リクエスト）
API_CALL_INTERVAL = 2.0

# 進捗ログ表示間隔
PROGRESS_LOG_INTERVAL = 10


def get_api_key() -> str:
    """Google Maps APIキーを環境変数または.envから取得する"""
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.environ.get("AURA_GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        logger.error("APIキーが見つかりません。環境変数 AURA_GOOGLE_MAPS_API_KEY を設定してください。")
        sys.exit(1)
    return api_key


def get_db_connection() -> sqlite3.Connection:
    """SQLiteデータベースへの同期接続を取得する"""
    if not DB_PATH.exists():
        logger.error(f"データベースが見つかりません: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def fetch_target_clinics(conn: sqlite3.Connection, limit: int | None = None) -> list[dict]:
    """
    google_place_idが存在し、まだ口コミ未取得のクリニックを取得する

    既にreviewsテーブルにsource='google'のレコードがあるクリニックはスキップ。
    """
    query = """
        SELECT c.id, c.name, c.google_place_id
        FROM clinics c
        WHERE c.google_place_id IS NOT NULL
          AND c.google_place_id != ''
          AND c.id NOT IN (
              SELECT DISTINCT clinic_id FROM reviews WHERE source = 'google'
          )
        ORDER BY c.name
    """
    if limit:
        query += f" LIMIT {limit}"

    rows = conn.execute(query).fetchall()
    return [dict(row) for row in rows]


def fetch_reviews_from_api(
    client: httpx.Client,
    api_key: str,
    place_id: str,
) -> list[dict] | None:
    """
    Google Places API (New) の Place Details で口コミを取得する

    Args:
        client: HTTPクライアント
        api_key: Google Maps APIキー
        place_id: Google Place ID（ChIJ... 形式）

    Returns:
        口コミリスト、またはエラー時None
    """
    url = f"{PLACES_API_BASE}/{place_id}"
    headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": REVIEW_FIELD_MASK,
    }

    response = client.get(url, headers=headers)

    if response.status_code != 200:
        logger.warning(
            f"API エラー (HTTP {response.status_code}): {response.text[:200]}"
        )
        return None

    data = response.json()
    return _extract_reviews(data.get("reviews", []))


def _extract_reviews(reviews: list[dict]) -> list[dict]:
    """
    APIレスポンスからレビュー情報を構造化する

    Google Places API (New) のレビューレスポンス形式に準拠。
    1リクエストあたり最大5件が返却される。
    """
    extracted = []
    for review in reviews[:5]:
        text = review.get("text", {}).get("text", "")
        if not text or not text.strip():
            # テキストが空のレビューはスキップ
            continue

        extracted.append({
            "author": review.get("authorAttribution", {}).get("displayName", ""),
            "rating": review.get("rating"),
            "text": text.strip(),
            "time": review.get("publishTime", ""),
        })
    return extracted


def parse_publish_time(time_str: str) -> datetime | None:
    """
    Google Places APIの投稿日時（RFC 3339）をdatetimeに変換する

    Args:
        time_str: "2024-01-15T10:30:00Z" 等のISO形式文字列

    Returns:
        datetimeオブジェクト、パース失敗時はNone
    """
    if not time_str:
        return None
    try:
        # "Z"をUTCタイムゾーンとして扱う
        return datetime.fromisoformat(time_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        logger.debug(f"日時パース失敗: {time_str}")
        return None


def insert_reviews(
    conn: sqlite3.Connection,
    clinic_id: str,
    reviews: list[dict],
    dry_run: bool = False,
) -> int:
    """
    取得した口コミをreviewsテーブルにINSERTする

    Args:
        conn: DB接続
        clinic_id: クリニックID
        reviews: 口コミリスト
        dry_run: Trueの場合、実際のINSERTは行わない

    Returns:
        挿入した件数
    """
    if not reviews:
        return 0

    insert_count = 0
    for review in reviews:
        review_id = str(ULID())
        created_at = parse_publish_time(review.get("time", ""))

        if dry_run:
            logger.info(
                f"  [DRY-RUN] INSERT: ★{review.get('rating', '?')} "
                f"by {review.get('author', '匿名')[:20]} — "
                f"{review.get('text', '')[:50]}..."
            )
            insert_count += 1
            continue

        try:
            conn.execute(
                """
                INSERT INTO reviews (id, clinic_id, procedure_id, source, author_name, text, rating, created_at)
                VALUES (?, ?, NULL, 'google', ?, ?, ?, ?)
                """,
                (
                    review_id,
                    clinic_id,
                    review.get("author", ""),
                    review.get("text", ""),
                    review.get("rating"),
                    created_at.isoformat() if created_at else None,
                ),
            )
            insert_count += 1
        except sqlite3.Error as e:
            logger.error(f"  INSERT失敗: {e}")

    return insert_count


def print_progress(
    processed: int,
    total: int,
    success: int,
    failed: int,
    total_reviews: int,
    start_time: float,
):
    """進捗統計を表示する"""
    elapsed = time.time() - start_time
    rate = processed / elapsed if elapsed > 0 else 0
    remaining = (total - processed) / rate if rate > 0 else 0

    logger.info(
        f"━━━ 進捗: {processed}/{total}件 "
        f"({processed / total * 100:.1f}%) ━━━\n"
        f"    成功: {success} | 失敗: {failed} | 口コミ累計: {total_reviews}\n"
        f"    経過: {elapsed:.0f}秒 | 残り: {remaining:.0f}秒 | "
        f"速度: {rate:.2f}件/秒"
    )


def run_collector(
    dry_run: bool = False,
    limit: int | None = None,
):
    """
    口コミ取得のメインループ

    Args:
        dry_run: Trueの場合、DBへの書き込みを行わない
        limit: 処理するクリニック数の上限
    """
    mode_label = "🔍 DRY-RUN モード" if dry_run else "🚀 本番実行モード"
    logger.info(f"\n{'='*60}")
    logger.info(f"AURA MVP — Google口コミ取得スクリプト")
    logger.info(f"モード: {mode_label}")
    logger.info(f"{'='*60}")

    # APIキー取得
    api_key = get_api_key()
    logger.info("✅ APIキー確認済み")

    # DB接続
    conn = get_db_connection()
    logger.info(f"✅ DB接続: {DB_PATH}")

    # 対象クリニック取得
    clinics = fetch_target_clinics(conn, limit=limit)
    total = len(clinics)

    if total == 0:
        logger.info("ℹ️  対象クリニックがありません（全て取得済みまたはgoogle_place_idなし）")
        conn.close()
        return

    logger.info(f"📋 対象クリニック: {total}件")
    if limit:
        logger.info(f"   （--limit {limit} による制限）")
    logger.info("")

    # 統計変数
    success_count = 0
    fail_count = 0
    skip_count = 0
    total_reviews = 0
    errors: list[dict] = []
    start_time = time.time()

    # HTTPクライアント（接続再利用でパフォーマンス向上）
    with httpx.Client(timeout=30.0) as client:
        for idx, clinic in enumerate(clinics, 1):
            clinic_id = clinic["id"]
            clinic_name = clinic["name"]
            place_id = clinic["google_place_id"]

            logger.info(f"[{idx}/{total}] {clinic_name} (place_id: {place_id[:20]}...)")

            # API呼び出し
            reviews = fetch_reviews_from_api(client, api_key, place_id)

            if reviews is None:
                fail_count += 1
                errors.append({
                    "clinic_name": clinic_name,
                    "place_id": place_id,
                    "reason": "API呼び出し失敗",
                })
                logger.warning(f"  ❌ API呼び出し失敗")
            elif len(reviews) == 0:
                skip_count += 1
                logger.info(f"  ⚪ 口コミなし（0件）")
                success_count += 1
            else:
                # 口コミをDBに挿入
                inserted = insert_reviews(conn, clinic_id, reviews, dry_run=dry_run)
                total_reviews += inserted
                success_count += 1
                logger.info(f"  ✅ {inserted}件の口コミを{'表示' if dry_run else '保存'}")

            # 進捗ログ（PROGRESS_LOG_INTERVAL件ごと）
            if idx % PROGRESS_LOG_INTERVAL == 0:
                print_progress(idx, total, success_count, fail_count, total_reviews, start_time)

            # レート制限（最後のリクエスト後は不要）
            if idx < total:
                time.sleep(API_CALL_INTERVAL)

    # コミット（dry-runでなければ）
    if not dry_run:
        conn.commit()
        logger.info("✅ DBコミット完了")

    # 最終統計
    elapsed = time.time() - start_time
    logger.info(f"\n{'='*60}")
    logger.info(f"📊 最終結果サマリー")
    logger.info(f"{'='*60}")
    logger.info(f"  処理クリニック数: {total}件")
    logger.info(f"  成功: {success_count}件（口コミなし含む: {skip_count}件）")
    logger.info(f"  失敗: {fail_count}件")
    logger.info(f"  取得口コミ総数: {total_reviews}件")
    logger.info(f"  所要時間: {elapsed:.1f}秒")

    if errors:
        logger.info(f"\n--- 失敗詳細 ---")
        for err in errors[:20]:
            logger.info(f"  ❌ {err['clinic_name']}: {err['reason']} (place_id: {err['place_id'][:20]})")
        if len(errors) > 20:
            logger.info(f"  ... 他 {len(errors) - 20}件")

    # DB内のレビュー件数を確認
    if not dry_run:
        count = conn.execute("SELECT COUNT(*) FROM reviews WHERE source = 'google'").fetchone()[0]
        logger.info(f"\n📊 DBのreviewsテーブル (source='google'): {count}件")

    conn.close()
    logger.info(f"\n{'='*60}")
    logger.info(f"✅ 完了")
    logger.info(f"{'='*60}")


def main():
    """CLIエントリポイント"""
    parser = argparse.ArgumentParser(
        description="Google Places APIで口コミを取得しDBに格納する"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="ドライラン: APIは呼び出すがDBに書き込まない",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="処理するクリニック数の上限",
    )
    args = parser.parse_args()

    run_collector(dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    main()
