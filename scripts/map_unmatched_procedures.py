"""
AURA MVP — 未マッチ施術名のマッピングスクリプト

case_photosテーブルでprocedure_idがNULLのレコードを、
SBC独自の商品名→既存の施術マスタ（procedures）へマッピングする。
"""

import sqlite3
import sys

# SBC独自商品名 → 既存procedures.id のマッピング辞書
# 美容医療の知識に基づいて対応付け
PROCEDURE_NAME_MAPPING = {
    # ===== 目元 (eye) =====
    "二重埋没": "01KSCWA1GA891CD09NZPTQKS47",  # 二重埋没法
    "二重術ナチュラル法": "01KSCWA1GA891CD09NZPTQKS47",  # 二重埋没法（SBC商品名）
    "二重術エバーナチュラル法": "01KSCWA1GA891CD09NZPTQKS47",  # 二重埋没法（SBC商品名）
    "二重術クイック法": "01KSCWA1GA891CD09NZPTQKS47",  # 二重埋没法（SBC商品名）
    "挙筋前転法": "01KSCWA1GC54VA703ZH40J3KZJ",  # 眼瞼下垂手術
    "眉下切開": "01KSCWA1GC54VA703ZH40J3KZJ",  # 眼瞼下垂手術（近似）
    "スーパーナチュラル眉下リフト": "01KSCWA1GC54VA703ZH40J3KZJ",  # 眼瞼下垂手術（SBC商品名）
    "グラマラスライン形成": "01KSCWA1GC54VA703ZH40J3KZH",  # 目尻切開・たれ目形成
    "スーパーナチュラル目の下のたるみ取りロング": "01KSCWA1GC54VA703ZH40J3KZM",  # 目の下のクマ取り（脱脂）
    "スーパーナチュラル目の上のたるみ取りロング": "01KSCWA1GC54VA703ZH40J3KZM",  # 目の下のクマ取り（近似）
    "プレミアム目の下のたるみ取り": "01KSCWA1GC54VA703ZH40J3KZM",  # 目の下のクマ取り（脱脂）
    "美肌アモーレ": "01KSCWA1GA891CD09NZPTQKS47",  # 二重埋没法（SBC美容糸法）

    # ===== 鼻 (nose) =====
    "フレックス・ノーズ": "01KSCWA1GC54VA703ZH40J3KZR",  # 鼻尖縮小（SBC商品名）
    "1day鼻先縮小": "01KSCWA1GC54VA703ZH40J3KZR",  # 鼻尖縮小
    "1day鼻先縮小ハイパー": "01KSCWA1GC54VA703ZH40J3KZR",  # 鼻尖縮小
    "チャウムプレミアム": "01KSCWA1GC54VA703ZH40J3KZQ",  # プロテーゼ隆鼻（SBC商品名）
    "アゴ修整": "01KSCWA1GQH6KC0QNGYM6370EH",  # ヒアルロン酸注入（あご形成）（近似）
    "ワシ鼻修整": "01KSCWA1GD937YVYH392KG47ZB",  # 鼻翼縮小（近似: 鼻整形カテゴリ）

    # ===== 肌 (skin) =====
    "レスチレン®リド": "01KSCWA1GHDNQ3TRAPX7NHYWV0",  # ヒアルロン酸注入（しわ・ほうれい線）
    "レスチレン®リフト™リド": "01KSCWA1GHDNQ3TRAPX7NHYWV0",  # ヒアルロン酸注入（しわ・ほうれい線）
    "リデンシティⅡ": "01KSCWA1GHDNQ3TRAPX7NHYWV0",  # ヒアルロン酸注入（しわ・ほうれい線）
    "ジュビダームビスタ®ウルトラXC": "01KSCWA1GHDNQ3TRAPX7NHYWV0",  # ヒアルロン酸注入
    "ジュビダームビスタ®ウルトラプラスXC": "01KSCWA1GHDNQ3TRAPX7NHYWV0",  # ヒアルロン酸注入
    "ジュビダームビスタ®ボリフトXC": "01KSCWA1GHDNQ3TRAPX7NHYWV0",  # ヒアルロン酸注入
    "ジュビダームビスタ®ボリューマ": "01KSCWA1GHDNQ3TRAPX7NHYWV0",  # ヒアルロン酸注入
    "Qスイッチヤグレーザー": "01KSCWA1GD937YVYH392KG47ZE",  # レーザートーニング（シミ・くすみ）
    "ピコスポット": "01KSCWA1GD937YVYH392KG47ZF",  # ピコレーザー（シミ・肝斑）
    "ケミカルピーリング": "01KSCWA1GD937YVYH392KG47ZH",  # ケミカルピーリング
    "ダーマペン": "01KSCWA1GEJM5BH550AGQ9TSZ7",  # ダーマペン（毛穴・ニキビ跡）
    "ポテンツァ": "01KSCWA1GEJM5BH550AGQ9TSZ7",  # ダーマペン（近似: マイクロニードル系）
    "ヴェルヴェットスキン": "01KSCWA1GEJM5BH550AGQ9TSZ7",  # ダーマペン+ピーリング（近似）
    "サブシジョン・肌育注射（ジュベルックなど）": "01KSCWA1GEJM5BH550AGQ9TSZ7",  # ダーマペン（近似）
    "コアトックス®": "01KSCWA1GKV3QNW4FZ2VG6GBPA",  # ボトックス注射（韓国製ボツリヌストキシン）
    "肩こり・肩痩せボツリヌス注射": "01KSCWA1GKV3QNW4FZ2VG6GBPA",  # ボトックス注射
    "ホワイトニング": "01KSCWA1GD937YVYH392KG47ZE",  # レーザートーニング（近似: 美白系）
    "うるおい注射": "01KSJ4PQSF2PH7FAHPQQJ59KCM",  # 水光注射（SBC商品名）
    "エリシスセンス": "01KSJ4PQSF2PH7FAHPQQJ59KCM",  # 水光注射（RF系美肌機器）
    "イソトレチノイン治療": None,  # 内服薬治療 — マスタに該当なし、スキップ
    "セラミック": None,  # 歯科系 — マスタに該当なし、スキップ
    "ホワイトニング（歯）": None,  # 歯科系
    "メディカル髪育注射": None,  # 発毛治療 — マスタに該当なし、スキップ

    # ===== 輪郭 (contour) =====
    "1日脂肪取り®顔やせ": "01KSCWA1GNPXSWDQXR3WYGBEPG",  # 脂肪溶解注射（二重あご・フェイスライン）
    "あご下筋肉縛り": "01KSCWA1GX0RKTRTAT35DRE00V",  # 脂肪吸引（顎下・頬）（近似）
    "ダブロGOLD": "01KSJ4PQSF2PH7FAHPQQJ59KCJ",  # HIFU（ハイフ）リフトアップ

    # ===== エイジング (anti_aging) =====
    "1dayリフト": "01KSCWA1GKV3QNW4FZ2VG6GBPB",  # 糸リフト（たるみ・引き締め）
    "切開リフト": "01KSCWA1GX0RKTRTAT35DRE00W",  # 糸リフト（フェイスライン引き上げ）（近似: リフト系）
}

# コンマ区切りの複合施術名を処理するためのヘルパー
def resolve_procedure_id(procedure_name: str) -> str | None:
    """施術名からprocedure_idを解決する。複合名（カンマ区切り）は最初のマッチを使用。"""
    # 完全一致
    if procedure_name in PROCEDURE_NAME_MAPPING:
        return PROCEDURE_NAME_MAPPING[procedure_name]

    # カンマ区切りの場合、最初の要素でマッチ
    if "," in procedure_name:
        parts = [p.strip() for p in procedure_name.split(",")]
        for part in parts:
            if part in PROCEDURE_NAME_MAPPING:
                return PROCEDURE_NAME_MAPPING[part]

    return None


def main():
    """未マッチのcase_photosにprocedure_idを設定する"""
    db_path = "data/aura.db"
    conn = sqlite3.connect(db_path)

    # 未マッチのcase_photosを取得
    cur = conn.execute("""
        SELECT id, procedure_name
        FROM case_photos
        WHERE procedure_id IS NULL
          AND procedure_name IS NOT NULL
          AND procedure_name != ''
          AND is_active = 1
    """)
    unmatched = cur.fetchall()
    print(f"未マッチのcase_photos: {len(unmatched)}件")

    # マッピング実行
    matched_count = 0
    skipped_count = 0
    no_mapping_count = 0
    no_mapping_names = set()

    for photo_id, procedure_name in unmatched:
        proc_id = resolve_procedure_id(procedure_name)
        if proc_id is None:
            # マッピング辞書にNoneが明示的に設定されている場合はスキップ
            if procedure_name in PROCEDURE_NAME_MAPPING:
                skipped_count += 1
            else:
                no_mapping_count += 1
                no_mapping_names.add(procedure_name)
            continue

        conn.execute(
            "UPDATE case_photos SET procedure_id = ? WHERE id = ?",
            (proc_id, photo_id),
        )
        matched_count += 1

    conn.commit()

    # 結果の統計
    print(f"\n=== マッピング結果 ===")
    print(f"マッチ成功: {matched_count}件")
    print(f"マスタ外（スキップ）: {skipped_count}件")
    print(f"マッピング未定義: {no_mapping_count}件")

    if no_mapping_names:
        print(f"\n--- マッピング未定義の施術名 ---")
        for name in sorted(no_mapping_names):
            count = sum(1 for _, pn in unmatched if pn == name)
            print(f"  {count:3d}件  {name}")

    # 最終統計
    total = conn.execute("SELECT COUNT(*) FROM case_photos WHERE is_active = 1").fetchone()[0]
    linked = conn.execute(
        "SELECT COUNT(*) FROM case_photos WHERE is_active = 1 AND procedure_id IS NOT NULL"
    ).fetchone()[0]
    print(f"\n=== 全体統計 ===")
    print(f"アクティブ症例写真: {total}件")
    print(f"施術ID紐付済: {linked}件 ({linked/total*100:.1f}%)")
    print(f"未紐付: {total - linked}件 ({(total-linked)/total*100:.1f}%)")

    conn.close()


if __name__ == "__main__":
    main()
