"""
AURA MVP — 厚労省「医療情報ネット（ナビイ）」オープンデータ取得

厚労省が公開するCSVオープンデータから、美容外科・形成外科・皮膚科を
標榜する医療機関を抽出し、クリニックDBの基盤データとして投入する。

データソース:
- 厚労省オープンデータ: https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/iryou/newpage_43373.html
- e-Govデータポータル: https://data.e-gov.go.jp/data/dataset/321fdf20-5f6a-49e5-bcab-35d81d652c65
- ライセンス: CC BY 4.0（商用利用可）

ファイル構成:
- 施設票（病院/診療所）: 基本情報（名称・住所・電話番号・開設者等）
- 診療科・診療時間票: 診療科目・診療時間情報
- 両者を医療機関コードで結合してフィルタリング

使い方:
    # ダウンロード済みCSVからの取り込み
    python -m src.collectors.mhlw_opendata --facility-csv <施設票CSV> --dept-csv <診療科CSV> --prefecture 東京都

    # 結果の確認
    python -m src.collectors.mhlw_opendata --count-only
"""

import argparse
import csv
import io
import json
import logging
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import httpx
from ulid import ULID

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# 美容医療に関連する診療科目キーワード
BEAUTY_DEPARTMENT_KEYWORDS = [
    "美容外科",
    "形成外科",
    "美容皮膚科",
    "皮膚科",  # 美容皮膚科を兼ねている場合が多い
]

# 対象とする施設種別
TARGET_FACILITY_TYPES = ["診療所", "病院"]

# 東京都コード
TOKYO_PREFECTURE_CODE = "13"


class MhlwOpenDataCollector:
    """厚労省オープンデータの取得・パース・フィルタリング"""

    def __init__(self, data_dir: str = "data/mhlw"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.clinics: list[dict] = []

    def load_facility_csv(self, csv_path: str, encoding: str = "utf-8-sig") -> list[dict]:
        """
        施設票CSVを読み込む

        主要カラム（定義書準拠、実際のカラム名はCSVヘッダーに依存）:
        - 医療機関コード
        - 医療機関名称
        - 都道府県コード / 都道府県名
        - 市区町村コード / 市区町村名
        - 住所
        - 電話番号
        - 開設者名
        - 管理者名
        - 病床数
        """
        logger.info(f"施設票CSV読み込み: {csv_path}")
        facilities = []

        with open(csv_path, encoding=encoding, newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            logger.info(f"カラム数: {len(headers)}, ヘッダー例: {headers[:5]}")

            for row in reader:
                facilities.append(row)

        logger.info(f"施設票レコード数: {len(facilities)}")
        return facilities

    def load_department_csv(self, csv_path: str, encoding: str = "utf-8-sig") -> list[dict]:
        """
        診療科・診療時間票CSVを読み込む

        主要カラム:
        - 医療機関コード（施設票との結合キー）
        - 診療科コード
        - 診療科名
        - 曜日別診療時間
        """
        logger.info(f"診療科CSV読み込み: {csv_path}")
        departments = []

        with open(csv_path, encoding=encoding, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                departments.append(row)

        logger.info(f"診療科レコード数: {len(departments)}")
        return departments

    def find_column_name(self, headers: list[str], keywords: list[str]) -> str | None:
        """カラム名をキーワードで柔軟に検索（表記揺れ対応）"""
        for header in headers:
            for keyword in keywords:
                if keyword in header:
                    return header
        return None

    def filter_beauty_clinics(
        self,
        facilities: list[dict],
        departments: list[dict],
        prefecture: str = "東京都",
    ) -> list[dict]:
        """
        美容外科・形成外科・美容皮膚科を標榜する施設を抽出

        1. 診療科票から美容関連科目を持つ医療機関コードを特定
        2. 施設票から該当施設の基本情報を取得
        3. 指定都道府県でフィルタリング
        """
        logger.info(f"美容関連施設の抽出開始（対象: {prefecture}）")

        if not departments:
            logger.warning("診療科データなし。施設名での推定フィルタリングを実行")
            return self._filter_by_name(facilities, prefecture)

        # Step 1: 診療科票から美容関連の医療機関コードを収集
        dept_headers = list(departments[0].keys()) if departments else []
        # 診療科名カラムを探す
        dept_col = self.find_column_name(dept_headers, ["診療科", "科目", "科名"])
        code_col = self.find_column_name(dept_headers, ["医療機関コード", "機関コード", "コード"])

        if not dept_col or not code_col:
            logger.warning(f"診療科カラムが見つかりません。ヘッダー: {dept_headers}")
            return self._filter_by_name(facilities, prefecture)

        beauty_codes: set[str] = set()
        dept_map: dict[str, list[str]] = {}  # コード → 診療科リスト

        for row in departments:
            dept_name = row.get(dept_col, "")
            org_code = row.get(code_col, "")
            if not org_code:
                continue

            # 診療科マップに追加
            if org_code not in dept_map:
                dept_map[org_code] = []
            dept_map[org_code].append(dept_name)

            # 美容関連キーワードチェック
            for keyword in BEAUTY_DEPARTMENT_KEYWORDS:
                if keyword in dept_name:
                    beauty_codes.add(org_code)
                    break

        logger.info(f"美容関連科目を持つ医療機関コード: {len(beauty_codes)}件")

        # Step 2: 施設票から該当施設を抽出
        fac_headers = list(facilities[0].keys()) if facilities else []
        fac_code_col = self.find_column_name(fac_headers, ["医療機関コード", "機関コード", "コード"])
        fac_name_col = self.find_column_name(fac_headers, ["医療機関名称", "施設名", "名称"])
        fac_addr_col = self.find_column_name(fac_headers, ["住所", "所在地"])
        fac_tel_col = self.find_column_name(fac_headers, ["電話番号", "電話"])
        fac_pref_col = self.find_column_name(fac_headers, ["都道府県", "県名", "都道府県名"])
        fac_city_col = self.find_column_name(fac_headers, ["市区町村", "市町村"])
        fac_opener_col = self.find_column_name(fac_headers, ["開設者", "設立者"])
        fac_bed_col = self.find_column_name(fac_headers, ["病床", "ベッド"])

        results = []
        for row in facilities:
            org_code = row.get(fac_code_col, "") if fac_code_col else ""
            if org_code not in beauty_codes:
                continue

            # 都道府県フィルタ
            pref = row.get(fac_pref_col, "") if fac_pref_col else ""
            if prefecture and prefecture not in pref:
                # 住所からもチェック
                addr = row.get(fac_addr_col, "") if fac_addr_col else ""
                if prefecture not in addr:
                    continue

            clinic = {
                "mhlw_code": org_code,
                "name": row.get(fac_name_col, "") if fac_name_col else "",
                "address": row.get(fac_addr_col, "") if fac_addr_col else "",
                "phone": row.get(fac_tel_col, "") if fac_tel_col else "",
                "prefecture": prefecture,
                "city": row.get(fac_city_col, "") if fac_city_col else "",
                "medical_corp_name": row.get(fac_opener_col, "") if fac_opener_col else "",
                "medical_departments": dept_map.get(org_code, []),
                "bed_count": int(row.get(fac_bed_col, 0) or 0) if fac_bed_col else 0,
                "source": "mhlw",
            }
            results.append(clinic)

        logger.info(f"抽出結果: {len(results)}施設（{prefecture}、美容関連科目）")
        return results

    def _filter_by_name(self, facilities: list[dict], prefecture: str) -> list[dict]:
        """施設名ベースの推定フィルタリング（診療科データがない場合のフォールバック）"""
        name_keywords = ["美容", "クリニック", "形成", "スキン"]
        fac_headers = list(facilities[0].keys()) if facilities else []
        fac_name_col = self.find_column_name(fac_headers, ["医療機関名称", "施設名", "名称"])
        fac_addr_col = self.find_column_name(fac_headers, ["住所", "所在地"])

        results = []
        for row in facilities:
            name = row.get(fac_name_col, "") if fac_name_col else ""
            addr = row.get(fac_addr_col, "") if fac_addr_col else ""
            if prefecture not in addr and prefecture not in name:
                continue
            if any(kw in name for kw in name_keywords):
                results.append({"name": name, "address": addr, "source": "mhlw_name_estimate"})

        logger.info(f"名前ベース推定: {len(results)}施設")
        return results

    def to_clinic_records(self, filtered: list[dict]) -> list[dict]:
        """抽出結果をクリニックDBレコード形式に変換"""
        records = []
        for item in filtered:
            record = {
                "id": str(ULID()),
                "name": item.get("name", ""),
                "address": item.get("address", ""),
                "prefecture": item.get("prefecture", "東京都"),
                "city": item.get("city", ""),
                "phone": item.get("phone", ""),
                "mhlw_code": item.get("mhlw_code", ""),
                "medical_departments": json.dumps(
                    item.get("medical_departments", []), ensure_ascii=False
                ),
                "medical_corp_name": item.get("medical_corp_name", ""),
                "doctor_count": item.get("doctor_count"),
                "bed_count": item.get("bed_count", 0),
                "source": "mhlw",
                "is_active": True,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
            }
            records.append(record)

        logger.info(f"クリニックDBレコード: {len(records)}件生成")
        self.clinics = records
        return records

    def save_json(self, output_path: str | None = None) -> str:
        """結果をJSONファイルに保存"""
        if not output_path:
            output_path = str(self.data_dir / "mhlw_beauty_clinics.json")

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.clinics, f, ensure_ascii=False, indent=2, default=str)

        logger.info(f"保存完了: {output_path} ({len(self.clinics)}件)")
        return output_path

    def print_summary(self):
        """抽出結果のサマリーを表示"""
        if not self.clinics:
            print("データなし")
            return

        print(f"\n{'='*60}")
        print(f"厚労省オープンデータ — 美容関連クリニック抽出結果")
        print(f"{'='*60}")
        print(f"総数: {len(self.clinics)}施設")

        # 区ごとの集計
        city_counts: dict[str, int] = {}
        for c in self.clinics:
            city = c.get("city", "不明")
            city_counts[city] = city_counts.get(city, 0) + 1

        if city_counts:
            print(f"\n--- 市区町村別 ---")
            for city, count in sorted(city_counts.items(), key=lambda x: -x[1])[:20]:
                print(f"  {city}: {count}件")

        # 診療科目の集計
        dept_counts: dict[str, int] = {}
        for c in self.clinics:
            depts = json.loads(c.get("medical_departments", "[]"))
            for dept in depts:
                for kw in BEAUTY_DEPARTMENT_KEYWORDS:
                    if kw in dept:
                        dept_counts[kw] = dept_counts.get(kw, 0) + 1

        if dept_counts:
            print(f"\n--- 診療科目別 ---")
            for dept, count in sorted(dept_counts.items(), key=lambda x: -x[1]):
                print(f"  {dept}: {count}件")

        # サンプル表示
        print(f"\n--- サンプル（先頭5件）---")
        for c in self.clinics[:5]:
            depts = json.loads(c.get("medical_departments", "[]"))
            print(f"  {c['name']} | {c['address'][:30]}... | {', '.join(depts[:3])}")


def main():
    """CLI エントリポイント"""
    parser = argparse.ArgumentParser(description="厚労省オープンデータから美容クリニックを抽出")
    parser.add_argument("--facility-csv", help="施設票CSVファイルパス")
    parser.add_argument("--dept-csv", help="診療科・診療時間票CSVファイルパス")
    parser.add_argument("--prefecture", default="東京都", help="対象都道府県")
    parser.add_argument("--output", help="出力JSONパス")
    parser.add_argument("--encoding", default="utf-8-sig", help="CSVエンコーディング")
    args = parser.parse_args()

    collector = MhlwOpenDataCollector()

    if not args.facility_csv:
        print("使い方:")
        print("  1. 厚労省オープンデータページからCSVをダウンロード:")
        print("     https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/iryou/newpage_43373.html")
        print("  2. 以下のコマンドで実行:")
        print(f"     python -m src.collectors.mhlw_opendata \\")
        print(f"       --facility-csv <施設票CSV> \\")
        print(f"       --dept-csv <診療科CSV> \\")
        print(f"       --prefecture {args.prefecture}")
        sys.exit(0)

    # CSVの読み込み
    facilities = collector.load_facility_csv(args.facility_csv, encoding=args.encoding)

    departments = []
    if args.dept_csv:
        departments = collector.load_department_csv(args.dept_csv, encoding=args.encoding)

    # フィルタリング
    filtered = collector.filter_beauty_clinics(facilities, departments, args.prefecture)

    # レコード変換
    collector.to_clinic_records(filtered)

    # サマリー表示
    collector.print_summary()

    # JSON保存
    output_path = collector.save_json(args.output)
    print(f"\n✅ {output_path} に保存しました")


if __name__ == "__main__":
    main()
