"""
Phase 41: クリニック紹介文の自動生成

既存データ（診療科、エリア、Google評価、口コミ数、医師情報、施術数、
チェーン名、スコア、グレード）から構造的に紹介文を生成。
LLMは使用せず、テンプレートベースの日本語文章を組み立てる。
"""

import sqlite3
import json

DB_PATH = "data/aura.db"


def generate_summary(clinic: dict) -> str:
    """クリニックデータから紹介文を生成"""
    parts = []

    name = clinic["name"]
    city = clinic["city"] or ""
    prefecture = clinic["prefecture"] or "東京都"
    chain = clinic["chain_name"] or ""
    grade = clinic["clinic_grade"] or ""
    score = clinic["clinic_score"] or 0
    rating = clinic["google_rating"] or 0
    review_count = clinic["google_review_count"] or 0
    doc_count = clinic["doctor_count"] or 0
    proc_count = clinic["proc_count"] or 0
    depts = clinic["medical_departments"] or ""

    # 1行目: 所在地と概要
    area_desc = f"{city}" if city else prefecture
    if chain:
        parts.append(f"{area_desc}に位置する{chain}グループのクリニック。")
    else:
        parts.append(f"{area_desc}に位置する美容クリニック。")

    # 診療科目
    if depts:
        # JSON配列形式の場合
        try:
            dept_list = json.loads(depts) if depts.startswith("[") else [d.strip() for d in depts.split(",") if d.strip()]
        except (json.JSONDecodeError, TypeError):
            dept_list = [d.strip() for d in depts.split(",") if d.strip()]

        if len(dept_list) >= 2:
            parts.append(f"{'・'.join(dept_list[:3])}を専門としています。")
        elif len(dept_list) == 1:
            parts.append(f"{dept_list[0]}を専門としています。")

    # Google評価
    if rating and rating > 0:
        if rating >= 4.5:
            parts.append(f"Google評価{rating:.1f}と非常に高い評価を得ており、{review_count}件の口コミがあります。")
        elif rating >= 4.0:
            parts.append(f"Google評価{rating:.1f}と安定した評価を受けています（{review_count}件）。")
        elif rating >= 3.5:
            parts.append(f"Google評価は{rating:.1f}（{review_count}件の口コミ）。")
        else:
            parts.append(f"Google評価{rating:.1f}（{review_count}件）。口コミの内容も合わせてご確認ください。")

    # 施術数
    if proc_count > 0:
        if proc_count >= 20:
            parts.append(f"対応施術は{proc_count}種類以上と幅広い選択肢を提供しています。")
        elif proc_count >= 10:
            parts.append(f"約{proc_count}種類の施術に対応しています。")

    # 医師情報
    if doc_count and doc_count > 0:
        if doc_count >= 5:
            parts.append(f"在籍医師{doc_count}名の大規模体制。")
        elif doc_count >= 2:
            parts.append(f"医師{doc_count}名体制。")

    # AURAグレード
    grade_comments = {
        "A": "AURAの客観評価では最高グレードAを獲得しており、情報の透明性と信頼性が高い水準にあります。",
        "B": "AURAの客観評価ではグレードBを獲得。情報の透明性は良好な水準です。",
        "C": "AURAの客観評価はグレードC。標準的な情報公開状況です。",
        "D": "AURA評価はグレードD。公開情報がやや限定的なため、カウンセリングでの確認をお勧めします。",
        "E": "AURA評価はグレードE。情報収集を継続中です。",
    }
    if grade in grade_comments:
        parts.append(grade_comments[grade])

    return "".join(parts)


def run():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    # クリニックデータと施術数を取得
    clinics = db.execute("""
        SELECT c.id, c.name, c.city, c.prefecture, c.chain_name,
               c.clinic_grade, c.clinic_score,
               c.google_rating, c.google_review_count,
               c.doctor_count, c.medical_departments,
               c.editorial_summary,
               (SELECT COUNT(*) FROM clinic_procedures cp 
                WHERE cp.clinic_id = c.id) as proc_count
        FROM clinics c
        WHERE c.is_active = 1
    """).fetchall()

    updated = 0
    skipped = 0

    for c in clinics:
        # 既存の紹介文がある場合はスキップ
        if c["editorial_summary"] and c["editorial_summary"].strip():
            skipped += 1
            continue

        clinic_data = dict(c)
        summary = generate_summary(clinic_data)

        if summary and len(summary) > 20:
            db.execute(
                "UPDATE clinics SET editorial_summary = ? WHERE id = ?",
                (summary, c["id"]),
            )
            updated += 1

    db.commit()
    print(f"✅ 紹介文生成完了: {updated}件更新, {skipped}件スキップ")

    # サンプル表示
    print("\n=== サンプル (上位3件) ===")
    samples = db.execute("""
        SELECT name, editorial_summary, clinic_grade, clinic_score
        FROM clinics WHERE editorial_summary IS NOT NULL AND editorial_summary != ''
        ORDER BY clinic_score DESC LIMIT 3
    """).fetchall()
    for s in samples:
        print(f"\n[{s['clinic_grade']}] {s['name']} (スコア: {s['clinic_score']})")
        print(f"  {s['editorial_summary']}")

    db.close()


if __name__ == "__main__":
    run()
