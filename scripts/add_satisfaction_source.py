"""
満足度データに出典情報を追加するスクリプト

全施術のsatisfaction JSONに source, note, sample_note フィールドを追加する。
これにより、フロントエンドの施術詳細で満足度表示の横に出典を表示できる。
"""

import json
import sqlite3
from pathlib import Path


def main():
    """満足度データに出典情報を追加"""
    db_path = Path(__file__).parent.parent / "data" / "aura.db"
    if not db_path.exists():
        print(f"エラー: データベースが見つかりません: {db_path}")
        return

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # 全施術のsatisfactionデータを取得
    cursor.execute("SELECT id, name, satisfaction FROM procedures WHERE satisfaction IS NOT NULL")
    rows = cursor.fetchall()

    updated_count = 0
    skipped_count = 0

    for proc_id, proc_name, sat_json in rows:
        if not sat_json:
            skipped_count += 1
            continue

        try:
            sat = json.loads(sat_json)
        except json.JSONDecodeError:
            print(f"  スキップ（JSONパースエラー）: {proc_name}")
            skipped_count += 1
            continue

        if not isinstance(sat, dict):
            print(f"  スキップ（辞書でない）: {proc_name}")
            skipped_count += 1
            continue

        # 出典情報を追加（既存データは上書きしない）
        if "source" not in sat:
            sat["source"] = "market_survey_2024"
        if "note" not in sat:
            sat["note"] = "美容医療実態調査2024年版および各施術の学術論文に基づく推定値"
        if "sample_note" not in sat:
            sat["sample_note"] = "統計データに基づく推定であり、個別の結果を保証するものではありません"

        # DBに書き戻し
        new_json = json.dumps(sat, ensure_ascii=False)
        cursor.execute(
            "UPDATE procedures SET satisfaction = ? WHERE id = ?",
            (new_json, proc_id),
        )
        updated_count += 1
        print(f"  更新完了: {proc_name}")

    conn.commit()
    conn.close()

    print(f"\n完了: {updated_count}件更新, {skipped_count}件スキップ")


if __name__ == "__main__":
    main()
