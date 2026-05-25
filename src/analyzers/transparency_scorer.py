"""
AURA MVP — 透明性スコア算出エンジン

クリニックの情報開示度を0-100で数値化する独自指標。
患者が「この クリニックはどれだけ情報を開示しているか」を判断するための
定量的な指標を提供する。

使い方:
    # 全件スコア算出
    uv run python -m src.analyzers.transparency_scorer

    # 統計のみ表示
    uv run python -m src.analyzers.transparency_scorer --stats

    # 特定クリニックのみ
    uv run python -m src.analyzers.transparency_scorer --clinic-id <ID>
"""

import argparse
import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# DBパス
DB_PATH = Path(__file__).parent.parent.parent / "data" / "aura.db"


@dataclass
class TransparencyBreakdown:
    """透明性スコアの内訳"""
    clinic_id: str
    clinic_name: str
    total_score: float
    website_score: float          # Webサイト存在 (10pt)
    departments_score: float      # 診療科の充実度 (10pt)
    doctor_info_score: float      # 医師情報の有無 (15pt)
    procedure_menu_score: float   # 施術メニュー公開 (15pt)
    price_display_score: float    # 価格表示 (15pt)
    review_response_score: float  # 口コミ応答 (10pt) ※将来実装、現時点は中間値
    opening_hours_score: float    # 営業時間公開 (5pt)
    specialist_score: float       # 専門医資格の明示 (10pt)
    facility_score: float         # 施設基準 (10pt)


def calculate_transparency_score(
    clinic: dict,
    doctor_count_in_db: int,
    procedure_source_counts: dict[str, int],
    has_price_data: bool,
    has_specialist: bool,
) -> TransparencyBreakdown:
    """
    クリニックの透明性スコアを算出する（0-100）

    Args:
        clinic: clinicsテーブルの行（辞書形式）
        doctor_count_in_db: doctorsテーブルにおけるこのクリニックの医師数
        procedure_source_counts: clinic_proceduresのsource別件数 {'department_inference': N, 'website_scrape': M}
        has_price_data: clinic_proceduresにprice_advertised/price_actualが入っているか
        has_specialist: 専門医データが存在するか
    """
    # --- 1. Webサイト存在 (10pt) ---
    website = clinic.get("website") or ""
    website_score = 10.0 if website.strip() else 0.0

    # --- 2. 診療科の充実度 (10pt) ---
    departments_raw = clinic.get("medical_departments") or "[]"
    try:
        departments = json.loads(departments_raw) if isinstance(departments_raw, str) else departments_raw
    except (json.JSONDecodeError, TypeError):
        departments = []

    dept_set = set(departments) if isinstance(departments, list) else set()
    departments_score = 0.0
    if "美容外科" in dept_set and "形成外科" in dept_set:
        departments_score = 10.0
    elif "美容外科" in dept_set and "美容皮膚科" in dept_set:
        departments_score = 8.0
    elif "美容外科" in dept_set or "形成外科" in dept_set:
        departments_score = 6.0
    elif "美容皮膚科" in dept_set:
        departments_score = 4.0
    elif len(dept_set) > 0:
        departments_score = 2.0

    # --- 3. 医師情報の有無 (15pt) ---
    doctor_info_score = 0.0
    if doctor_count_in_db >= 3:
        doctor_info_score = 15.0
    elif doctor_count_in_db >= 1:
        doctor_info_score = 10.0
    elif (clinic.get("doctor_count") or 0) > 0:
        # 厚労省データに医師数があるが個別データはない
        doctor_info_score = 3.0

    # --- 4. 施術メニュー公開 (15pt) ---
    procedure_menu_score = 0.0
    website_scrape_count = procedure_source_counts.get("website_scrape", 0)
    chain_inference_count = procedure_source_counts.get("chain_inference", 0)
    dept_inference_count = procedure_source_counts.get("department_inference", 0)

    if website_scrape_count > 0:
        # 公式サイトから実データ取得済み
        procedure_menu_score = 15.0
    elif chain_inference_count > 0:
        # チェーン推定データ
        procedure_menu_score = 10.0
    elif dept_inference_count > 0:
        # 診療科ベースの推定のみ
        procedure_menu_score = 5.0

    # --- 5. 価格表示 (15pt) ---
    price_display_score = 0.0
    if has_price_data:
        price_display_score = 15.0
    elif website_scrape_count > 0:
        # スクレイピング済みだが価格は取れなかった
        price_display_score = 5.0

    # --- 6. 口コミ応答 (10pt) ---
    # 現時点ではクリニック側の口コミ返信データを持っていないため、中間値を使用
    review_response_score = 5.0

    # --- 7. 営業時間公開 (5pt) ---
    opening_hours_raw = clinic.get("opening_hours")
    opening_hours_score = 0.0
    if opening_hours_raw:
        try:
            oh = json.loads(opening_hours_raw) if isinstance(opening_hours_raw, str) else opening_hours_raw
            if oh and isinstance(oh, dict) and oh.get("periods"):
                opening_hours_score = 5.0
            elif oh and isinstance(oh, dict):
                opening_hours_score = 3.0
        except (json.JSONDecodeError, TypeError):
            pass

    # --- 8. 専門医資格の明示 (10pt) ---
    specialist_score = 0.0
    if has_specialist:
        specialist_score = 10.0

    # --- 9. 施設基準 (10pt) ---
    facility_standards_raw = clinic.get("facility_standards") or "[]"
    try:
        facility_standards = json.loads(facility_standards_raw) if isinstance(facility_standards_raw, str) else facility_standards_raw
    except (json.JSONDecodeError, TypeError):
        facility_standards = []

    facility_score = 0.0
    if isinstance(facility_standards, list) and len(facility_standards) > 0:
        facility_score = min(10.0, len(facility_standards) * 2.5)

    # --- 合計 ---
    total_score = (
        website_score
        + departments_score
        + doctor_info_score
        + procedure_menu_score
        + price_display_score
        + review_response_score
        + opening_hours_score
        + specialist_score
        + facility_score
    )

    return TransparencyBreakdown(
        clinic_id=clinic.get("id", ""),
        clinic_name=clinic.get("name", ""),
        total_score=round(min(100.0, total_score), 1),
        website_score=website_score,
        departments_score=departments_score,
        doctor_info_score=doctor_info_score,
        procedure_menu_score=procedure_menu_score,
        price_display_score=price_display_score,
        review_response_score=review_response_score,
        opening_hours_score=opening_hours_score,
        specialist_score=specialist_score,
        facility_score=facility_score,
    )


def run_scoring(db_path: str | None = None, clinic_id: str | None = None, stats_only: bool = False):
    """
    全クリニックの透明性スコアを算出してDBに書き込む

    Args:
        db_path: DBファイルパス（デフォルト: data/aura.db）
        clinic_id: 特定のクリニックIDのみ処理
        stats_only: 統計のみ表示（DB更新なし）
    """
    path = db_path or str(DB_PATH)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # --- クリニック取得 ---
    if clinic_id:
        cursor.execute("SELECT * FROM clinics WHERE id = ?", (clinic_id,))
    else:
        cursor.execute("SELECT * FROM clinics WHERE is_active = 1")

    clinics = [dict(row) for row in cursor.fetchall()]
    logger.info(f"対象クリニック: {len(clinics)}件")

    if not clinics:
        logger.warning("対象クリニックがありません")
        conn.close()
        return

    # --- 医師数の集計（クリニックID別） ---
    cursor.execute("""
        SELECT clinic_id, COUNT(*) as cnt
        FROM doctors
        GROUP BY clinic_id
    """)
    doctor_counts = {row["clinic_id"]: row["cnt"] for row in cursor.fetchall()}

    # --- clinic_proceduresのsource別集計（クリニックID別） ---
    cursor.execute("""
        SELECT clinic_id, source, COUNT(*) as cnt
        FROM clinic_procedures
        WHERE is_active = 1
        GROUP BY clinic_id, source
    """)
    proc_source_map: dict[str, dict[str, int]] = {}
    for row in cursor.fetchall():
        cid = row["clinic_id"]
        proc_source_map.setdefault(cid, {})[row["source"]] = row["cnt"]

    # --- 価格データの有無（クリニックID別） ---
    cursor.execute("""
        SELECT clinic_id
        FROM clinic_procedures
        WHERE is_active = 1
          AND (price_advertised IS NOT NULL OR price_actual IS NOT NULL)
        GROUP BY clinic_id
    """)
    clinics_with_price = {row["clinic_id"] for row in cursor.fetchall()}

    # --- 専門医データの有無（クリニックID別） ---
    cursor.execute("""
        SELECT clinic_id
        FROM doctors
        WHERE board_certifications IS NOT NULL
          AND board_certifications != '[]'
          AND board_certifications != ''
        GROUP BY clinic_id
    """)
    clinics_with_specialist = {row["clinic_id"] for row in cursor.fetchall()}

    # --- スコア算出 ---
    results: list[TransparencyBreakdown] = []
    for clinic in clinics:
        cid = clinic["id"]
        breakdown = calculate_transparency_score(
            clinic=clinic,
            doctor_count_in_db=doctor_counts.get(cid, 0),
            procedure_source_counts=proc_source_map.get(cid, {}),
            has_price_data=cid in clinics_with_price,
            has_specialist=cid in clinics_with_specialist,
        )
        results.append(breakdown)

    # --- 統計表示 ---
    scores = [r.total_score for r in results]
    avg_score = sum(scores) / len(scores) if scores else 0
    min_score = min(scores) if scores else 0
    max_score = max(scores) if scores else 0

    # スコア分布
    buckets = {"0-20": 0, "20-40": 0, "40-60": 0, "60-80": 0, "80-100": 0}
    for s in scores:
        if s < 20:
            buckets["0-20"] += 1
        elif s < 40:
            buckets["20-40"] += 1
        elif s < 60:
            buckets["40-60"] += 1
        elif s < 80:
            buckets["60-80"] += 1
        else:
            buckets["80-100"] += 1

    print(f"\n{'='*60}")
    print(f"AURA 透明性スコア — 算出結果")
    print(f"{'='*60}")
    print(f"対象: {len(results)}件")
    print(f"平均: {avg_score:.1f}pt / 最小: {min_score:.1f}pt / 最大: {max_score:.1f}pt")
    print(f"\n--- スコア分布 ---")
    for bucket, count in buckets.items():
        bar = "█" * (count // 5) + "▌" * (1 if count % 5 >= 3 else 0)
        print(f"  {bucket:>6}pt: {count:>4}件  {bar}")

    # 各軸の平均
    print(f"\n--- 各軸の平均スコア ---")
    axis_avgs = {
        "Webサイト (10pt)": sum(r.website_score for r in results) / len(results),
        "診療科 (10pt)": sum(r.departments_score for r in results) / len(results),
        "医師情報 (15pt)": sum(r.doctor_info_score for r in results) / len(results),
        "施術メニュー (15pt)": sum(r.procedure_menu_score for r in results) / len(results),
        "価格表示 (15pt)": sum(r.price_display_score for r in results) / len(results),
        "口コミ応答 (10pt)": sum(r.review_response_score for r in results) / len(results),
        "営業時間 (5pt)": sum(r.opening_hours_score for r in results) / len(results),
        "専門医 (10pt)": sum(r.specialist_score for r in results) / len(results),
        "施設基準 (10pt)": sum(r.facility_score for r in results) / len(results),
    }
    for axis, avg in axis_avgs.items():
        max_pt = float(axis.split("(")[1].split("pt")[0])
        pct = (avg / max_pt) * 100 if max_pt > 0 else 0
        print(f"  {axis:<22}: {avg:>5.1f}  ({pct:.0f}%)")

    # TOP5
    top5 = sorted(results, key=lambda r: r.total_score, reverse=True)[:5]
    print(f"\n--- 高スコアTOP5 ---")
    for r in top5:
        print(f"  {r.total_score:>5.1f}pt  {r.clinic_name}")

    # LOW5
    low5 = sorted(results, key=lambda r: r.total_score)[:5]
    print(f"\n--- 低スコアBOTTOM5 ---")
    for r in low5:
        print(f"  {r.total_score:>5.1f}pt  {r.clinic_name}")

    if stats_only:
        print(f"\n※ stats_only モード: DB更新はスキップされました")
        conn.close()
        return

    # --- DB更新 ---
    logger.info("transparency_score をDBに書き込み中...")
    updated = 0
    for r in results:
        cursor.execute(
            "UPDATE clinics SET transparency_score = ?, updated_at = ? WHERE id = ?",
            (r.total_score, datetime.now().isoformat(), r.clinic_id),
        )
        updated += 1

    conn.commit()
    logger.info(f"✅ {updated}件のclinics.transparency_scoreを更新しました")

    # 監査ログ
    cursor.execute(
        """INSERT INTO audit_logs (table_name, record_id, action, changed_fields, changed_by, source, timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            "clinics",
            "batch",
            "update",
            json.dumps({
                "field": "transparency_score",
                "count": updated,
                "avg_score": round(avg_score, 1),
            }),
            "transparency_scorer",
            "aura_analysis",
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    conn.close()

    print(f"\n✅ 完了: {updated}件のクリニックに透明性スコアを付与しました")


def main():
    """CLIエントリポイント"""
    parser = argparse.ArgumentParser(description="AURA 透明性スコア算出")
    parser.add_argument("--db", help="DBファイルパス（デフォルト: data/aura.db）")
    parser.add_argument("--clinic-id", help="特定クリニックIDのみ処理")
    parser.add_argument("--stats", action="store_true", help="統計のみ表示（DB更新なし）")
    args = parser.parse_args()

    run_scoring(
        db_path=args.db,
        clinic_id=args.clinic_id,
        stats_only=args.stats,
    )


if __name__ == "__main__":
    main()
