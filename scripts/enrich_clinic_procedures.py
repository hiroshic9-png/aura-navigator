"""
AURA MVP — 4カテゴリ clinic_procedures 拡充スクリプト

anti_aging / body / breast / hair_removal の4カテゴリに
チェーン推定 + 診療科目ベースでclinic_proceduresを投入する。
"""

import json
import sqlite3

DB_PATH = "data/aura.db"

# チェーン別の対応施術カテゴリ
CHAIN_PROCEDURE_MAP = {
    "湘南美容クリニック": ["anti_aging", "body", "breast", "hair_removal"],
    "TCB東京中央美容外科": ["anti_aging", "body", "breast", "hair_removal"],
    "品川美容外科": ["anti_aging", "body", "hair_removal"],
    "共立美容外科": ["anti_aging", "body", "breast"],
    "聖心美容クリニック": ["anti_aging", "body", "breast", "hair_removal"],
    "城本クリニック": ["anti_aging", "body", "breast", "hair_removal"],
    "高須クリニック": ["anti_aging", "body", "breast"],
    "水の森美容クリニック": ["anti_aging", "body", "breast"],
    "ガーデンクリニック": ["anti_aging", "body", "breast", "hair_removal"],
    "TAクリニック": ["anti_aging", "body", "breast"],
    "東京美容外科": ["anti_aging", "body", "breast"],
    "もとび美容外科": ["anti_aging", "body", "breast"],
    "大塚美容形成外科": ["anti_aging", "body", "breast"],
    "THE CLINIC": ["body", "breast"],
    "ヴェリテクリニック": ["anti_aging", "body", "breast"],
    # 脱毛専門チェーン
    "リゼクリニック": ["hair_removal"],
    "レジーナクリニック": ["hair_removal"],
    "エミナルクリニック": ["hair_removal"],
    "フレイアクリニック": ["hair_removal"],
    "アリシアクリニック": ["hair_removal"],
    "じぶんクリニック": ["hair_removal"],
    "ルシアクリニック": ["hair_removal"],
    "グロウクリニック": ["hair_removal"],
    "B-LINEクリニック": ["hair_removal"],
    # 皮膚科系チェーン
    "銀座よしえクリニック": ["anti_aging"],
    "シロノクリニック": ["anti_aging"],
    "表参道スキンクリニック": ["anti_aging"],
}

# 診療科目ベースの施術推定
DEPARTMENT_PROCEDURE_MAP = {
    "美容外科": ["anti_aging", "body", "breast"],
    "形成外科": ["anti_aging", "body"],
    "美容皮膚科": ["anti_aging"],
    "皮膚科": ["anti_aging"],
}

# カテゴリごとの代表施術（クリニックがそのカテゴリに対応する場合に紐付け）
CATEGORY_KEY_PROCEDURES = {
    "anti_aging": [
        "HIFU（ハイフ）リフトアップ",
        "ヒアルロン酸注入（しわ・ほうれい線）",
        "ボトックス注射（しわ・表情じわ）",
        "糸リフト（たるみ・引き締め）",
        "PRP療法（再生医療）",
        "水光注射",
        "エレクトロポレーション",
    ],
    "body": [
        "脂肪吸引（腹部・太もも）",
        "脂肪溶解注射（ボディ）",
        "クールスカルプティング",
        "HIFU痩身（ハイフ）",
    ],
    "breast": [
        "豊胸手術（シリコンバッグ）",
        "豊胸手術（脂肪注入）",
        "ヒアルロン酸豊胸",
    ],
    "hair_removal": [
        "医療レーザー脱毛（全身）",
        "医療レーザー脱毛（顔）",
        "医療レーザー脱毛（VIO）",
    ],
}


def main():
    """4カテゴリのclinic_proceduresを投入"""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    # 施術ID取得
    procedures = db.execute("SELECT id, name, category FROM procedures").fetchall()
    proc_by_name = {p["name"]: p for p in procedures}

    # 既存のclinic_proceduresを取得（重複防止）
    existing = set()
    rows = db.execute(
        "SELECT clinic_id, procedure_id FROM clinic_procedures WHERE is_active = 1"
    ).fetchall()
    for r in rows:
        existing.add((r["clinic_id"], r["procedure_id"]))

    # 全クリニック取得
    clinics = db.execute(
        "SELECT id, chain_name, medical_departments FROM clinics WHERE is_active = 1"
    ).fetchall()

    import uuid

    inserted = 0
    category_counts = {"anti_aging": 0, "body": 0, "breast": 0, "hair_removal": 0}

    for clinic in clinics:
        clinic_id = clinic["id"]
        chain = clinic["chain_name"] or ""
        depts_raw = clinic["medical_departments"] or "[]"
        try:
            depts = json.loads(depts_raw) if depts_raw else []
        except (json.JSONDecodeError, TypeError):
            depts = []

        # このクリニックが対応するカテゴリを特定
        target_categories = set()

        # チェーンベース推定
        if chain and chain in CHAIN_PROCEDURE_MAP:
            target_categories.update(CHAIN_PROCEDURE_MAP[chain])

        # 診療科目ベース推定
        for dept in depts:
            for dept_key, cats in DEPARTMENT_PROCEDURE_MAP.items():
                if dept_key in str(dept):
                    target_categories.update(cats)

        # 施術データ投入
        for category in target_categories:
            proc_names = CATEGORY_KEY_PROCEDURES.get(category, [])
            for proc_name in proc_names:
                proc = proc_by_name.get(proc_name)
                if not proc:
                    continue
                if (clinic_id, proc["id"]) in existing:
                    continue

                db.execute("""
                    INSERT INTO clinic_procedures (clinic_id, procedure_id, source, is_active)
                    VALUES (?, ?, 'chain_inference', 1)
                """, (clinic_id, proc["id"]))
                existing.add((clinic_id, proc["id"]))
                category_counts[category] = category_counts.get(category, 0) + 1
                inserted += 1

    db.commit()
    db.close()

    print(f"=== clinic_procedures投入完了: {inserted}件 ===\n")
    for cat, count in category_counts.items():
        label = {"anti_aging": "アンチエイジング", "body": "痩身・ボディ",
                 "breast": "豊胸・バスト", "hair_removal": "医療脱毛"}.get(cat, cat)
        print(f"  {label}: {count}件")


if __name__ == "__main__":
    main()
