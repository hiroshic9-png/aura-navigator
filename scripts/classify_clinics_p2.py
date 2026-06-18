"""
P2改善: 一般皮膚科の分類改善

「美容皮膚科」「美容外科」「形成外科」を診療科に含まないクリニックを特定し、
editorial_summary で「一般診療も対応」と区別する。

将来、一般皮膚科が混在した場合に対応するための分類ロジック。
現時点では全クリニックが美容診療科を持つが、
improve_summaries_p2.py との整合性を保つ。
"""

import sqlite3
import json

DB_PATH = "data/aura.db"


def is_beauty_clinic(depts_json: str) -> bool:
    """
    美容クリニックかどうか判定する

    美容皮膚科・美容外科・形成外科のいずれかを
    診療科に含む場合は美容クリニックと判定。
    """
    if not depts_json:
        return False
    try:
        dept_list = (
            json.loads(depts_json) if depts_json.startswith("[")
            else [d.strip() for d in depts_json.split(",") if d.strip()]
        )
    except (json.JSONDecodeError, TypeError):
        return False
    beauty_depts = ["美容皮膚科", "美容外科", "形成外科"]
    return any(d in dept_list for d in beauty_depts)


def has_general_dermatology(depts_json: str) -> bool:
    """一般皮膚科を含むか判定する（美容皮膚科とは別）"""
    if not depts_json:
        return False
    try:
        dept_list = (
            json.loads(depts_json) if depts_json.startswith("[")
            else [d.strip() for d in depts_json.split(",") if d.strip()]
        )
    except (json.JSONDecodeError, TypeError):
        return False
    general_depts = ["皮膚科", "内科", "外科", "整形外科", "眼科", "耳鼻咽喉科"]
    return any(d in dept_list for d in general_depts)


def classify_clinic(depts_json: str) -> str:
    """
    クリニックを分類する

    返り値:
    - "beauty_only": 美容診療科のみ
    - "beauty_and_general": 美容 + 一般診療
    - "general_only": 一般診療のみ（美容科なし）
    - "unknown": 診療科情報なし
    """
    if not depts_json:
        return "unknown"

    beauty = is_beauty_clinic(depts_json)
    general = has_general_dermatology(depts_json)

    if beauty and general:
        return "beauty_and_general"
    elif beauty:
        return "beauty_only"
    elif general:
        return "general_only"
    return "unknown"


def run():
    """クリニックの分類を実行し、統計を報告する"""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    clinics = db.execute("""
        SELECT id, name, city, medical_departments, editorial_summary
        FROM clinics
        WHERE is_active = 1
    """).fetchall()

    # 分類統計
    stats = {
        "beauty_only": 0,
        "beauty_and_general": 0,
        "general_only": 0,
        "unknown": 0,
    }
    general_clinics = []
    mixed_clinics = []

    for c in clinics:
        classification = classify_clinic(c["medical_departments"])
        stats[classification] += 1

        if classification == "general_only":
            general_clinics.append(dict(c))
        elif classification == "beauty_and_general":
            mixed_clinics.append(dict(c))

    # editorial_summary の更新: 非美容クリニックに「一般診療も対応」を反映
    updated = 0
    for c_data in general_clinics:
        summary = c_data["editorial_summary"] or ""
        # 既に「一般診療も対応」が含まれていなければ追記
        if "一般診療も対応" not in summary:
            if "美容クリニック" in summary:
                # テンプレートの「美容クリニック」を置換
                summary = summary.replace("美容クリニック", "クリニック（一般診療も対応）")
            elif summary:
                # 既存サマリーに注記を追加
                summary = summary.rstrip("。") + "。一般診療にも対応しています。"
            db.execute(
                "UPDATE clinics SET editorial_summary = ? WHERE id = ?",
                (summary, c_data["id"]),
            )
            updated += 1

    db.commit()

    # 結果報告
    print("[完了] クリニック分類改善")
    print()
    print("=== 分類統計 ===")
    print(f"  美容クリニックのみ: {stats['beauty_only']}件")
    print(f"  美容 + 一般診療: {stats['beauty_and_general']}件")
    print(f"  一般診療のみ: {stats['general_only']}件")
    print(f"  診療科情報なし: {stats['unknown']}件")
    print(f"  合計: {sum(stats.values())}件")
    print()
    print(f"  editorial_summary 更新: {updated}件")

    if general_clinics:
        print()
        print("=== 一般診療のみのクリニック ===")
        for c in general_clinics[:10]:
            print(f"  {c['name']} / 診療科: {c['medical_departments']}")
            print(f"    サマリー: {(c['editorial_summary'] or '')[:80]}...")

    if mixed_clinics:
        print()
        print("=== 美容+一般診療のクリニック（上位5件） ===")
        for c in mixed_clinics[:5]:
            print(f"  {c['name']} / 診療科: {c['medical_departments']}")

    db.close()


if __name__ == "__main__":
    run()
