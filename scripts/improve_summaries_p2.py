"""
P2改善: editorial_summaryの個別化

テンプレート生成（「[X区]に位置する美容クリニック。」）の紹介文を、
各クリニック固有のデータ（医師、施術、口コミ、価格）から
個別化された文章に置き換える。

全1358クリニックの editorial_summary を再生成し、
変更前後のサンプルを報告する。
"""

import sqlite3
import json
from typing import Optional
from datetime import datetime, timedelta

DB_PATH = "data/aura.db"

# カテゴリ英語キー → 日本語ラベル
CATEGORY_LABELS = {
    "eye": "目元",
    "skin": "肌",
    "contour": "輪郭・小顔",
    "nose": "鼻",
    "anti_aging": "アンチエイジング",
    "body": "痩身・ボディ",
    "breast": "豊胸・バスト",
    "hair_removal": "医療脱毛",
}


def is_beauty_clinic(depts_json: str) -> bool:
    """美容クリニックかどうかを判定する"""
    if not depts_json:
        return False
    try:
        dept_list = json.loads(depts_json) if depts_json.startswith("[") else [
            d.strip() for d in depts_json.split(",") if d.strip()
        ]
    except (json.JSONDecodeError, TypeError):
        return False
    beauty_depts = ["美容皮膚科", "美容外科", "形成外科"]
    return any(d in dept_list for d in beauty_depts)


def get_top_categories(db: sqlite3.Connection, clinic_id: str) -> list[str]:
    """クリニックの得意施術カテゴリ上位3件を日本語で返す"""
    rows = db.execute("""
        SELECT p.category, COUNT(*) as cnt
        FROM clinic_procedures cp
        JOIN procedures p ON cp.procedure_id = p.id
        WHERE cp.clinic_id = ? AND cp.is_active = 1
        GROUP BY p.category
        ORDER BY cnt DESC
        LIMIT 3
    """, (clinic_id,)).fetchall()
    return [CATEGORY_LABELS.get(r[0], r[0]) for r in rows if r[0]]


def get_review_trend(db: sqlite3.Connection, clinic_id: str) -> Optional[str]:
    """
    口コミの評価トレンドを判定する

    直近6ヶ月 vs それ以前の平均ratingを比較し、
    上昇/下降/安定/不明 を返す。
    """
    cutoff = (datetime.now() - timedelta(days=180)).isoformat()

    recent = db.execute("""
        SELECT AVG(rating), COUNT(*) FROM reviews
        WHERE clinic_id = ? AND created_at >= ? AND rating IS NOT NULL
          AND (is_spam != 1 OR is_spam IS NULL)
    """, (clinic_id, cutoff)).fetchone()

    older = db.execute("""
        SELECT AVG(rating), COUNT(*) FROM reviews
        WHERE clinic_id = ? AND created_at < ? AND rating IS NOT NULL
          AND (is_spam != 1 OR is_spam IS NULL)
    """, (clinic_id, cutoff)).fetchone()

    recent_avg, recent_count = recent[0], recent[1]
    older_avg, older_count = older[0], older[1]

    # 各期間に最低2件必要
    if not recent_avg or recent_count < 2 or not older_avg or older_count < 2:
        return None

    diff = recent_avg - older_avg
    if diff > 0.3:
        return "improving"
    elif diff < -0.3:
        return "declining"
    return "stable"


def get_red_flag_ratio(db: sqlite3.Connection, clinic_id: str) -> float:
    """レッドフラグ口コミの割合を返す"""
    total = db.execute("""
        SELECT COUNT(*) FROM reviews
        WHERE clinic_id = ? AND (is_spam != 1 OR is_spam IS NULL)
    """, (clinic_id,)).fetchone()[0]

    if total == 0:
        return 0.0

    rf_count = db.execute("""
        SELECT COUNT(*) FROM reviews
        WHERE clinic_id = ? AND red_flags IS NOT NULL AND red_flags != '[]'
          AND (is_spam != 1 OR is_spam IS NULL)
    """, (clinic_id,)).fetchone()[0]

    return rf_count / total


def get_price_stats(db: sqlite3.Connection, clinic_id: str) -> dict:
    """クリニックの価格統計と市場平均を返す"""
    # このクリニックの平均価格
    clinic_avg = db.execute("""
        SELECT AVG(price_advertised)
        FROM clinic_procedures
        WHERE clinic_id = ? AND price_advertised > 0 AND is_active = 1
    """, (clinic_id,)).fetchone()[0]

    # 市場全体の平均価格（全クリニック）
    market_avg = db.execute("""
        SELECT AVG(price_advertised)
        FROM clinic_procedures
        WHERE price_advertised > 0 AND is_active = 1
    """).fetchone()[0]

    return {
        "avg": clinic_avg,
        "market_avg": market_avg,
    }


def generate_individual_summary(
    clinic: dict,
    doctors: list,
    top_categories: list,
    trend: Optional[str],
    red_flag_ratio: float,
    price_stats: dict,
) -> str:
    """
    クリニック固有のデータから個別化された紹介文を生成する

    強み・注意点を識別し、テンプレートではない固有の文章にする。
    """
    strengths = []
    warnings = []

    city = clinic["city"] or ""
    chain = clinic["chain_name"] or ""
    rating = clinic["google_rating"] or 0
    review_count = clinic["google_review_count"] or 0
    grade = clinic["clinic_grade"] or ""
    depts_json = clinic["medical_departments"] or ""
    beauty = is_beauty_clinic(depts_json)

    # === 強みの識別 ===

    # 1. Google評価が高い
    if rating and rating >= 4.5:
        strengths.append(f"口コミ評価{rating:.1f}と非常に高評価")
    elif rating and rating >= 4.0:
        strengths.append(f"口コミ評価{rating:.1f}と安定した評価")

    # 2. 専門医在籍
    certified_docs = [d for d in doctors if d["jsaps_certified"] or (d["trust_score"] and d["trust_score"] >= 70)]
    if certified_docs:
        if len(certified_docs) >= 3:
            strengths.append(f"専門医資格保有の医師{len(certified_docs)}名在籍")
        elif len(certified_docs) >= 1:
            strengths.append("専門医資格保有の医師が在籍")

    # 3. 価格帯の特徴
    if price_stats["avg"] and price_stats["market_avg"]:
        ratio = price_stats["avg"] / price_stats["market_avg"]
        if ratio < 0.8:
            strengths.append("市場相場より低価格帯")
        elif ratio > 1.3:
            strengths.append("プレミアム価格帯")

    # 4. 得意施術カテゴリ
    if top_categories:
        cat_str = "\u30fb".join(top_categories[:3])
        strengths.append(f"{cat_str}の施術が充実")

    # 5. 口コミトレンド
    if trend == "improving":
        strengths.append("最近の口コミ評価が上昇傾向")

    # 6. 大規模体制
    if len(doctors) >= 5:
        strengths.append(f"医師{len(doctors)}名の大規模体制")
    elif len(doctors) >= 3:
        strengths.append(f"医師{len(doctors)}名体制")

    # 7. 口コミ件数が多い
    if review_count and review_count >= 200:
        strengths.append(f"口コミ{review_count}件と豊富な実績")

    # 8. チェーン系
    if chain:
        strengths.append(f"{chain}グループ")

    # === 注意点の識別 ===

    if rating and rating < 3.5 and rating > 0:
        warnings.append("口コミ評価がやや低め")

    if red_flag_ratio > 0.15:
        warnings.append("注意すべき口コミがやや多い")

    if trend == "declining":
        warnings.append("最近の口コミ評価が下降傾向")

    if review_count and review_count < 10 and review_count > 0:
        warnings.append("口コミが少なく判断材料が限定的")

    # === サマリー生成 ===
    area_desc = city if city else "東京都"
    summary = f"{area_desc}の"

    if beauty:
        summary += "美容クリニック。"
    else:
        summary += "クリニック（一般診療も対応）。"

    # 強みを連結（最大3つ）
    if strengths:
        summary += "。".join(strengths[:3]) + "。"

    # AURAグレード
    grade_notes = {
        "A": "AURA評価は最高グレードA（情報充実度が高水準）。",
        "B": "AURA評価はグレードB（情報公開が良好）。",
        "C": "AURA評価はグレードC（標準的な情報公開）。",
        "D": "AURA評価はグレードD。公開情報がやや限定的です。",
        "E": "AURA評価はグレードE。情報収集を継続中です。",
    }
    if grade in grade_notes:
        summary += grade_notes[grade]

    # 注意点
    if warnings:
        summary += "なお、" + "、".join(warnings) + "の点は確認をお勧めします。"

    return summary


def run():
    """全クリニックの editorial_summary を個別化して更新する"""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    # 市場平均価格を事前に1回だけ取得（パフォーマンス対策）
    market_avg = db.execute("""
        SELECT AVG(price_advertised)
        FROM clinic_procedures
        WHERE price_advertised > 0 AND is_active = 1
    """).fetchone()[0]

    # 全アクティブクリニックを取得
    clinics = db.execute("""
        SELECT id, name, city, prefecture, chain_name,
               clinic_grade, clinic_score,
               google_rating, google_review_count,
               doctor_count, medical_departments,
               editorial_summary
        FROM clinics
        WHERE is_active = 1
    """).fetchall()

    updated = 0
    samples_before_after = []

    for c in clinics:
        clinic_data = dict(c)
        clinic_id = c["id"]

        # 医師情報を取得
        doctors_rows = db.execute("""
            SELECT name, jsaps_certified, trust_score
            FROM doctors
            WHERE clinic_id = ? AND is_active = 1
        """, (clinic_id,)).fetchall()
        doctors = [dict(d) for d in doctors_rows]

        # 得意施術カテゴリ
        top_cats = get_top_categories(db, clinic_id)

        # 口コミトレンド
        trend = get_review_trend(db, clinic_id)

        # レッドフラグ割合
        rf_ratio = get_red_flag_ratio(db, clinic_id)

        # クリニック価格統計
        clinic_avg = db.execute("""
            SELECT AVG(price_advertised)
            FROM clinic_procedures
            WHERE clinic_id = ? AND price_advertised > 0 AND is_active = 1
        """, (clinic_id,)).fetchone()[0]

        price_stats = {
            "avg": clinic_avg,
            "market_avg": market_avg,
        }

        # 個別化サマリー生成
        new_summary = generate_individual_summary(
            clinic_data, doctors, top_cats, trend, rf_ratio, price_stats,
        )

        if new_summary and len(new_summary) > 20:
            old_summary = c["editorial_summary"] or ""

            # 変更サンプル収集（前後比較用、最大5件）
            if len(samples_before_after) < 5 and old_summary != new_summary:
                samples_before_after.append({
                    "name": c["name"],
                    "id": clinic_id,
                    "grade": c["clinic_grade"],
                    "old": old_summary,
                    "new": new_summary,
                })

            db.execute(
                "UPDATE clinics SET editorial_summary = ? WHERE id = ?",
                (new_summary, clinic_id),
            )
            updated += 1

    db.commit()

    # 結果報告
    print(f"[完了] editorial_summary 個別化: {updated}件更新 / {len(clinics)}件中")
    print()

    # 変更前後サンプル5件
    print("=== 変更前後サンプル ===")
    for i, s in enumerate(samples_before_after, 1):
        print(f"\n--- サンプル {i}: {s['name']} [{s['grade']}] ---")
        print(f"  [変更前] {s['old'][:120]}...")
        print(f"  [変更後] {s['new'][:120]}...")

    # 統計: テンプレートパターンの残存チェック
    template_remaining = db.execute(
        "SELECT COUNT(*) FROM clinics WHERE is_active=1 AND editorial_summary LIKE '%に位置する美容クリニック%'"
    ).fetchone()[0]
    print(f"\n[統計] テンプレートパターン残存: {template_remaining}件")

    # 美容/非美容の分類統計
    all_clinics = db.execute(
        "SELECT medical_departments FROM clinics WHERE is_active=1"
    ).fetchall()
    beauty_count = sum(1 for c in all_clinics if is_beauty_clinic(c["medical_departments"]))
    non_beauty = len(all_clinics) - beauty_count
    print(f"[分類] 美容クリニック: {beauty_count}件 / 非美容: {non_beauty}件")

    db.close()


if __name__ == "__main__":
    run()
