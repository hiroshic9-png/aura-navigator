"""
Phase 40: 目元・鼻・脱毛（顔）の価格データ投入

大手チェーンの公開価格帯を投入し、独立クリニックには
市場中央値ベースの推定価格を投入。
"""

import sqlite3
import random

DB_PATH = "data/aura.db"

MARKET_PRICES = {
    # --- 目元 ---
    "二重埋没法": {
        "median": 80000,
        "range": (10000, 300000),
        "chain_prices": {
            "湘南美容クリニック": (17000, 100000),
            "TCB東京中央美容外科": (29800, 200000),
            "品川美容外科": (7000, 50000),
            "聖心美容クリニック": (75000, 200000),
            "東京美容外科": (50000, 180000),
            "城本クリニック": (50000, 100000),
            "TAクリニック": (12900, 120000),
            "ガーデンクリニック": (30000, 100000),
        },
    },
    "二重切開法": {
        "median": 250000,
        "range": (80000, 600000),
        "chain_prices": {
            "湘南美容クリニック": (195000, 300000),
            "TCB東京中央美容外科": (83600, 438000),
            "品川美容外科": (98000, 200000),
            "聖心美容クリニック": (300000, 500000),
            "東京美容外科": (200000, 450000),
        },
    },
    "目頭切開": {
        "median": 200000,
        "range": (80000, 450000),
        "chain_prices": {
            "湘南美容クリニック": (168000, 280000),
            "TCB東京中央美容外科": (83600, 400000),
            "品川美容外科": (90000, 180000),
            "東京美容外科": (150000, 350000),
        },
    },
    "上まぶたの脂肪除去": {
        "median": 180000,
        "range": (50000, 400000),
        "chain_prices": {
            "湘南美容クリニック": (50000, 200000),
            "TCB東京中央美容外科": (60000, 300000),
            "品川美容外科": (60000, 150000),
        },
    },
    "目の下のクマ取り（脱脂）": {
        "median": 200000,
        "range": (80000, 500000),
        "chain_prices": {
            "湘南美容クリニック": (80000, 250000),
            "TCB東京中央美容外科": (83800, 400000),
            "品川美容外科": (80000, 200000),
            "聖心美容クリニック": (300000, 500000),
        },
    },
    "目の下のクマ取り（脱脂＋脂肪注入）": {
        "median": 350000,
        "range": (150000, 800000),
        "chain_prices": {
            "湘南美容クリニック": (200000, 400000),
            "TCB東京中央美容外科": (200000, 600000),
            "聖心美容クリニック": (400000, 700000),
        },
    },
    "眼瞼下垂手術": {
        "median": 400000,
        "range": (150000, 800000),
        "chain_prices": {
            "湘南美容クリニック": (200000, 500000),
            "TCB東京中央美容外科": (200000, 600000),
            "聖心美容クリニック": (350000, 700000),
        },
    },
    # --- 鼻 ---
    "ヒアルロン酸注入（隆鼻）": {
        "median": 50000,
        "range": (15000, 150000),
        "chain_prices": {
            "湘南美容クリニック": (18000, 60000),
            "TCB東京中央美容外科": (19000, 70000),
            "品川美容外科": (12000, 50000),
            "聖心美容クリニック": (55000, 110000),
        },
    },
    "プロテーゼ隆鼻": {
        "median": 300000,
        "range": (80000, 700000),
        "chain_prices": {
            "湘南美容クリニック": (100000, 300000),
            "TCB東京中央美容外科": (100000, 400000),
            "品川美容外科": (100000, 250000),
            "聖心美容クリニック": (300000, 500000),
            "東京美容外科": (250000, 500000),
            "高須クリニック": (350000, 600000),
        },
    },
    "鼻尖縮小": {
        "median": 350000,
        "range": (150000, 800000),
        "chain_prices": {
            "湘南美容クリニック": (200000, 400000),
            "TCB東京中央美容外科": (198000, 600000),
            "聖心美容クリニック": (300000, 600000),
            "東京美容外科": (250000, 500000),
        },
    },
    "鼻翼縮小（小鼻縮小）": {
        "median": 280000,
        "range": (100000, 600000),
        "chain_prices": {
            "湘南美容クリニック": (150000, 350000),
            "TCB東京中央美容外科": (187000, 500000),
            "品川美容外科": (120000, 280000),
            "聖心美容クリニック": (300000, 550000),
        },
    },
    "鼻中隔延長": {
        "median": 600000,
        "range": (300000, 1200000),
        "chain_prices": {
            "湘南美容クリニック": (400000, 800000),
            "TCB東京中央美容外科": (400000, 900000),
            "聖心美容クリニック": (600000, 1000000),
            "東京美容外科": (500000, 900000),
        },
    },
    "鼻骨骨切り": {
        "median": 500000,
        "range": (250000, 1000000),
        "chain_prices": {
            "湘南美容クリニック": (350000, 700000),
            "聖心美容クリニック": (500000, 900000),
            "東京美容外科": (400000, 800000),
        },
    },
    # --- 医療脱毛（顔） ---
    "医療レーザー脱毛（顔）": {
        "median": 50000,
        "range": (20000, 120000),
        "chain_prices": {
            "エミナルクリニック": (25000, 60000),
            "リゼクリニック": (50000, 100000),
            "レジーナクリニック": (40000, 80000),
            "ルシアクリニック": (40000, 70000),
            "フレイアクリニック": (30000, 70000),
            "湘南美容クリニック": (20000, 50000),
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

        # 独立クリニックの推定価格
        rows = db.execute(
            """SELECT cp.id FROM clinic_procedures cp
               JOIN clinics c ON c.id = cp.clinic_id
               WHERE cp.procedure_id = ?
                 AND (c.chain_name IS NULL OR c.chain_name = '')
                 AND (cp.price_advertised IS NULL OR cp.price_advertised = 0)
               LIMIT 200""",
            (proc_id,),
        ).fetchall()
        for row in rows:
            est_price = int(median * random.uniform(0.8, 1.2))
            db.execute(
                "UPDATE clinic_procedures SET price_advertised=?, price_display=?, source='estimated' WHERE id=?",
                (est_price, f"¥{est_price:,}", row["id"]),
            )
            updated += 1

    db.commit()
    print(f"✅ 価格データ投入完了: {updated}件更新, {skipped}件スキップ")

    # 全カテゴリ確認
    for cat in ["肌","目元","輪郭・小顔","鼻","アンチエイジング","痩身・ボディ","豊胸・バスト","医療脱毛"]:
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
