"""
AURA MVP — Phase 66: クリニックスコアv2 再計算スクリプト

全クリニックのスコアを新アルゴリズムで再計算する:
  - 価格カバー率をカバー率ベースに変更
  - 口コミトレンド（improving/stable/declining）を反映
  - 施術多様性を考慮

Before/Afterのグレード分布を出力する。
"""

import json
import sqlite3
from datetime import datetime, timedelta

import sys
sys.path.insert(0, ".")
from src.analyzers.clinic_scoring import score_clinic, get_clinic_grade

DB_PATH = "data/aura.db"

# トレンド判定の閾値（直近3ヶ月 vs それ以前の平均rating差）
TREND_THRESHOLD = 0.3


def compute_trend(db: sqlite3.Connection, clinic_id: str, now: datetime) -> str | None:
    """
    口コミトレンドを算出

    直近3ヶ月のrating平均 vs それ以前のrating平均を比較。
    差 > 0.3 = 'improving', < -0.3 = 'declining', その他 = 'stable'
    どちらかの期間にデータが不足（2件未満）の場合はNone。
    """
    three_months_ago = (now - timedelta(days=90)).isoformat()

    # 直近3ヶ月
    recent = db.execute("""
        SELECT AVG(rating) as avg_r, COUNT(*) as cnt
        FROM reviews
        WHERE clinic_id = ? AND is_spam != 1 AND rating IS NOT NULL
          AND created_at >= ?
    """, (clinic_id, three_months_ago)).fetchone()

    # それ以前
    older = db.execute("""
        SELECT AVG(rating) as avg_r, COUNT(*) as cnt
        FROM reviews
        WHERE clinic_id = ? AND is_spam != 1 AND rating IS NOT NULL
          AND created_at < ?
    """, (clinic_id, three_months_ago)).fetchone()

    # データ不足チェック（各期間2件以上必要）
    if not recent or not older:
        return None
    if (recent["cnt"] or 0) < 2 or (older["cnt"] or 0) < 2:
        return None
    if recent["avg_r"] is None or older["avg_r"] is None:
        return None

    diff = recent["avg_r"] - older["avg_r"]
    if diff > TREND_THRESHOLD:
        return "improving"
    elif diff < -TREND_THRESHOLD:
        return "declining"
    else:
        return "stable"


def compute_price_coverage(db: sqlite3.Connection, clinic_id: str) -> float:
    """価格カバー率を算出（価格あり施術数 / 総施術数）"""
    row = db.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN price_advertised IS NOT NULL AND price_advertised > 0 THEN 1 ELSE 0 END) as has_price
        FROM clinic_procedures
        WHERE clinic_id = ? AND is_active = 1
    """, (clinic_id,)).fetchone()

    total = row["total"] or 0
    has_price = row["has_price"] or 0
    if total == 0:
        return 0.0
    return has_price / total


def compute_procedure_diversity(db: sqlite3.Connection, clinic_id: str) -> int:
    """提供施術数（ユニークなprocedure_idの数）"""
    row = db.execute("""
        SELECT COUNT(DISTINCT procedure_id) as cnt
        FROM clinic_procedures
        WHERE clinic_id = ? AND is_active = 1
    """, (clinic_id,)).fetchone()
    return row["cnt"] or 0


def main():
    """全クリニックのスコアをv2アルゴリズムで再計算"""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    # Before: 現在のグレード分布を取得
    before_dist = {}
    before_stats = {}
    rows = db.execute(
        "SELECT clinic_grade, COUNT(*) as cnt FROM clinics WHERE is_active = 1 GROUP BY clinic_grade"
    ).fetchall()
    for r in rows:
        before_dist[r["clinic_grade"]] = r["cnt"]

    row = db.execute(
        "SELECT MIN(clinic_score) as mn, MAX(clinic_score) as mx, AVG(clinic_score) as av FROM clinics WHERE is_active = 1"
    ).fetchone()
    before_stats = {"min": row["mn"], "max": row["mx"], "avg": row["av"]}

    # 全クリニック取得
    clinics = db.execute(
        "SELECT id, google_rating, google_review_count, website, verified_at FROM clinics WHERE is_active = 1"
    ).fetchall()

    now = datetime.now()
    updated = 0
    after_dist = {}
    trend_counts = {"improving": 0, "stable": 0, "declining": 0, "unknown": 0}
    score_changes = []  # (clinic_id, old_score, new_score)

    for c in clinics:
        clinic_id = c["id"]

        # 医師データ取得
        doc_stats = db.execute("""
            SELECT
                COUNT(*) as cnt,
                AVG(trust_score) as avg_ts,
                MAX(CASE WHEN board_certifications IS NOT NULL AND board_certifications != '' AND board_certifications != '[]' THEN 1 ELSE 0 END) as has_cert
            FROM doctors
            WHERE clinic_id = ? AND is_active = 1
        """, (clinic_id,)).fetchone()

        # 口コミデータ取得
        rev_stats = db.execute("""
            SELECT
                COUNT(*) as cnt,
                AVG(sentiment_score) as avg_sent,
                SUM(CASE WHEN red_flags IS NOT NULL AND red_flags != '[]' THEN 1 ELSE 0 END) as rf_count
            FROM reviews
            WHERE clinic_id = ? AND is_spam != 1
        """, (clinic_id,)).fetchone()

        # 施術・価格データ取得
        proc_stats = db.execute("""
            SELECT
                COUNT(*) as proc_count,
                SUM(CASE WHEN price_advertised IS NOT NULL AND price_advertised > 0 THEN 1 ELSE 0 END) as price_count
            FROM clinic_procedures
            WHERE clinic_id = ? AND is_active = 1
        """, (clinic_id,)).fetchone()

        # 検証日からの経過日数
        days_since = 30
        if c["verified_at"]:
            try:
                verified = datetime.fromisoformat(str(c["verified_at"]))
                days_since = (now - verified).days
            except (ValueError, TypeError):
                pass

        # レッドフラグ比率
        rev_count = rev_stats["cnt"] or 0
        rf_count = rev_stats["rf_count"] or 0
        rf_ratio = rf_count / rev_count if rev_count > 0 else 0.0

        # Phase 66: 新パラメータ算出
        price_coverage = compute_price_coverage(db, clinic_id)
        trend = compute_trend(db, clinic_id, now)
        diversity = compute_procedure_diversity(db, clinic_id)

        if trend:
            trend_counts[trend] += 1
        else:
            trend_counts["unknown"] += 1

        # 現在のスコアを取得（Before/After比較用）
        old_row = db.execute(
            "SELECT clinic_score FROM clinics WHERE id = ?", (clinic_id,)
        ).fetchone()
        old_score = old_row["clinic_score"] if old_row else 0

        # v2スコア算出
        result = score_clinic(
            google_rating=c["google_rating"],
            google_review_count=c["google_review_count"],
            has_website=bool(c["website"] and c["website"].strip()),
            doctor_count=doc_stats["cnt"] or 0,
            avg_doctor_trust_score=doc_stats["avg_ts"],
            has_certified_doctor=bool(doc_stats["has_cert"]),
            review_count=rev_count,
            avg_sentiment=rev_stats["avg_sent"],
            red_flag_count=rf_count,
            red_flag_ratio=rf_ratio,
            price_data_count=proc_stats["price_count"] or 0,
            procedure_count=proc_stats["proc_count"] or 0,
            days_since_verified=days_since,
            # Phase 66 v2 パラメータ
            price_coverage_ratio=price_coverage,
            trend_direction=trend,
            procedure_diversity=diversity,
        )

        grade = get_clinic_grade(result.total)
        after_dist[grade] = after_dist.get(grade, 0) + 1

        score_changes.append((clinic_id, old_score or 0, result.total))

        # DB更新
        db.execute("""
            UPDATE clinics
            SET clinic_score = ?, clinic_grade = ?, clinic_score_breakdown = ?
            WHERE id = ?
        """, (
            round(result.total, 1),
            grade,
            json.dumps(result.to_dict(), ensure_ascii=False),
            clinic_id,
        ))
        updated += 1

    db.commit()
    db.close()

    # === 結果出力 ===
    print("=" * 60)
    print("  Phase 66: クリニックスコアv2 再計算結果")
    print("=" * 60)
    print(f"\n  対象: {updated}クリニック\n")

    # グレード分布 Before/After
    print("  グレード分布:")
    print(f"  {'Grade':<6} {'Before':>8} {'After':>8} {'差分':>8}")
    print(f"  {'-'*30}")
    for grade in ["A", "B", "C", "D", "E"]:
        b = before_dist.get(grade, 0)
        a = after_dist.get(grade, 0)
        diff = a - b
        sign = "+" if diff > 0 else ""
        print(f"  {grade:<6} {b:>8} {a:>8} {sign}{diff:>7}")

    # スコア統計 Before/After
    new_scores = [s[2] for s in score_changes]
    after_stats = {
        "min": min(new_scores) if new_scores else 0,
        "max": max(new_scores) if new_scores else 0,
        "avg": sum(new_scores) / len(new_scores) if new_scores else 0,
    }

    print(f"\n  スコア統計:")
    print(f"  {'':>10} {'Before':>10} {'After':>10}")
    print(f"  {'-'*30}")
    print(f"  {'Min':>10} {before_stats['min']:>10.1f} {after_stats['min']:>10.1f}")
    print(f"  {'Max':>10} {before_stats['max']:>10.1f} {after_stats['max']:>10.1f}")
    print(f"  {'Avg':>10} {before_stats['avg']:>10.1f} {after_stats['avg']:>10.1f}")

    # トレンド分布
    print(f"\n  口コミトレンド分布:")
    for k, v in trend_counts.items():
        print(f"    {k:>12}: {v:>4}クリニック")

    # スコア変動TOP10（上昇）
    score_changes.sort(key=lambda x: x[2] - x[1], reverse=True)
    print(f"\n  スコア上昇TOP5:")
    for cid, old, new in score_changes[:5]:
        print(f"    {cid[:12]}... {old:.1f} -> {new:.1f} ({new-old:+.1f})")

    # スコア変動TOP10（下降）
    print(f"\n  スコア下降TOP5:")
    for cid, old, new in score_changes[-5:]:
        print(f"    {cid[:12]}... {old:.1f} -> {new:.1f} ({new-old:+.1f})")

    print(f"\n{'=' * 60}")


if __name__ == "__main__":
    main()
