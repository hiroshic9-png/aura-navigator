"""
AURA MVP — データ品質スケジューラー

定期的にデータ品質を検査し、鮮度切れを自動検出する。

実行方法:
    # 鮮度チェック（日次想定）
    python -m src.db.scheduler freshness

    # 品質レポート（週次想定）
    python -m src.db.scheduler report

    # 全チェック
    python -m src.db.scheduler all
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path


# 鮮度ポリシー（日数）
FRESHNESS_POLICIES = {
    "mhlw": {"fresh": 180, "aging": 365},   # 厚労省: 半年以内=fresh, 1年以内=aging
    "navi": {"fresh": 90, "aging": 180},     # 施術データ: 3ヶ月以内=fresh
    "google": {"fresh": 14, "aging": 30},    # Google: 2週間以内=fresh
    "manual": {"fresh": 90, "aging": 180},   # 手動: 3ヶ月以内
}


def get_db():
    """DB接続取得"""
    db_path = Path(__file__).parent.parent.parent / "data" / "aura.db"
    if not db_path.exists():
        print(f"❌ DB未検出: {db_path}")
        sys.exit(1)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def check_freshness(conn):
    """
    鮮度チェック（日次想定）

    全テーブルのfetched_at/last_verified_dateを検査し、
    鮮度切れレコードのpublish_statusを自動更新する。
    """
    now = datetime.now()
    results = {"checked_at": now.isoformat(), "actions": []}

    # 施術データの鮮度チェック
    cols = [row[1] for row in conn.execute("PRAGMA table_info(procedures)").fetchall()]
    if "publish_status" in cols and "last_verified_date" in cols:
        procs = conn.execute("""
            SELECT id, name, source, fetched_at, last_verified_date, publish_status
            FROM procedures WHERE publish_status != 'hidden'
        """).fetchall()

        stale_count = 0
        for proc in procs:
            # 検証日と取得日のうち新しい方を基準にする
            verified = proc["last_verified_date"]
            fetched = proc["fetched_at"]
            base_date_str = verified or fetched
            if not base_date_str:
                continue

            try:
                base_date = datetime.fromisoformat(base_date_str)
            except (ValueError, TypeError):
                continue

            age_days = (now - base_date).days
            source = proc["source"] or "navi"
            policy = FRESHNESS_POLICIES.get(source, FRESHNESS_POLICIES["manual"])

            if age_days > policy["aging"] and proc["publish_status"] != "stale":
                conn.execute(
                    "UPDATE procedures SET publish_status = 'stale' WHERE id = ?",
                    (proc["id"],)
                )
                stale_count += 1
                results["actions"].append({
                    "type": "stale_marked",
                    "table": "procedures",
                    "name": proc["name"],
                    "age_days": age_days,
                })

        results["procedures_checked"] = len(procs)
        results["procedures_stale"] = stale_count
    else:
        results["procedures_note"] = "publish_status/last_verified_dateカラム未存在"

    # クリニックの鮮度チェック
    clinic_cols = [row[1] for row in conn.execute("PRAGMA table_info(clinics)").fetchall()]
    if "publish_status" in clinic_cols:
        clinics = conn.execute("""
            SELECT id, name, source, fetched_at, publish_status
            FROM clinics WHERE publish_status != 'hidden'
        """).fetchall()

        clinic_stale = 0
        for clinic in clinics:
            fetched = clinic["fetched_at"]
            if not fetched:
                continue
            try:
                fetch_date = datetime.fromisoformat(fetched)
            except (ValueError, TypeError):
                continue

            age_days = (now - fetch_date).days
            source = clinic["source"] or "mhlw"
            policy = FRESHNESS_POLICIES.get(source, FRESHNESS_POLICIES["mhlw"])

            if age_days > policy["aging"] and clinic["publish_status"] != "stale":
                conn.execute(
                    "UPDATE clinics SET publish_status = 'stale' WHERE id = ?",
                    (clinic["id"],)
                )
                clinic_stale += 1

        results["clinics_checked"] = len(clinics)
        results["clinics_stale"] = clinic_stale
    else:
        results["clinics_note"] = "publish_statusカラム未存在"

    conn.commit()
    return results


def generate_quality_report(conn):
    """
    データ品質レポート（週次想定）

    全データの充填率・整合性・鮮度を総合的に検査。
    """
    report = {
        "generated_at": datetime.now().isoformat(),
        "tables": {},
        "issues": [],
        "recommendations": [],
    }

    # 施術データの品質
    proc_count = conn.execute("SELECT COUNT(*) FROM procedures").fetchone()[0]
    report["tables"]["procedures"] = {"count": proc_count}

    if proc_count > 0:
        # フィールド充填率
        fill_check = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN advertised_price IS NOT NULL AND advertised_price != '' AND advertised_price != '{}' THEN 1 ELSE 0 END) as has_adv,
                SUM(CASE WHEN real_price IS NOT NULL AND real_price != '' AND real_price != '{}' THEN 1 ELSE 0 END) as has_real,
                SUM(CASE WHEN risks IS NOT NULL AND risks != '[]' THEN 1 ELSE 0 END) as has_risks,
                SUM(CASE WHEN counseling_questions IS NOT NULL AND counseling_questions != '[]' THEN 1 ELSE 0 END) as has_questions,
                SUM(CASE WHEN downtime_real IS NOT NULL AND downtime_real != '' THEN 1 ELSE 0 END) as has_dt
            FROM procedures
        """).fetchone()

        total = fill_check[0]
        fields = {
            "広告価格": fill_check[1],
            "実際の相場": fill_check[2],
            "リスク情報": fill_check[3],
            "カウンセリング質問": fill_check[4],
            "実際の回復期間": fill_check[5],
        }

        report["tables"]["procedures"]["fill_rates"] = {}
        for label, val in fields.items():
            rate = (val / total * 100) if total > 0 else 0
            report["tables"]["procedures"]["fill_rates"][label] = f"{val}/{total} ({rate:.0f}%)"
            if rate < 100:
                report["issues"].append(f"施術: {label}の充填率 {rate:.0f}%（{total-val}件不足）")

        # JSON破損チェック
        broken = 0
        procs = conn.execute("SELECT id, name, advertised_price, real_price, risks, counseling_questions FROM procedures").fetchall()
        for p in procs:
            for col_idx in [2, 3, 4, 5]:
                val = p[col_idx]
                if val:
                    try:
                        json.loads(val)
                    except json.JSONDecodeError:
                        broken += 1
                        report["issues"].append(f"施術 '{p[1]}': JSON破損")
        report["tables"]["procedures"]["json_broken"] = broken

    # クリニックデータの品質
    clinic_count = conn.execute("SELECT COUNT(*) FROM clinics").fetchone()[0]
    report["tables"]["clinics"] = {"count": clinic_count}

    null_checks = {
        "名前NULL": "SELECT COUNT(*) FROM clinics WHERE name IS NULL",
        "住所NULL": "SELECT COUNT(*) FROM clinics WHERE address IS NULL",
        "都市NULL": "SELECT COUNT(*) FROM clinics WHERE city IS NULL",
        "mhlw_codeNULL": "SELECT COUNT(*) FROM clinics WHERE mhlw_code IS NULL",
    }
    for label, sql in null_checks.items():
        val = conn.execute(sql).fetchone()[0]
        if val > 0:
            report["issues"].append(f"クリニック: {label} {val}件")

    # 重複チェック
    dups = conn.execute("""
        SELECT name, address, COUNT(*) as cnt
        FROM clinics GROUP BY name, address HAVING cnt > 1
    """).fetchall()
    if dups:
        report["issues"].append(f"クリニック: 名前+住所の重複 {len(dups)}組")

    # Google Places統合状況
    google_null = conn.execute(
        "SELECT COUNT(*) FROM clinics WHERE google_place_id IS NULL"
    ).fetchone()[0]
    google_pct = (1 - google_null / clinic_count) * 100 if clinic_count > 0 else 0
    report["tables"]["clinics"]["google_integration"] = f"{clinic_count - google_null}/{clinic_count} ({google_pct:.0f}%)"
    if google_pct < 50:
        report["recommendations"].append(
            f"Google Places APIの統合を推奨（現在{google_pct:.0f}%）。"
            "APIキーを設定し、python -m src.collectors.google_places --all-wards を実行。"
        )

    # 総合評価
    report["issue_count"] = len(report["issues"])
    report["status"] = "healthy" if len(report["issues"]) == 0 else "needs_attention"

    return report


def main():
    parser = argparse.ArgumentParser(description="AURA データ品質スケジューラー")
    parser.add_argument("action", choices=["freshness", "report", "all"],
                        help="freshness: 鮮度チェック, report: 品質レポート, all: 全実行")
    args = parser.parse_args()

    conn = get_db()

    if args.action in ("freshness", "all"):
        print("=== 鮮度チェック ===")
        result = check_freshness(conn)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print()

    if args.action in ("report", "all"):
        print("=== データ品質レポート ===")
        report = generate_quality_report(conn)
        print(json.dumps(report, ensure_ascii=False, indent=2))

    conn.close()


if __name__ == "__main__":
    main()
