#!/usr/bin/env python3
"""
症例写真 → 医師 紐付けスクリプト

case_photosテーブルのdoctor_name（テキスト）を元に、
doctorsテーブルのnameとマッチングしてdoctor_idを設定する。

マッチング戦略（フォールバック方式）:
  1. 完全一致: doctor_name == doctors.name
  2. 部分一致: doctor_name が doctors.name に含まれる（または逆）
  3. 姓のみ一致: doctor_nameの姓部分がdoctors.nameの先頭と一致
     ※ 同一clinic_id（またはチェーン）内で一意の場合のみ

使い方:
    uv run python scripts/link_case_photos_doctors.py --dry-run
    uv run python scripts/link_case_photos_doctors.py
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "aura.db"

# 医師名として不適切な値（ゴミデータ除外パターン）
INVALID_DOCTOR_NAMES = {
    "二重埋没法", "二重切開法", "目頭切開", "目尻切開",
    "鼻尖縮小", "隆鼻", "小鼻縮小", "糸リフト",
    "不在日", "世界最高峰", "下北沢",
    "上野院院長",  # 院名が紛れ込んでいるケース
}

# 医師名として無効なパターン（正規表現）
INVALID_NAME_PATTERNS = [
    re.compile(r"^[A-Za-z0-9\s]+$"),     # 英数字のみ
    re.compile(r"^[\s　]+$"),              # 空白のみ
    re.compile(r"院[長$]"),                # 「○○院長」単独
    re.compile(r"^.{1}$"),                 # 1文字のみ
]


def is_valid_doctor_name(name: str) -> bool:
    """有効な医師名かどうかを判定"""
    if not name or not name.strip():
        return False
    name = name.strip()
    if name in INVALID_DOCTOR_NAMES:
        return False
    for pattern in INVALID_NAME_PATTERNS:
        if pattern.match(name):
            return False
    return True


def extract_surname(name: str) -> str | None:
    """医師名から姓を抽出（日本語の姓は通常1-3文字）"""
    name = name.strip()
    # 「姓 名」（スペース区切り）
    parts = re.split(r"[\s　]+", name)
    if len(parts) >= 2:
        return parts[0]
    # スペースなしの場合、2-3文字を姓と推定
    if len(name) >= 3:
        # 3文字姓（長谷川、小笠原等）は少数だが考慮
        return name[:2]  # まず2文字で試行
    return None


def build_doctor_lookup(conn: sqlite3.Connection) -> dict:
    """
    doctorsテーブルから検索用の辞書を構築

    戻り値:
        {
            "names": {name: [doctor_rows]},  # 名前→医師リスト
            "by_clinic": {clinic_id: [doctor_rows]},  # クリニックID→医師リスト
            "chain_clinics": {chain_name: [clinic_ids]},  # チェーン名→クリニックIDリスト
        }
    """
    c = conn.cursor()

    # 全医師データを取得
    c.execute("""
        SELECT d.id, d.name, d.clinic_id, c.chain_name
        FROM doctors d
        LEFT JOIN clinics c ON d.clinic_id = c.id
        WHERE d.is_active != 0 OR d.is_active IS NULL
    """)
    doctors = c.fetchall()

    names: dict[str, list] = {}
    by_clinic: dict[str, list] = {}
    chain_clinics: dict[str, list] = {}

    for doc_id, doc_name, clinic_id, chain_name in doctors:
        if not is_valid_doctor_name(doc_name):
            continue

        doc_row = {
            "id": doc_id,
            "name": doc_name.strip(),
            "clinic_id": clinic_id,
            "chain_name": chain_name,
        }

        # 名前インデックス
        clean_name = doc_name.strip()
        names.setdefault(clean_name, []).append(doc_row)

        # クリニック別インデックス
        if clinic_id:
            by_clinic.setdefault(clinic_id, []).append(doc_row)

        # チェーン別クリニックインデックス
        if chain_name:
            if chain_name not in chain_clinics:
                chain_clinics[chain_name] = set()
            chain_clinics[chain_name].add(clinic_id)

    # setをlistに変換
    chain_clinics = {k: list(v) for k, v in chain_clinics.items()}

    return {
        "names": names,
        "by_clinic": by_clinic,
        "chain_clinics": chain_clinics,
    }


def get_chain_name_for_clinic(conn: sqlite3.Connection, clinic_id: str) -> str | None:
    """clinic_idからチェーン名を取得"""
    c = conn.cursor()
    c.execute("SELECT chain_name FROM clinics WHERE id = ?", (clinic_id,))
    row = c.fetchone()
    return row[0] if row else None


def resolve_doctor_id(
    doctor_name: str,
    clinic_id: str | None,
    chain_name: str | None,
    lookup: dict,
) -> tuple[str | None, str]:
    """
    doctor_nameテキストからdoctor_idを解決する

    マッチング優先順位:
      1. 完全一致（同一チェーン内で優先）
      2. 部分一致（doctor_nameがdoctors.nameに含まれる or 逆）
      3. 姓のみ一致（同一チェーン内で一意の場合のみ）

    戻り値: (doctor_id or None, match_method)
    """
    if not doctor_name or not is_valid_doctor_name(doctor_name):
        return None, "invalid"

    clean_name = doctor_name.strip()
    names_lookup = lookup["names"]
    by_clinic = lookup["by_clinic"]
    chain_clinics = lookup["chain_clinics"]

    # チェーン内の全医師を取得
    chain_doctors = []
    if chain_name and chain_name in chain_clinics:
        for cid in chain_clinics[chain_name]:
            chain_doctors.extend(by_clinic.get(cid, []))

    # ---- Step 1: 完全一致 ----
    if clean_name in names_lookup:
        candidates = names_lookup[clean_name]

        # 同一チェーン内で完全一致
        if chain_name:
            chain_matches = [d for d in candidates if d["chain_name"] == chain_name]
            if len(chain_matches) == 1:
                return chain_matches[0]["id"], "exact_chain"
            if chain_matches:
                # 複数一致の場合は最初のものを使用
                return chain_matches[0]["id"], "exact_chain_multi"

        # チェーン外でも完全一致が1件なら採用
        if len(candidates) == 1:
            return candidates[0]["id"], "exact"

    # ---- Step 2: 部分一致 ----
    partial_matches = []
    search_pool = chain_doctors if chain_doctors else [
        doc for docs in names_lookup.values() for doc in docs
    ]

    for doc in search_pool:
        doc_name = doc["name"]
        # doctor_nameがdoctors.nameに含まれる or 逆
        if clean_name in doc_name or doc_name in clean_name:
            partial_matches.append(doc)

    if len(partial_matches) == 1:
        return partial_matches[0]["id"], "partial"

    # ---- Step 3: 姓のみ一致（同一チェーン内で一意の場合のみ） ----
    surname = extract_surname(clean_name)
    if surname and chain_doctors:
        surname_matches = [
            d for d in chain_doctors
            if d["name"].startswith(surname)
        ]
        if len(surname_matches) == 1:
            return surname_matches[0]["id"], "surname"

    return None, "no_match"


def main():
    """メイン処理"""
    import argparse

    parser = argparse.ArgumentParser(description="症例写真 → 医師 紐付けスクリプト")
    parser.add_argument("--dry-run", action="store_true", help="DB書き込みせずに結果を表示")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    print("=" * 60)
    print("症例写真 → 医師 紐付けスクリプト")
    print("=" * 60)

    # --- 医師データのロード ---
    print("\n--- 医師データのロード ---")
    lookup = build_doctor_lookup(conn)
    total_doctors = sum(len(v) for v in lookup["names"].values())
    print(f"  有効医師データ: {total_doctors}件")
    print(f"  チェーン数: {len(lookup['chain_clinics'])}件")
    for chain, cids in lookup["chain_clinics"].items():
        doc_count = sum(len(lookup["by_clinic"].get(cid, [])) for cid in cids)
        if chain:
            print(f"    {chain}: {doc_count}名")

    # --- 対象データ取得 ---
    print("\n--- case_photos doctor_name → doctor_id マッピング ---")
    c.execute("""
        SELECT cp.id, cp.doctor_name, cp.clinic_id
        FROM case_photos cp
        WHERE (cp.is_active != 0 OR cp.is_active IS NULL)
        AND cp.doctor_name IS NOT NULL AND cp.doctor_name != ''
    """)
    rows = c.fetchall()
    print(f"  doctor_name非NULLの症例写真: {len(rows)}件")

    if not rows:
        print("\n  ⚠️  doctor_nameが設定された症例写真がありません。")
        print("  スクレイパーでdoctor_nameを取得してから再実行してください。")

        # 全体統計を表示
        _print_final_stats(conn, c, args.dry_run)
        conn.close()
        return

    # --- マッチング実行 ---
    updated = 0
    match_stats: dict[str, int] = {}
    failed_names: dict[str, int] = {}

    # clinic_id → chain_name のキャッシュ
    chain_cache: dict[str, str | None] = {}

    for cp_id, doctor_name, clinic_id in rows:
        # チェーン名をキャッシュ付きで解決
        if clinic_id and clinic_id not in chain_cache:
            chain_cache[clinic_id] = get_chain_name_for_clinic(conn, clinic_id)
        chain_name = chain_cache.get(clinic_id)

        doctor_id, method = resolve_doctor_id(
            doctor_name, clinic_id, chain_name, lookup
        )

        match_stats[method] = match_stats.get(method, 0) + 1

        if doctor_id:
            if not args.dry_run:
                c.execute(
                    "UPDATE case_photos SET doctor_id = ? WHERE id = ?",
                    (doctor_id, cp_id),
                )
            updated += 1
        else:
            name = doctor_name.strip()
            failed_names[name] = failed_names.get(name, 0) + 1

    if not args.dry_run:
        conn.commit()

    # --- 結果表示 ---
    total_target = len(rows)
    match_rate = (updated / total_target * 100) if total_target > 0 else 0

    print(f"\n  ✅ マッチ成功: {updated}/{total_target}件 ({match_rate:.1f}%)")
    print(f"  ❌ 未マッチ: {total_target - updated}件")

    print("\n  マッチ方法内訳:")
    method_labels = {
        "exact_chain": "完全一致（同一チェーン内）",
        "exact_chain_multi": "完全一致（同一チェーン内・複数候補）",
        "exact": "完全一致（全体）",
        "partial": "部分一致",
        "surname": "姓のみ一致",
        "no_match": "未マッチ",
        "invalid": "無効な医師名",
    }
    for method, count in sorted(match_stats.items(), key=lambda x: -x[1]):
        label = method_labels.get(method, method)
        print(f"    {label}: {count}件")

    if failed_names:
        print(f"\n  未マッチ医師名 (上位15件):")
        for name, cnt in sorted(failed_names.items(), key=lambda x: -x[1])[:15]:
            print(f"    「{name}」: {cnt}件")

    # --- 最終統計 ---
    _print_final_stats(conn, c, args.dry_run)
    conn.close()


def _print_final_stats(conn: sqlite3.Connection, c: sqlite3.Cursor, dry_run: bool):
    """最終統計を表示"""
    print(f"\n{'='*60}")
    print(f"{'[DRY-RUN] ' if dry_run else ''}完了")
    print(f"{'='*60}")

    c.execute("""
        SELECT COUNT(*) FROM case_photos
        WHERE is_active != 0 OR is_active IS NULL
    """)
    total = c.fetchone()[0]

    c.execute("""
        SELECT COUNT(*) FROM case_photos
        WHERE doctor_id IS NOT NULL
        AND (is_active != 0 OR is_active IS NULL)
    """)
    with_doctor = c.fetchone()[0]

    c.execute("""
        SELECT COUNT(*) FROM case_photos
        WHERE doctor_name IS NOT NULL AND doctor_name != ''
        AND (is_active != 0 OR is_active IS NULL)
    """)
    with_doctor_name = c.fetchone()[0]

    doctor_rate = (with_doctor / total * 100) if total > 0 else 0
    print(f"  有効症例写真: {total}件")
    print(f"  doctor_name設定済み: {with_doctor_name}/{total}件")
    print(f"  doctor_id紐付け済み: {with_doctor}/{total} ({doctor_rate:.1f}%)")


if __name__ == "__main__":
    main()
