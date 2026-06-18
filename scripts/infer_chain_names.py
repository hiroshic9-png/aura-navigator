"""
AURA MVP — チェーン名推定スクリプト

クリニック名のパターンマッチングで大手チェーンを自動推定し、
chain_nameカラムに設定する。
"""

import sqlite3
import re

DB_PATH = "data/aura.db"

# チェーン名推定ルール（優先度順）
# (正規表現パターン, chain_name)
CHAIN_RULES = [
    # 大手チェーン
    (r"湘南美容|SBC湘南|ＳＢＣ湘南", "湘南美容クリニック"),
    (r"東京中央美容|TCB|ＴＣＢ", "TCB東京中央美容外科"),
    (r"品川美容|品川スキン", "品川美容外科"),
    (r"共立美容", "共立美容外科"),
    (r"聖心美容", "聖心美容クリニック"),
    (r"城本クリニック|城本美容", "城本クリニック"),
    (r"高須クリニック|高須美容", "高須クリニック"),
    (r"水の森美容", "水の森美容クリニック"),
    (r"ガーデンクリニック|ガーデン美容", "ガーデンクリニック"),
    (r"TAクリニック|ＴＡクリニック", "TAクリニック"),
    (r"東京美容外科", "東京美容外科"),
    (r"もとび美容", "もとび美容外科"),

    # 脱毛系チェーン
    (r"リゼクリニック|リゼ美容", "リゼクリニック"),
    (r"レジーナクリニック|レジーナ", "レジーナクリニック"),
    (r"エミナルクリニック|エミナル", "エミナルクリニック"),
    (r"フレイアクリニック|フレイア", "フレイアクリニック"),
    (r"アリシアクリニック|アリシア", "アリシアクリニック"),
    (r"じぶんクリニック", "じぶんクリニック"),
    (r"ルシアクリニック|ルシア", "ルシアクリニック"),

    # 中堅チェーン
    (r"湘南AGAクリニック", "湘南AGAクリニック"),
    (r"ABCクリニック|ＡＢＣクリニック", "ABCクリニック"),
    (r"表参道スキンクリニック", "表参道スキンクリニック"),
    (r"銀座よしえクリニック|銀座よしえ", "銀座よしえクリニック"),
    (r"シロノクリニック", "シロノクリニック"),
    (r"椿クリニック", "椿クリニック"),
    (r"大塚美容", "大塚美容形成外科"),
    (r"東京イセアクリニック|イセアクリニック", "イセアクリニック"),
    (r"ヴェリテクリニック|ヴェリテ", "ヴェリテクリニック"),
    (r"プリモ麻布十番", "プリモ麻布十番クリニック"),
    (r"グロウクリニック|GLOW", "グロウクリニック"),
    (r"セルリアンタワー", "セルリアンタワーイセアクリニック"),
    (r"B-LINE CLINIC|B-LINE|ビーラインクリニック", "B-LINEクリニック"),
    (r"銀座S美容|銀座Ｓ美容", "銀座S美容・形成外科"),
    (r"THE CLINIC|ザクリニック", "THE CLINIC"),
    (r"ザ・クリニック", "THE CLINIC"),
    (r"真崎医院|真崎クリニック", "真崎クリニック"),
    (r"id美容クリニック|id美容", "id美容クリニック"),
]


def main():
    """チェーン名を推定してDBに設定"""
    db = sqlite3.connect(DB_PATH)
    clinics = db.execute(
        "SELECT id, name FROM clinics WHERE is_active = 1"
    ).fetchall()

    updated = 0
    chain_counts = {}

    for clinic_id, name in clinics:
        for pattern, chain_name in CHAIN_RULES:
            if re.search(pattern, name):
                db.execute(
                    "UPDATE clinics SET chain_name = ? WHERE id = ?",
                    (chain_name, clinic_id)
                )
                chain_counts[chain_name] = chain_counts.get(chain_name, 0) + 1
                updated += 1
                break  # 最初にマッチしたルールを適用

    db.commit()
    db.close()

    print(f"=== チェーン名推定完了: {updated}院 ===\n")
    for chain, count in sorted(chain_counts.items(), key=lambda x: -x[1]):
        print(f"  {chain}: {count}院")
    print(f"\n個人院: {len(clinics) - updated}院")


if __name__ == "__main__":
    main()
