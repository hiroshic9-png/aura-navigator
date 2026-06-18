"""
AURA MVP — 価格インテリジェンスエンジン

施術別の東京エリア価格統計を構築し、
クリニック別の「相場対比」ラベルを提供する。

機能:
1. 施術別価格統計（中央値/25・75パーセンタイル/件数）
2. 相場対比ラベル（お手頃/平均的/高め/プレミアム）
3. エリア別価格差分析
"""

import asyncio
import json
import logging
import statistics
from dataclasses import dataclass, field

from sqlalchemy import select

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ============================================================
# データクラス
# ============================================================

@dataclass
class PriceStats:
    """施術別の価格統計"""
    procedure_id: str
    procedure_name: str
    category: str
    sample_count: int = 0
    median: int | None = None
    percentile_25: int | None = None
    percentile_75: int | None = None
    min_price: int | None = None
    max_price: int | None = None
    # エリア別
    area_stats: dict[str, dict] = field(default_factory=dict)


@dataclass
class PriceContext:
    """クリニック施術価格の相場対比コンテキスト"""
    label: str  # お手頃/平均的/高め/プレミアム
    icon: str  # CSSクラス用識別子（legacy、UI側はCSSで色分け）
    ratio: float | None  # 相場中央値との比率
    median: int | None  # 相場中央値
    sample_count: int  # サンプル数


# ============================================================
# 相場対比ラベル
# ============================================================

def get_price_label(price: int, median: int) -> PriceContext:
    """
    価格と相場中央値から相場対比ラベルを算出

    相場比:
    - 0.7未満: お手頃（相場より安い）
    - 0.7-1.3: 平均的
    - 1.3-2.0: やや高め
    - 2.0以上: プレミアム
    """
    if median <= 0:
        return PriceContext(label="相場不明", icon="", ratio=None, median=None, sample_count=0)

    ratio = price / median

    if ratio < 0.7:
        return PriceContext(label="お手頃", icon="", ratio=round(ratio, 2), median=median, sample_count=0)
    elif ratio <= 1.3:
        return PriceContext(label="平均的", icon="", ratio=round(ratio, 2), median=median, sample_count=0)
    elif ratio <= 2.0:
        return PriceContext(label="やや高め", icon="", ratio=round(ratio, 2), median=median, sample_count=0)
    else:
        return PriceContext(label="プレミアム", icon="", ratio=round(ratio, 2), median=median, sample_count=0)


# ============================================================
# 価格統計の構築
# ============================================================

async def build_price_stats() -> dict[str, PriceStats]:
    """
    全施術の東京エリア価格統計を構築する

    clinic_proceduresテーブルの実データから
    施術ごとの中央値・パーセンタイルを算出。

    Returns:
        施術ID → PriceStats の辞書
    """
    from src.db.database import AsyncSessionLocal, ClinicProcedure, ProcedureTable, ClinicTable

    result: dict[str, PriceStats] = {}

    async with AsyncSessionLocal() as session:
        # 施術マスタを取得
        proc_result = await session.execute(select(ProcedureTable))
        procedures = {p.id: p for p in proc_result.scalars().all()}

        # 価格データのある施術リンクを取得（クリニック情報もJOIN）
        query = (
            select(
                ClinicProcedure.procedure_id,
                ClinicProcedure.price_advertised,
                ClinicTable.city,
            )
            .join(ClinicTable, ClinicProcedure.clinic_id == ClinicTable.id)
            .where(ClinicProcedure.price_advertised.isnot(None))
            .where(ClinicProcedure.price_advertised > 0)
        )
        rows = await session.execute(query)

        # 施術別に価格を集約
        price_map: dict[str, list[int]] = {}
        area_price_map: dict[str, dict[str, list[int]]] = {}

        for row in rows:
            proc_id = row.procedure_id
            price = row.price_advertised
            city = row.city or "不明"

            price_map.setdefault(proc_id, []).append(price)
            area_price_map.setdefault(proc_id, {}).setdefault(city, []).append(price)

        # 統計算出
        for proc_id, prices in price_map.items():
            proc = procedures.get(proc_id)
            if not proc or len(prices) < 3:
                continue

            sorted_prices = sorted(prices)
            n = len(sorted_prices)

            stats = PriceStats(
                procedure_id=proc_id,
                procedure_name=proc.name,
                category=proc.category or "",
                sample_count=n,
                median=int(statistics.median(sorted_prices)),
                percentile_25=sorted_prices[n // 4] if n >= 4 else sorted_prices[0],
                percentile_75=sorted_prices[(3 * n) // 4] if n >= 4 else sorted_prices[-1],
                min_price=sorted_prices[0],
                max_price=sorted_prices[-1],
            )

            # エリア別統計（上位5エリアのみ）
            area_data = area_price_map.get(proc_id, {})
            sorted_areas = sorted(area_data.items(), key=lambda x: len(x[1]), reverse=True)[:5]
            for city, area_prices in sorted_areas:
                if len(area_prices) >= 2:
                    stats.area_stats[city] = {
                        "median": int(statistics.median(area_prices)),
                        "count": len(area_prices),
                        "min": min(area_prices),
                        "max": max(area_prices),
                    }

            result[proc_id] = stats

    logger.info(f"価格統計構築完了: {len(result)}施術")
    return result


def format_price(price: int | None) -> str:
    """価格を読みやすい形式にフォーマット"""
    if price is None:
        return "—"
    if price >= 10000:
        man = price / 10000
        if man == int(man):
            return f"{int(man)}万円"
        return f"{man:.1f}万円"
    return f"{price:,}円"


# ============================================================
# CLI エントリポイント
# ============================================================

async def main():
    """価格統計を構築して表示"""
    stats = await build_price_stats()

    print(f"\n{'='*70}")
    print(f"  AURA 施術別価格統計（東京エリア）")
    print(f"{'='*70}")

    categories: dict[str, list[PriceStats]] = {}
    for s in stats.values():
        categories.setdefault(s.category, []).append(s)

    cat_labels = {
        "eye": "目元", "nose": "鼻", "contour": "輪郭",
        "skin": "肌・美白", "anti_aging": "エイジング", "body": "ボディ",
        "breast": "豊胸", "hair_removal": "脱毛",
    }

    for cat, procs in sorted(categories.items()):
        label = cat_labels.get(cat, cat)
        print(f"\n  {label}")
        print(f"  {'─'*60}")
        for s in sorted(procs, key=lambda x: x.median or 0):
            p25 = format_price(s.percentile_25)
            med = format_price(s.median)
            p75 = format_price(s.percentile_75)
            print(f"  {s.procedure_name[:25]:<26} 中央値:{med:>8} ({p25}〜{p75}) n={s.sample_count}")

    print(f"\n{'='*70}\n")


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    asyncio.run(main())
