"""
クリニック↔施術の診療科ベース紐付けスクリプト

クリニックの medical_departments（診療科）から対応可能な施術カテゴリを推定し、
clinic_procedures テーブルに紐付けレコードを挿入する。

§4.1データ投入検証原則: source='department_inference' でエビデンスを記録。

マッピングルール:
- 「美容外科」→ eye全般, nose全般, contour全般
- 「美容皮膚科」→ skin全般, contourのうち注入系
- 「形成外科」→ eye全般, nose全般, contour全般, skin（ボトックス、ヒアルロン酸）
- 「皮膚科」→ skin（レーザー系、ピーリング、ダーマペン）のみ

使い方:
  python clinic_enrichment.py          # dry-runモード（件数確認のみ）
  python clinic_enrichment.py --execute  # 実行モード（DBに書き込み）
"""

import sqlite3
import json
import os
import sys
from datetime import datetime, timezone
from collections import defaultdict


# 施術名からサブカテゴリを分類
# skin カテゴリの細分化: 注入系 / レーザー系 / その他
SKIN_INJECTION_PROCEDURES = {
    "ボトックス注射（しわ・表情じわ）",
    "ヒアルロン酸注入（しわ・ほうれい線）",
}

SKIN_LASER_PROCEDURES = {
    "ピコレーザー（シミ・肝斑）",
    "フォトフェイシャル（IPL光治療）",
    "レーザートーニング（シミ・くすみ）",
    "ケミカルピーリング（ニキビ跡・毛穴）",
    "ダーマペン（毛穴・ニキビ跡）",
}

SKIN_THREAD_PROCEDURES = {
    "糸リフト（たるみ・引き締め）",
}

# contour カテゴリの細分化: 注入系 / 外科系
CONTOUR_INJECTION_PROCEDURES = {
    "エラボトックス（小顔）",
    "脂肪溶解注射（二重あご・フェイスライン）",
    "ヒアルロン酸注入（あご形成）",
}

CONTOUR_SURGICAL_PROCEDURES = {
    "バッカルファット除去（頬の膨らみ）",
    "糸リフト（フェイスライン引き上げ）",
    "脂肪吸引（顎下・頬）",
}


def get_procedure_ids_by_department(
    procedures: list[tuple], department: str
) -> set[str]:
    """
    診療科に基づいて、対応可能な施術IDのセットを返す。

    Args:
        procedures: (id, name, category) のタプルリスト
        department: 診療科名

    Returns:
        対応可能な施術IDのセット
    """
    result = set()

    for proc_id, proc_name, proc_category in procedures:
        if department == "美容外科":
            # eye全般, nose全般, contour全般
            if proc_category in ("eye", "nose", "contour"):
                result.add(proc_id)

        elif department == "美容皮膚科":
            # skin全般
            if proc_category == "skin":
                result.add(proc_id)
            # contourのうち注入系
            if proc_name in CONTOUR_INJECTION_PROCEDURES:
                result.add(proc_id)

        elif department == "形成外科":
            # eye全般, nose全般, contour全般
            if proc_category in ("eye", "nose", "contour"):
                result.add(proc_id)
            # skin のうちボトックス・ヒアルロン酸
            if proc_name in SKIN_INJECTION_PROCEDURES:
                result.add(proc_id)

        elif department == "皮膚科":
            # skin のうちレーザー系・ピーリング・ダーマペンのみ
            if proc_name in SKIN_LASER_PROCEDURES:
                result.add(proc_id)

    return result


def main():
    """メイン処理: dry-run または実行モードでクリニック↔施術の紐付けを行う"""
    is_execute = "--execute" in sys.argv
    mode_label = "🚀 実行モード" if is_execute else "🔍 dry-runモード（--execute で実行）"

    db_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "aura.db")
    db_path = os.path.normpath(db_path)

    print(f"📦 データベース: {db_path}")
    print(f"📋 モード: {mode_label}")
    print()

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # 施術一覧を取得
    cur.execute("SELECT id, name, category FROM procedures ORDER BY category, name")
    procedures = cur.fetchall()
    print(f"施術数: {len(procedures)}件")

    # クリニック一覧を取得（medical_departmentsがある全件）
    cur.execute(
        "SELECT id, name, medical_departments FROM clinics "
        "WHERE medical_departments IS NOT NULL AND medical_departments != ''"
    )
    clinics = cur.fetchall()
    print(f"クリニック数: {len(clinics)}件（medical_departments有り）")
    print()

    # 紐付けレコードの生成
    now = datetime.now(timezone.utc).isoformat()
    records_to_insert = []

    # 統計情報
    stats = {
        "total_records": 0,
        "clinics_with_procedures": 0,
        "category_counts": defaultdict(int),
        "department_counts": defaultdict(int),
        "procedure_counts": defaultdict(int),
    }

    for clinic_id, clinic_name, depts_str in clinics:
        try:
            departments = json.loads(depts_str)
        except (json.JSONDecodeError, TypeError):
            continue

        if not isinstance(departments, list):
            continue

        # 各診療科から対応施術を集約（重複除去）
        matched_procedure_ids = set()
        matched_departments = set()
        for dept in departments:
            dept_procedures = get_procedure_ids_by_department(procedures, dept)
            if dept_procedures:
                matched_departments.add(dept)
            matched_procedure_ids.update(dept_procedures)

        if matched_procedure_ids:
            stats["clinics_with_procedures"] += 1
            for dept in matched_departments:
                stats["department_counts"][dept] += 1

        for proc_id in matched_procedure_ids:
            records_to_insert.append((clinic_id, proc_id, "department_inference", now, True))
            stats["total_records"] += 1

            # カテゴリ別カウント
            for p_id, p_name, p_category in procedures:
                if p_id == proc_id:
                    stats["category_counts"][p_category] += 1
                    stats["procedure_counts"][p_name] += 1
                    break

    # 結果表示
    print("=== 紐付け結果サマリー ===")
    print(f"  生成レコード数: {stats['total_records']}件")
    print(f"  紐付け対象クリニック数: {stats['clinics_with_procedures']}件")
    print()

    print("=== カテゴリ別内訳 ===")
    for category in ["eye", "nose", "skin", "contour"]:
        count = stats["category_counts"].get(category, 0)
        print(f"  {category}: {count}件")
    print()

    print("=== 診療科別クリニック数 ===")
    for dept, count in sorted(stats["department_counts"].items(), key=lambda x: -x[1]):
        print(f"  {dept}: {count}クリニック")
    print()

    print("=== 施術別紐付け数（上位10） ===")
    sorted_procs = sorted(stats["procedure_counts"].items(), key=lambda x: -x[1])
    for proc_name, count in sorted_procs[:10]:
        print(f"  {proc_name}: {count}件")
    print(f"  ... 他 {len(sorted_procs) - 10}施術")
    print()

    if is_execute:
        # 既存データの確認
        cur.execute("SELECT COUNT(*) FROM clinic_procedures")
        existing_count = cur.fetchone()[0]
        if existing_count > 0:
            print(f"⚠ 既存データ: {existing_count}件あります。重複を避けるためINSERT OR IGNOREを使用します。")

        # INSERT実行
        print("=== DB書き込み開始 ===")
        inserted_count = 0

        # バッチ挿入（パフォーマンス向上のためバッチサイズ1000）
        batch_size = 1000
        for i in range(0, len(records_to_insert), batch_size):
            batch = records_to_insert[i : i + batch_size]
            cur.executemany(
                "INSERT OR IGNORE INTO clinic_procedures "
                "(clinic_id, procedure_id, source, fetched_at, is_active) "
                "VALUES (?, ?, ?, ?, ?)",
                batch,
            )
            inserted_count += cur.rowcount
            if (i // batch_size + 1) % 10 == 0 or i + batch_size >= len(records_to_insert):
                print(f"  進捗: {min(i + batch_size, len(records_to_insert))}/{len(records_to_insert)}件処理済み")

        conn.commit()
        print()

        # 検証
        cur.execute("SELECT COUNT(*) FROM clinic_procedures")
        final_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM clinic_procedures WHERE source = 'department_inference'")
        inference_count = cur.fetchone()[0]

        print("=== 書き込み後の検証 ===")
        print(f"  総レコード数: {final_count}件")
        print(f"  うち department_inference: {inference_count}件")
        print(f"  新規挿入: {inserted_count}件")
        print()

        # カテゴリ別検証
        print("=== カテゴリ別検証（DB実数） ===")
        cur.execute("""
            SELECT p.category, COUNT(*)
            FROM clinic_procedures cp
            JOIN procedures p ON cp.procedure_id = p.id
            WHERE cp.source = 'department_inference'
            GROUP BY p.category
            ORDER BY p.category
        """)
        for category, count in cur.fetchall():
            print(f"  {category}: {count}件")

        print()
        print("✅ DB書き込み完了")
    else:
        print("ℹ️ dry-runモードのため、DBへの書き込みは行いませんでした。")
        print("   実行するには: python clinic_enrichment.py --execute")

    conn.close()
    print()
    print("✅ 完了")


if __name__ == "__main__":
    main()
