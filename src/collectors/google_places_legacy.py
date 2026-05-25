"""
AURA MVP — Google Maps Places API（レガシー版）コレクター

Google Maps Places API（レガシー Text Search）を使用して、
東京の美容クリニックの評価・口コミ数・営業時間を取得する。

使い方:
    # テスト: 新宿区だけ
    python -m src.collectors.google_places_legacy --area 新宿区

    # 本番: 東京23区全域
    python -m src.collectors.google_places_legacy --all-wards
"""

import argparse
import asyncio
import json
import logging
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# レガシーPlaces APIエンドポイント
TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
DETAIL_URL = "https://maps.googleapis.com/maps/api/place/details/json"

# 東京23区の中心座標
TOKYO_WARDS = {
    "新宿区": (35.6938, 139.7034),
    "渋谷区": (35.6620, 139.7038),
    "港区": (35.6581, 139.7514),
    "中央区": (35.6717, 139.7729),
    "千代田区": (35.6940, 139.7535),
    "豊島区": (35.7263, 139.7165),
    "品川区": (35.6090, 139.7300),
    "目黒区": (35.6411, 139.6985),
    "世田谷区": (35.6461, 139.6530),
    "大田区": (35.5613, 139.7160),
    "杉並区": (35.6993, 139.6364),
    "練馬区": (35.7356, 139.6516),
    "板橋区": (35.7518, 139.7090),
    "北区": (35.7528, 139.7339),
    "台東区": (35.7126, 139.7801),
    "墨田区": (35.7107, 139.8015),
    "江東区": (35.6729, 139.8172),
    "荒川区": (35.7363, 139.7834),
    "文京区": (35.7081, 139.7527),
    "足立区": (35.7756, 139.8047),
    "葛飾区": (35.7436, 139.8477),
    "江戸川区": (35.7066, 139.8685),
    "中野区": (35.7076, 139.6638),
}

# API呼び出し間隔（レート制限対策）
API_CALL_INTERVAL = 0.3


@dataclass
class PlaceResult:
    """検索結果"""
    place_id: str
    name: str
    address: str
    lat: float
    lng: float
    rating: float | None = None
    review_count: int | None = None
    website: str | None = None
    phone: str | None = None
    opening_hours: dict | None = None
    editorial_summary: str | None = None
    photos: list[str] | None = None
    types: list[str] | None = None


class GooglePlacesLegacy:
    """Google Maps Places API（レガシー版）コレクター"""

    def __init__(self, api_key: str, data_dir: str = "data/google"):
        self.api_key = api_key
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.results: list[PlaceResult] = []
        self._seen_place_ids: set[str] = set()
        self._api_calls = 0

    async def text_search(
        self,
        query: str,
        lat: float,
        lng: float,
        radius_meters: int = 3000,
    ) -> list[PlaceResult]:
        """Text Searchで検索（ページネーション対応）"""
        params = {
            "query": query,
            "location": f"{lat},{lng}",
            "radius": radius_meters,
            "language": "ja",
            "key": self.api_key,
        }

        all_results = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            # 最初のリクエスト
            resp = await client.get(TEXT_SEARCH_URL, params=params)
            self._api_calls += 1
            data = resp.json()

            if data.get("status") != "OK":
                logger.error(f"API error: {data.get('status')} — {data.get('error_message','')}")
                return []

            results = self._parse_results(data.get("results", []))
            all_results.extend(results)

            # ページネーション（最大3ページ = 60件）
            for page in range(2):
                next_token = data.get("next_page_token")
                if not next_token:
                    break

                # next_page_tokenが有効になるまで少し待つ必要がある
                await asyncio.sleep(2.0)

                params_next = {
                    "pagetoken": next_token,
                    "key": self.api_key,
                }
                resp = await client.get(TEXT_SEARCH_URL, params=params_next)
                self._api_calls += 1
                data = resp.json()

                if data.get("status") != "OK":
                    break

                results = self._parse_results(data.get("results", []))
                all_results.extend(results)

        logger.info(f"検索 '{query}': {len(all_results)}件（API calls: {self._api_calls}）")
        return all_results

    def _parse_results(self, places: list[dict]) -> list[PlaceResult]:
        """APIレスポンスをパース"""
        results = []
        for p in places:
            place_id = p.get("place_id", "")
            if place_id in self._seen_place_ids:
                continue
            self._seen_place_ids.add(place_id)

            loc = p.get("geometry", {}).get("location", {})
            hours = p.get("opening_hours", {})
            photos = [ph.get("photo_reference", "") for ph in p.get("photos", [])[:3]]

            results.append(PlaceResult(
                place_id=place_id,
                name=p.get("name", ""),
                address=p.get("formatted_address", ""),
                lat=loc.get("lat", 0.0),
                lng=loc.get("lng", 0.0),
                rating=p.get("rating"),
                review_count=p.get("user_ratings_total"),
                website=None,  # Text Searchでは取得不可
                opening_hours={"weekday_text": hours.get("weekday_text", [])} if hours else None,
                photos=photos if photos else None,
                types=p.get("types", []),
            ))
        return results

    async def search_ward(self, ward: str) -> list[PlaceResult]:
        """特定の区を3クエリで検索"""
        if ward not in TOKYO_WARDS:
            logger.error(f"'{ward}' は東京23区ではありません")
            return []

        lat, lng = TOKYO_WARDS[ward]
        queries = ["美容クリニック", "美容外科", "美容皮膚科"]
        all_results = []

        for query in queries:
            results = await self.text_search(
                query=f"{query} {ward}",
                lat=lat,
                lng=lng,
                radius_meters=3000,
            )
            all_results.extend(results)
            await asyncio.sleep(API_CALL_INTERVAL)

        self.results.extend(all_results)
        return all_results

    async def search_all_wards(self) -> list[PlaceResult]:
        """東京23区全域を検索"""
        total = 0
        for ward in TOKYO_WARDS:
            results = await self.search_ward(ward)
            total += len(results)
            logger.info(f"{ward}: {len(results)}件（累計: {total}）")
            await asyncio.sleep(API_CALL_INTERVAL)

        logger.info(f"全区検索完了: {len(self.results)}施設（重複排除済み, API calls: {self._api_calls}）")
        return self.results

    def to_json(self) -> list[dict]:
        """結果をJSON化"""
        return [asdict(r) for r in self.results]

    def save_json(self, output_path: str | None = None) -> str:
        """結果をJSONファイルに保存"""
        if not output_path:
            output_path = str(self.data_dir / "google_beauty_clinics.json")

        data = self.to_json()
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)

        logger.info(f"保存完了: {output_path} ({len(data)}件)")
        return output_path

    def print_summary(self):
        """検索結果のサマリー"""
        if not self.results:
            print("データなし")
            return

        print(f"\n{'='*50}")
        print(f"Google Maps — 美容クリニック検索結果")
        print(f"{'='*50}")
        print(f"総数: {len(self.results)}施設")
        print(f"API呼び出し: {self._api_calls}回")

        rated = [r for r in self.results if r.rating is not None]
        if rated:
            avg = sum(r.rating for r in rated) / len(rated)
            print(f"平均評価: {avg:.2f}（{len(rated)}施設）")

        reviewed = [r for r in self.results if r.review_count is not None]
        if reviewed:
            total = sum(r.review_count for r in reviewed)
            print(f"口コミ総数: {total:,}件")

        # 区ごとの集計
        ward_counts: dict[str, int] = {}
        for r in self.results:
            for ward in TOKYO_WARDS:
                if ward in r.address:
                    ward_counts[ward] = ward_counts.get(ward, 0) + 1
                    break
        if ward_counts:
            print(f"\n上位10区:")
            for ward, count in sorted(ward_counts.items(), key=lambda x: -x[1])[:10]:
                print(f"  {ward}: {count}件")

        if rated:
            top5 = sorted(rated, key=lambda r: (r.rating or 0, r.review_count or 0), reverse=True)[:5]
            print(f"\n高評価TOP5:")
            for r in top5:
                print(f"  ★{r.rating:.1f}（{r.review_count}件）{r.name}")


# google_ingest.pyからインポートされるため、TOKYO_WARDSをエクスポート
__all__ = ["GooglePlacesLegacy", "TOKYO_WARDS", "PlaceResult"]
