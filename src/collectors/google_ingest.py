"""
AURA MVP — Google Places データDB書き込み

Google Places APIで取得したデータを、既存の厚労省クリニックデータに統合する。
名前+住所のマッチングで紐付け、評価・口コミ数・写真等をDB更新。

使い方:
    # 1. Google Placesから検索（JSONファイルに保存される）
    python -m src.collectors.google_places --all-wards

    # 2. JSONファイルからDBに書き込み
    python -m src.collectors.google_ingest

    # 3. 特定区だけ取得して書き込み（テスト用）
    python -m src.collectors.google_ingest --area 新宿区
"""

import argparse
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import select, update

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def ingest_from_json(json_path: str) -> dict:
    """
    Google Places JSONファイルからDBに書き込み

    厚労省クリニックデータとのマッチングを行い、
    一致したクリニックにGoogle情報を付与する。
    """
    from src.db.database import AsyncSessionLocal, ClinicTable

    with open(json_path, encoding="utf-8") as f:
        google_data = json.load(f)

    logger.info(f"Google Places データ: {len(google_data)}件")

    stats = {
        "total_google": len(google_data),
        "matched": 0,
        "updated": 0,
        "no_match": 0,
        "already_has_google": 0,
        "chain_matched": 0,  # チェーン名+距離マッチ
    }

    async with AsyncSessionLocal() as session:
        # 全クリニックを取得
        result = await session.execute(select(ClinicTable).where(ClinicTable.is_active == True))
        clinics = result.scalars().all()
        logger.info(f"DBクリニック: {len(clinics)}件")

        # 名前→クリニックのインデックスを構築（高速マッチング用）
        name_index: dict[str, list] = {}
        short_name_index: dict[str, list] = {}  # 医療法人除去版
        for clinic in clinics:
            normalized = _normalize_name(clinic.name)
            if normalized not in name_index:
                name_index[normalized] = []
            name_index[normalized].append(clinic)

            # 短縮名インデックス（医療法人プレフィックス除去）
            short = _strip_legal_prefix(normalized)
            if short != normalized and len(short) > 2:
                if short not in short_name_index:
                    short_name_index[short] = []
                short_name_index[short].append(clinic)

        for g in google_data:
            g_name = _normalize_name(g.get("name", ""))
            g_address = g.get("address", "")
            place_id = g.get("place_id", "")

            if not g_name or not place_id:
                continue

            # マッチング: 正規化名で完全一致 → 部分一致 → チェーン名+距離 → 住所マッチ
            matched_clinic = None
            best_score = 0.0
            match_type = "none"

            # 正規化名と短縮名（医療法人除去版）の両方で検索
            g_short = _strip_legal_prefix(g_name)

            # 1. 完全一致（正規化名 or 短縮名）
            for check_name in [g_name, g_short]:
                if check_name in name_index:
                    candidates = name_index[check_name]
                    if len(candidates) == 1:
                        matched_clinic = candidates[0]
                        best_score = 1.0
                        match_type = "exact"
                        break
                    else:
                        for c in candidates:
                            score = _address_similarity(g_address, c.address or "")
                            if score > best_score:
                                best_score = score
                                matched_clinic = c
                                match_type = "exact_addr"
                if matched_clinic:
                    break

            # 1b. 短縮名INDEXでも検索（DB側の医療法人除去名）
            if not matched_clinic and g_short in short_name_index:
                candidates = short_name_index[g_short]
                if len(candidates) == 1:
                    matched_clinic = candidates[0]
                    best_score = 1.0
                    match_type = "short_exact"
                else:
                    for c in candidates:
                        score = _address_similarity(g_address, c.address or "")
                        if score > best_score:
                            best_score = score
                            matched_clinic = c
                            match_type = "short_exact_addr"

            # 2. 部分一致（完全一致がなかった場合）— 正規化名と短縮名の両方でチェック
            if not matched_clinic:
                for normalized_name, candidates in name_index.items():
                    # 正規化名同士または短縮名同士で部分一致
                    if (g_name in normalized_name or normalized_name in g_name or
                        g_short in normalized_name or normalized_name in g_short):
                        for c in candidates:
                            addr_score = _address_similarity(g_address, c.address or "")
                            name_score = _name_similarity(g_name, normalized_name)
                            total = name_score * 0.6 + addr_score * 0.4
                            if total > best_score and total >= 0.4:  # 閾値を0.5→0.4に緩和
                                best_score = total
                                matched_clinic = c
                                match_type = "partial"

            # 3. チェーン名+距離マッチ（上記で見つからなかった場合）
            if not matched_clinic:
                from src.collectors.chain_matcher import identify_chain, haversine_distance, _normalize_full
                g_lat = g.get("lat", 0.0)
                g_lng = g.get("lng", 0.0)
                g_chain = identify_chain(g.get("name", ""))
                if g_lat and g_lng and g_chain.is_chain and g_chain.chain_name:
                    g_chain_norm = _normalize_full(g_chain.chain_name)
                    best_dist = 500.0  # 最大500m
                    for clinic in clinics:
                        if not clinic.lat or not clinic.lng:
                            continue
                        # 名前に同じチェーン名が含まれるか簡易チェック
                        c_norm = _normalize_full(clinic.name)
                        if g_chain_norm not in c_norm and c_norm not in g_chain_norm:
                            continue
                        # 距離計算
                        dist = haversine_distance(g_lat, g_lng, clinic.lat, clinic.lng)
                        if dist < best_dist:
                            best_dist = dist
                            matched_clinic = clinic
                            match_type = "chain_distance"
                    if match_type == "chain_distance":
                        stats["chain_matched"] += 1
                        logger.info(
                            f"チェーンマッチ: {g.get('name','')} → {matched_clinic.name} "
                            f"(距離: {best_dist:.0f}m)"
                        )

            # 4. 住所ベースマッチ（上記で見つからなかった場合）
            if not matched_clinic:
                g_addr_norm = g_address.replace('　', '').replace(' ', '').replace('日本、', '')
                if len(g_addr_norm) > 10:
                    for clinic in clinics:
                        if not clinic.address:
                            continue
                        addr_score = _address_similarity(g_address, clinic.address)
                        if addr_score >= 0.80:
                            c_norm = _normalize_name(clinic.name)
                            c_short = _strip_legal_prefix(c_norm)
                            name_score = max(
                                _name_similarity(g_short, c_short),
                                _name_similarity(g_name, c_norm),
                            )
                            if name_score >= 0.40:
                                total = addr_score * 0.7 + name_score * 0.3
                                if total > best_score and total >= 0.65:
                                    best_score = total
                                    matched_clinic = clinic
                                    match_type = "address_match"
                    if match_type == "address_match":
                        stats["address_matched"] = stats.get("address_matched", 0) + 1
                        logger.info(
                            f"住所マッチ: {g.get('name','')} → {matched_clinic.name}"
                        )

            if matched_clinic:
                stats["matched"] += 1

                # 既にGoogle情報があるか
                if matched_clinic.google_place_id:
                    stats["already_has_google"] += 1
                    # 既存でも評価・口コミ数は最新に更新
                    matched_clinic.google_rating = g.get("rating")
                    matched_clinic.google_review_count = g.get("review_count")
                    stats["updated"] += 1
                else:
                    # 新規書き込み
                    matched_clinic.google_place_id = place_id
                    matched_clinic.google_rating = g.get("rating")
                    matched_clinic.google_review_count = g.get("review_count")
                    matched_clinic.google_photos = json.dumps(
                        g.get("photos", []), ensure_ascii=False
                    )
                    matched_clinic.opening_hours = json.dumps(
                        g.get("opening_hours") or {}, ensure_ascii=False
                    )
                    matched_clinic.editorial_summary = g.get("editorial_summary")

                    # Webサイトが未設定なら補完
                    if not matched_clinic.website and g.get("website"):
                        matched_clinic.website = g["website"]

                    stats["updated"] += 1
            else:
                stats["no_match"] += 1

        await session.commit()

    # 監査ログ記録
    await _log_audit(stats)

    return stats


def _normalize_name(name: str) -> str:
    """クリニック名を正規化（マッチング用）"""
    # 全角英数→半角
    name = name.translate(str.maketrans(
        'ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ０１２３４５６７８９',
        'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
    ))
    # スペース除去
    name = name.replace('　', '').replace(' ', '')
    # 表記揺れ
    name = name.replace('SBC', 'SBC')
    name = name.replace('TCB', 'TCB')
    return name


def _strip_legal_prefix(name: str) -> str:
    """医療法人・一般社団法人等のプレフィックスを除去した短縮名を返す"""
    import re
    # 方式: 法人種別 + 法人名（「会」「団」等で終了）を除去
    # 例: 「医療法人社団蘇青会榊原クリニック」→ 蘇青会 で分割 → 「榊原クリニック」
    patterns = [
        # 「医療法人社団○○会」「医療法人社団○○」をマッチ（「会」で終わるものを優先）
        r'^医療法人社団\S{1,8}?[会団院]',
        r'^医療法人財団\S{1,8}?[会団院]',
        r'^医療法人\S{1,8}?[会団院]',
        r'^一般社団法人\S{1,8}?[会団院]',
        r'^一般財団法人\S{1,8}?[会団院]',
        r'^株式会社\S{1,8}',
        # 「会」等で終わらないパターン（フォールバック: 空白区切り）
        r'^医療法人社団\S+?\s+',
        r'^医療法人\S+?\s+',
        r'^一般社団法人\S+?\s+',
    ]
    result = name
    for p in patterns:
        m = re.match(p, result)
        if m:
            result = result[m.end():]
            break
    # 先頭の空白を除去
    result = result.strip()
    # 最低限の長さチェック（除去しすぎた場合は元の名前を返す）
    if len(result) < 4:
        return name
    return result


def _name_similarity(a: str, b: str) -> float:
    """名前の類似度（0.0-1.0）"""
    if a == b:
        return 1.0
    if a in b or b in a:
        shorter = min(len(a), len(b))
        longer = max(len(a), len(b))
        return shorter / longer if longer > 0 else 0.0

    # 共通文字割合
    common = sum(1 for c in a if c in b)
    return common / max(len(a), 1)


def _address_similarity(a: str, b: str) -> float:
    """住所の類似度（0.0-1.0）"""
    a = a.replace("　", "").replace(" ", "")
    b = b.replace("　", "").replace(" ", "")

    if not a or not b:
        return 0.0

    # 区名一致
    score = 0.0
    from src.collectors.google_places_legacy import TOKYO_WARDS
    for ward in TOKYO_WARDS:
        if ward in a and ward in b:
            score += 0.4
            break

    # 町名以降の共通文字
    common = sum(1 for c in a if c in b)
    score += 0.6 * (common / max(len(a), 1))

    return min(score, 1.0)


async def _log_audit(stats: dict):
    """監査ログに記録"""
    from src.db.database import AsyncSessionLocal, AuditLog

    async with AsyncSessionLocal() as session:
        log = AuditLog(
            table_name="clinics",
            record_id="google_places_ingest",
            action="bulk_update",
            changed_fields=json.dumps(stats, ensure_ascii=False),
            changed_by="google_ingest",
            source="google_places_api",
        )
        session.add(log)
        await session.commit()


async def run_single_area(area: str):
    """単一エリアでテスト取得+DB書き込み"""
    from src.config import settings

    api_key = settings.google_maps_api_key
    if not api_key:
        print("APIキーが設定されていません。")
        print(".env ファイルに AURA_GOOGLE_MAPS_API_KEY を設定してください。")
        return

    from src.collectors.google_places_legacy import GooglePlacesLegacy, TOKYO_WARDS

    if area not in TOKYO_WARDS:
        print(f"エラー: '{area}' は東京23区ではありません。")
        return

    collector = GooglePlacesLegacy(api_key)
    lat, lng = TOKYO_WARDS[area]

    # 3クエリで区を検索
    await collector.search_ward(area)

    if not collector.results:
        print(f"{area}: 検索結果なし")
        return

    # JSONに保存
    json_path = collector.save_json(f"data/google/google_{area}.json")

    # DBに書き込み
    stats = await ingest_from_json(json_path)
    _print_stats(stats, area)


async def run_all_wards():
    """全23区を取得+DB書き込み"""
    from src.config import settings

    api_key = settings.google_maps_api_key
    if not api_key:
        print("APIキーが設定されていません。")
        print(".env ファイルに AURA_GOOGLE_MAPS_API_KEY を設定してください。")
        return

    from src.collectors.google_places_legacy import GooglePlacesLegacy

    collector = GooglePlacesLegacy(api_key)
    await collector.search_all_wards()
    collector.print_summary()

    if not collector.results:
        print("検索結果なし")
        return

    # JSONに保存
    json_path = collector.save_json()

    # DBに書き込み
    stats = await ingest_from_json(json_path)
    _print_stats(stats, "東京23区全域")


def _print_stats(stats: dict, label: str):
    """統計結果を表示"""
    print(f"\n{'='*50}")
    print(f"Google Places → DB書き込み結果 [{label}]")
    print(f"{'='*50}")
    print(f"Google取得:     {stats['total_google']}件")
    print(f"DB一致:         {stats['matched']}件")
    print(f"  うち新規:     {stats['updated'] - stats['already_has_google']}件")
    print(f"  うち更新:     {stats['already_has_google']}件")
    print(f"未マッチ:       {stats['no_match']}件")
    match_rate = stats['matched'] / max(stats['total_google'], 1) * 100
    print(f"マッチ率:       {match_rate:.1f}%")


def main():
    parser = argparse.ArgumentParser(description="Google Places データをDBに書き込み")
    parser.add_argument("--area", help="特定エリアのみ取得+書き込み（例: 新宿区）")
    parser.add_argument("--json", help="既存のJSONファイルからDB書き込みのみ実行")
    parser.add_argument("--all-wards", action="store_true", help="全23区を取得+DB書き込み")
    args = parser.parse_args()

    if args.json:
        # 既存JSONからの書き込みのみ
        stats = asyncio.run(ingest_from_json(args.json))
        _print_stats(stats, args.json)
    elif args.area:
        asyncio.run(run_single_area(args.area))
    elif args.all_wards:
        asyncio.run(run_all_wards())
    else:
        parser.print_help()
        print("\n例:")
        print("  # テスト: 新宿区だけ取得+DB書き込み")
        print("  python -m src.collectors.google_ingest --area 新宿区")
        print()
        print("  # 本番: 全23区を取得+DB書き込み")
        print("  python -m src.collectors.google_ingest --all-wards")


if __name__ == "__main__":
    main()
