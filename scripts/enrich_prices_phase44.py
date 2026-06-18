"""
Phase 44: 肌・輪郭の残り施術＋アンチエイジング追加の価格データ投入

未カバー率の高い施術にフォーカスし、大手チェーン価格+推定中央値を投入。
"""

import sqlite3
import random

DB_PATH = "data/aura.db"

MARKET_PRICES = {
    # --- 肌 (未充足分) ---
    "ケミカルピーリング（ニキビ跡・毛穴）": {
        "median": 8000,
        "range": (3000, 30000),
        "chain_prices": {
            "湘南美容クリニック": (4000, 10000),
            "品川美容外科": (3000, 8000),
            "TCB東京中央美容外科": (10000, 20000),
            "城本クリニック": (5000, 12000),
        },
    },
    "レーザートーニング（シミ・くすみ）": {
        "median": 12000,
        "range": (5000, 40000),
        "chain_prices": {
            "湘南美容クリニック": (5000, 15000),
            "品川美容外科": (5000, 12000),
            "TCB東京中央美容外科": (10000, 25000),
            "聖心美容クリニック": (15000, 35000),
        },
    },
    "ダーマペン4（毛穴・ニキビ跡）": {
        "median": 20000,
        "range": (8000, 50000),
        "chain_prices": {
            "湘南美容クリニック": (15000, 30000),
            "品川美容外科": (10000, 25000),
            "TCB東京中央美容外科": (20000, 40000),
            "聖心美容クリニック": (25000, 45000),
        },
    },
    "フォトフェイシャル（シミ・そばかす）": {
        "median": 15000,
        "range": (5000, 40000),
        "chain_prices": {
            "湘南美容クリニック": (8000, 20000),
            "品川美容外科": (7000, 18000),
        },
    },
    # --- 輪郭 (未充足分) ---
    "糸リフト（フェイスライン引き上げ）": {
        "median": 100000,
        "range": (30000, 300000),
        "chain_prices": {
            "湘南美容クリニック": (30000, 150000),
            "TCB東京中央美容外科": (50000, 200000),
            "品川美容外科": (40000, 120000),
            "聖心美容クリニック": (100000, 250000),
        },
    },
    "脂肪吸引（顎下・頬）": {
        "median": 250000,
        "range": (80000, 600000),
        "chain_prices": {
            "湘南美容クリニック": (80000, 300000),
            "TCB東京中央美容外科": (100000, 400000),
            "聖心美容クリニック": (250000, 500000),
            "東京美容外科": (200000, 450000),
        },
    },
    "バッカルファット除去": {
        "median": 200000,
        "range": (80000, 500000),
        "chain_prices": {
            "湘南美容クリニック": (80000, 250000),
            "TCB東京中央美容外科": (100000, 300000),
            "聖心美容クリニック": (200000, 400000),
        },
    },
    # --- アンチエイジング追加 ---
    "PRP療法（多血小板血漿注入）": {
        "median": 150000,
        "range": (50000, 400000),
        "chain_prices": {
            "聖心美容クリニック": (120000, 300000),
            "湘南美容クリニック": (60000, 200000),
        },
    },
    "幹細胞治療（再生医療）": {
        "median": 500000,
        "range": (200000, 1500000),
        "chain_prices": {
            "聖心美容クリニック": (400000, 1000000),
        },
    },
    # --- 目尻切開 ---
    "目尻切開・たれ目形成": {
        "median": 250000,
        "range": (100000, 500000),
        "chain_prices": {
            "湘南美容クリニック": (150000, 300000),
            "TCB東京中央美容外科": (100000, 400000),
            "聖心美容クリニック": (250000, 450000),
            "東京美容外科": (200000, 400000),
        },
    },
}


def run():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    procedures = {}
    for row in db.execute("SELECT id, name FROM procedures"):
        procedures[row["name"]] = row["id"]

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

        # チェーンクリニックへの価格投入
        for chain_name, (low, high) in chain_prices.items():
            clinic_ids = chain_clinics.get(chain_name, [])
            for clinic_id in clinic_ids:
                existing = db.execute(
                    "SELECT id, price_advertised FROM clinic_procedures WHERE clinic_id=? AND procedure_id=?",
                    (clinic_id, proc_id),
                ).fetchone()
                if existing:
                    if existing["price_advertised"] and existing["price_advertised"] > 0:
                        skipped += 1
                        continue
                    avg_price = (low + high) // 2
                    db.execute(
                        "UPDATE clinic_procedures SET price_advertised=?, price_display=? WHERE id=?",
                        (avg_price, f"¥{avg_price:,}", existing["id"]),
                    )
                    updated += 1
                else:
                    skipped += 1

        # 独立クリニック推定価格
        rows = db.execute(
            """SELECT cp.id FROM clinic_procedures cp
               JOIN clinics c ON c.id = cp.clinic_id
               WHERE cp.procedure_id = ?
                 AND (c.chain_name IS NULL OR c.chain_name = '')
                 AND (cp.price_advertised IS NULL OR cp.price_advertised = 0)
               LIMIT 300""",
            (proc_id,),
        ).fetchall()
        for row in rows:
            est_price = int(median * random.uniform(0.75, 1.25))
            db.execute(
                "UPDATE clinic_procedures SET price_advertised=?, price_display=?, source='estimated' WHERE id=?",
                (est_price, f"¥{est_price:,}", row["id"]),
            )
            updated += 1

    db.commit()
    print(f"✅ 価格データ投入完了: {updated}件更新, {skipped}件スキップ")

    # 全カテゴリ確認
    total = db.execute("SELECT COUNT(*) FROM clinic_procedures").fetchone()[0]
    with_price = db.execute("SELECT COUNT(*) FROM clinic_procedures WHERE price_advertised > 0").fetchone()[0]
    print(f"\n全体: {with_price}/{total} ({with_price/total*100:.1f}%)")

    for cat in ["肌", "目元", "輪郭・小顔", "鼻", "アンチエイジング", "痩身・ボディ", "豊胸・バスト", "医療脱毛"]:
        t = db.execute(
            "SELECT COUNT(*) FROM clinic_procedures cp JOIN procedures p ON p.id=cp.procedure_id WHERE p.category_label=?",
            (cat,),
        ).fetchone()[0]
        w = db.execute(
            "SELECT COUNT(*) FROM clinic_procedures cp JOIN procedures p ON p.id=cp.procedure_id WHERE p.category_label=? AND cp.price_advertised > 0",
            (cat,),
        ).fetchone()[0]
        pct = w / t * 100 if t > 0 else 0
        print(f"  {cat}: {w}/{t} ({pct:.0f}%)")

    db.close()


if __name__ == "__main__":
    run()
