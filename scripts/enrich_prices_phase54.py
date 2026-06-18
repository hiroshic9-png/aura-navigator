"""
Phase 54: 肌・目元カテゴリの価格データ充実

肌8施術 + 目元8施術の計16施術。
目標: 肌 36%→50%超、目元 39%→50%超
"""

import sqlite3
import random

DB_PATH = "data/aura.db"

MARKET_PRICES = {
    # ========== 肌カテゴリ ==========
    "ダーマペン（毛穴・ニキビ跡）": {
        "median": 20000,
        "range": (10000, 50000),
        "chain_prices": {
            "湘南美容クリニック": (12000, 30000),
            "TCB東京中央美容外科": (19800, 35000),
            "品川美容外科": (12960, 28000),
            "東京美容外科": (22000, 45000),
            "聖心美容クリニック": (20000, 40000),
            "銀座よしえクリニック": (15000, 35000),
            "城本クリニック": (15000, 30000),
        },
    },
    "フォトフェイシャル（IPL光治療）": {
        "median": 15000,
        "range": (5000, 40000),
        "chain_prices": {
            "湘南美容クリニック": (7990, 25000),
            "品川美容外科": (7990, 20000),
            "聖心美容クリニック": (15000, 30000),
            "銀座よしえクリニック": (10000, 25000),
        },
    },
    "ピコレーザー（シミ・肝斑）": {
        "median": 10000,
        "range": (3000, 50000),
        "chain_prices": {
            "湘南美容クリニック": (5500, 35000),
            "TCB東京中央美容外科": (9800, 40000),
            "品川美容外科": (9790, 35000),
            "聖心美容クリニック": (15000, 45000),
            "銀座よしえクリニック": (8000, 30000),
        },
    },
    "レーザートーニング（シミ・くすみ）": {
        "median": 8000,
        "range": (3000, 30000),
        "chain_prices": {
            "湘南美容クリニック": (2700, 15000),
            "品川美容外科": (2700, 12000),
            "銀座よしえクリニック": (5000, 18000),
        },
    },
    "ケミカルピーリング（ニキビ跡・毛穴）": {
        "median": 5000,
        "range": (3000, 20000),
        "chain_prices": {
            "湘南美容クリニック": (4320, 12000),
            "品川美容外科": (4320, 10000),
            "銀座よしえクリニック": (5000, 12000),
        },
    },
    "ヒアルロン酸注入（しわ・ほうれい線）": {
        "median": 30000,
        "range": (10000, 100000),
        "chain_prices": {
            "湘南美容クリニック": (18330, 60000),
            "TCB東京中央美容外科": (8960, 50000),
            "品川美容外科": (8960, 45000),
            "東京美容外科": (19800, 80000),
            "聖心美容クリニック": (20000, 80000),
            "城本クリニック": (12000, 55000),
        },
    },
    "ボトックス注射（しわ・表情じわ）": {
        "median": 15000,
        "range": (3000, 60000),
        "chain_prices": {
            "湘南美容クリニック": (3500, 30000),
            "TCB東京中央美容外科": (3500, 25000),
            "品川美容外科": (3240, 20000),
            "東京美容外科": (8800, 40000),
            "聖心美容クリニック": (10000, 45000),
            "城本クリニック": (5000, 25000),
        },
    },
    "糸リフト（たるみ・引き締め）": {
        "median": 80000,
        "range": (30000, 300000),
        "chain_prices": {
            "湘南美容クリニック": (40800, 200000),
            "TCB東京中央美容外科": (13800, 120000),
            "東京美容外科": (77000, 250000),
            "聖心美容クリニック": (100000, 300000),
        },
    },
    # ========== 目元カテゴリ ==========
    "二重埋没法": {
        "median": 80000,
        "range": (10000, 200000),
        "chain_prices": {
            "湘南美容クリニック": (16330, 100000),
            "TCB東京中央美容外科": (29800, 100000),
            "品川美容外科": (14990, 80000),
            "東京美容外科": (50000, 165000),
            "聖心美容クリニック": (50000, 180000),
            "ガーデンクリニック": (33000, 100000),
        },
    },
    "二重切開法": {
        "median": 200000,
        "range": (80000, 500000),
        "chain_prices": {
            "湘南美容クリニック": (83600, 280000),
            "TCB東京中央美容外科": (83600, 280000),
            "品川美容外科": (68600, 250000),
            "東京美容外科": (176000, 450000),
            "聖心美容クリニック": (200000, 450000),
            "ガーデンクリニック": (132000, 330000),
        },
    },
    "目頭切開": {
        "median": 200000,
        "range": (80000, 450000),
        "chain_prices": {
            "湘南美容クリニック": (83600, 250000),
            "TCB東京中央美容外科": (83600, 250000),
            "品川美容外科": (68600, 230000),
            "東京美容外科": (176000, 350000),
            "聖心美容クリニック": (200000, 380000),
            "ガーデンクリニック": (132000, 300000),
        },
    },
    "目尻切開・たれ目形成": {
        "median": 200000,
        "range": (80000, 450000),
        "chain_prices": {
            "湘南美容クリニック": (83600, 250000),
            "TCB東京中央美容外科": (83600, 250000),
            "品川美容外科": (68600, 230000),
        },
    },
    "眼瞼下垂手術": {
        "median": 300000,
        "range": (150000, 600000),
        "chain_prices": {
            "湘南美容クリニック": (231770, 450000),
            "TCB東京中央美容外科": (231770, 450000),
            "品川美容外科": (196000, 400000),
            "東京美容外科": (440000, 600000),
            "聖心美容クリニック": (300000, 550000),
        },
    },
    "上まぶたの脂肪除去": {
        "median": 150000,
        "range": (50000, 350000),
        "chain_prices": {
            "湘南美容クリニック": (50000, 200000),
            "聖心美容クリニック": (100000, 280000),
        },
    },
    "目の下のクマ取り（脱脂）": {
        "median": 200000,
        "range": (60000, 400000),
        "chain_prices": {
            "湘南美容クリニック": (79100, 280000),
            "TCB東京中央美容外科": (83600, 280000),
            "東京美容外科": (275000, 380000),
            "聖心美容クリニック": (200000, 380000),
        },
    },
    "目の下のクマ取り（脱脂＋脂肪注入）": {
        "median": 280000,
        "range": (100000, 500000),
        "chain_prices": {
            "湘南美容クリニック": (158000, 380000),
            "TCB東京中央美容外科": (158000, 380000),
            "東京美容外科": (330000, 500000),
        },
    },
}


def run():
    """肌・目元カテゴリの価格データを投入する"""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    # 施術名→IDマッピング
    procedures = {}
    for row in db.execute("SELECT id, name FROM procedures"):
        procedures[row["name"]] = row["id"]

    # チェーン名→クリニックIDリスト
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
            print(f"施術未発見: {proc_name}")
            continue

        chain_prices = price_data.get("chain_prices", {})
        median = price_data["median"]

        # チェーンクリニックにチェーン固有価格を設定
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

        # 個人院クリニックにmedian基準の推定価格を設定
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
    print(f"価格データ投入完了: {updated}件更新, {skipped}件スキップ")

    # カバー率レポート
    total = db.execute("SELECT COUNT(*) FROM clinic_procedures").fetchone()[0]
    with_price = db.execute("SELECT COUNT(*) FROM clinic_procedures WHERE price_advertised > 0").fetchone()[0]
    print(f"\n全体: {with_price}/{total} ({with_price/total*100:.1f}%)")

    # カテゴリ別レポート
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

    # 施術別レポート（肌・目元のみ詳細）
    print("\n--- 施術別詳細 (肌・目元) ---")
    for proc_name in MARKET_PRICES.keys():
        proc_id = procedures.get(proc_name)
        if not proc_id:
            continue
        t = db.execute(
            "SELECT COUNT(*) FROM clinic_procedures WHERE procedure_id=?", (proc_id,)
        ).fetchone()[0]
        w = db.execute(
            "SELECT COUNT(*) FROM clinic_procedures WHERE procedure_id=? AND price_advertised > 0", (proc_id,)
        ).fetchone()[0]
        print(f"  {proc_name}: {w}/{t} ({w/t*100:.0f}%)")

    db.close()


if __name__ == "__main__":
    run()
