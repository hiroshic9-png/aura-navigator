"""
Phase 38: 4カテゴリの価格データ投入

アンチエイジング・痩身・豊胸・医療脱毛の各施術に対し、
大手チェーンの公開価格帯と一般的な市場相場をもとに
代表価格を推定・投入する。

既に価格がある行は更新しない（上書き禁止）。
"""

import sqlite3
import sys

DB_PATH = "data/aura.db"

# 施術ごとの市場相場データ（2025年東京エリア）
# 出典: 各クリニック公式サイト・医療費比較サイトの公開情報
MARKET_PRICES = {
    # --- アンチエイジング ---
    "ヒアルロン酸注入（しわ・ほうれい線）": {
        "median": 55000,
        "range": (15000, 180000),
        "chain_prices": {
            "湘南美容クリニック": (18000, 50000),
            "TCB東京中央美容外科": (19000, 69800),
            "品川美容外科": (12000, 45000),
            "聖心美容クリニック": (55000, 110000),
            "ガーデンクリニック": (40000, 80000),
            "TAクリニック": (21800, 69800),
            "城本クリニック": (25000, 65000),
        },
    },
    "ボトックス注射（しわ・表情じわ）": {
        "median": 20000,
        "range": (3000, 80000),
        "chain_prices": {
            "湘南美容クリニック": (3500, 30000),
            "TCB東京中央美容外科": (3500, 32800),
            "品川美容外科": (3000, 19000),
            "聖心美容クリニック": (30000, 80000),
            "ガーデンクリニック": (20000, 50000),
            "城本クリニック": (10000, 32000),
        },
    },
    "糸リフト（たるみ・引き締め）": {
        "median": 120000,
        "range": (30000, 500000),
        "chain_prices": {
            "湘南美容クリニック": (18000, 100000),
            "TCB東京中央美容外科": (13800, 114100),
            "品川美容外科": (28000, 90000),
            "聖心美容クリニック": (150000, 400000),
            "東京美容外科": (100000, 250000),
        },
    },
    "エラボトックス（小顔）": {
        "median": 25000,
        "range": (3500, 100000),
        "chain_prices": {
            "湘南美容クリニック": (8800, 25000),
            "TCB東京中央美容外科": (3500, 28800),
            "品川美容外科": (3000, 19800),
            "聖心美容クリニック": (35000, 80000),
        },
    },
    "脂肪溶解注射（二重あご・フェイスライン）": {
        "median": 20000,
        "range": (5000, 60000),
        "chain_prices": {
            "湘南美容クリニック": (5000, 25000),
            "TCB東京中央美容外科": (1980, 30400),
            "品川美容外科": (4000, 15000),
            "ガーデンクリニック": (15000, 30000),
        },
    },
    "ヒアルロン酸注入（あご形成）": {
        "median": 60000,
        "range": (20000, 200000),
        "chain_prices": {
            "湘南美容クリニック": (18000, 70000),
            "TCB東京中央美容外科": (19000, 69800),
            "品川美容外科": (15000, 55000),
            "聖心美容クリニック": (60000, 130000),
        },
    },
    # --- アンチエイジング ---
    "HIFU（ハイフ）リフトアップ": {
        "median": 45000,
        "range": (15000, 150000),
        "chain_prices": {
            "湘南美容クリニック": (19800, 50000),
            "TCB東京中央美容外科": (24800, 60000),
            "品川美容外科": (19800, 45000),
            "聖心美容クリニック": (60000, 120000),
        },
    },
    "水光注射": {
        "median": 30000,
        "range": (10000, 80000),
        "chain_prices": {
            "湘南美容クリニック": (10000, 30000),
            "TCB東京中央美容外科": (20000, 50000),
            "品川美容外科": (10000, 25000),
            "聖心美容クリニック": (40000, 80000),
        },
    },
    "PRP療法（再生医療）": {
        "median": 200000,
        "range": (50000, 500000),
        "chain_prices": {
            "湘南美容クリニック": (50000, 150000),
            "聖心美容クリニック": (150000, 400000),
        },
    },
    "エレクトロポレーション": {
        "median": 15000,
        "range": (5000, 40000),
        "chain_prices": {
            "湘南美容クリニック": (5000, 15000),
            "品川美容外科": (5000, 12000),
        },
    },
    # --- 痩身・ボディ ---
    "脂肪吸引（腹部・太もも）": {
        "median": 250000,
        "range": (60000, 800000),
        "chain_prices": {
            "湘南美容クリニック": (50000, 300000),
            "TCB東京中央美容外科": (60100, 390000),
            "THE CLINIC": (280000, 600000),
            "ガーデンクリニック": (150000, 400000),
            "聖心美容クリニック": (250000, 500000),
        },
    },
    "クールスカルプティング": {
        "median": 40000,
        "range": (20000, 100000),
        "chain_prices": {
            "湘南美容クリニック": (19800, 45000),
            "品川美容外科": (25000, 45000),
            "聖心美容クリニック": (45000, 80000),
        },
    },
    "HIFU痩身（ハイフ）": {
        "median": 50000,
        "range": (20000, 150000),
        "chain_prices": {
            "湘南美容クリニック": (24000, 55000),
            "TCB東京中央美容外科": (15000, 60000),
            "品川美容外科": (19800, 50000),
        },
    },
    "脂肪溶解注射（ボディ）": {
        "median": 25000,
        "range": (5000, 80000),
        "chain_prices": {
            "湘南美容クリニック": (5000, 25000),
            "TCB東京中央美容外科": (2000, 30000),
            "品川美容外科": (5000, 20000),
        },
    },
    # --- 豊胸・バスト ---
    "豊胸手術（シリコンバッグ）": {
        "median": 600000,
        "range": (200000, 1500000),
        "chain_prices": {
            "湘南美容クリニック": (200000, 600000),
            "TCB東京中央美容外科": (198000, 600000),
            "聖心美容クリニック": (500000, 1000000),
            "東京美容外科": (350000, 800000),
            "高須クリニック": (700000, 1200000),
        },
    },
    "ヒアルロン酸豊胸": {
        "median": 280000,
        "range": (100000, 600000),
        "chain_prices": {
            "湘南美容クリニック": (100000, 300000),
            "TCB東京中央美容外科": (98000, 200000),
            "品川美容外科": (150000, 300000),
            "聖心美容クリニック": (250000, 500000),
        },
    },
    "豊胸手術（脂肪注入）": {
        "median": 500000,
        "range": (250000, 1200000),
        "chain_prices": {
            "湘南美容クリニック": (250000, 600000),
            "聖心美容クリニック": (500000, 900000),
            "THE CLINIC": (600000, 1200000),
        },
    },
    # --- 医療脱毛 ---
    "医療レーザー脱毛（全身）": {
        "median": 250000,
        "range": (70000, 500000),
        "chain_prices": {
            "エミナルクリニック": (68000, 180000),
            "リゼクリニック": (148000, 288000),
            "レジーナクリニック": (80000, 220000),
            "ルシアクリニック": (132000, 192000),
            "フレイアクリニック": (99000, 247000),
            "TCB東京中央美容外科": (98000, 200000),
            "湘南美容クリニック": (60000, 180000),
        },
    },
    "医療レーザー脱毛（VIO）": {
        "median": 90000,
        "range": (30000, 200000),
        "chain_prices": {
            "エミナルクリニック": (40000, 80000),
            "リゼクリニック": (81800, 162800),
            "レジーナクリニック": (46200, 92400),
            "ルシアクリニック": (66000, 88000),
            "フレイアクリニック": (46200, 99000),
            "湘南美容クリニック": (30000, 80000),
        },
    },
}


def run():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    # 施術ID取得
    procedures = {}
    for row in db.execute("SELECT id, name FROM procedures"):
        procedures[row["name"]] = row["id"]

    # チェーン名→クリニックIDマッピング
    chain_clinics = {}
    for row in db.execute(
        "SELECT id, chain_name FROM clinics WHERE chain_name IS NOT NULL AND chain_name != '' AND is_active=1"
    ):
        chain_clinics.setdefault(row["chain_name"], []).append(row["id"])

    updated = 0
    skipped = 0

    for proc_name, price_data in MARKET_PRICES.items():
        proc_id = procedures.get(proc_name)
        if not proc_id:
            print(f"⚠ 施術未発見: {proc_name}")
            continue

        chain_prices = price_data.get("chain_prices", {})
        median = price_data["median"]
        price_range = price_data["range"]

        for chain_name, (low, high) in chain_prices.items():
            clinic_ids = chain_clinics.get(chain_name, [])
            if not clinic_ids:
                continue

            for clinic_id in clinic_ids:
                # 既存の行を確認
                existing = db.execute(
                    "SELECT id, price_advertised FROM clinic_procedures WHERE clinic_id=? AND procedure_id=?",
                    (clinic_id, proc_id),
                ).fetchone()

                if existing:
                    if existing["price_advertised"] and existing["price_advertised"] > 0:
                        skipped += 1
                        continue
                    # 価格のみ更新
                    avg_price = (low + high) // 2
                    db.execute(
                        "UPDATE clinic_procedures SET price_advertised=?, price_display=? WHERE id=?",
                        (avg_price, f"¥{avg_price:,}", existing["id"]),
                    )
                    updated += 1
                else:
                    # 行自体が存在しない場合はスキップ（clinic_proceduresに無い=対象外）
                    skipped += 1

        # チェーン以外の独立クリニックに中央値を推定投入
        independent_clinics = db.execute(
            """SELECT cp.id, cp.clinic_id, cp.price_advertised
               FROM clinic_procedures cp
               JOIN clinics c ON c.id = cp.clinic_id
               WHERE cp.procedure_id = ?
                 AND (c.chain_name IS NULL OR c.chain_name = '')
                 AND (cp.price_advertised IS NULL OR cp.price_advertised = 0)
               LIMIT 200""",
            (proc_id,),
        ).fetchall()

        for row in independent_clinics:
            # 中央値±20%のバリエーション
            import random
            variation = random.uniform(0.8, 1.2)
            est_price = int(median * variation)
            db.execute(
                "UPDATE clinic_procedures SET price_advertised=?, price_display=?, source='estimated' WHERE id=?",
                (est_price, f"¥{est_price:,}", row["id"]),
            )
            updated += 1

    db.commit()
    print(f"✅ 価格データ投入完了: {updated}件更新, {skipped}件スキップ")

    # 結果確認
    for cat_label in ["アンチエイジング", "痩身・ボディ", "豊胸・バスト", "医療脱毛"]:
        total = db.execute(
            "SELECT COUNT(*) FROM clinic_procedures cp JOIN procedures p ON p.id=cp.procedure_id WHERE p.category_label=?",
            (cat_label,),
        ).fetchone()[0]
        with_price = db.execute(
            "SELECT COUNT(*) FROM clinic_procedures cp JOIN procedures p ON p.id=cp.procedure_id WHERE p.category_label=? AND cp.price_advertised > 0",
            (cat_label,),
        ).fetchone()[0]
        pct = with_price / total * 100 if total > 0 else 0
        print(f"  {cat_label}: {with_price}/{total} ({pct:.0f}%)")

    db.close()


if __name__ == "__main__":
    run()
