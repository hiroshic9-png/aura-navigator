#!/usr/bin/env python
"""
AURA MVP — 本番起動スクリプト

Renderの永続ディスク（/data）にDBがなければ、
1. バンドルされた初期DB（/app/data/aura.db）をコピー
2. バンドルDBもなければ GitHub Releases から最新DBをダウンロード
"""

import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

# GitHub Releases からDBをダウンロードする際のURL
_DB_RELEASE_URL = os.environ.get(
    "AURA_DB_URL",
    "https://github.com/hiroshic9-png/aura-navigator/releases/download/db-latest/aura.db",
)


def download_db(target: Path) -> bool:
    """GitHub Releases からDBファイルをダウンロード"""
    print(f"[起動] DBをダウンロード中: {_DB_RELEASE_URL}")
    try:
        urllib.request.urlretrieve(_DB_RELEASE_URL, str(target))
        size_mb = target.stat().st_size / 1024 / 1024
        print(f"[起動] ダウンロード完了 ({size_mb:.1f}MB)")
        return True
    except Exception as e:
        print(f"[起動] ダウンロード失敗: {e}")
        return False


def main():
    """起動前処理とuvicorn起動"""
    data_dir = Path("/data")
    app_data_dir = Path("/app/data")
    db_bundled = app_data_dir / "aura.db"

    # DBの配置先を決定（永続ディスクがあればそちら、なければアプリ内）
    if data_dir.exists() and data_dir.is_mount():
        db_target = data_dir / "aura.db"
        print("[起動] 永続ディスク検出: /data")
    else:
        db_target = db_bundled
        app_data_dir.mkdir(parents=True, exist_ok=True)
        print("[起動] 永続ディスクなし: /app/data を使用")

    # DBがなければ初期化
    if not db_target.exists():
        print("[起動] DBが見つかりません。ダウンロードを試行します。")
        if not download_db(db_target):
            print("[起動] ⚠ DBなしで起動します。一部機能が制限されます。")

    # uvicorn起動
    port = int(os.environ.get("PORT", "8400"))
    workers = int(os.environ.get("WEB_CONCURRENCY", "1"))

    print(f"[起動] AURA MVP を起動します (port={port}, workers={workers})")

    cmd = [
        sys.executable, "-m", "uvicorn",
        "src.main:app",
        "--host", "0.0.0.0",
        "--port", str(port),
        "--workers", str(workers),
    ]
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()

