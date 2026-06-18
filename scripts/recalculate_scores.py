#!/usr/bin/env python3
"""
医師trust_score一括再計算スクリプト (v4)

v4スコアリングロジックで全有効医師のtrust_scoreを再計算する。
case_photos件数はchain_name単位で集計し、同チェーンの医師に均等配分する。

使い方:
    uv run python scripts/recalculate_scores.py --dry-run
    uv run python scripts/recalculate_scores.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

# スコアリングエンジンをインポート
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from analyzers.doctor_scoring import calculate_trust_score

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "aura.db"


def main():
    """メイン処理"""
    import argparse
    parser = argparse.ArgumentParser(description="医師trust_score一括再計算 (v4)")
    parser.add_argument("--dry-run", action="store_true", help="DBに書き込まず結果のみ表示")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    print("=" * 60)
    print("医師trust_score一括再計算 (v4)")
    print("=" * 60)

    # 1. chain_name単位でcase_photos件数を集計
    print("\n--- 症例写真件数の集計 ---")
    c.execute("""
        SELECT clinic_name, COUNT(*) as cnt
        FROM case_photos
        WHERE is_active != 0 OR is_active IS NULL
        GROUP BY clinic_name
    """)
    chain_case_counts: dict[str, int] = {}
    for row in c.fetchall():
        if row["clinic_name"]:
            chain_case_counts[row["clinic_name"]] = row["cnt"]
            print(f"  {row['clinic_name']}: {row['cnt']}件")

    # 2. chain_name → 所属医師数
    c.execute("""
        SELECT c.chain_name, COUNT(d.id) as doctor_count
        FROM doctors d
        JOIN clinics c ON d.clinic_id = c.id
        WHERE (d.is_active != 0 OR d.is_active IS NULL)
        AND c.chain_name IS NOT NULL AND c.chain_name != ''
        GROUP BY c.chain_name
    """)
    chain_doctor_counts: dict[str, int] = {}
    for row in c.fetchall():
        chain_doctor_counts[row["chain_name"]] = row["doctor_count"]

    # 3. 全有効医師を取得
    c.execute("""
        SELECT d.id, d.name, d.board_certifications, d.hospital_background,
               d.experience_years, d.profile_url, d.specialties, d.title,
               d.photo_url, c.chain_name
        FROM doctors d
        LEFT JOIN clinics c ON d.clinic_id = c.id
        WHERE d.is_active != 0 OR d.is_active IS NULL
    """)
    doctors = c.fetchall()
    print(f"\n--- 対象医師: {len(doctors)}名 ---")

    # 4. 各医師のスコアを再計算
    updated = 0
    scores = []
    for doc in doctors:
        # 症例写真件数: chain_name全体を医師数で割って推定
        chain = doc["chain_name"]
        case_count = 0
        if chain and chain in chain_case_counts:
            doctor_count = chain_doctor_counts.get(chain, 1)
            # チェーン全体の症例をチェーン内の医師数で割る（推定）
            case_count = chain_case_counts[chain] // max(doctor_count, 1)

        breakdown = calculate_trust_score(
            board_certifications=doc["board_certifications"],
            jsaps_certified=False,
            hospital_background=doc["hospital_background"],
            experience_years=doc["experience_years"],
            annual_case_count=None,
            profile_url=doc["profile_url"],
            specialties=doc["specialties"],
            title=doc["title"],
            case_photos_count=case_count,
            has_photo_url=bool(doc["photo_url"]),
            linked_review_count=0,
        )

        score = breakdown.total
        scores.append(score)

        if not args.dry_run:
            c.execute(
                "UPDATE doctors SET trust_score = ?, trust_score_breakdown = ? WHERE id = ?",
                (score, breakdown.to_json(), doc["id"]),
            )
        updated += 1

    if not args.dry_run:
        conn.commit()

    # 5. 統計出力
    if scores:
        scores.sort()
        n = len(scores)
        avg = sum(scores) / n
        median = scores[n // 2]
        high = sum(1 for s in scores if s >= 70)
        mid = sum(1 for s in scores if 40 <= s < 70)
        low = sum(1 for s in scores if 20 <= s < 40)
        pending = sum(1 for s in scores if s < 20)

        print(f"\n{'=' * 60}")
        print(f"{'[DRY-RUN] ' if args.dry_run else ''}再計算完了: {updated}名")
        print(f"{'=' * 60}")
        print(f"\n  平均: {avg:.1f}pt")
        print(f"  中央値: {median:.1f}pt")
        print(f"  範囲: {scores[0]:.1f} - {scores[-1]:.1f}")
        print(f"\n  分布:")
        print(f"    情報充実 (70+pt): {high}名 ({high/n*100:.1f}%)")
        print(f"    一部確認 (40-69pt): {mid}名 ({mid/n*100:.1f}%)")
        print(f"    情報限定 (20-39pt): {low}名 ({low/n*100:.1f}%)")
        print(f"    収集中   (<20pt): {pending}名 ({pending/n*100:.1f}%)")

        # ヒストグラム的な表示
        print(f"\n  スコア分布（10pt刻み）:")
        for bucket_start in range(0, 100, 10):
            bucket_end = bucket_start + 10
            count = sum(1 for s in scores if bucket_start <= s < bucket_end)
            bar = "█" * (count // 5) + ("▌" if count % 5 >= 3 else "")
            print(f"    {bucket_start:3d}-{bucket_end:3d}: {bar} {count}")

    conn.close()


if __name__ == "__main__":
    main()
