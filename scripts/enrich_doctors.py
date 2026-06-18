"""
AURA MVP — 医師プロフィール再スクレイプスクリプト

既存の profile_url にアクセスし、ページ内テキストから
資格・経歴・経験年数を抽出して doctors テーブルを更新する。

実行:
    uv run python scripts/enrich_doctors.py
"""

import asyncio
import json
import logging
import re
import sqlite3
import time
from pathlib import Path

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "aura.db"

# 専門医資格のパターン
CERTIFICATION_PATTERNS = [
    r"日本形成外科学会[^\s]*専門医",
    r"形成外科専門医",
    r"日本美容外科学会[^\s]*専門医",
    r"美容外科専門医",
    r"JSAPS",
    r"皮膚科専門医",
    r"日本皮膚科学会[^\s]*専門医",
    r"眼科専門医",
    r"麻酔科専門医",
    r"外科専門医",
    r"日本抗加齢医学会専門医",
    r"レーザー[^\s]*専門医",
]

# 経験年数の抽出パターン
EXPERIENCE_PATTERNS = [
    r"(?:経験|実績|キャリア)[^\d]{0,10}(\d{1,2})\s*年",
    r"(\d{4})\s*年[^\d]*(?:卒業|卒|医学部)",  # 卒業年から推定
    r"(\d{4})\s*年[^\d]*(?:入局|研修)",
]

# 大学病院・勤務経歴パターン
HOSPITAL_PATTERNS = [
    r"(?:東京|京都|大阪|名古屋|北海道|東北|九州|千葉|神戸|横浜市立|慶應義塾|慶応|順天堂|日本医科|昭和|帝京|東邦|杏林|東京女子医科|聖マリアンナ|東海|藤田医科|金沢|岡山|広島|長崎|熊本|鹿児島|琉球|山形|新潟|信州|三重|滋賀医科|奈良県立医科|和歌山県立医科|徳島|香川|愛媛|高知|佐賀|大分|宮崎|秋田|弘前|群馬|富山|福井|岐阜|浜松医科|福島県立医科|札幌医科|旭川医科|防衛医科)大学",
    r"(?:国立|県立|市立|都立)[^\s]*(?:病院|医療センター)",
    r"(?:虎の門|聖路加|慈恵|済生会|赤十字|がんセンター)",
]


def extract_certifications(text: str) -> list[str]:
    """テキストから専門医資格を抽出"""
    certs = []
    for pattern in CERTIFICATION_PATTERNS:
        matches = re.findall(pattern, text)
        certs.extend(matches)
    # 重複を排除しつつ順序を保持
    seen = set()
    unique_certs = []
    for c in certs:
        normalized = c.strip()
        if normalized not in seen:
            seen.add(normalized)
            unique_certs.append(normalized)
    return unique_certs


def extract_experience_years(text: str) -> int | None:
    """テキストから経験年数を抽出"""
    # 直接的な表現
    for pattern in EXPERIENCE_PATTERNS[:1]:
        m = re.search(pattern, text)
        if m:
            return int(m.group(1))

    # 卒業年から推定
    for pattern in EXPERIENCE_PATTERNS[1:]:
        m = re.search(pattern, text)
        if m:
            grad_year = int(m.group(1))
            if 1970 <= grad_year <= 2024:
                return 2026 - grad_year
    return None


def extract_hospital_background(text: str) -> str | None:
    """テキストから大学病院・勤務経歴を抽出"""
    backgrounds = []
    for pattern in HOSPITAL_PATTERNS:
        matches = re.findall(pattern, text)
        for m in matches:
            # マッチした大学名+「大学」を含む前後の文を抽出
            idx = text.find(m)
            if idx >= 0:
                start = max(0, idx - 20)
                end = min(len(text), idx + len(m) + 30)
                context = text[start:end].strip()
                if context not in backgrounds:
                    backgrounds.append(context)
    return " / ".join(backgrounds[:3]) if backgrounds else None


def detect_jsaps(text: str, certifications: list[str]) -> bool:
    """JSAPS資格の検出"""
    combined = text + " " + " ".join(certifications)
    return bool(re.search(r"JSAPS|日本美容外科学会.*専門医|美容外科専門医", combined))


async def fetch_profile(client: httpx.AsyncClient, url: str) -> str | None:
    """プロフィールページのテキストを取得"""
    try:
        resp = await client.get(url, follow_redirects=True, timeout=15.0)
        if resp.status_code == 200:
            # HTMLタグを除去してテキスト抽出
            text = re.sub(r"<script[^>]*>.*?</script>", "", resp.text, flags=re.DOTALL)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            return text
        else:
            logger.warning(f"  HTTP {resp.status_code}: {url}")
            return None
    except Exception as e:
        logger.warning(f"  取得失敗: {url} — {e}")
        return None


async def enrich_doctors():
    """全医師のプロフィールを再スクレイプして情報を補完"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 対象医師を取得
    doctors = cursor.execute("""
        SELECT id, name, profile_url, board_certifications, experience_years,
               hospital_background, jsaps_certified, specialties
        FROM doctors
        WHERE profile_url IS NOT NULL AND profile_url != ''
    """).fetchall()

    logger.info(f"対象医師数: {len(doctors)}")

    updated = 0
    enriched_certs = 0
    enriched_exp = 0
    enriched_bg = 0
    enriched_jsaps = 0
    errors = 0

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "ja,en;q=0.9",
    }

    async with httpx.AsyncClient(headers=headers) as client:
        for i, doc in enumerate(doctors):
            if i % 50 == 0 and i > 0:
                logger.info(f"  進捗: {i}/{len(doctors)} ({updated}件更新)")

            # レート制限（1秒に2リクエスト）
            if i > 0 and i % 2 == 0:
                await asyncio.sleep(0.5)

            text = await fetch_profile(client, doc["profile_url"])
            if not text:
                errors += 1
                continue

            # 抽出
            new_certs = extract_certifications(text)
            new_exp = extract_experience_years(text)
            new_bg = extract_hospital_background(text)
            new_jsaps = detect_jsaps(text, new_certs)

            # 既存データとマージ
            updates = {}

            # 資格: 既存データがなければ更新
            existing_certs = doc["board_certifications"] or "[]"
            try:
                existing_list = json.loads(existing_certs)
            except (json.JSONDecodeError, TypeError):
                existing_list = []

            if new_certs and (not existing_list or len(new_certs) > len(existing_list)):
                updates["board_certifications"] = json.dumps(new_certs, ensure_ascii=False)
                enriched_certs += 1

            # 経験年数: 既存データがなければ更新
            if new_exp and not doc["experience_years"]:
                updates["experience_years"] = new_exp
                enriched_exp += 1

            # 勤務経歴: 既存データがなければ更新
            if new_bg and not doc["hospital_background"]:
                updates["hospital_background"] = new_bg
                enriched_bg += 1

            # JSAPS: 未設定の場合のみ
            if new_jsaps and not doc["jsaps_certified"]:
                updates["jsaps_certified"] = True
                enriched_jsaps += 1

            # 更新
            if updates:
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                values = list(updates.values()) + [doc["id"]]
                cursor.execute(f"UPDATE doctors SET {set_clause} WHERE id = ?", values)
                updated += 1

    conn.commit()

    # trust_scoreを再計算
    logger.info("trust_scoreを再計算中...")
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.analyzers.doctor_scoring import calculate_trust_score

    all_docs = cursor.execute("""
        SELECT id, board_certifications, experience_years, specialties,
               profile_url, title, hospital_background, annual_case_count, jsaps_certified
        FROM doctors
    """).fetchall()

    for doc in all_docs:
        result = calculate_trust_score(
            board_certifications=doc["board_certifications"],
            experience_years=doc["experience_years"],
            specialties=doc["specialties"],
            profile_url=doc["profile_url"],
            title=doc["title"],
            hospital_background=doc["hospital_background"],
            annual_case_count=doc["annual_case_count"],
            jsaps_certified=bool(doc["jsaps_certified"]) if doc["jsaps_certified"] else False,
        )
        cursor.execute(
            "UPDATE doctors SET trust_score = ?, trust_score_breakdown = ? WHERE id = ?",
            (result.total, result.to_json(), doc["id"]),
        )

    conn.commit()

    # 結果レポート
    logger.info("=" * 50)
    logger.info("補完結果:")
    logger.info(f"  対象: {len(doctors)}名")
    logger.info(f"  更新: {updated}名")
    logger.info(f"  資格補完: {enriched_certs}名")
    logger.info(f"  経験年数補完: {enriched_exp}名")
    logger.info(f"  勤務経歴補完: {enriched_bg}名")
    logger.info(f"  JSAPS検出: {enriched_jsaps}名")
    logger.info(f"  取得エラー: {errors}名")
    logger.info("=" * 50)

    # 更新後のスコア分布
    score_dist = cursor.execute("""
        SELECT
            CASE
                WHEN trust_score < 10 THEN '0-9'
                WHEN trust_score < 20 THEN '10-19'
                WHEN trust_score < 30 THEN '20-29'
                WHEN trust_score < 40 THEN '30-39'
                WHEN trust_score < 50 THEN '40-49'
                WHEN trust_score < 60 THEN '50-59'
                WHEN trust_score >= 60 THEN '60+'
            END as range,
            COUNT(*) as count
        FROM doctors
        GROUP BY range
        ORDER BY range
    """).fetchall()

    logger.info("\n更新後スコア分布:")
    for row in score_dist:
        logger.info(f"  {row[0]:>6}: {row[1]}名")

    conn.close()


if __name__ == "__main__":
    asyncio.run(enrich_doctors())
