"""
AURA MVP -- P0-3: 医師データクレンジングスクリプト

非医師レコード（歯科衛生士・労働衛生・看護師等）を特定し、
is_active=0 に設定して無効化する。
名前が1文字のレコード（姓のみの可能性）はリストアップのみ行う。

実行:
    .venv/bin/python scripts/cleanse_doctors_p0.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "aura.db"

# 医師として不適切な名前パターン
INVALID_NAMES = [
    "歯科衛生士",
    "労働衛生",
    "看護師",
    "スタッフ",
    "受付",
    "事務",
    "助手",
    "技師",
    "衛生士",
]


def main():
    """医師データクレンジングのメイン処理"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 修正前の統計
    total = cursor.execute("SELECT COUNT(*) FROM doctors").fetchone()[0]
    active = cursor.execute(
        "SELECT COUNT(*) FROM doctors WHERE is_active = 1"
    ).fetchone()[0]
    inactive = cursor.execute(
        "SELECT COUNT(*) FROM doctors WHERE is_active = 0 OR is_active IS NULL"
    ).fetchone()[0]

    print(f"\n{'='*60}")
    print(f"  P0-3: 医師データクレンジング")
    print(f"{'='*60}")
    print(f"\n  [修正前の統計]")
    print(f"  {'─'*40}")
    print(f"  医師レコード総数:  {total}")
    print(f"  アクティブ:        {active}")
    print(f"  非アクティブ:      {inactive}")

    # === 1. 非医師レコードの特定と無効化 ===
    print(f"\n  [非医師レコードの特定]")
    print(f"  {'─'*40}")

    # 完全一致で検索
    placeholders = ", ".join(["?"] * len(INVALID_NAMES))
    invalid_doctors = cursor.execute(
        f"""
        SELECT d.id, d.name, d.title, d.is_active, c.name as clinic_name
        FROM doctors d
        LEFT JOIN clinics c ON d.clinic_id = c.id
        WHERE d.name IN ({placeholders})
        ORDER BY d.name
        """,
        INVALID_NAMES,
    ).fetchall()

    # 既にis_active=0のレコードはスキップ
    to_deactivate = []
    for doc in invalid_doctors:
        status = "active" if doc["is_active"] else "already_inactive"
        print(
            f"  - \"{doc['name']}\" (title={doc['title']}) "
            f"@ {doc['clinic_name'] or '不明'} [{status}]"
        )
        if doc["is_active"]:
            to_deactivate.append(doc["id"])

    if not invalid_doctors:
        print("  該当レコードなし")

    # 無効化実行
    deactivated_count = 0
    if to_deactivate:
        placeholders = ", ".join(["?"] * len(to_deactivate))
        cursor.execute(
            f"UPDATE doctors SET is_active = 0 WHERE id IN ({placeholders})",
            to_deactivate,
        )
        deactivated_count = cursor.rowcount
        conn.commit()
        print(f"\n  >> {deactivated_count}件を無効化 (is_active=0)")
    else:
        print(f"\n  >> 無効化対象なし（全て既に処理済み、または該当なし）")

    # === 2. 名前が1文字のレコードの確認 ===
    print(f"\n  [名前が1文字のレコード（姓のみの可能性）]")
    print(f"  {'─'*40}")

    single_char_doctors = cursor.execute(
        """
        SELECT d.id, d.name, d.title, d.is_active, d.trust_score,
               c.name as clinic_name
        FROM doctors d
        LEFT JOIN clinics c ON d.clinic_id = c.id
        WHERE length(d.name) = 1
        ORDER BY d.name
        """
    ).fetchall()

    if single_char_doctors:
        for doc in single_char_doctors:
            status = "active" if doc["is_active"] else "inactive"
            score = f"score={doc['trust_score']:.1f}" if doc["trust_score"] else "score=未算出"
            print(
                f"  - \"{doc['name']}\" (title={doc['title']}) "
                f"@ {doc['clinic_name'] or '不明'} "
                f"[{status}, {score}]"
            )
        print(f"\n  >> {len(single_char_doctors)}件検出 -- is_activeは維持（要目視確認）")
    else:
        print("  該当レコードなし")

    # === 3. 修正後の統計 ===
    after_total = cursor.execute("SELECT COUNT(*) FROM doctors").fetchone()[0]
    after_active = cursor.execute(
        "SELECT COUNT(*) FROM doctors WHERE is_active = 1"
    ).fetchone()[0]
    after_inactive = cursor.execute(
        "SELECT COUNT(*) FROM doctors WHERE is_active = 0 OR is_active IS NULL"
    ).fetchone()[0]

    print(f"\n  [修正後の統計]")
    print(f"  {'─'*40}")
    print(f"  医師レコード総数:  {after_total}")
    print(f"  アクティブ:        {after_active} (変化: {after_active - active:+d})")
    print(f"  非アクティブ:      {after_inactive} (変化: {after_inactive - inactive:+d})")

    # === 4. 影響確認: APIフィルタの確認 ===
    print(f"\n  [APIフィルタ確認]")
    print(f"  {'─'*40}")
    # 無効化した医師がAPIで返されないことを確認
    if to_deactivate:
        placeholders = ", ".join(["?"] * len(to_deactivate))
        still_visible = cursor.execute(
            f"""
            SELECT id, name FROM doctors
            WHERE id IN ({placeholders}) AND is_active = 1
            """,
            to_deactivate,
        ).fetchall()
        if still_visible:
            print(f"  [WARNING] 無効化が反映されていないレコード: {len(still_visible)}件")
            for doc in still_visible:
                print(f"    - {doc['name']} (id={doc['id']})")
        else:
            print(f"  OK: 無効化された{deactivated_count}件はis_active=0で")
            print(f"      APIフィルタ (DoctorTable.is_active != 0) により除外される")
    else:
        print(f"  -- 新規無効化なし")

    print(f"\n{'='*60}\n")

    conn.close()


if __name__ == "__main__":
    main()
