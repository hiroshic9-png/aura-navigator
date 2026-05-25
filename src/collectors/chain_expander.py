"""
AURA MVP — チェーン展開スクリプト（B-3）

スクレイピングで取得した施術・価格データを同一チェーン内の他院に展開する。
1院で取得したメニューデータを同一チェーンの全院に共有することで、
少ないスクレイピングで多くのクリニックのデータを充実させる。

使い方:
    # 統計のみ（DB更新なし）
    uv run python -m src.collectors.chain_expander --stats

    # 実行
    uv run python -m src.collectors.chain_expander

    # dry-run
    uv run python -m src.collectors.chain_expander --dry-run
"""

import argparse
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.collectors.chain_matcher import CHAIN_PATTERNS, _normalize_full

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# DBパス
DB_PATH = Path(__file__).parent.parent.parent / "data" / "aura.db"


def run_chain_expansion(
    db_path: str | None = None,
    dry_run: bool = False,
    stats_only: bool = False,
):
    """
    チェーン展開を実行する。

    ロジック:
    1. チェーン名が一致するクリニック群を特定
    2. 各チェーン内で、website_scrapeデータを持つ院を「ソース院」に指定
    3. ソース院のclinic_proceduresを他院にコピー（source='chain_inference'）
    4. 既にwebsite_scrapeデータがある院はスキップ
    """
    path = db_path or str(DB_PATH)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # === チェーン別にクリニックをグルーピング ===
    cursor.execute("""
        SELECT id, name, chain_name
        FROM clinics
        WHERE is_active = 1 AND chain_name IS NOT NULL AND chain_name != ''
    """)
    chain_groups: dict[str, list[dict]] = {}
    for row in cursor.fetchall():
        chain = row["chain_name"]
        norm_chain = _normalize_full(chain)
        # 既知のチェーンパターンにマッチするか確認
        matched_chain = None
        for known_chain, patterns in CHAIN_PATTERNS.items():
            for pattern in patterns:
                if _normalize_full(pattern) in norm_chain or norm_chain in _normalize_full(pattern):
                    matched_chain = known_chain
                    break
            if matched_chain:
                break

        if matched_chain:
            chain_groups.setdefault(matched_chain, []).append(dict(row))

    # chain_nameがNULLだがクリニック名からチェーン判定できるものも追加
    cursor.execute("""
        SELECT id, name, chain_name
        FROM clinics
        WHERE is_active = 1 AND (chain_name IS NULL OR chain_name = '')
    """)
    for row in cursor.fetchall():
        norm_name = _normalize_full(row["name"])
        for known_chain, patterns in CHAIN_PATTERNS.items():
            for pattern in patterns:
                if _normalize_full(pattern) in norm_name:
                    chain_groups.setdefault(known_chain, []).append(dict(row))
                    break

    # === 統計表示 ===
    total_chains = len(chain_groups)
    total_clinics_in_chains = sum(len(v) for v in chain_groups.values())

    print(f"\n{'='*60}")
    print(f"AURA B-3: チェーン展開")
    print(f"{'='*60}")
    print(f"チェーン数: {total_chains}")
    print(f"チェーン所属クリニック数: {total_clinics_in_chains}")

    # 各チェーンでwebsite_scrapeデータを持つ院を確認
    total_expanded = 0
    total_procedures_copied = 0

    for chain_name, clinics in sorted(chain_groups.items(), key=lambda x: -len(x[1])):
        clinic_ids = [c["id"] for c in clinics]

        # website_scrapeデータを持つ院を取得
        placeholders = ",".join("?" * len(clinic_ids))
        cursor.execute(f"""
            SELECT DISTINCT clinic_id
            FROM clinic_procedures
            WHERE clinic_id IN ({placeholders}) AND source = 'website_scrape'
        """, clinic_ids)
        source_clinic_ids = {row["clinic_id"] for row in cursor.fetchall()}

        if not source_clinic_ids:
            if not stats_only:
                logger.debug(f"  {chain_name}: スクレイプデータなし（{len(clinics)}院）")
            continue

        # ソース院の施術データを取得
        source_id = list(source_clinic_ids)[0]  # 最初のソース院を使用
        cursor.execute("""
            SELECT procedure_id, price_advertised, price_actual, price_display
            FROM clinic_procedures
            WHERE clinic_id = ? AND source = 'website_scrape' AND is_active = 1
        """, (source_id,))
        source_procedures = [dict(row) for row in cursor.fetchall()]

        if not source_procedures:
            continue

        # 展開対象院（source_clinic_idsに含まれない院）
        target_clinics = [c for c in clinics if c["id"] not in source_clinic_ids]
        expanded_count = 0

        for target in target_clinics:
            target_id = target["id"]

            # 既にwebsite_scrapeがある院はスキップ
            cursor.execute("""
                SELECT COUNT(*) as cnt FROM clinic_procedures
                WHERE clinic_id = ? AND source = 'website_scrape'
            """, (target_id,))
            if cursor.fetchone()["cnt"] > 0:
                continue

            for proc in source_procedures:
                if not dry_run:
                    # UPSERT: 既存のdepartment_inferenceを上書き
                    cursor.execute("""
                        UPDATE clinic_procedures
                        SET source = 'chain_inference',
                            price_advertised = ?,
                            price_actual = ?,
                            price_display = ?,
                            fetched_at = ?
                        WHERE clinic_id = ? AND procedure_id = ?
                    """, (
                        proc["price_advertised"],
                        proc["price_actual"],
                        proc["price_display"],
                        datetime.now(timezone.utc).isoformat(),
                        target_id,
                        proc["procedure_id"],
                    ))

                    if cursor.rowcount == 0:
                        # 新規INSERT
                        cursor.execute("""
                            INSERT OR IGNORE INTO clinic_procedures
                            (clinic_id, procedure_id, price_advertised, price_actual,
                             price_display, source, fetched_at, is_active)
                            VALUES (?, ?, ?, ?, ?, 'chain_inference', ?, 1)
                        """, (
                            target_id,
                            proc["procedure_id"],
                            proc["price_advertised"],
                            proc["price_actual"],
                            proc["price_display"],
                            datetime.now(timezone.utc).isoformat(),
                        ))

                total_procedures_copied += 1

            expanded_count += 1
            total_expanded += 1

        source_name = next(c["name"] for c in clinics if c["id"] == source_id)
        print(f"\n  {chain_name} ({len(clinics)}院)")
        print(f"    ソース: {source_name}")
        print(f"    施術数: {len(source_procedures)}件")
        print(f"    展開先: {expanded_count}院")
        print(f"    スキップ: {len(source_clinic_ids) - 1}院（既にデータあり）")

    if not dry_run and total_expanded > 0:
        conn.commit()

        # 監査ログ
        cursor.execute(
            """INSERT INTO audit_logs (table_name, record_id, action, changed_fields, changed_by, source, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                "clinic_procedures",
                "batch",
                "chain_expansion",
                json.dumps({
                    "expanded_clinics": total_expanded,
                    "procedures_copied": total_procedures_copied,
                }),
                "chain_expander",
                "chain_inference",
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()

    print(f"\n{'='*60}")
    print(f"結果サマリー")
    print(f"{'='*60}")
    print(f"  展開先クリニック数: {total_expanded}")
    print(f"  コピーされた施術レコード数: {total_procedures_copied}")
    if dry_run:
        print(f"\n  ※ dry-runモード: DB更新はスキップされました")

    conn.close()
    print(f"\n✅ 完了")


def main():
    """CLIエントリポイント"""
    parser = argparse.ArgumentParser(description="AURA チェーン展開")
    parser.add_argument("--db", help="DBファイルパス")
    parser.add_argument("--dry-run", action="store_true", help="DB更新なしで実行")
    parser.add_argument("--stats", action="store_true", help="統計のみ表示")
    args = parser.parse_args()

    run_chain_expansion(
        db_path=args.db,
        dry_run=args.dry_run,
        stats_only=args.stats,
    )


if __name__ == "__main__":
    main()
