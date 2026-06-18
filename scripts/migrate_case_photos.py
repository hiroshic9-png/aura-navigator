"""
beauty-search PostgreSQL → aura-mvp SQLite データ移行スクリプト

beauty-searchで収集した症例写真データを
aura-mvpのSQLiteデータベースに投入する。

使用方法:
    cd projects/beauty-search
    uv run python ../aura-mvp/backend/scripts/migrate_case_photos.py
"""

import asyncio
import sqlite3
import os
import struct
import time
from datetime import datetime
from pathlib import Path


# パス設定
AURA_MVP_DB = Path(__file__).resolve().parent.parent / "data" / "aura.db"


def generate_ulid():
    """簡易ULID生成"""
    timestamp_ms = int(time.time() * 1000)
    ts_bytes = struct.pack(">Q", timestamp_ms)[2:]
    rand_bytes = os.urandom(10)
    encoding = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    ulid_bytes = ts_bytes + rand_bytes
    val = int.from_bytes(ulid_bytes, "big")
    chars = []
    for _ in range(26):
        chars.append(encoding[val & 31])
        val >>= 5
    return "".join(reversed(chars))


async def fetch_from_beauty_search():
    """beauty-search PostgreSQLから全症例写真を取得"""
    from backend.core.config import settings
    from backend.core.database import AuraDatabase

    db = AuraDatabase(settings.database_url)
    await db.connect()

    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, doctor_id, clinic_id, procedure_name, category,
                   before_image_path, after_image_path, source_url, source,
                   updated_at
            FROM case_photos
            ORDER BY updated_at DESC
        """)
        print(f"beauty-search から {len(rows)} 件取得")

    await db.disconnect()
    return [dict(r) for r in rows]


def insert_to_aura_mvp(rows):
    """aura-mvp SQLiteに症例写真を投入"""
    if not AURA_MVP_DB.exists():
        print(f"エラー: データベースが見つかりません: {AURA_MVP_DB}")
        return 0

    conn = sqlite3.connect(str(AURA_MVP_DB))
    cursor = conn.cursor()

    # 既存の症例写真IDを取得（重複防止）
    cursor.execute("SELECT source_case_id FROM case_photos")
    existing_ids = {row[0] for row in cursor.fetchall()}
    print(f"aura-mvp に既存の症例写真: {len(existing_ids)} 件")

    inserted = 0
    skipped = 0
    now = datetime.now().isoformat()

    for row in rows:
        source_case_id = row["id"]

        if source_case_id in existing_ids:
            skipped += 1
            continue

        ulid = generate_ulid()
        source = row["source"]

        # クリニック名の推定
        clinic_name_map = {
            "sbc": "湘南美容クリニック",
            "tcb": "TCB東京中央美容外科",
            "shinagawa": "品川美容外科",
            "tribeau": "トリビュー",
        }
        clinic_name = clinic_name_map.get(source)

        cursor.execute("""
            INSERT INTO case_photos (
                id, category, procedure_name,
                before_image_url, after_image_url, source_url,
                clinic_name, source_case_id,
                source, fetched_at, created_at, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ulid,
            row["category"],
            row.get("procedure_name"),
            row.get("before_image_path"),
            row.get("after_image_path"),
            row.get("source_url"),
            clinic_name,
            source_case_id,
            source,
            row["updated_at"].isoformat() if row.get("updated_at") else now,
            now,
            1,
        ))
        inserted += 1

        if inserted % 1000 == 0:
            conn.commit()
            print(f"  ... {inserted} 件投入済み")

    conn.commit()
    conn.close()

    print(f"\n=== 移行完了 ===")
    print(f"投入: {inserted} 件")
    print(f"スキップ（重複）: {skipped} 件")
    return inserted


def verify():
    """投入後の検証"""
    conn = sqlite3.connect(str(AURA_MVP_DB))
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM case_photos")
    total = cursor.fetchone()[0]

    cursor.execute("SELECT source, COUNT(*) FROM case_photos GROUP BY source ORDER BY COUNT(*) DESC")
    by_source = cursor.fetchall()

    cursor.execute("SELECT category, COUNT(*) FROM case_photos GROUP BY category ORDER BY COUNT(*) DESC")
    by_cat = cursor.fetchall()

    print(f"\n=== aura-mvp 検証 ===")
    print(f"合計: {total} 件")
    print(f"\nソース別:")
    for source, cnt in by_source:
        print(f"  {source}: {cnt} 件")
    print(f"\nカテゴリ別:")
    for cat, cnt in by_cat:
        print(f"  {cat}: {cnt} 件")

    conn.close()


async def main():
    print("=" * 50)
    print("AURA 症例写真データ移行")
    print("beauty-search PostgreSQL → aura-mvp SQLite")
    print("=" * 50)

    rows = await fetch_from_beauty_search()
    insert_to_aura_mvp(rows)
    verify()


if __name__ == "__main__":
    asyncio.run(main())
