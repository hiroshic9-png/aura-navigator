#!/usr/bin/env python
"""
AURA MVP — 本番起動スクリプト

Renderの永続ディスク（/data）にDBがなければ、バンドルされた初期DBをコピーし、
uvicornを起動する。
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    """起動前処理とuvicorn起動"""
    data_dir = Path("/data")
    db_target = data_dir / "aura.db"
    db_bundled = Path("/app/data/aura.db")

    # 永続ディスクにDBがなければバンドルされた初期DBをコピー
    if data_dir.exists() and not db_target.exists():
        if db_bundled.exists():
            print(f"[起動] 初期DBをコピー: {db_bundled} → {db_target}")
            shutil.copy2(db_bundled, db_target)
            print(f"[起動] コピー完了 ({db_target.stat().st_size / 1024 / 1024:.1f}MB)")
        else:
            print("[起動] バンドルDBが見つかりません。空のDBで起動します。")

    # ローカル環境（/dataがない場合）
    if not data_dir.exists():
        print("[起動] ローカル環境で起動（永続ディスクなし）")

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
