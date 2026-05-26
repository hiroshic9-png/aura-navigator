"""
AURA MVP — スクレイプキャッシュから電話番号・営業時間を抽出

HTMLキャッシュ(index.html)から正規表現で電話番号を抽出し、
clinicsテーブルのphoneカラムに格納する。

LLM不要・API不要の高速バッチ処理。
"""

import json
import logging
import os
import re
import sqlite3
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "aura.db"
CACHE_DIR = PROJECT_ROOT / "data" / "scrape_cache"

# 電話番号の正規表現パターン
# tel:リンクから抽出（最も信頼性が高い）
PHONE_HREF_PATTERN = re.compile(r'href=["\']tel:([\d\-]+)["\']')

# テキストから抽出（フォールバック）
PHONE_TEXT_PATTERNS = [
    re.compile(r'(?:tel|TEL|電話番号?)[\s:：]+(\d{2,4}[-\s]?\d{2,4}[-\s]?\d{3,4})'),
    re.compile(r'(\d{3,4}-\d{3,4}-\d{3,4})'),  # ハイフン区切り
    re.compile(r'(0\d{9,10})'),  # 連続数字（市外局番つき）
]

# フリーダイヤルのパターン
FREEDIAL_PATTERN = re.compile(r'(0120[-\s]?\d{2,3}[-\s]?\d{3,4})')

# 営業時間の正規表現パターン
HOURS_PATTERNS = [
    re.compile(r'(\d{1,2}:\d{2})\s*[〜～~ー\-]\s*(\d{1,2}:\d{2})'),
]


def normalize_phone(phone: str) -> str:
    """電話番号を正規化する（ハイフン区切り）"""
    # ハイフン以外の区切り文字を除去
    digits = re.sub(r'[^\d]', '', phone)

    if not digits:
        return ""

    # フリーダイヤル
    if digits.startswith("0120"):
        if len(digits) >= 10:
            return f"0120-{digits[4:7]}-{digits[7:]}"
        return digits

    # 03-xxxx-xxxx (東京)
    if digits.startswith("03") and len(digits) == 10:
        return f"03-{digits[2:6]}-{digits[6:]}"

    # 0x-xxxx-xxxx (その他市外局番2桁)
    if len(digits) == 10 and digits.startswith("0"):
        return f"{digits[:2]}-{digits[2:6]}-{digits[6:]}"

    # 0xx-xxx-xxxx (市外局番3桁)
    if len(digits) == 10 and digits.startswith("0"):
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"

    # 携帯 080/090/070
    if digits.startswith(("080", "090", "070")) and len(digits) == 11:
        return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"

    # そのまま返す
    return digits


def extract_phone_from_html(html: str) -> str | None:
    """HTMLから電話番号を抽出する"""
    # 1. tel:リンクから抽出（最も信頼性が高い）
    href_matches = PHONE_HREF_PATTERN.findall(html)
    if href_matches:
        # フリーダイヤルを優先
        for m in href_matches:
            if m.startswith("0120"):
                return normalize_phone(m)
        # 固定電話を優先（携帯より）
        for m in href_matches:
            digits = re.sub(r'[^\d]', '', m)
            if digits.startswith("03") or digits.startswith("04"):
                return normalize_phone(m)
        # 最初のマッチを使用
        return normalize_phone(href_matches[0])

    # 2. テキストから抽出（フォールバック）
    for pattern in PHONE_TEXT_PATTERNS:
        text_matches = pattern.findall(html)
        if text_matches:
            phone = normalize_phone(text_matches[0])
            if len(re.sub(r'[^\d]', '', phone)) >= 9:  # 最低9桁
                return phone

    return None


def extract_hours_from_html(html: str) -> str | None:
    """HTMLから営業時間を抽出する（簡易版）"""
    for pattern in HOURS_PATTERNS:
        matches = pattern.findall(html)
        if matches and len(matches) >= 1:
            # 最初のマッチを採用（通常は代表的な診療時間）
            open_time, close_time = matches[0]
            return f"{open_time}-{close_time}"
    return None


def main():
    """メイン処理"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # キャッシュディレクトリのクリニックID一覧
    cache_ids = set()
    if CACHE_DIR.exists():
        for d in CACHE_DIR.iterdir():
            if d.is_dir() and (d / "index.html").exists():
                cache_ids.add(d.name)

    logger.info(f"index.htmlキャッシュ: {len(cache_ids)}件")

    # DBのクリニックと照合
    if not cache_ids:
        logger.info("処理対象なし")
        return

    phone_updated = 0
    phone_already = 0
    phone_not_found = 0

    for i, clinic_id in enumerate(sorted(cache_ids)):
        idx_path = CACHE_DIR / clinic_id / "index.html"
        html = idx_path.read_text(encoding="utf-8", errors="replace")

        # 既に電話番号があるか確認
        row = conn.execute(
            "SELECT phone FROM clinics WHERE id = ?", (clinic_id,)
        ).fetchone()

        if row is None:
            continue  # DBにないクリニック

        if row["phone"] and row["phone"].strip():
            phone_already += 1
            continue  # 既に設定済み

        # 電話番号抽出
        phone = extract_phone_from_html(html)

        if phone:
            conn.execute(
                "UPDATE clinics SET phone = ? WHERE id = ?",
                (phone, clinic_id),
            )
            phone_updated += 1
            if (i + 1) % 50 == 0 or phone_updated <= 5:
                logger.info(f"[{i+1}/{len(cache_ids)}] {clinic_id[:20]}... → {phone}")
        else:
            phone_not_found += 1

    conn.commit()
    conn.close()

    logger.info(f"\n=== 電話番号抽出 完了 ===")
    logger.info(f"キャッシュ対象: {len(cache_ids)}件")
    logger.info(f"更新: {phone_updated}件")
    logger.info(f"既設定: {phone_already}件")
    logger.info(f"抽出不可: {phone_not_found}件")

    # 最終統計
    conn2 = sqlite3.connect(DB_PATH)
    row = conn2.execute(
        "SELECT COUNT(*) as total, "
        "SUM(CASE WHEN phone IS NOT NULL AND phone != '' THEN 1 ELSE 0 END) as has_phone "
        "FROM clinics"
    ).fetchone()
    conn2.close()
    logger.info(f"電話番号充填率: {row[1]}/{row[0]} ({100.0*row[1]/row[0]:.1f}%)")


if __name__ == "__main__":
    main()
