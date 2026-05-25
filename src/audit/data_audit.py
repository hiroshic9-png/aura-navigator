"""
AURA MVP — 全件データ監査スクリプト

全レコードを対象に以下を網羅的に検証:
1. データ完全性（必須フィールド、NULL、空文字）
2. データ鮮度（取得日、更新日、陳腐化判定）
3. 座標・住所の妥当性
4. Googleデータの整合性（マッチ品質、異常値）
5. JSON列の構造健全性
6. 重複レコード検出
7. クロスソース矛盾検出
8. 施術データの品質
"""

import asyncio
import json
import re
from collections import Counter, defaultdict
from datetime import datetime

REPORT_LINES = []

def log(msg):
    print(msg)
    REPORT_LINES.append(msg)


def section(title):
    log(f"\n{'='*60}")
    log(f"  {title}")
    log(f"{'='*60}")


def subsection(title):
    log(f"\n--- {title} ---")


async def run_audit():
    from sqlalchemy import select, func, text
    from src.db.database import AsyncSessionLocal, ClinicTable, ProcedureTable, AuditLog

    async with AsyncSessionLocal() as s:
        # 全クリニック取得
        result = await s.execute(select(ClinicTable))
        clinics = result.scalars().all()

        # 全施術取得
        result = await s.execute(select(ProcedureTable))
        procedures = result.scalars().all()

        # 監査ログ取得
        result = await s.execute(select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(50))
        audit_logs = result.scalars().all()

    now = datetime.now()

    # ============================================================
    section("1. 基本統計")
    # ============================================================
    log(f"監査実行日時: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"クリニック総数: {len(clinics)}")
    log(f"施術総数: {len(procedures)}")
    log(f"監査ログ直近件数: {len(audit_logs)}")

    active_clinics = [c for c in clinics if c.is_active]
    inactive_clinics = [c for c in clinics if not c.is_active]
    log(f"アクティブ: {len(active_clinics)} / 非アクティブ: {len(inactive_clinics)}")

    # ============================================================
    section("2. データ完全性（全件）")
    # ============================================================

    # 2a. 必須フィールドのNULL/空文字チェック
    subsection("2a. 必須フィールド充填率")
    required_fields = {
        'name': '施設名',
        'address': '住所',
        'prefecture': '都道府県',
        'city': '市区町村',
    }
    for field, label in required_fields.items():
        missing = [c for c in clinics if not getattr(c, field, None)]
        empty_str = [c for c in clinics if getattr(c, field, None) == '']
        log(f"  {label} ({field}): NULL={len(missing)}, 空文字={len(empty_str)}, 充填={len(clinics)-len(missing)-len(empty_str)}/{len(clinics)}")
        if missing:
            for c in missing[:3]:
                log(f"    ⚠ ID={c.id} name={c.name}")

    # 2b. 推奨フィールド充填率
    subsection("2b. 推奨フィールド充填率")
    recommended_fields = {
        'lat': '緯度', 'lng': '経度', 'phone': '電話番号',
        'website': 'Webサイト', 'mhlw_code': '厚労省コード',
        'medical_departments': '診療科目', 'doctor_count': '医師数',
        'medical_corp_name': '開設法人名', 'postal_code': '郵便番号',
    }
    for field, label in recommended_fields.items():
        filled = sum(1 for c in clinics if getattr(c, field, None))
        rate = filled / len(clinics) * 100 if clinics else 0
        flag = "✅" if rate >= 80 else "⚠️" if rate >= 50 else "❌"
        log(f"  {flag} {label} ({field}): {filled}/{len(clinics)} ({rate:.1f}%)")

    # 2c. Googleデータ充填率
    subsection("2c. Googleデータ充填率")
    google_fields = {
        'google_place_id': 'Place ID',
        'google_rating': '評価',
        'google_review_count': '口コミ数',
        'google_photos': '写真',
        'opening_hours': '営業時間',
        'editorial_summary': '紹介文',
    }
    for field, label in google_fields.items():
        if field == 'google_photos':
            filled = sum(1 for c in clinics if getattr(c, field) and getattr(c, field) != '[]' and getattr(c, field) != 'null')
        elif field == 'opening_hours':
            filled = sum(1 for c in clinics if getattr(c, field) and getattr(c, field) not in ('{}', 'null', '{"weekday_text": []}'))
        else:
            filled = sum(1 for c in clinics if getattr(c, field, None))
        rate = filled / len(clinics) * 100
        log(f"  {label}: {filled}/{len(clinics)} ({rate:.1f}%)")

    # ============================================================
    section("3. データ鮮度監査（全件）")
    # ============================================================

    # 3a. created_at / updated_at / fetched_at の分布
    subsection("3a. タイムスタンプ分布")
    created_dates = [c.created_at for c in clinics if c.created_at]
    updated_dates = [c.updated_at for c in clinics if c.updated_at]
    fetched_dates = [c.fetched_at for c in clinics if c.fetched_at]

    if created_dates:
        log(f"  created_at: 最古={min(created_dates)}, 最新={max(created_dates)}")
    if updated_dates:
        log(f"  updated_at: 最古={min(updated_dates)}, 最新={max(updated_dates)}")
    if fetched_dates:
        log(f"  fetched_at: 最古={min(fetched_dates)}, 最新={max(fetched_dates)}")

    # 3b. 鮮度判定（ポリシーベース）
    subsection("3b. ソース別鮮度判定")
    source_counter = Counter(c.source for c in clinics)
    for source, count in source_counter.most_common():
        log(f"  ソース '{source}': {count}件")

        # ポリシーに基づく鮮度判定
        from src.analyzers.freshness import FRESHNESS_POLICIES, DataSource
        policy_key = None
        for ds in DataSource:
            if ds.value == source:
                policy_key = ds
                break
        
        if policy_key and policy_key in FRESHNESS_POLICIES:
            policy = FRESHNESS_POLICIES[policy_key]
            source_clinics = [c for c in clinics if c.source == source]
            stale = 0
            aging = 0
            fresh = 0
            no_timestamp = 0
            for c in source_clinics:
                ts = c.fetched_at or c.created_at
                if not ts:
                    no_timestamp += 1
                    continue
                age_days = (now - ts).days
                if age_days > policy.max_age_days:
                    stale += 1
                elif age_days > policy.refresh_interval_days:
                    aging += 1
                else:
                    fresh += 1
            log(f"    ポリシー: 最大有効{policy.max_age_days}日, 推奨更新{policy.refresh_interval_days}日")
            log(f"    🟢 新鮮(fresh): {fresh}件")
            log(f"    🟡 要更新(aging): {aging}件")
            log(f"    🔴 陳腐化(stale): {stale}件")
            if no_timestamp:
                log(f"    ⚠️ タイムスタンプなし: {no_timestamp}件")
        else:
            log(f"    （鮮度ポリシー未定義）")

    # 3c. verified_at の状態
    subsection("3c. 検証日時(verified_at)の状態")
    verified_count = sum(1 for c in clinics if c.verified_at)
    not_verified = sum(1 for c in clinics if not c.verified_at)
    log(f"  検証済み: {verified_count}件")
    log(f"  未検証: {not_verified}件")

    # 3d. publish_status の分布
    subsection("3d. 公開ステータス分布")
    status_counter = Counter(c.publish_status for c in clinics)
    for status, count in status_counter.most_common():
        log(f"  {status}: {count}件")

    # ============================================================
    section("4. 座標・住所の妥当性（全件）")
    # ============================================================

    # 4a. 座標の範囲チェック（東京都）
    subsection("4a. 座標の範囲チェック")
    tokyo_lat_range = (35.0, 36.0)
    tokyo_lng_range = (138.8, 140.0)
    coord_issues = []
    no_coords = 0
    zero_coords = 0
    out_of_range = 0

    for c in clinics:
        if c.lat is None or c.lng is None:
            no_coords += 1
        elif c.lat == 0 and c.lng == 0:
            zero_coords += 1
            coord_issues.append(f"  ⚠ 座標(0,0): {c.name} [{c.id}]")
        elif not (tokyo_lat_range[0] <= c.lat <= tokyo_lat_range[1] and
                  tokyo_lng_range[0] <= c.lng <= tokyo_lng_range[1]):
            out_of_range += 1
            coord_issues.append(f"  ⚠ 範囲外({c.lat:.4f},{c.lng:.4f}): {c.name}")

    log(f"  座標なし: {no_coords}件")
    log(f"  座標(0,0): {zero_coords}件")
    log(f"  東京都範囲外: {out_of_range}件")
    log(f"  正常: {len(clinics) - no_coords - zero_coords - out_of_range}件")
    for issue in coord_issues[:10]:
        log(issue)
    if len(coord_issues) > 10:
        log(f"  ...他{len(coord_issues)-10}件")

    # 4b. 住所フォーマットチェック
    subsection("4b. 住所フォーマットチェック")
    addr_issues = []
    for c in clinics:
        addr = c.address or ''
        if not addr:
            continue
        if '東京都' not in addr and c.prefecture == '東京都':
            addr_issues.append(f"  「東京都」なし: {c.name} → {addr[:40]}")
        elif len(addr) < 10:
            addr_issues.append(f"  住所が短すぎ: {c.name} → {addr}")

    log(f"  住所異常: {len(addr_issues)}件")
    for issue in addr_issues[:5]:
        log(issue)

    # 4c. 市区町村の分布
    subsection("4c. 市区町村分布（上位15）")
    city_counter = Counter(c.city for c in clinics if c.city)
    for city, count in city_counter.most_common(15):
        log(f"  {city}: {count}件")

    # ============================================================
    section("5. Googleデータ整合性（全件）")
    # ============================================================

    google_clinics = [c for c in clinics if c.google_place_id]

    # 5a. 評価の異常値
    subsection("5a. Google評価の異常値チェック")
    rating_issues = []
    for c in google_clinics:
        r = c.google_rating
        if r is not None:
            if r < 1.0 or r > 5.0:
                rating_issues.append(f"  範囲外(★{r}): {c.name}")
            elif r == 0:
                rating_issues.append(f"  評価0: {c.name}")
    log(f"  評価異常: {len(rating_issues)}件")
    for issue in rating_issues:
        log(issue)

    # 5b. 口コミ数の異常値
    subsection("5b. 口コミ数分布")
    review_counts = [c.google_review_count or 0 for c in google_clinics]
    if review_counts:
        log(f"  最小: {min(review_counts)}")
        log(f"  最大: {max(review_counts)}")
        log(f"  平均: {sum(review_counts)/len(review_counts):.0f}")
        log(f"  中央値: {sorted(review_counts)[len(review_counts)//2]}")
        log(f"  0件: {sum(1 for r in review_counts if r == 0)}件")
        log(f"  1000件超: {sum(1 for r in review_counts if r > 1000)}件")

    # 5c. 写真データの健全性
    subsection("5c. 写真データ健全性")
    photo_issues = 0
    photo_valid = 0
    photo_empty = 0
    for c in google_clinics:
        raw = c.google_photos
        if not raw or raw in ('[]', 'null'):
            photo_empty += 1
            continue
        try:
            photos = json.loads(raw)
            if isinstance(photos, list):
                photo_valid += 1
                for p in photos:
                    if not isinstance(p, str) or len(p) < 10:
                        photo_issues += 1
                        break
            else:
                photo_issues += 1
        except json.JSONDecodeError:
            photo_issues += 1

    log(f"  有効な写真データ: {photo_valid}件")
    log(f"  写真なし/空: {photo_empty}件")
    log(f"  JSON異常: {photo_issues}件")

    # 5d. 営業時間データの健全性
    subsection("5d. 営業時間データ健全性")
    hours_valid = 0
    hours_empty = 0
    hours_invalid = 0
    hours_no_weekday = 0
    for c in google_clinics:
        raw = c.opening_hours
        if not raw or raw in ('{}', 'null'):
            hours_empty += 1
            continue
        try:
            hours = json.loads(raw)
            if isinstance(hours, dict):
                wt = hours.get('weekday_text', [])
                if isinstance(wt, list) and len(wt) > 0:
                    hours_valid += 1
                else:
                    hours_no_weekday += 1
            else:
                hours_invalid += 1
        except json.JSONDecodeError:
            hours_invalid += 1

    log(f"  有効な営業時間: {hours_valid}件")
    log(f"  weekday_textなし: {hours_no_weekday}件")
    log(f"  営業時間空: {hours_empty}件")
    log(f"  JSON異常: {hours_invalid}件")

    # 5e. place_idの重複チェック
    subsection("5e. place_idの重複チェック")
    place_ids = [c.google_place_id for c in google_clinics if c.google_place_id]
    pid_counter = Counter(place_ids)
    duplicates = {pid: cnt for pid, cnt in pid_counter.items() if cnt > 1}
    log(f"  ユニークplace_id: {len(set(place_ids))}件")
    log(f"  重複place_id: {len(duplicates)}件")
    for pid, cnt in list(duplicates.items())[:5]:
        dup_names = [c.name for c in google_clinics if c.google_place_id == pid]
        log(f"    {pid[:30]}... → {dup_names}")

    # ============================================================
    section("6. 重複レコード検出（全件）")
    # ============================================================

    # 6a. 完全一致（名前+住所）
    subsection("6a. 名前+住所の完全一致")
    name_addr = Counter((c.name, c.address) for c in clinics)
    exact_dupes = {k: v for k, v in name_addr.items() if v > 1}
    log(f"  重複グループ: {len(exact_dupes)}件")
    for (name, addr), cnt in list(exact_dupes.items())[:5]:
        log(f"    {cnt}件: {name} @ {(addr or '')[:30]}")

    # 6b. 名前のみ一致（支院の可能性）
    subsection("6b. 名前のみ一致（上位10）")
    name_only = Counter(c.name for c in clinics)
    name_dupes = {k: v for k, v in name_only.items() if v > 1}
    log(f"  同名グループ: {len(name_dupes)}件")
    for name, cnt in sorted(name_dupes.items(), key=lambda x: -x[1])[:10]:
        log(f"    {cnt}件: {name}")

    # 6c. mhlw_codeの重複チェック
    subsection("6c. 厚労省コードの重複")
    mhlw_codes = [c.mhlw_code for c in clinics if c.mhlw_code]
    mhlw_counter = Counter(mhlw_codes)
    mhlw_dupes = {k: v for k, v in mhlw_counter.items() if v > 1}
    log(f"  ユニーク厚労省コード: {len(set(mhlw_codes))}件")
    log(f"  重複: {len(mhlw_dupes)}件")
    for code, cnt in list(mhlw_dupes.items())[:5]:
        dup_names = [c.name for c in clinics if c.mhlw_code == code]
        log(f"    {code}: {dup_names}")

    # ============================================================
    section("7. JSON列の構造健全性（全件）")
    # ============================================================

    json_fields = {
        'medical_departments': '診療科目',
        'google_photos': '写真',
        'opening_hours': '営業時間',
        'facility_standards': '施設基準',
        'procedures_offered': '提供施術',
        'specialties': '専門分野',
    }
    for field, label in json_fields.items():
        valid = 0
        invalid = 0
        null_or_empty = 0
        for c in clinics:
            raw = getattr(c, field, None)
            if not raw or raw in ('null', ''):
                null_or_empty += 1
                continue
            try:
                json.loads(raw)
                valid += 1
            except (json.JSONDecodeError, TypeError):
                invalid += 1
                if invalid <= 3:
                    log(f"  ❌ {label} JSON不正: {c.name} → {str(raw)[:50]}")
        flag = "✅" if invalid == 0 else "❌"
        log(f"  {flag} {label}: 有効={valid}, NULL/空={null_or_empty}, 不正={invalid}")

    # ============================================================
    section("8. 施術データ品質監査（全件）")
    # ============================================================

    subsection("8a. 施術 基本統計")
    log(f"  施術総数: {len(procedures)}")
    cat_counter = Counter(p.category for p in procedures)
    for cat, cnt in cat_counter.most_common():
        log(f"    {cat}: {cnt}件")

    subsection("8b. 施術 データ充填率")
    proc_fields = {
        'description': '説明',
        'advertised_price': '広告価格',
        'real_price': '実勢価格',
        'downtime_official': 'DT公式',
        'downtime_real': 'DT実際',
        'risks': 'リスク',
        'counseling_questions': 'カウンセリング質問',
        'hidden_costs': '隠れコスト',
        'evidence_level': 'エビデンスレベル',
    }
    for field, label in proc_fields.items():
        filled = sum(1 for p in procedures if getattr(p, field, None))
        rate = filled / len(procedures) * 100 if procedures else 0
        flag = "✅" if rate >= 80 else "⚠️" if rate >= 50 else "❌"
        log(f"  {flag} {label}: {filled}/{len(procedures)} ({rate:.1f}%)")

    subsection("8c. 施術 価格データの妥当性")
    price_issues = []
    for p in procedures:
        try:
            adv = json.loads(p.advertised_price) if p.advertised_price else None
            real = json.loads(p.real_price) if p.real_price else None

            if adv and real and isinstance(adv, dict) and isinstance(real, dict):
                adv_min = adv.get('min_price', 0)
                real_min = real.get('min_price', 0)
                if adv_min and real_min:
                    if adv_min > real_min:
                        price_issues.append(f"  ⚠ 広告>実勢: {p.name} (広告{adv_min:,}円 > 実勢{real_min:,}円)")
                    ratio = real_min / adv_min if adv_min > 0 else 0
                    if ratio > 100:
                        price_issues.append(f"  ⚠ 倍率{ratio:.0f}x: {p.name}")
        except (json.JSONDecodeError, TypeError):
            price_issues.append(f"  ❌ 価格JSON不正: {p.name}")

    log(f"  価格異常: {len(price_issues)}件")
    for issue in price_issues:
        log(issue)

    subsection("8d. 施術 鮮度")
    for p in procedures:
        ts = p.fetched_at or p.created_at
        if ts:
            age = (now - ts).days
            if age > 365:
                log(f"  🔴 {age}日経過: {p.name}")
            elif age > 180:
                log(f"  🟡 {age}日経過: {p.name}")

    # ============================================================
    section("9. クロスソース矛盾検出")
    # ============================================================

    subsection("9a. Googleマッチ品質 — 名前差異チェック（全件）")
    name_mismatch = []
    from src.collectors.google_ingest import _normalize_name, _strip_legal_prefix
    for c in google_clinics:
        if not c.name or not c.google_place_id:
            continue
        # DB名とGoogle名の比較（Google名はDB未保存なので間接チェック）
        # 代わりにDB名の正規化品質を確認
        norm = _normalize_name(c.name)
        short = _strip_legal_prefix(norm)
        if len(short) < 3:
            name_mismatch.append(f"  ⚠ 短縮名が短すぎ: {c.name} → '{short}'")

    log(f"  短縮名異常: {len(name_mismatch)}件")
    for issue in name_mismatch[:5]:
        log(issue)

    subsection("9b. 評価なしだがplace_idあり")
    no_rating_with_pid = [c for c in google_clinics if c.google_place_id and c.google_rating is None]
    log(f"  place_idありだが評価なし: {len(no_rating_with_pid)}件")
    for c in no_rating_with_pid[:5]:
        log(f"    {c.name}")

    subsection("9c. Webサイトの形式チェック（全件）")
    web_issues = []
    for c in clinics:
        w = c.website
        if not w:
            continue
        if not w.startswith(('http://', 'https://')):
            web_issues.append(f"  ❌ URL不正: {c.name} → {w[:50]}")
        elif len(w) > 400:
            web_issues.append(f"  ⚠ URL長すぎ({len(w)}文字): {c.name}")
    log(f"  URL異常: {len(web_issues)}件")
    for issue in web_issues[:5]:
        log(issue)

    # ============================================================
    section("10. 監査ログ確認")
    # ============================================================
    log(f"  直近の監査ログ: {len(audit_logs)}件")
    for al in audit_logs[:10]:
        ts = al.timestamp.strftime('%m/%d %H:%M') if al.timestamp else '?'
        log(f"  [{ts}] {al.action}: {al.table_name}/{al.record_id[:20]}... by {al.changed_by}")

    # ============================================================
    section("11. 総合判定")
    # ============================================================

    issues = []
    warnings = []

    # クリティカル判定
    if zero_coords > 0:
        issues.append(f"座標(0,0)のレコード: {zero_coords}件")
    if len(exact_dupes) > 0:
        issues.append(f"完全重複レコード: {len(exact_dupes)}グループ")
    if len(mhlw_dupes) > 0:
        issues.append(f"厚労省コード重複: {len(mhlw_dupes)}件")
    if len(duplicates) > 0:
        issues.append(f"Google place_id重複: {len(duplicates)}件")

    # 警告判定
    if not_verified > len(clinics) * 0.5:
        warnings.append(f"未検証レコード: {not_verified}件（{not_verified/len(clinics)*100:.0f}%）")
    if no_coords > len(clinics) * 0.3:
        warnings.append(f"座標なし: {no_coords}件")
    if hours_no_weekday > len(google_clinics) * 0.5:
        warnings.append(f"営業時間データ不完全: {hours_no_weekday}件")

    log(f"\n  🔴 クリティカル問題: {len(issues)}件")
    for issue in issues:
        log(f"    • {issue}")

    log(f"\n  🟡 警告: {len(warnings)}件")
    for w in warnings:
        log(f"    • {w}")

    if not issues:
        log(f"\n  ✅ クリティカルなデータ破損は検出されませんでした")

    # レポートファイル保存
    report_path = "data/audit_report.txt"
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(REPORT_LINES))
    log(f"\n監査レポート保存: {report_path}")


if __name__ == "__main__":
    asyncio.run(run_audit())
