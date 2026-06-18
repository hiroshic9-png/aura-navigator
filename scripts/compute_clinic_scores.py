"""
AURA MVP — クリニック総合スコア一括算出スクリプト

全クリニックのスコアを算出し、DBに保存する。
"""

import json
import sqlite3
from datetime import datetime

# パスをプロジェクトルートに合わせてインポート
import sys
sys.path.insert(0, ".")
from src.analyzers.clinic_scoring import score_clinic, get_clinic_grade

DB_PATH = "data/aura.db"


def main():
    """全クリニックのスコアを算出"""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    # カラム追加（存在しない場合）
    try:
        db.execute("ALTER TABLE clinics ADD COLUMN clinic_score REAL")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE clinics ADD COLUMN clinic_grade TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE clinics ADD COLUMN clinic_score_breakdown TEXT")
    except sqlite3.OperationalError:
        pass

    clinics = db.execute(
        "SELECT id, google_rating, google_review_count, website, verified_at FROM clinics WHERE is_active = 1"
    ).fetchall()

    now = datetime.now()
    updated = 0
    grade_dist = {}

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
        days_since = 30  # デフォルト
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

        # スコア算出
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
        )

        grade = get_clinic_grade(result.total)
        grade_dist[grade] = grade_dist.get(grade, 0) + 1

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

    print(f"=== スコア算出完了: {updated}クリニック ===\n")
    print("グレード分布:")
    for grade in ["A", "B", "C", "D", "E"]:
        count = grade_dist.get(grade, 0)
        bar = "█" * (count // 10)
        print(f"  {grade}: {count:>4}院 {bar}")


if __name__ == "__main__":
    main()
