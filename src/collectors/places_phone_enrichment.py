"""
AURA MVP — Google Places Details APIで電話番号・営業時間を一括エンリッチ

google_place_idが設定済みだが電話番号が未取得のクリニックに対し、
Places Details API (Legacy) で電話番号と営業時間を取得してDBに格納する。

コスト:
    Place Details (Basic): $0.00 (FieldMask最小化でBasic SKU)
    Place Details (Contact): $0.003/リクエスト → 月5,000件無料

使い方:
    # ドライラン
    uv run python -m src.collectors.places_phone_enrichment --dry-run --limit 10

    # 本番（100件ずつ）
    uv run python -m src.collectors.places_phone_enrichment --limit 100

    # 全件
    uv run python -m src.collectors.places_phone_enrichment
"""

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "aura.db"

# Google Places API (New) エンドポイント
PLACES_DETAILS_URL = "https://places.googleapis.com/v1/places"

# 取得フィールド（コスト最小化: Contact Data SKU）
FIELD_MASK = "nationalPhoneNumber,currentOpeningHours,regularOpeningHours"

# レート制限
API_CALL_INTERVAL = 0.3  # 秒


def get_api_key() -> str:
    """Google Maps APIキーを取得する"""
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.environ.get("AURA_GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        logger.error("AURA_GOOGLE_MAPS_API_KEY が未設定です")
        sys.exit(1)
    return api_key


def get_target_clinics(limit: int | None = None) -> list[dict]:
    """電話番号が未取得でplace_idがあるクリニックを取得する"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    query = """
        SELECT id, name, google_place_id
        FROM clinics
        WHERE google_place_id IS NOT NULL AND google_place_id != ''
          AND (phone IS NULL OR phone = '')
        ORDER BY name
    """
    if limit:
        query += f" LIMIT {limit}"

    rows = conn.execute(query).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def fetch_place_details(
    client: httpx.Client,
    api_key: str,
    place_id: str,
) -> dict | None:
    """Places API (New) で電話番号・営業時間を取得する"""

    url = f"{PLACES_DETAILS_URL}/{place_id}"
    headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    }

    try:
        response = client.get(url, headers=headers)

        if response.status_code == 404:
            return None
        if response.status_code != 200:
            logger.warning(f"  API error ({response.status_code}): {response.text[:100]}")
            return None

        return response.json()

    except httpx.HTTPError as e:
        logger.warning(f"  HTTP error: {e}")
        return None


def parse_opening_hours(hours_data: dict | None) -> str:
    """営業時間データをJSON文字列に変換する"""
    if not hours_data:
        return ""

    # regularOpeningHoursを優先（currentは本日分）
    periods = hours_data.get("periods", [])
    weekday_descriptions = hours_data.get("weekdayDescriptions", [])

    if weekday_descriptions:
        return json.dumps(
            {"descriptions": weekday_descriptions},
            ensure_ascii=False,
        )
    elif periods:
        return json.dumps(
            {"periods": periods},
            ensure_ascii=False,
        )
    return ""


def update_clinic(
    conn: sqlite3.Connection,
    clinic_id: str,
    phone: str | None,
    opening_hours: str | None,
) -> tuple[bool, bool]:
    """クリニックの電話番号と営業時間を更新する"""
    phone_updated = False
    hours_updated = False

    updates = []
    values = []

    if phone:
        updates.append("phone = ?")
        values.append(phone)
        phone_updated = True

    if opening_hours:
        updates.append("opening_hours = ?")
        values.append(opening_hours)
        hours_updated = True

    if updates:
        values.append(clinic_id)
        conn.execute(
            f"UPDATE clinics SET {', '.join(updates)} WHERE id = ?",
            values,
        )

    return phone_updated, hours_updated


def main():
    parser = argparse.ArgumentParser(
        description="Google Places APIで電話番号・営業時間を一括取得"
    )
    parser.add_argument("--dry-run", action="store_true", help="ドライラン")
    parser.add_argument("--limit", type=int, default=None, help="処理上限数")
    args = parser.parse_args()

    api_key = get_api_key()
    clinics = get_target_clinics(limit=args.limit)

    logger.info(f"対象クリニック: {len(clinics)}件")
    logger.info(f"モード: {'ドライラン' if args.dry_run else '本番'}")

    if not clinics:
        logger.info("対象なし（全クリニックに電話番号が設定済み、またはplace_id未設定）")
        return

    conn = sqlite3.connect(DB_PATH)
    phones_added = 0
    hours_added = 0
    errors = 0
    start_time = time.time()

    with httpx.Client(timeout=30.0) as client:
        for i, clinic in enumerate(clinics):
            place_id = clinic["google_place_id"]
            name = clinic["name"]

            logger.info(f"[{i+1}/{len(clinics)}] {name}")

            data = fetch_place_details(client, api_key, place_id)

            if data is None:
                errors += 1
                continue

            phone = data.get("nationalPhoneNumber")
            regular_hours = data.get("regularOpeningHours")
            current_hours = data.get("currentOpeningHours")
            hours_str = parse_opening_hours(regular_hours or current_hours)

            if args.dry_run:
                logger.info(f"  [DRY-RUN] phone={phone}, hours={'あり' if hours_str else 'なし'}")
            else:
                p, h = update_clinic(conn, clinic["id"], phone, hours_str)
                if p:
                    phones_added += 1
                if h:
                    hours_added += 1

            if phone:
                logger.info(f"  → {phone}")

            # レート制限
            time.sleep(API_CALL_INTERVAL)

            # 進捗ログ
            if (i + 1) % 50 == 0:
                elapsed = time.time() - start_time
                logger.info(
                    f"--- 進捗: {i+1}/{len(clinics)} | "
                    f"電話: +{phones_added} | 営業時間: +{hours_added} | "
                    f"経過: {elapsed:.0f}秒 ---"
                )

    if not args.dry_run:
        conn.commit()

    conn.close()

    elapsed = time.time() - start_time
    logger.info(f"\n{'='*50}")
    logger.info(f"完了")
    logger.info(f"{'='*50}")
    logger.info(f"処理: {len(clinics)}件")
    logger.info(f"電話番号追加: {phones_added}件")
    logger.info(f"営業時間追加: {hours_added}件")
    logger.info(f"エラー: {errors}件")
    logger.info(f"所要時間: {elapsed:.1f}秒")

    # 最終統計
    conn2 = sqlite3.connect(DB_PATH)
    stats = conn2.execute("""
        SELECT
          COUNT(*) as total,
          SUM(CASE WHEN phone IS NOT NULL AND phone != '' THEN 1 ELSE 0 END) as has_phone,
          SUM(CASE WHEN opening_hours IS NOT NULL AND opening_hours != '' AND opening_hours != '{}' THEN 1 ELSE 0 END) as has_hours
        FROM clinics
    """).fetchone()
    conn2.close()
    logger.info(f"\n電話番号: {stats[1]}/{stats[0]} ({100.0*stats[1]/stats[0]:.1f}%)")
    logger.info(f"営業時間: {stats[2]}/{stats[0]} ({100.0*stats[2]/stats[0]:.1f}%)")


if __name__ == "__main__":
    main()
