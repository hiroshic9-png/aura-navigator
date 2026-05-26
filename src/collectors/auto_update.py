"""
AURA MVP — 自動データ更新パイプライン

クリニック情報の鮮度を自動的に維持するためのパイプライン。

機能:
1. Webスクレイプキャッシュの定期更新（menu.html/doctor.html/index.html）
2. 更新されたキャッシュからの差分抽出（価格・医師・電話番号）
3. Google Places APIからの評価・口コミ更新
4. 更新履歴の記録（audit_logs）

実行方法:
    # フル更新（全ステップ）
    python -m src.collectors.auto_update --full

    # ステップ指定
    python -m src.collectors.auto_update --step scrape
    python -m src.collectors.auto_update --step extract-prices
    python -m src.collectors.auto_update --step extract-phones
    python -m src.collectors.auto_update --step extract-doctors

    # ドライラン
    python -m src.collectors.auto_update --full --dry-run

    # 更新頻度の低いクリニックのみ（30日以上前）
    python -m src.collectors.auto_update --full --stale-days 30
"""

import argparse
import asyncio
import json
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "aura.db"
CACHE_DIR = PROJECT_ROOT / "data" / "scrape_cache"

load_dotenv(PROJECT_ROOT / ".env")


class DataFreshnessChecker:
    """データの鮮度を管理するクラス"""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path

    def get_stale_clinics(self, stale_days: int = 30) -> list[dict]:
        """
        指定日数以上データが更新されていないクリニックを取得する。

        Returns:
            クリニック情報のリスト（id, name, website, last_scraped）
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        cutoff = datetime.now() - timedelta(days=stale_days)

        # スクレイプキャッシュの最終更新日をチェック
        stale = []
        rows = conn.execute(
            "SELECT id, name, website FROM clinics WHERE website IS NOT NULL AND website != ''"
        ).fetchall()

        for row in rows:
            clinic_id = row["id"]
            cache_dir = CACHE_DIR / clinic_id

            # キャッシュが存在しない → 未取得
            if not cache_dir.exists():
                stale.append({
                    "id": clinic_id,
                    "name": row["name"],
                    "website": row["website"],
                    "last_scraped": None,
                    "reason": "no_cache",
                })
                continue

            # index.htmlの最終更新日チェック
            index_path = cache_dir / "index.html"
            if index_path.exists():
                mtime = datetime.fromtimestamp(index_path.stat().st_mtime)
                if mtime < cutoff:
                    stale.append({
                        "id": clinic_id,
                        "name": row["name"],
                        "website": row["website"],
                        "last_scraped": mtime.isoformat(),
                        "reason": "stale",
                    })
            else:
                stale.append({
                    "id": clinic_id,
                    "name": row["name"],
                    "website": row["website"],
                    "last_scraped": None,
                    "reason": "no_index",
                })

        conn.close()
        return stale

    def get_freshness_report(self) -> dict:
        """データ鮮度のレポートを生成する"""
        conn = sqlite3.connect(self.db_path)

        report = {}

        # 全体統計
        total = conn.execute("SELECT COUNT(*) FROM clinics").fetchone()[0]
        report["total_clinics"] = total

        # フィールド別充填率
        fields = {
            "phone": "phone IS NOT NULL AND phone != ''",
            "website": "website IS NOT NULL AND website != ''",
            "google_place_id": "google_place_id IS NOT NULL AND google_place_id != ''",
            "google_rating": "google_rating IS NOT NULL",
            "opening_hours": "opening_hours IS NOT NULL AND opening_hours != '' AND opening_hours != '{}'",
            "transparency_score": "transparency_score IS NOT NULL",
        }

        report["fill_rates"] = {}
        for field, condition in fields.items():
            count = conn.execute(f"SELECT COUNT(*) FROM clinics WHERE {condition}").fetchone()[0]
            report["fill_rates"][field] = {
                "count": count,
                "total": total,
                "pct": round(100.0 * count / total, 1) if total > 0 else 0,
            }

        # 価格データ
        cp_total = conn.execute("SELECT COUNT(*) FROM clinic_procedures").fetchone()[0]
        cp_priced = conn.execute(
            "SELECT COUNT(*) FROM clinic_procedures WHERE price_advertised > 0"
        ).fetchone()[0]
        report["price_data"] = {
            "total": cp_total,
            "priced": cp_priced,
            "pct": round(100.0 * cp_priced / cp_total, 1) if cp_total > 0 else 0,
        }

        # 医師データ
        doc_total = conn.execute("SELECT COUNT(*) FROM doctors").fetchone()[0]
        doc_cert = conn.execute(
            "SELECT COUNT(*) FROM doctors WHERE board_certifications IS NOT NULL AND board_certifications != '[]'"
        ).fetchone()[0]
        report["doctor_data"] = {
            "total": doc_total,
            "certified": doc_cert,
            "pct": round(100.0 * doc_cert / doc_total, 1) if doc_total > 0 else 0,
        }

        # 口コミデータ
        review_total = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
        report["review_data"] = {"total": review_total}

        # キャッシュ鮮度
        now = time.time()
        cache_stats = {"total": 0, "fresh_7d": 0, "fresh_30d": 0, "stale": 0}
        if CACHE_DIR.exists():
            for d in CACHE_DIR.iterdir():
                if d.is_dir():
                    cache_stats["total"] += 1
                    idx = d / "index.html"
                    if idx.exists():
                        age_days = (now - idx.stat().st_mtime) / 86400
                        if age_days <= 7:
                            cache_stats["fresh_7d"] += 1
                        elif age_days <= 30:
                            cache_stats["fresh_30d"] += 1
                        else:
                            cache_stats["stale"] += 1

        report["cache_freshness"] = cache_stats

        conn.close()
        return report


class AutoUpdater:
    """自動更新パイプラインの実行エンジン"""

    def __init__(self, dry_run: bool = False, stale_days: int = 30):
        self.dry_run = dry_run
        self.stale_days = stale_days
        self.checker = DataFreshnessChecker()
        self.results = {}

    async def run_full_pipeline(self):
        """フルパイプラインの実行"""
        logger.info("=" * 60)
        logger.info("AURA 自動更新パイプライン")
        logger.info(f"モード: {'ドライラン' if self.dry_run else '本番'}")
        logger.info(f"対象: {self.stale_days}日以上未更新のクリニック")
        logger.info("=" * 60)

        # Step 0: 鮮度レポート
        report = self.checker.get_freshness_report()
        self._print_freshness_report(report)

        # Step 1: スクレイプ（Webサイトから最新HTML取得）
        await self.step_scrape()

        # Step 2: 電話番号抽出
        self.step_extract_phones()

        # Step 3: 価格抽出（LLMが必要 — 本番のみ）
        if not self.dry_run:
            await self.step_extract_prices()

        # Step 4: 最終レポート
        report_after = self.checker.get_freshness_report()
        logger.info("\n=== 更新後のレポート ===")
        self._print_freshness_report(report_after)

    async def step_scrape(self):
        """Step 1: Webスクレイプ（キャッシュ更新）"""
        logger.info("\n--- Step 1: Webスクレイプ ---")

        stale = self.checker.get_stale_clinics(self.stale_days)
        # websiteがあるもののみ
        targets = [c for c in stale if c.get("website")]

        logger.info(f"更新対象: {len(targets)}クリニック")

        if self.dry_run:
            for c in targets[:5]:
                logger.info(f"  [DRY-RUN] {c['name']} ({c['reason']})")
            if len(targets) > 5:
                logger.info(f"  ... 他{len(targets)-5}件")
            self.results["scrape"] = {"targets": len(targets), "updated": 0}
            return

        # Webスクレイパーを呼び出し
        try:
            from src.collectors.website_scraper import WebsiteScraper

            scraper = WebsiteScraper()
            updated = 0

            for i, clinic in enumerate(targets):
                try:
                    logger.info(f"[{i+1}/{len(targets)}] {clinic['name']}")
                    await scraper.scrape_clinic(
                        clinic_id=clinic["id"],
                        website=clinic["website"],
                        cache_dir=str(CACHE_DIR / clinic["id"]),
                    )
                    updated += 1
                except Exception as e:
                    logger.warning(f"  スクレイプ失敗: {e}")

                await asyncio.sleep(2.0)  # レート制限

            self.results["scrape"] = {"targets": len(targets), "updated": updated}

        except ImportError:
            logger.warning("WebsiteScraperが見つかりません。スクレイプをスキップ。")
            self.results["scrape"] = {"targets": len(targets), "updated": 0, "skipped": True}

    def step_extract_phones(self):
        """Step 2: 電話番号抽出"""
        logger.info("\n--- Step 2: 電話番号抽出 ---")

        try:
            from src.collectors.phone_extraction import extract_phone_from_html

            conn = sqlite3.connect(DB_PATH)
            updated = 0

            for d in sorted(CACHE_DIR.iterdir()):
                if not d.is_dir():
                    continue
                idx_path = d / "index.html"
                if not idx_path.exists():
                    continue

                clinic_id = d.name
                # 既に電話番号があるか確認
                row = conn.execute(
                    "SELECT phone FROM clinics WHERE id = ?", (clinic_id,)
                ).fetchone()
                if row is None or (row[0] and row[0].strip()):
                    continue

                html = idx_path.read_text(encoding="utf-8", errors="replace")
                phone = extract_phone_from_html(html)

                if phone and not self.dry_run:
                    conn.execute(
                        "UPDATE clinics SET phone = ? WHERE id = ?",
                        (phone, clinic_id),
                    )
                    updated += 1

            if not self.dry_run:
                conn.commit()
            conn.close()

            logger.info(f"電話番号更新: {updated}件")
            self.results["phones"] = {"updated": updated}

        except ImportError:
            logger.warning("phone_extractionモジュールが見つかりません")

    async def step_extract_prices(self):
        """Step 3: 価格抽出（LLM使用）"""
        logger.info("\n--- Step 3: 価格抽出（LLM） ---")

        api_key = os.environ.get("AURA_ANTHROPIC_API_KEY", "")
        if not api_key:
            logger.warning("AURA_ANTHROPIC_API_KEY未設定。価格抽出をスキップ。")
            self.results["prices"] = {"skipped": True}
            return

        try:
            from src.collectors.price_llm_extraction import (
                extract_prices_with_llm,
                extract_text_from_html,
                get_procedures,
                update_prices,
            )

            procedures = get_procedures()
            conn = sqlite3.connect(DB_PATH)
            updated = 0

            # 価格が未設定のクリニック × キャッシュありの組み合わせ
            for d in sorted(CACHE_DIR.iterdir()):
                if not d.is_dir():
                    continue
                menu_path = d / "menu.html"
                if not menu_path.exists():
                    continue

                clinic_id = d.name
                # 価格がゼロのclinic_proceduresがあるか
                row = conn.execute(
                    """SELECT COUNT(*) FROM clinic_procedures
                       WHERE clinic_id = ?
                       AND (price_advertised IS NULL OR price_advertised = 0)""",
                    (clinic_id,),
                ).fetchone()

                if row[0] == 0:
                    continue  # 全て価格設定済み

                name_row = conn.execute(
                    "SELECT name FROM clinics WHERE id = ?", (clinic_id,)
                ).fetchone()
                if not name_row:
                    continue

                html = menu_path.read_text(encoding="utf-8", errors="replace")
                text = extract_text_from_html(html)

                if len(text) < 100:
                    continue

                prices = await extract_prices_with_llm(name_row[0], text, procedures)
                if prices:
                    count = update_prices(clinic_id, prices)
                    updated += count

                await asyncio.sleep(1.0)

            conn.close()
            logger.info(f"価格更新: {updated}件")
            self.results["prices"] = {"updated": updated}

        except ImportError as e:
            logger.warning(f"price_llm_extractionモジュールエラー: {e}")
            self.results["prices"] = {"skipped": True}

    def _print_freshness_report(self, report: dict):
        """鮮度レポートを表示する"""
        logger.info(f"\n{'='*50}")
        logger.info(f"データ鮮度レポート")
        logger.info(f"{'='*50}")
        logger.info(f"総クリニック数: {report['total_clinics']}")

        logger.info("\n--- フィールド充填率 ---")
        for field, data in report["fill_rates"].items():
            bar = "█" * int(data["pct"] / 5) + "░" * (20 - int(data["pct"] / 5))
            logger.info(f"  {field:20s} {bar} {data['pct']:5.1f}% ({data['count']}/{data['total']})")

        logger.info(f"\n--- 価格データ ---")
        pd = report["price_data"]
        logger.info(f"  充填率: {pd['pct']:.1f}% ({pd['priced']}/{pd['total']})")

        logger.info(f"\n--- 医師データ ---")
        dd = report["doctor_data"]
        logger.info(f"  資格充填率: {dd['pct']:.1f}% ({dd['certified']}/{dd['total']})")

        logger.info(f"\n--- 口コミ ---")
        logger.info(f"  総数: {report['review_data']['total']}件")

        cs = report["cache_freshness"]
        logger.info(f"\n--- キャッシュ鮮度 ---")
        logger.info(f"  7日以内: {cs['fresh_7d']}件")
        logger.info(f"  30日以内: {cs['fresh_30d']}件")
        logger.info(f"  30日超: {cs['stale']}件")
        logger.info(f"  合計: {cs['total']}件")


async def main():
    parser = argparse.ArgumentParser(description="AURA データ自動更新パイプライン")
    parser.add_argument("--full", action="store_true", help="フルパイプライン実行")
    parser.add_argument("--step", choices=["scrape", "extract-prices", "extract-phones", "extract-doctors", "report"],
                        help="特定ステップのみ実行")
    parser.add_argument("--dry-run", action="store_true", help="ドライラン")
    parser.add_argument("--stale-days", type=int, default=30, help="更新対象の閾値（日数）")
    args = parser.parse_args()

    updater = AutoUpdater(dry_run=args.dry_run, stale_days=args.stale_days)

    if args.step == "report":
        report = updater.checker.get_freshness_report()
        updater._print_freshness_report(report)
    elif args.full:
        await updater.run_full_pipeline()
    elif args.step == "extract-phones":
        updater.step_extract_phones()
    elif args.step == "extract-prices":
        await updater.step_extract_prices()
    elif args.step == "scrape":
        await updater.step_scrape()
    else:
        # デフォルト: レポートのみ
        report = updater.checker.get_freshness_report()
        updater._print_freshness_report(report)


if __name__ == "__main__":
    asyncio.run(main())
