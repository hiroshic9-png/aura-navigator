"""
AURA MVP — Google Maps Places API (New) コレクター

Google Maps Places API (New) を使用して、東京の美容クリニックの
エンリッチメントデータ（評価・口コミ・写真・営業時間）を取得する。

Layer B: 厚労省データ（Layer A）に対するエンリッチメント層。

重要な制限事項:
- レビューは1リクエストあたり最大5件のみ（ページネーション不可）
- FieldMaskの指定でコスト最適化が必須
- Text Search (New): Pro SKU → 月5,000無料イベント
- Place Details (New): Pro SKU → 月5,000無料イベント

使い方:
    # 東京の美容クリニックを検索
    python -m src.collectors.google_places --query "美容クリニック" --area "新宿区"

    # 厚労省データとのマッチング
    python -m src.collectors.google_places --match-mhlw data/mhlw/mhlw_beauty_clinics.json

    # 東京23区の全区を一括検索
    python -m src.collectors.google_places --all-wards
"""

import argparse
import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from ulid import ULID

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Google Maps Places API (New) エンドポイント
PLACES_API_BASE = "https://places.googleapis.com/v1/places"
TEXT_SEARCH_URL = f"{PLACES_API_BASE}:searchText"

# 東京23区の中心座標（美容クリニックが集中するエリア優先）
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

# FieldMask（コスト最適化: 必要なフィールドのみ要求）
# Basic (SKU: Place Details Essentials): 無料枠大
BASIC_FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.location",
    "places.types",
])

# Pro (SKU: Place Details Pro): 月5,000無料
PRO_FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.location",
    "places.types",
    "places.rating",
    "places.userRatingCount",
    "places.websiteUri",
    "places.nationalPhoneNumber",
    "places.currentOpeningHours",
    "places.editorialSummary",
    "places.photos",
    "places.reviews",
])

# API呼び出し間隔（レート制限対策）
API_CALL_INTERVAL = 0.5  # 秒


@dataclass
class PlaceResult:
    """Google Places API検索結果"""

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
    reviews: list[dict] | None = None
    types: list[str] | None = None


class GooglePlacesCollector:
    """Google Maps Places API (New) コレクター"""

    def __init__(self, api_key: str, data_dir: str = "data/google"):
        self.api_key = api_key
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.results: list[PlaceResult] = []
        self._seen_place_ids: set[str] = set()  # 重複排除用

    async def text_search(
        self,
        query: str,
        lat: float,
        lng: float,
        radius_meters: int = 5000,
        max_results: int = 20,
        use_pro_fields: bool = True,
    ) -> list[PlaceResult]:
        """
        Text Search (New) APIでクリニックを検索

        Args:
            query: 検索クエリ（例: "美容クリニック"）
            lat: 中心緯度
            lng: 中心経度
            radius_meters: 検索半径（メートル）
            max_results: 最大結果数（最大20）
            use_pro_fields: Pro SKUフィールドを要求するか
        """
        field_mask = PRO_FIELD_MASK if use_pro_fields else BASIC_FIELD_MASK

        request_body = {
            "textQuery": query,
            "locationBias": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lng},
                    "radius": radius_meters,
                }
            },
            "languageCode": "ja",
            "maxResultCount": min(max_results, 20),
        }

        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": field_mask,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(TEXT_SEARCH_URL, json=request_body, headers=headers)

            if response.status_code != 200:
                logger.error(f"API error {response.status_code}: {response.text[:200]}")
                return []

            data = response.json()

        places = data.get("places", [])
        results = []

        for place in places:
            place_id = place.get("id", "")
            if place_id in self._seen_place_ids:
                continue  # 重複スキップ
            self._seen_place_ids.add(place_id)

            result = PlaceResult(
                place_id=place_id,
                name=place.get("displayName", {}).get("text", ""),
                address=place.get("formattedAddress", ""),
                lat=place.get("location", {}).get("latitude", 0.0),
                lng=place.get("location", {}).get("longitude", 0.0),
                rating=place.get("rating"),
                review_count=place.get("userRatingCount"),
                website=place.get("websiteUri"),
                phone=place.get("nationalPhoneNumber"),
                opening_hours=place.get("currentOpeningHours"),
                editorial_summary=place.get("editorialSummary", {}).get("text"),
                photos=self._extract_photo_names(place.get("photos", [])),
                reviews=self._extract_reviews(place.get("reviews", [])),
                types=place.get("types", []),
            )
            results.append(result)

        logger.info(f"検索 '{query}' @({lat:.4f},{lng:.4f}): {len(results)}件 (重複除外済)")
        return results

    def _extract_photo_names(self, photos: list[dict]) -> list[str]:
        """写真のリソース名を抽出（最大5枚）"""
        return [p.get("name", "") for p in photos[:5] if p.get("name")]

    def _extract_reviews(self, reviews: list[dict]) -> list[dict]:
        """レビュー情報を構造化（最大5件/リクエスト）"""
        extracted = []
        for review in reviews[:5]:
            extracted.append({
                "author": review.get("authorAttribution", {}).get("displayName", ""),
                "rating": review.get("rating"),
                "text": review.get("text", {}).get("text", ""),
                "time": review.get("publishTime", ""),
                "language": review.get("originalText", {}).get("languageCode", ""),
            })
        return extracted

    async def search_all_wards(
        self,
        queries: list[str] | None = None,
        radius_meters: int = 3000,
    ) -> list[PlaceResult]:
        """
        東京23区の全区を検索

        各区の中心座標で複数クエリを実行し、重複排除して統合。
        """
        if queries is None:
            queries = ["美容クリニック", "美容外科", "美容皮膚科"]

        all_results = []

        for ward_name, (lat, lng) in TOKYO_WARDS.items():
            for query in queries:
                logger.info(f"検索中: {ward_name} — '{query}'")
                results = await self.text_search(
                    query=f"{query} {ward_name}",
                    lat=lat,
                    lng=lng,
                    radius_meters=radius_meters,
                )
                all_results.extend(results)
                # レート制限対策
                await asyncio.sleep(API_CALL_INTERVAL)

        self.results = all_results
        logger.info(f"全区検索完了: {len(all_results)}施設（重複排除済み）")
        return all_results

    def match_with_mhlw(
        self, mhlw_data: list[dict], threshold: float = 0.6
    ) -> list[dict]:
        """
        厚労省データとのマッチング

        施設名と住所の類似度でマッチングし、Google Mapsデータをエンリッチメントする。
        """
        matched = []
        unmatched_google = []
        unmatched_mhlw = list(range(len(mhlw_data)))

        for result in self.results:
            best_match = None
            best_score = 0.0

            for idx, mhlw_clinic in enumerate(mhlw_data):
                score = self._calc_match_score(result, mhlw_clinic)
                if score > best_score:
                    best_score = score
                    best_match = idx

            if best_match is not None and best_score >= threshold:
                # マッチ成功: 厚労省データにGoogleデータをマージ
                merged = {**mhlw_data[best_match]}
                merged["google_place_id"] = result.place_id
                merged["google_rating"] = result.rating
                merged["google_review_count"] = result.review_count
                merged["website"] = result.website or merged.get("website")
                merged["lat"] = result.lat
                merged["lng"] = result.lng
                merged["google_photos"] = json.dumps(result.photos or [], ensure_ascii=False)
                merged["opening_hours"] = json.dumps(result.opening_hours or {}, ensure_ascii=False)
                merged["editorial_summary"] = result.editorial_summary
                merged["match_score"] = best_score
                matched.append(merged)

                if best_match in unmatched_mhlw:
                    unmatched_mhlw.remove(best_match)
            else:
                # マッチなし: Googleのみのデータ
                unmatched_google.append(result)

        logger.info(
            f"マッチング結果: "
            f"成功={len(matched)}, "
            f"Google未マッチ={len(unmatched_google)}, "
            f"厚労省未マッチ={len(unmatched_mhlw)}"
        )
        return matched

    def _calc_match_score(self, google_result: PlaceResult, mhlw_clinic: dict) -> float:
        """施設名と住所の類似度スコアを計算（0.0-1.0）"""
        score = 0.0

        # 名前の部分一致
        google_name = google_result.name.replace(" ", "").replace("　", "")
        mhlw_name = mhlw_clinic.get("name", "").replace(" ", "").replace("　", "")

        if google_name == mhlw_name:
            score += 0.6
        elif google_name in mhlw_name or mhlw_name in google_name:
            score += 0.4
        else:
            # 共通文字列の割合
            common = sum(1 for c in google_name if c in mhlw_name)
            if len(google_name) > 0:
                score += 0.3 * (common / len(google_name))

        # 住所の部分一致
        google_addr = google_result.address.replace(" ", "").replace("　", "")
        mhlw_addr = mhlw_clinic.get("address", "").replace(" ", "").replace("　", "")

        if google_addr and mhlw_addr:
            # 区名の一致
            for ward in TOKYO_WARDS:
                if ward in google_addr and ward in mhlw_addr:
                    score += 0.2
                    break
            # 町名レベルの一致
            common_addr = sum(1 for c in google_addr if c in mhlw_addr)
            if len(google_addr) > 0:
                score += 0.2 * (common_addr / len(google_addr))

        return min(score, 1.0)

    def to_json(self) -> list[dict]:
        """結果をJSON化"""
        return [
            {
                "place_id": r.place_id,
                "name": r.name,
                "address": r.address,
                "lat": r.lat,
                "lng": r.lng,
                "rating": r.rating,
                "review_count": r.review_count,
                "website": r.website,
                "phone": r.phone,
                "editorial_summary": r.editorial_summary,
                "photos": r.photos,
                "reviews": r.reviews,
                "types": r.types,
            }
            for r in self.results
        ]

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
        """検索結果のサマリーを表示"""
        if not self.results:
            print("データなし")
            return

        print(f"\n{'='*60}")
        print(f"Google Maps Places API — 美容クリニック検索結果")
        print(f"{'='*60}")
        print(f"総数: {len(self.results)}施設")

        # 評価の分布
        rated = [r for r in self.results if r.rating is not None]
        if rated:
            avg_rating = sum(r.rating for r in rated) / len(rated)
            print(f"平均評価: {avg_rating:.2f} ({len(rated)}施設)")

        # レビュー数の分布
        reviewed = [r for r in self.results if r.review_count is not None]
        if reviewed:
            total_reviews = sum(r.review_count for r in reviewed)
            print(f"口コミ総数: {total_reviews}件")

        # 区ごとの集計
        ward_counts: dict[str, int] = {}
        for r in self.results:
            for ward in TOKYO_WARDS:
                if ward in r.address:
                    ward_counts[ward] = ward_counts.get(ward, 0) + 1
                    break

        if ward_counts:
            print(f"\n--- 区別 ---")
            for ward, count in sorted(ward_counts.items(), key=lambda x: -x[1])[:10]:
                print(f"  {ward}: {count}件")

        # 高評価クリニック
        if rated:
            top5 = sorted(rated, key=lambda r: (r.rating or 0, r.review_count or 0), reverse=True)[:5]
            print(f"\n--- 高評価TOP5 ---")
            for r in top5:
                print(f"  ★{r.rating:.1f} ({r.review_count}件) {r.name}")


async def _run_poc(api_key: str, query: str, area: str):
    """PoCテスト: 単一エリアでの検索"""
    collector = GooglePlacesCollector(api_key)

    if area in TOKYO_WARDS:
        lat, lng = TOKYO_WARDS[area]
    else:
        # デフォルト: 新宿
        lat, lng = TOKYO_WARDS["新宿区"]

    results = await collector.text_search(
        query=f"{query} {area}",
        lat=lat,
        lng=lng,
        radius_meters=5000,
    )
    collector.results = results
    collector.print_summary()

    if results:
        output = collector.save_json()
        print(f"\n✅ {output} に保存しました")


async def _run_all_wards(api_key: str):
    """東京23区全区検索"""
    collector = GooglePlacesCollector(api_key)
    await collector.search_all_wards()
    collector.print_summary()

    if collector.results:
        output = collector.save_json()
        print(f"\n✅ {output} に保存しました")


def main():
    """CLIエントリポイント"""
    parser = argparse.ArgumentParser(description="Google Maps Places APIで美容クリニックを検索")
    parser.add_argument("--api-key", help="Google Maps APIキー（未指定時は環境変数AURA_GOOGLE_MAPS_API_KEYを使用）")
    parser.add_argument("--query", default="美容クリニック", help="検索クエリ")
    parser.add_argument("--area", default="新宿区", help="検索エリア（東京23区名）")
    parser.add_argument("--all-wards", action="store_true", help="東京23区全区を検索")
    parser.add_argument("--match-mhlw", help="厚労省データとのマッチング（JSONパス指定）")
    args = parser.parse_args()

    import os

    api_key = args.api_key or os.environ.get("AURA_GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        print("❌ Google Maps APIキーが必要です")
        print("   --api-key <KEY> または環境変数 AURA_GOOGLE_MAPS_API_KEY を設定してください")
        print()
        print("   GCPコンソールでの取得手順:")
        print("   1. https://console.cloud.google.com/apis/credentials")
        print("   2. APIキーを作成")
        print("   3. Places API (New) を有効化")
        return

    if args.all_wards:
        asyncio.run(_run_all_wards(api_key))
    else:
        asyncio.run(_run_poc(api_key, args.query, args.area))


if __name__ == "__main__":
    main()
