#!/usr/bin/env python3
"""
品川美容外科 医師写真URL抽出スクリプト

品川美容外科のドクター一覧ページからHTML内の画像パスを抽出し、
doctors.photo_url に設定する。

品川のページはJSで動的表示されるが、HTMLソース自体には画像データが含まれている。
パターン: <img class="lazy" src="/assets/img/common/doctor/xxx.jpg" alt="名前【画像】">

使い方:
    uv run python scripts/collect_shinagawa_photos.py --dry-run
    uv run python scripts/collect_shinagawa_photos.py
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import httpx

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "aura.db"
DOCTOR_PAGE_URL = "https://www.shinagawa.com/doctor/"
BASE_URL = "https://www.shinagawa.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "ja,en;q=0.5",
}

# 写真パスと名前を抽出する正規表現
PHOTO_PATTERN = re.compile(
    r'src=["\']([/a-zA-Z0-9_.\-]+/doctor/[^"\' ]+)["\'][^>]*alt=["\']([^【]+)【画像】["\']',
    re.IGNORECASE,
)


def main():
    """メイン処理"""
    import argparse

    parser = argparse.ArgumentParser(description="品川美容外科 医師写真URL抽出")
    parser.add_argument("--dry-run", action="store_true", help="DB書き込みせずに結果のみ表示")
    args = parser.parse_args()

    print("=" * 60)
    print("品川美容外科 医師写真URL抽出")
    print("=" * 60)

    # 1. ページ取得
    print(f"\nページ取得: {DOCTOR_PAGE_URL}")
    resp = httpx.get(DOCTOR_PAGE_URL, headers=HEADERS, follow_redirects=True, timeout=15)
    resp.raise_for_status()
    html = resp.text
    print(f"  HTML: {len(html):,} bytes")

    # 2. 画像パス抽出
    matches = PHOTO_PATTERN.findall(html)
    # 重複除去（同じ名前が複数院に表示される場合がある）
    seen: dict[str, str] = {}
    for img_path, raw_name in matches:
        clean_name = raw_name.strip().replace(" ", "").replace("\u3000", "")
        if clean_name not in seen:
            seen[clean_name] = f"{BASE_URL}{img_path}"

    print(f"  ユニーク医師画像: {len(seen)}件 (全マッチ: {len(matches)}件)")

    # 3. DB更新
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    updated = 0
    not_found = []

    for clean_name, photo_url in seen.items():
        # doctorsテーブルで名前マッチ（品川チェーン限定）
        c.execute(
            """SELECT d.id, d.name FROM doctors d
            JOIN clinics c ON d.clinic_id = c.id
            WHERE c.chain_name = '品川美容外科'
            AND (d.is_active != 0 OR d.is_active IS NULL)
            AND d.photo_url IS NULL
            AND REPLACE(REPLACE(d.name, ' ', ''), '　', '') = ?""",
            (clean_name,),
        )
        row = c.fetchone()
        if row:
            prefix = "[DRY-RUN] " if args.dry_run else ""
            print(f"  ✅ {prefix}{row[1]} → {photo_url}")
            if not args.dry_run:
                c.execute("UPDATE doctors SET photo_url = ? WHERE id = ?", (photo_url, row[0]))
            updated += 1
        else:
            not_found.append(clean_name)

    if not args.dry_run:
        conn.commit()

    print(f"\n{'=' * 60}")
    print(f"{'[DRY-RUN] ' if args.dry_run else ''}完了")
    print(f"{'=' * 60}")
    print(f"  更新: {updated}名")
    print(f"  未マッチ: {len(not_found)}名")
    if not_found[:10]:
        print(f"  未マッチ例: {not_found[:10]}")

    # 品川写真URL設定状況
    c.execute(
        """SELECT COUNT(*) FROM doctors d JOIN clinics c ON d.clinic_id = c.id
        WHERE c.chain_name = '品川美容外科' AND (d.is_active != 0 OR d.is_active IS NULL)"""
    )
    total = c.fetchone()[0]
    c.execute(
        """SELECT COUNT(*) FROM doctors d JOIN clinics c ON d.clinic_id = c.id
        WHERE c.chain_name = '品川美容外科' AND (d.is_active != 0 OR d.is_active IS NULL)
        AND d.photo_url IS NOT NULL"""
    )
    with_photo = c.fetchone()[0]
    print(f"\n  品川 写真URL: {with_photo}/{total}名 ({with_photo / total * 100:.1f}%)")

    conn.close()


if __name__ == "__main__":
    main()
