"""
AURA MVP — 口コミ分析深化バッチスクリプト

全口コミに対して以下の新分析を実行:
1. レッドフラグ検出（圧力販売・トラブル・スタッフ問題・会計問題）
2. 品質スコア算出（0-100）
3. 医師×口コミマッピング

使い方:
    uv run python scripts/enrich_reviews.py
"""

import asyncio
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, func

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def main():
    """口コミ分析深化のメイン処理"""
    from src.db.database import AsyncSessionLocal, ReviewTable, DoctorTable
    from src.analyzers.review_analyzer import ReviewAnalyzer

    analyzer = ReviewAnalyzer()

    # 統計カウンター
    stats = {
        "total": 0,
        "red_flag_count": 0,
        "doctor_mapped": 0,
        "quality_scored": 0,
        "flag_categories": defaultdict(int),
        "quality_distribution": defaultdict(int),
    }

    async with AsyncSessionLocal() as session:
        # 全口コミを取得
        result = await session.execute(select(ReviewTable))
        reviews = result.scalars().all()
        stats["total"] = len(reviews)
        logger.info(f"口コミ総数: {stats['total']}件")

        # クリニック別の医師マップを構築
        doc_result = await session.execute(select(DoctorTable))
        all_doctors = doc_result.scalars().all()
        clinic_doctor_map: dict[str, list] = defaultdict(list)
        for doc in all_doctors:
            if doc.clinic_id:
                clinic_doctor_map[doc.clinic_id].append(doc)
        logger.info(f"医師データ: {len(all_doctors)}名 / {len(clinic_doctor_map)}クリニック")

        # バッチ処理
        batch_size = 500
        for i in range(0, len(reviews), batch_size):
            batch = reviews[i:i + batch_size]
            for review in batch:
                text = review.text or ""
                clinic_doctors = clinic_doctor_map.get(review.clinic_id, [])

                # 分析実行（既存の感情分析・アスペクトも再算出）
                analysis = analyzer.analyze(
                    review_id=review.id,
                    text=text,
                    rating=review.rating,
                    clinic_doctors=clinic_doctors,
                    created_at=review.created_at,
                )

                # DB更新: 既存フィールド
                review.sentiment_score = analysis.sentiment_score
                review.aspects = json.dumps(analysis.aspects, ensure_ascii=False)
                review.is_spam = analysis.is_spam
                review.analyzed_at = datetime.now()

                # DB更新: 新フィールド
                review.red_flags = json.dumps(analysis.red_flags, ensure_ascii=False) if analysis.red_flags else None
                review.quality_score = analysis.quality_score
                review.doctor_id = analysis.matched_doctor_id

                # 統計集計
                if analysis.red_flags:
                    stats["red_flag_count"] += 1
                    for flag in analysis.red_flags:
                        stats["flag_categories"][flag["category"]] += 1

                if analysis.matched_doctor_id:
                    stats["doctor_mapped"] += 1

                stats["quality_scored"] += 1
                if analysis.quality_score >= 70:
                    stats["quality_distribution"]["高品質(70+)"] += 1
                elif analysis.quality_score >= 40:
                    stats["quality_distribution"]["標準(40-69)"] += 1
                else:
                    stats["quality_distribution"]["低品質(0-39)"] += 1

            await session.commit()
            logger.info(f"バッチ完了: {min(i + batch_size, len(reviews))}/{len(reviews)}")

    # 結果表示
    print(f"\n{'='*60}")
    print(f"  口コミ分析深化 完了レポート")
    print(f"{'='*60}")
    print(f"\n  📊 基本統計")
    print(f"  {'─'*40}")
    print(f"  口コミ総数:       {stats['total']}件")
    print(f"  品質スコア算出:   {stats['quality_scored']}件")
    print(f"  医師マッピング:   {stats['doctor_mapped']}件")
    print(f"  レッドフラグ:     {stats['red_flag_count']}件")

    print(f"\n  🚩 レッドフラグ内訳")
    print(f"  {'─'*40}")
    labels = {
        "pressure_sales": "圧力販売",
        "treatment_trouble": "施術トラブル",
        "staff_issue": "スタッフ問題",
        "billing_issue": "会計問題",
    }
    for cat, count in sorted(stats["flag_categories"].items(), key=lambda x: -x[1]):
        print(f"  {labels.get(cat, cat)}: {count}件")

    print(f"\n  ⭐ 品質スコア分布")
    print(f"  {'─'*40}")
    for level, count in sorted(stats["quality_distribution"].items()):
        pct = count / stats["total"] * 100 if stats["total"] > 0 else 0
        print(f"  {level}: {count}件 ({pct:.1f}%)")

    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
