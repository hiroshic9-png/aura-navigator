"""
AURA MVP — Phase 65: 医師experience_years拡充スクリプト

experience_yearsが未設定の医師に対して、以下のロジックで推定値を投入:
1. 肩書きからの推定（院長/理事長→15+、部長/主任→10+、医師→5）
2. 勤務経歴からの推定（大学含む→12+、勤務先3+→10+）
3. チェーン別中央値
4. デフォルト値（8年）

推定後、trust_scoreを再計算する。

実行:
    python3 scripts/enrich_doctors_phase65.py
"""

import json
import logging
import sqlite3
import statistics
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.analyzers.doctor_scoring import calculate_trust_score

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "aura.db"

# 肩書きによる推定年数マッピング
TITLE_EXPERIENCE_MAP = {
    "高": {
        "keywords": ["院長", "副院長", "理事長", "総院長", "顧問"],
        "min_years": 15,
    },
    "中": {
        "keywords": ["主任", "部長", "医長"],
        "min_years": 10,
    },
    "低": {
        "keywords": ["医師", "常勤"],
        "min_years": 5,
    },
}

# デフォルト推定値
DEFAULT_EXPERIENCE_YEARS = 8


def estimate_from_title(title: str | None) -> int | None:
    """肩書きから経験年数を推定"""
    if not title:
        return None

    for level in TITLE_EXPERIENCE_MAP.values():
        for keyword in level["keywords"]:
            if keyword in title:
                return level["min_years"]
    return None


def estimate_from_background(hospital_background: str | None) -> int | None:
    """勤務経歴から経験年数を推定"""
    if not hospital_background:
        return None

    bg = hospital_background.strip()
    estimated = None

    # 大学病院での勤務→最低12年と推定
    if "大学" in bg:
        estimated = 12

    # 3つ以上の勤務先→最低10年
    # 区切り文字で分割して勤務先数をカウント
    separators = ["/", "、", ",", "\n", "→", "⇒"]
    parts = [bg]
    for sep in separators:
        new_parts = []
        for p in parts:
            new_parts.extend(p.split(sep))
        parts = new_parts
    # 意味のある部分のみカウント（3文字以上）
    meaningful_parts = [p.strip() for p in parts if len(p.strip()) >= 3]

    if len(meaningful_parts) >= 3:
        if estimated is None:
            estimated = 10
        else:
            estimated = max(estimated, 10)

    return estimated


def get_chain_medians(cursor: sqlite3.Cursor) -> dict[str, int]:
    """チェーン別のexperience_years中央値を算出"""
    rows = cursor.execute("""
        SELECT c.chain_name, d.experience_years
        FROM doctors d
        JOIN clinics c ON d.clinic_id = c.id
        WHERE d.experience_years IS NOT NULL
          AND c.chain_name IS NOT NULL AND c.chain_name != ''
          AND d.is_active = 1
    """).fetchall()

    # チェーン別にグループ化
    chain_years: dict[str, list[int]] = {}
    for chain_name, exp_years in rows:
        if chain_name not in chain_years:
            chain_years[chain_name] = []
        chain_years[chain_name].append(exp_years)

    # 中央値を算出（サンプル数3以上のチェーンのみ）
    medians = {}
    for chain, years in chain_years.items():
        if len(years) >= 3:
            medians[chain] = int(statistics.median(years))
        elif len(years) >= 1:
            # サンプル少数でも参考値として使用
            medians[chain] = int(statistics.median(years))

    return medians


def main():
    """医師experience_years拡充のメイン処理"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 更新前の統計
    before_stats = cursor.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN experience_years IS NOT NULL THEN 1 ELSE 0 END) as has_exp,
            SUM(CASE WHEN experience_years IS NULL THEN 1 ELSE 0 END) as no_exp
        FROM doctors WHERE is_active = 1
    """).fetchone()

    logger.info(f"更新前: 総数={before_stats['total']}, "
                f"experience_years有={before_stats['has_exp']}, "
                f"無={before_stats['no_exp']}")

    # チェーン別中央値を事前計算
    chain_medians = get_chain_medians(cursor)
    logger.info(f"チェーン別中央値: {len(chain_medians)}チェーン")
    for chain, median in sorted(chain_medians.items(), key=lambda x: -x[1])[:5]:
        logger.info(f"  {chain}: {median}年")

    # experience_yearsが未設定の医師を取得
    target_doctors = cursor.execute("""
        SELECT d.id, d.name, d.title, d.hospital_background, c.chain_name
        FROM doctors d
        LEFT JOIN clinics c ON d.clinic_id = c.id
        WHERE d.experience_years IS NULL AND d.is_active = 1
    """).fetchall()

    logger.info(f"対象医師数: {len(target_doctors)}名")

    # 推定ロジックの統計
    estimation_stats = {
        "title": 0,
        "background": 0,
        "chain_median": 0,
        "default": 0,
    }

    for doc in target_doctors:
        estimated_years = None
        source = None

        # ステップ1: 肩書きから推定
        title_est = estimate_from_title(doc["title"])

        # ステップ2: 勤務経歴から推定
        bg_est = estimate_from_background(doc["hospital_background"])

        # 両方ある場合は大きい方を採用
        if title_est is not None and bg_est is not None:
            if bg_est >= title_est:
                estimated_years = bg_est
                source = "background"
            else:
                estimated_years = title_est
                source = "title"
        elif title_est is not None:
            estimated_years = title_est
            source = "title"
        elif bg_est is not None:
            estimated_years = bg_est
            source = "background"

        # ステップ3: チェーン別中央値
        if estimated_years is None and doc["chain_name"]:
            chain_median = chain_medians.get(doc["chain_name"])
            if chain_median is not None:
                estimated_years = chain_median
                source = "chain_median"

        # ステップ4: デフォルト値
        if estimated_years is None:
            estimated_years = DEFAULT_EXPERIENCE_YEARS
            source = "default"

        # 更新
        cursor.execute(
            "UPDATE doctors SET experience_years = ? WHERE id = ?",
            (estimated_years, doc["id"]),
        )
        estimation_stats[source] += 1

    conn.commit()
    logger.info("experience_years推定完了")
    logger.info(f"  肩書きから:       {estimation_stats['title']}名")
    logger.info(f"  勤務経歴から:     {estimation_stats['background']}名")
    logger.info(f"  チェーン中央値:   {estimation_stats['chain_median']}名")
    logger.info(f"  デフォルト値:     {estimation_stats['default']}名")

    # trust_scoreを再計算（全医師）
    logger.info("trust_score再計算中...")
    all_docs = cursor.execute("""
        SELECT id, board_certifications, experience_years, specialties,
               profile_url, title, hospital_background, annual_case_count, jsaps_certified
        FROM doctors WHERE is_active = 1
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
    logger.info("trust_score再計算完了")

    # 更新後の統計
    after_stats = cursor.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN experience_years IS NOT NULL THEN 1 ELSE 0 END) as has_exp,
            SUM(CASE WHEN experience_years IS NULL THEN 1 ELSE 0 END) as no_exp
        FROM doctors WHERE is_active = 1
    """).fetchone()

    # experience_years分布
    exp_dist = cursor.execute("""
        SELECT
            CASE
                WHEN experience_years < 5 THEN '1-4年'
                WHEN experience_years < 10 THEN '5-9年'
                WHEN experience_years < 15 THEN '10-14年'
                WHEN experience_years < 20 THEN '15-19年'
                WHEN experience_years >= 20 THEN '20年以上'
            END as range,
            COUNT(*) as count
        FROM doctors WHERE is_active = 1 AND experience_years IS NOT NULL
        GROUP BY range ORDER BY range
    """).fetchall()

    # trust_score分布
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
        FROM doctors WHERE is_active = 1
        GROUP BY range ORDER BY range
    """).fetchall()

    # レポート出力
    print(f"\n{'='*60}")
    print(f"  Phase 65: 医師experience_years拡充 完了レポート")
    print(f"{'='*60}")

    print(f"\n  [更新サマリ]")
    print(f"  {'─'*40}")
    before_pct = before_stats['has_exp'] / before_stats['total'] * 100
    after_pct = after_stats['has_exp'] / after_stats['total'] * 100
    print(f"  experience_years有: {before_stats['has_exp']}/{before_stats['total']} "
          f"({before_pct:.0f}%) -> {after_stats['has_exp']}/{after_stats['total']} ({after_pct:.0f}%)")

    print(f"\n  [推定ソース内訳]")
    print(f"  {'─'*40}")
    print(f"  肩書き推定:       {estimation_stats['title']}名")
    print(f"  勤務経歴推定:     {estimation_stats['background']}名")
    print(f"  チェーン中央値:   {estimation_stats['chain_median']}名")
    print(f"  デフォルト(8年):  {estimation_stats['default']}名")

    print(f"\n  [experience_years分布]")
    print(f"  {'─'*40}")
    for row in exp_dist:
        print(f"  {row['range']:>8}: {row['count']}名")

    print(f"\n  [trust_score分布]")
    print(f"  {'─'*40}")
    for row in score_dist:
        bar = "#" * (row['count'] // 10)
        print(f"  {row['range']:>6}: {row['count']:>4}名  {bar}")

    print(f"\n{'='*60}\n")

    conn.close()


if __name__ == "__main__":
    main()
