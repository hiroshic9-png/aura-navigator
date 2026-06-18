#!/usr/bin/env python3
"""
医師SNSリンク抽出スクリプト

各医師のprofile_urlからInstagram/Twitter/TikTok/YouTubeリンクを抽出し、
doctors テーブルの SNS カラムに保存する。

使い方:
    uv run python scripts/collect_doctor_sns.py --dry-run --limit 20
    uv run python scripts/collect_doctor_sns.py --source sbc
    uv run python scripts/collect_doctor_sns.py --all
"""

from __future__ import annotations

import re
import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "aura.db"

# リクエスト設定
REQUEST_DELAY = 1.0  # 秒
REQUEST_TIMEOUT = 8  # 秒

# SNSパターン
SNS_PATTERNS = {
    "instagram": re.compile(
        r'https?://(?:www\.)?instagram\.com/([a-zA-Z0-9_.]+)/?', re.IGNORECASE
    ),
    "twitter": re.compile(
        r'https?://(?:www\.)?(?:twitter\.com|x\.com)/([a-zA-Z0-9_]+)/?', re.IGNORECASE
    ),
    "tiktok": re.compile(
        r'https?://(?:www\.)?tiktok\.com/@([a-zA-Z0-9_.]+)/?', re.IGNORECASE
    ),
    "youtube": re.compile(
        r'https?://(?:www\.)?youtube\.com/(?:@|channel/|c/)([a-zA-Z0-9_\-]+)/?',
        re.IGNORECASE,
    ),
}

# 除外するSNSアカウント（クリニック公式/ボット等）
EXCLUDED_ACCOUNTS = {
    "instagram": {"p", "reel", "stories", "explore", "accounts", ""},
    "twitter": {"intent", "share", "search", "hashtag", "home", ""},
    "tiktok": {""},
    "youtube": {"watch", "results", "playlist", ""},
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "ja,en;q=0.5",
}


def extract_sns_links(html: str) -> dict[str, str | None]:
    """HTMLからSNSリンクを抽出する"""
    results: dict[str, str | None] = {
        "instagram_url": None,
        "twitter_url": None,
        "tiktok_url": None,
        "youtube_url": None,
    }

    for platform, pattern in SNS_PATTERNS.items():
        matches = pattern.findall(html)
        for account in matches:
            # 除外リストをチェック
            if account.lower() in EXCLUDED_ACCOUNTS.get(platform, set()):
                continue
            # 最初の有効なマッチを採用
            col = f"{platform}_url"
            if col in results and results[col] is None:
                if platform == "instagram":
                    results[col] = f"https://www.instagram.com/{account}/"
                elif platform == "twitter":
                    results[col] = f"https://x.com/{account}"
                elif platform == "tiktok":
                    results[col] = f"https://www.tiktok.com/@{account}"
                elif platform == "youtube":
                    results[col] = f"https://www.youtube.com/@{account}"
                break

    return results


def main():
    """メイン処理"""
    import argparse

    parser = argparse.ArgumentParser(description="医師SNSリンク抽出")
    parser.add_argument("--dry-run", action="store_true", help="DB書き込みせずに結果のみ表示")
    parser.add_argument("--limit", type=int, default=0, help="処理件数の上限")
    parser.add_argument("--source", type=str, help="ソース絞り込み (sbc/tcb/shinagawa)")
    parser.add_argument("--all", action="store_true", help="全医師を処理")
    args = parser.parse_args()

    if not args.all and not args.source and args.limit == 0:
        print("--all, --source, または --limit を指定してください")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    print("=" * 60)
    print("医師SNSリンク抽出")
    print("=" * 60)

    # 対象医師を取得（SNS未設定 & profile_urlあり）
    where_clauses = [
        "(is_active != 0 OR is_active IS NULL)",
        "profile_url IS NOT NULL AND profile_url != ''",
        "(instagram_url IS NULL AND twitter_url IS NULL AND tiktok_url IS NULL AND youtube_url IS NULL)",
    ]
    if args.source:
        where_clauses.append(f"source = '{args.source}'")

    query = f"SELECT id, name, profile_url, source FROM doctors WHERE {' AND '.join(where_clauses)}"
    if args.limit > 0:
        query += f" LIMIT {args.limit}"

    c.execute(query)
    doctors = c.fetchall()
    print(f"\n対象: {len(doctors)}名")

    # httpxクライアント
    client = httpx.Client(
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
        verify=False,  # SSL証明書エラーを無視
    )

    total_found = 0
    ig_count = tw_count = tk_count = yt_count = 0

    for i, doc in enumerate(doctors, 1):
        url = doc["profile_url"]
        name = doc["name"]

        try:
            resp = client.get(url)
            resp.raise_for_status()
            html = resp.text

            sns = extract_sns_links(html)
            found_any = any(v is not None for v in sns.values())

            if found_any:
                total_found += 1
                parts = []
                if sns["instagram_url"]:
                    ig_count += 1
                    parts.append(f"IG:{sns['instagram_url']}")
                if sns["twitter_url"]:
                    tw_count += 1
                    parts.append(f"TW:{sns['twitter_url']}")
                if sns["tiktok_url"]:
                    tk_count += 1
                    parts.append(f"TT:{sns['tiktok_url']}")
                if sns["youtube_url"]:
                    yt_count += 1
                    parts.append(f"YT:{sns['youtube_url']}")

                prefix = "[DRY-RUN] " if args.dry_run else ""
                print(f"  [{i}/{len(doctors)}] ✅ {prefix}{name} → {' | '.join(parts)}")

                if not args.dry_run:
                    updates = []
                    params = []
                    for col, val in sns.items():
                        if val is not None:
                            updates.append(f"{col} = ?")
                            params.append(val)
                    if updates:
                        params.append(doc["id"])
                        c.execute(
                            f"UPDATE doctors SET {', '.join(updates)} WHERE id = ?",
                            params,
                        )
            else:
                # 50件ごとに進捗表示
                if i % 50 == 0:
                    print(f"  [{i}/{len(doctors)}] 処理中... (SNS発見: {total_found})")

        except Exception:
            # タイムアウト・接続エラーは無視
            if i % 50 == 0:
                print(f"  [{i}/{len(doctors)}] 処理中... (SNS発見: {total_found})")

        time.sleep(REQUEST_DELAY)

    if not args.dry_run:
        conn.commit()

    client.close()

    print(f"\n{'=' * 60}")
    print(f"{'[DRY-RUN] ' if args.dry_run else ''}完了: {total_found}名のSNSリンクを発見")
    print(f"{'=' * 60}")
    print(f"  Instagram: {ig_count}")
    print(f"  Twitter/X: {tw_count}")
    print(f"  TikTok:    {tk_count}")
    print(f"  YouTube:   {yt_count}")

    conn.close()


if __name__ == "__main__":
    main()
