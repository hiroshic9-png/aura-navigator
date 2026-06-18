#!/usr/bin/env python3
"""
症例写真 紐付けスクリプト

case_photosテーブルの以下の紐付けを一括実行:
1. procedure_name → procedure_id（施術マスタFK）
2. clinic_name/source → clinic_id（クリニックFK）

使い方:
    uv run python scripts/link_case_photos.py --dry-run
    uv run python scripts/link_case_photos.py
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "aura.db"

# ==========================================
# Step 1: procedure_name → procedure_id マッピング
# ==========================================

# 完全一致マッピング（case_photos.procedure_name → procedures.name）
EXACT_PROC_MAP: dict[str, str] = {
    "二重埋没法": "二重埋没法",
    "二重切開法": "二重切開法",
    "クールスカルプティング": "クールスカルプティング",
    "糸リフト": "糸リフト（フェイスライン引き上げ）",
    "目頭切開": "目頭切開",
}

# キーワードマッピング（procedure_name中のキーワード → procedures.name）
KEYWORD_PROC_MAP: list[tuple[str, str]] = [
    # 目もと
    ("二重・二重整形", "二重埋没法"),
    ("二重整形", "二重埋没法"),
    ("埋没法", "二重埋没法"),
    ("切開法", "二重切開法"),
    ("目頭切開", "目頭切開"),
    ("目尻切開", "目尻切開・たれ目形成"),
    ("たれ目", "目尻切開・たれ目形成"),
    ("眼瞼下垂", "眼瞼下垂手術"),
    ("まぶた", "上まぶたの脂肪除去"),
    ("クマ取り", "目の下のクマ取り（脱脂）"),
    ("クマ治療", "目の下のクマ取り（脱脂）"),
    ("下まぶた", "目の下のクマ取り（脱脂）"),
    ("脂肪注入（目", "目の下のクマ取り（脱脂＋脂肪注入）"),
    ("涙袋", "ヒアルロン酸注入（しわ・ほうれい線）"),
    # 鼻
    ("隆鼻", "プロテーゼ隆鼻"),
    ("小鼻縮小", "鼻翼縮小（小鼻縮小）"),
    ("鼻翼縮小", "鼻翼縮小（小鼻縮小）"),
    ("鼻翼挙上", "鼻翼縮小（小鼻縮小）"),
    ("鼻尖縮小", "鼻尖縮小"),
    ("鼻尖形成", "鼻尖縮小"),
    ("鼻中隔延長", "鼻中隔延長"),
    ("鼻骨", "鼻骨骨切り"),
    ("ヒアルロン酸注入（鼻", "ヒアルロン酸注入（隆鼻）"),
    # 肌・アンチエイジング
    ("若返り", "糸リフト（たるみ・引き締め）"),
    ("美肌糸リフト", "糸リフト（たるみ・引き締め）"),
    ("糸リフト", "糸リフト（フェイスライン引き上げ）"),
    ("ダーマペン", "ダーマペン（毛穴・ニキビ跡）"),
    ("ピーリング", "ケミカルピーリング（ニキビ跡・毛穴）"),
    ("ピコレーザー", "ピコレーザー（シミ・肝斑）"),
    ("レーザートーニング", "レーザートーニング（シミ・くすみ）"),
    ("シミ取り", "ピコレーザー（シミ・肝斑）"),
    ("ほくろ", "ピコレーザー（シミ・肝斑）"),
    ("フォトフェイシャル", "フォトフェイシャル（IPL光治療）"),
    ("フォトシルクプラス", "フォトフェイシャル（IPL光治療）"),
    ("光治療", "フォトフェイシャル（IPL光治療）"),
    ("ルメッカ", "フォトフェイシャル（IPL光治療）"),
    ("ボトックス", "ボトックス注射（しわ・表情じわ）"),
    ("ヒアルロン酸注入（あご", "ヒアルロン酸注入（あご形成）"),
    ("ヒアルロン酸", "ヒアルロン酸注入（しわ・ほうれい線）"),
    ("水光注射", "水光注射"),
    ("ハイフ", "HIFU（ハイフ）リフトアップ"),
    ("RF", "HIFU（ハイフ）リフトアップ"),
    ("サーマクール", "HIFU（ハイフ）リフトアップ"),
    # 輪郭
    ("エラボトックス", "エラボトックス（小顔）"),
    ("小顔", "エラボトックス（小顔）"),
    ("バッカルファット", "バッカルファット除去（頬の膨らみ）"),
    ("ジョールファット", "バッカルファット除去（頬の膨らみ）"),
    ("メーラーファット", "バッカルファット除去（頬の膨らみ）"),
    ("脂肪溶解", "脂肪溶解注射（二重あご・フェイスライン）"),
    # ボディ
    ("豊胸", "豊胸手術（脂肪注入）"),
    ("バスト", "豊胸手術（脂肪注入）"),
    ("脂肪吸引", "脂肪吸引（腹部・太もも）"),
    ("ベイザー脂肪吸引", "脂肪吸引（腹部・太もも）"),
    ("クールスカルプティング", "クールスカルプティング"),
    ("医療痩身", "脂肪溶解注射（ボディ）"),
    # 脱毛
    ("脱毛", "医療レーザー脱毛（全身）"),
    # その他
    ("ニキビ", "ダーマペン（毛穴・ニキビ跡）"),
    ("毛穴", "ケミカルピーリング（ニキビ跡・毛穴）"),
    ("人中短縮", "鼻翼縮小（小鼻縮小）"),
    ("口角挙上", "ボトックス注射（しわ・表情じわ）"),
]

# ソース → チェーン名マッピング
SOURCE_CHAIN_MAP: dict[str, str] = {
    "sbc": "湘南美容クリニック",
    "tcb": "TCB東京中央美容外科",
    "shinagawa": "品川美容外科",
}


def resolve_procedure_id(proc_name: str, proc_lookup: dict[str, str]) -> str | None:
    """施術名テキストからprocedure_idを解決"""
    if not proc_name:
        return None

    # 1. 完全一致
    if proc_name in EXACT_PROC_MAP:
        target_name = EXACT_PROC_MAP[proc_name]
        return proc_lookup.get(target_name)

    # 2. 複合施術名を分割（「・」区切り）
    parts = re.split(r"[・、]", proc_name)
    first_part = parts[0].strip()

    # 最初のパートで完全一致
    if first_part in EXACT_PROC_MAP:
        target_name = EXACT_PROC_MAP[first_part]
        return proc_lookup.get(target_name)

    # 3. キーワードマッチ（最初のパート → 全文の順）
    for keyword, target_name in KEYWORD_PROC_MAP:
        if keyword in first_part:
            return proc_lookup.get(target_name)

    for keyword, target_name in KEYWORD_PROC_MAP:
        if keyword in proc_name:
            return proc_lookup.get(target_name)

    return None


def main():
    """メイン処理"""
    import argparse

    parser = argparse.ArgumentParser(description="症例写真 紐付けスクリプト")
    parser.add_argument("--dry-run", action="store_true", help="DB書き込みせずに結果を表示")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    print("=" * 60)
    print("症例写真 紐付けスクリプト")
    print("=" * 60)

    # --- procedure_idカラム追加 ---
    c.execute("PRAGMA table_info(case_photos)")
    columns = [row[1] for row in c.fetchall()]
    if "procedure_id" not in columns:
        if args.dry_run:
            print("\n[DRY-RUN] ALTER TABLE case_photos ADD COLUMN procedure_id VARCHAR(26)")
        else:
            c.execute("ALTER TABLE case_photos ADD COLUMN procedure_id VARCHAR(26)")
            conn.commit()
            print("\n✅ procedure_id カラム追加完了")
    else:
        print("\nprocedure_id カラム既存")

    # --- proceduresマスタをロード ---
    c.execute("SELECT id, name FROM procedures")
    proc_lookup: dict[str, str] = {}  # name → id
    for row in c.fetchall():
        proc_lookup[row[1]] = row[0]
    print(f"  procedures マスタ: {len(proc_lookup)}件")

    # --- Step 1: procedure_name → procedure_id ---
    print("\n--- Step 1: procedure_name → procedure_id マッピング ---")
    c.execute("""SELECT id, procedure_name FROM case_photos
    WHERE (is_active != 0 OR is_active IS NULL)
    AND procedure_name IS NOT NULL AND procedure_name != ''""")
    rows = c.fetchall()
    print(f"  対象: {len(rows)}件")

    proc_updated = 0
    proc_failed = []
    proc_stats: dict[str, int] = {}

    for cp_id, proc_name in rows:
        proc_id = resolve_procedure_id(proc_name, proc_lookup)
        if proc_id:
            proc_stats[proc_id] = proc_stats.get(proc_id, 0) + 1
            if not args.dry_run:
                c.execute("UPDATE case_photos SET procedure_id = ? WHERE id = ?", (proc_id, cp_id))
            proc_updated += 1
        else:
            if proc_name not in [p for p, _ in proc_failed[:50]]:
                proc_failed.append((proc_name, 1))

    if not args.dry_run:
        conn.commit()

    # マッチ先の名前解決
    id_to_name = {v: k for k, v in proc_lookup.items()}
    print(f"\n  ✅ マッチ成功: {proc_updated}/{len(rows)}件 ({proc_updated/len(rows)*100:.1f}%)")
    print(f"  ❌ 未マッチ: {len(rows) - proc_updated}件")

    print("\n  マッチ先分布:")
    for proc_id, cnt in sorted(proc_stats.items(), key=lambda x: -x[1])[:15]:
        name = id_to_name.get(proc_id, proc_id[:8])
        print(f"    {name}: {cnt}件")

    if proc_failed:
        print(f"\n  未マッチ施術名 (上位10件):")
        unique_failed: dict[str, int] = {}
        for cp_id, proc_name in rows:
            if not resolve_procedure_id(proc_name, proc_lookup):
                unique_failed[proc_name] = unique_failed.get(proc_name, 0) + 1
        for name, cnt in sorted(unique_failed.items(), key=lambda x: -x[1])[:10]:
            print(f"    「{name}」: {cnt}件")

    # --- Step 2: clinic_name/source → clinic_id ---
    print("\n--- Step 2: clinic_name/source → clinic_id マッピング ---")

    # チェーン名→代表clinic_idを取得
    chain_clinic_map: dict[str, str] = {}
    for source, chain_name in SOURCE_CHAIN_MAP.items():
        c.execute("""SELECT id FROM clinics WHERE chain_name = ?
        ORDER BY google_review_count DESC NULLS LAST LIMIT 1""", (chain_name,))
        row = c.fetchone()
        if row:
            chain_clinic_map[source] = row[0]
            print(f"  {chain_name} 代表院 → {row[0][:8]}...")

    # tribeau（個別クリニック名でマッチ）
    c.execute("""SELECT DISTINCT clinic_name FROM case_photos
    WHERE source = 'tribeau' AND clinic_name IS NOT NULL AND clinic_name != ''
    AND clinic_name != 'トリビュー'""")
    tribeau_names = [row[0] for row in c.fetchall()]
    print(f"  Tribeau 個別クリニック名: {len(tribeau_names)}件")

    # 更新実行
    clinic_updated = 0

    # SBC/TCB/品川: sourceベースで代表院にマッピング
    for source, clinic_id in chain_clinic_map.items():
        if args.dry_run:
            c.execute("""SELECT COUNT(*) FROM case_photos
            WHERE source = ? AND clinic_id IS NULL
            AND (is_active != 0 OR is_active IS NULL)""", (source,))
            cnt = c.fetchone()[0]
            print(f"  [DRY-RUN] {source}: {cnt}件 → clinic_id={clinic_id[:8]}...")
            clinic_updated += cnt
        else:
            c.execute("""UPDATE case_photos SET clinic_id = ?
            WHERE source = ? AND clinic_id IS NULL
            AND (is_active != 0 OR is_active IS NULL)""", (clinic_id, source))
            clinic_updated += c.rowcount

    # Tribeau: clinic_nameでfuzzyマッチ
    tribeau_matched = 0
    c.execute("""SELECT id, clinic_name FROM case_photos
    WHERE source = 'tribeau' AND clinic_id IS NULL
    AND (is_active != 0 OR is_active IS NULL)
    AND clinic_name IS NOT NULL AND clinic_name != '' AND clinic_name != 'トリビュー'""")
    for cp_id, cname in c.fetchall():
        c2 = conn.cursor()
        c2.execute("SELECT id FROM clinics WHERE name LIKE ?", (f"%{cname}%",))
        row = c2.fetchone()
        if row and not args.dry_run:
            c.execute("UPDATE case_photos SET clinic_id = ? WHERE id = ?", (row[0], cp_id))
            tribeau_matched += 1
        elif row:
            tribeau_matched += 1

    clinic_updated += tribeau_matched
    if not args.dry_run:
        conn.commit()

    print(f"\n  ✅ clinic_id 設定: {clinic_updated}件")
    print(f"    うちTribeau個別マッチ: {tribeau_matched}件")

    # --- 最終統計 ---
    print(f"\n{'='*60}")
    print(f"{'[DRY-RUN] ' if args.dry_run else ''}完了")
    print(f"{'='*60}")

    c.execute("SELECT COUNT(*) FROM case_photos WHERE is_active != 0 OR is_active IS NULL")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM case_photos WHERE procedure_id IS NOT NULL AND (is_active != 0 OR is_active IS NULL)")
    with_proc = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM case_photos WHERE clinic_id IS NOT NULL AND (is_active != 0 OR is_active IS NULL)")
    with_clinic = c.fetchone()[0]

    print(f"  有効症例写真: {total}件")
    print(f"  procedure_id設定: {with_proc}/{total} ({with_proc/total*100:.1f}%)")
    print(f"  clinic_id設定: {with_clinic}/{total} ({with_clinic/total*100:.1f}%)")

    conn.close()


if __name__ == "__main__":
    main()
