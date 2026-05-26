"""
AURA MVP -- クリニックPlace ID拡充スクリプト（Legacy API版）

DBに登録済みだがgoogle_place_idが未設定のクリニックに対し、
Google Maps Places API (Legacy) Find Place From Text で
名前+住所でマッチングし、Place IDと評価データを紐付けるバッチ。

使い方:
    # ドライラン（5件のみテスト）
    python -m src.collectors.place_id_enrichment --dry-run --limit 5

    # 本番実行（50件ずつ）
    python -m src.collectors.place_id_enrichment --limit 50

    # 全件実行
    python -m src.collectors.place_id_enrichment

コスト:
    Find Place: Basic SKU ($0.017/リクエスト)
    月5,000件まで$200クレジットで無料
"""

import argparse
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# パス解決
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "aura.db"

# Google Maps API (Legacy) エンドポイント
FIND_PLACE_URL = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
PLACE_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"

# API呼び出し間隔
API_CALL_INTERVAL = 0.5

# 進捗ログ間隔
PROGRESS_LOG_INTERVAL = 20


def get_api_key() -> str:
    """Google Maps APIキーを取得する"""
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.environ.get("AURA_GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        logger.error("APIキーが見つかりません。AURA_GOOGLE_MAPS_API_KEY を設定してください。")
        sys.exit(1)
    return api_key


def get_db_connection() -> sqlite3.Connection:
    """DB接続を取得する"""
    if not DB_PATH.exists():
        logger.error(f"DBが見つかりません: {DB_PATH}")
        sys.exit(1)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def fetch_clinics_without_place_id(conn: sqlite3.Connection, limit: int | None = None) -> list[dict]:
    """google_place_idが未設定のクリニック一覧を取得する"""
    query = """
        SELECT id, name, address, city, phone
        FROM clinics
        WHERE (google_place_id IS NULL OR google_place_id = '')
        ORDER BY name
    """
    if limit:
        query += f" LIMIT {limit}"

    rows = conn.execute(query).fetchall()
    return [dict(row) for row in rows]


def find_place(
    client: httpx.Client,
    api_key: str,
    clinic_name: str,
    clinic_address: str,
) -> dict | None:
    """
    Legacy Find Place From Text APIでクリニックを検索する

    名前+住所を入力し、最もマッチするPlace IDを返す。
    """
    # 検索クエリ: クリニック名 + 市区町村名（精度向上のため）
    search_input = clinic_name
    if clinic_address:
        # 住所から区名を抽出して追加
        for ward in _TOKYO_WARDS:
            if ward in clinic_address:
                search_input = f"{clinic_name} {ward}"
                break

    params = {
        "input": search_input,
        "inputtype": "textquery",
        "fields": "place_id,name,rating,user_ratings_total,formatted_address",
        "key": api_key,
        "language": "ja",
        "locationbias": "rectangle:35.5,139.5|35.9,139.95",  # 東京エリア
    }

    try:
        response = client.get(FIND_PLACE_URL, params=params)

        if response.status_code != 200:
            logger.warning(f"  API error ({response.status_code})")
            return None

        data = response.json()
        status = data.get("status", "")

        if status != "OK":
            if status == "ZERO_RESULTS":
                return None
            logger.warning(f"  API status: {status}")
            return None

        candidates = data.get("candidates", [])
        if not candidates:
            return None

        # 最初の候補を使用（Find Placeは最も関連性の高い1件を返す）
        best = candidates[0]

        # 名前の一致度を検証（全く関係ないものを排除）
        google_name = _normalize(best.get("name", ""))
        db_name = _normalize(clinic_name)

        if not _is_reasonable_match(db_name, google_name):
            logger.info(f"  -- 不一致: '{best.get('name', '')}' (スキップ)")
            return None

        return {
            "place_id": best.get("place_id", ""),
            "name": best.get("name", ""),
            "address": best.get("formatted_address", ""),
            "rating": best.get("rating"),
            "review_count": best.get("user_ratings_total"),
        }

    except httpx.HTTPError as e:
        logger.warning(f"  HTTP error: {e}")
        return None
    except Exception as e:
        logger.warning(f"  Unexpected error: {e}")
        return None


def _is_reasonable_match(db_name: str, google_name: str) -> bool:
    """名前の一致度が妥当かチェックする"""
    if not db_name or not google_name:
        return False

    # 完全一致 or 包含関係
    if db_name == google_name:
        return True
    if db_name in google_name or google_name in db_name:
        return True

    # 共通文字の割合（60%以上で妥当とみなす）
    common = sum(1 for c in db_name if c in google_name)
    if len(db_name) > 0 and common / len(db_name) >= 0.6:
        return True

    return False


def _normalize(text: str) -> str:
    """テキストの正規化"""
    import unicodedata
    text = unicodedata.normalize("NFKC", text)
    return text.replace(" ", "").replace("\u3000", "").replace("　", "")


# 東京23区
_TOKYO_WARDS = [
    "渋谷区", "新宿区", "港区", "中央区", "千代田区", "豊島区",
    "品川区", "目黒区", "世田谷区", "大田区", "杉並区", "練馬区",
    "板橋区", "北区", "台東区", "墨田区", "江東区", "荒川区",
    "文京区", "足立区", "葛飾区", "江戸川区", "中野区",
]


def update_clinic_place_id(
    conn: sqlite3.Connection,
    clinic_id: str,
    place_data: dict,
    dry_run: bool = False,
) -> bool:
    """クリニックのPlace ID・評価データを更新する"""
    if dry_run:
        rating = place_data.get("rating")
        reviews = place_data.get("review_count", 0)
        rating_str = f"★{rating:.1f}" if rating else "-"
        logger.info(f"  [DRY-RUN] UPDATE: {rating_str} ({reviews}件) | {place_data.get('name', '')}")
        return True

    try:
        conn.execute(
            """
            UPDATE clinics
            SET google_place_id = ?,
                google_rating = ?,
                google_review_count = ?
            WHERE id = ?
            """,
            (
                place_data["place_id"],
                place_data.get("rating"),
                place_data.get("review_count"),
                clinic_id,
            ),
        )
        return True
    except sqlite3.Error as e:
        logger.error(f"  UPDATE失敗: {e}")
        return False


def run_enrichment(dry_run: bool = False, limit: int | None = None):
    """Place ID拡充のメインループ"""
    mode_label = "DRY-RUN" if dry_run else "本番実行"
    logger.info(f"\n{'='*60}")
    logger.info(f"AURA MVP -- Place ID拡充スクリプト (Legacy API)")
    logger.info(f"モード: {mode_label}")
    logger.info(f"{'='*60}")

    api_key = get_api_key()
    logger.info("APIキー確認済み")

    conn = get_db_connection()
    logger.info(f"DB接続: {DB_PATH}")

    clinics = fetch_clinics_without_place_id(conn, limit=limit)
    total = len(clinics)

    if total == 0:
        logger.info("対象クリニックがありません（全てPlace ID設定済み）")
        conn.close()
        return

    logger.info(f"対象クリニック: {total}件")
    if limit:
        logger.info(f"（--limit {limit} による制限）")

    matched = 0
    not_found = 0
    errors = 0
    start_time = time.time()

    with httpx.Client(timeout=30.0) as client:
        for idx, clinic in enumerate(clinics, 1):
            clinic_id = clinic["id"]
            clinic_name = clinic["name"]
            clinic_address = clinic.get("address", "") or ""

            logger.info(f"[{idx}/{total}] {clinic_name}")

            result = find_place(client, api_key, clinic_name, clinic_address)

            if result is None:
                not_found += 1
            elif result["place_id"]:
                success = update_clinic_place_id(conn, clinic_id, result, dry_run=dry_run)
                if success:
                    matched += 1
                    if not dry_run:
                        rating_str = f"★{result['rating']:.1f}" if result.get("rating") else "-"
                        review_str = f"{result.get('review_count', 0)}件"
                        logger.info(f"  -> {rating_str} ({review_str}) | {result.get('name', '')}")
                else:
                    errors += 1
            else:
                not_found += 1

            # 進捗ログ
            if idx % PROGRESS_LOG_INTERVAL == 0:
                elapsed = time.time() - start_time
                rate = idx / elapsed if elapsed > 0 else 0
                remaining = (total - idx) / rate if rate > 0 else 0
                logger.info(
                    f"--- 進捗: {idx}/{total} ({idx/total*100:.1f}%) | "
                    f"マッチ: {matched} | 未検出: {not_found} | "
                    f"残り約{remaining:.0f}秒 ---"
                )

            if idx < total:
                time.sleep(API_CALL_INTERVAL)

    if not dry_run:
        conn.commit()
        logger.info("DBコミット完了")

    elapsed = time.time() - start_time
    logger.info(f"\n{'='*60}")
    logger.info(f"最終結果サマリー")
    logger.info(f"{'='*60}")
    logger.info(f"  処理: {total}件")
    logger.info(f"  マッチ成功: {matched}件 ({matched/total*100:.1f}%)")
    logger.info(f"  未検出: {not_found}件")
    logger.info(f"  エラー: {errors}件")
    logger.info(f"  所要時間: {elapsed:.1f}秒")

    result_row = conn.execute(
        "SELECT COUNT(*) FROM clinics WHERE google_place_id IS NOT NULL AND google_place_id != ''"
    ).fetchone()
    total_clinics = conn.execute("SELECT COUNT(*) FROM clinics").fetchone()[0]
    logger.info(f"\n  DB: Place ID設定済みクリニック: {result_row[0]}/{total_clinics}")

    conn.close()


def main():
    """CLIエントリポイント"""
    parser = argparse.ArgumentParser(
        description="Place IDが未設定のクリニックにGoogle Places APIでPlace IDを紐付ける"
    )
    parser.add_argument("--dry-run", action="store_true", help="ドライラン")
    parser.add_argument("--limit", type=int, default=None, help="処理上限数")
    args = parser.parse_args()

    run_enrichment(dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    main()
