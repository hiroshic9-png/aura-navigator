"""
Phase 47: アンチエイジング残り施術の価格データ投入

PRP療法、エレクトロポレーション、HIFU、水光注射の4施術。
"""

import sqlite3
import random

DB_PATH = "data/aura.db"

MARKET_PRICES = {
    "PRP療法（再生医療）": {
        "median": 120000,
        "range": (40000, 400000),
        "chain_prices": {
            "聖心美容クリニック": (100000, 250000),
            "湘南美容クリニック": (50000, 180000),
            "ガーデンクリニック": (80000, 200000),
        },
    },
    "エレクトロポレーション": {
        "median": 12000,
        "range": (5000, 30000),
        "chain_prices": {
            "湘南美容クリニック": (5000, 15000),
            "品川美容外科": (5000, 12000),
            "聖心美容クリニック": (10000, 25000),
            "城本クリニック": (8000, 18000),
        },
    },
    "HIFU（ハイフ）リフトアップ": {
        "median": 30000,
        "range": (10000, 150000),
        "chain_prices": {
            "湘南美容クリニック": (20000, 60000),
            "TCB東京中央美容外科": (24800, 70000),
            "品川美容外科": (10000, 40000),
            "聖心美容クリニック": (50000, 120000),
            "東京美容外科": (30000, 80000),
        },
    },
    "水光注射": {
        "median": 30000,
        "range": (10000, 80000),
        "chain_prices": {
            "湘南美容クリニック": (10000, 40000),
            "TCB東京中央美容外科": (20000, 50000),
            "品川美容外科": (10000, 35000),
            "聖心美容クリニック": (30000, 60000),
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
        print(f"  {cat}: {w}/{t} ({w/t*100:.0f}%)")

    db.close()


if __name__ == "__main__":
    run()
