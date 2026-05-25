"""
AURA MVP — Google Places追加検索+DB書き込みスクリプト

密度の高いエリアを細分化した追加検索と、
23区外の主要都市をカバーする追加検索を実行する。

使い方:
    cd backend
    uv run python src/collectors/google_places_extra.py
"""

import asyncio
import json
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# 高密度エリアの細分化座標（中心から外れた地点を追加）
EXTRA_SEARCH_POINTS = {
    # 中央区 — 銀座・日本橋・築地
    "中央区_銀座": (35.6717, 139.7651),
    "中央区_日本橋": (35.6839, 139.7744),

    # 港区 — 表参道・六本木・赤坂
    "港区_表参道": (35.6651, 139.7121),
    "港区_六本木": (35.6626, 139.7314),
    "港区_赤坂": (35.6736, 139.7366),

    # 渋谷区 — 恵比寿・原宿
    "渋谷区_恵比寿": (35.6464, 139.7100),
    "渋谷区_原宿": (35.6702, 139.7027),

    # 新宿区 — 西新宿・高田馬場
    "新宿区_西新宿": (35.6944, 139.6917),
    "新宿区_東新宿": (35.6963, 139.7131),

    # 23区外の主要都市
    "町田市": (35.5489, 139.4468),
    "立川市": (35.6979, 139.4141),
    "八王子市": (35.6564, 139.3239),
    "武蔵野市": (35.7031, 139.5596),  # 吉祥寺
    "府中市": (35.6685, 139.4772),
    "調布市": (35.6519, 139.5415),
}


async def run_extra_search():
    """追加検索を実行"""
    from src.config import settings
    from src.collectors.google_places_legacy import GooglePlacesLegacy

    api_key = settings.google_maps_api_key
    if not api_key:
        print("APIキーが設定されていません。")
        return

    collector = GooglePlacesLegacy(api_key)

    for label, (lat, lng) in EXTRA_SEARCH_POINTS.items():
        queries = ["美容クリニック", "美容外科", "美容皮膚科"]
        for query in queries:
            results = await collector.text_search(
                query=f"{query} {label.split('_')[0]}",
                lat=lat,
                lng=lng,
                radius_meters=2000,  # 半径を小さくして精度向上
            )
            collector.results.extend(results)
            await asyncio.sleep(0.3)
        logger.info(f"{label}: 累計 {len(collector.results)}件")
        await asyncio.sleep(0.3)

    # 結果を保存
    if collector.results:
        json_path = collector.save_json("data/google/google_extra_search.json")
        collector.print_summary()

        # DBに書き込み
        from src.collectors.google_ingest import ingest_from_json
        stats = await ingest_from_json(json_path)

        print(f"\n{'='*50}")
        print(f"追加検索結果")
        print(f"{'='*50}")
        print(f"Google取得:     {stats['total_google']}件")
        print(f"DB一致:         {stats['matched']}件")
        print(f"  うち新規:     {stats['updated'] - stats['already_has_google']}件")
        print(f"  うち更新:     {stats['already_has_google']}件")
        print(f"  チェーン:     {stats['chain_matched']}件")
        print(f"未マッチ:       {stats['no_match']}件")
        match_rate = stats['matched'] / max(stats['total_google'], 1) * 100
        print(f"マッチ率:       {match_rate:.1f}%")
    else:
        print("検索結果なし")


if __name__ == "__main__":
    asyncio.run(run_extra_search())
