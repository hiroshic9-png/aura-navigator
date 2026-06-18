"""
AURA MVP — Phase 65: 口コミアスペクト拡充分析スクリプト

既存のaspectsデータ（service/price/skill/wait/facility）に
新たな3カテゴリ（counseling/result/aftercare）を追加分析してマージする。

キーワードマッチングでカテゴリ判定し、ポジティブ/ネガティブキーワードで
センチメント方向を決定する。既存aspectsは上書きしない（追記のみ）。

実行:
    python3 scripts/enrich_aspects_phase65.py
"""

import json
import logging
import sqlite3
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "aura.db"

# 新規追加アスペクトのキーワード定義
# ポジティブ/ネガティブを明示的に分けて定義
NEW_ASPECT_KEYWORDS: dict[str, dict[str, list[str]]] = {
    "counseling": {
        "positive": [
            "カウンセリング", "相談", "説明", "丁寧", "聴いて", "聞いて",
            "納得", "分かりやすい", "わかりやすい", "しっかり説明",
            "相談しやすい", "質問しやすい", "時間をかけて", "じっくり",
            "親身", "寄り添", "不安を解消", "安心して相談",
        ],
        "negative": [
            "圧力", "勧誘", "押し売り", "しつこい", "強引",
            "説明がない", "説明不足", "聞いてくれない", "急かされ",
            "カウンセラー任せ", "流れ作業", "話を聞かない",
            "質問できない", "断りにくい", "営業感",
        ],
    },
    "result": {
        "positive": [
            "結果", "効果", "仕上がり", "満足", "自然", "きれい", "綺麗",
            "ダウンタイム", "腫れが少", "痛みが少", "目立たない",
            "理想通り", "思い通り", "素晴らしい仕上がり", "大満足",
            "変化", "若返", "小顔", "すっきり",
        ],
        "negative": [
            "効果なし", "変化なし", "変わらない", "不自然",
            "腫れ", "痛み", "内出血", "ダウンタイムが長",
            "左右差", "失敗", "やり直し", "修正",
            "傷跡", "凹凸", "引きつり", "しこり",
        ],
    },
    "aftercare": {
        "positive": [
            "アフター", "経過", "フォロー", "検診", "保証", "再手術",
            "経過観察", "術後", "通院", "ケア",
            "アフターケアが充実", "術後のフォロー", "しっかりフォロー",
            "何かあれば", "相談できる", "安心",
        ],
        "negative": [
            "アフターケアがない", "フォローなし", "放置",
            "術後の対応が悪い", "連絡がつかない",
            "保証がない", "追加費用", "再診料",
            "経過を見てくれない", "術後放置",
        ],
    },
}

# 既存アスペクト（更新しないカテゴリ）
EXISTING_ASPECTS = {"service", "price", "skill", "wait", "facility"}


def analyze_new_aspects(text: str) -> dict[str, str]:
    """
    テキストから新規3カテゴリのアスペクトを分析

    Returns:
        検出されたアスペクトの辞書 例: {"counseling": "positive", "result": "negative"}
    """
    aspects: dict[str, str] = {}

    for aspect_name, keywords in NEW_ASPECT_KEYWORDS.items():
        pos_hits = sum(1 for kw in keywords["positive"] if kw in text)
        neg_hits = sum(1 for kw in keywords["negative"] if kw in text)

        if pos_hits > 0 or neg_hits > 0:
            if pos_hits >= neg_hits:
                aspects[aspect_name] = "positive"
            else:
                aspects[aspect_name] = "negative"

    return aspects


def main():
    """口コミアスペクト拡充のメイン処理"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 更新前のアスペクト分布
    reviews = cursor.execute("""
        SELECT id, text, aspects FROM reviews
        WHERE text IS NOT NULL AND text != ''
    """).fetchall()

    logger.info(f"口コミ総数: {len(reviews)}件")

    # 更新前のカテゴリ集計
    before_categories: dict[str, int] = {}
    for review in reviews:
        if review["aspects"]:
            try:
                aspects = json.loads(review["aspects"])
                for k in aspects:
                    before_categories[k] = before_categories.get(k, 0) + 1
            except (json.JSONDecodeError, TypeError):
                pass

    logger.info("更新前アスペクト分布:")
    for k, v in sorted(before_categories.items(), key=lambda x: -x[1]):
        logger.info(f"  {k}: {v}件")

    # 新アスペクト分析
    stats = {
        "total_analyzed": 0,
        "updated": 0,
        "new_aspects_added": {cat: 0 for cat in NEW_ASPECT_KEYWORDS},
        "sentiment_dist": {
            cat: {"positive": 0, "negative": 0}
            for cat in NEW_ASPECT_KEYWORDS
        },
    }

    batch_size = 500
    for i in range(0, len(reviews), batch_size):
        batch = reviews[i:i + batch_size]

        for review in batch:
            stats["total_analyzed"] += 1
            text = review["text"]

            # 既存aspectsをパース
            existing_aspects = {}
            if review["aspects"]:
                try:
                    existing_aspects = json.loads(review["aspects"])
                except (json.JSONDecodeError, TypeError):
                    existing_aspects = {}

            # 新アスペクトを分析
            new_aspects = analyze_new_aspects(text)

            if not new_aspects:
                continue

            # 既存aspectsにマージ（既存キーは上書きしない）
            merged = False
            for aspect_name, sentiment in new_aspects.items():
                if aspect_name not in existing_aspects:
                    existing_aspects[aspect_name] = sentiment
                    stats["new_aspects_added"][aspect_name] += 1
                    stats["sentiment_dist"][aspect_name][sentiment] += 1
                    merged = True

            if merged:
                # DB更新
                cursor.execute(
                    "UPDATE reviews SET aspects = ? WHERE id = ?",
                    (json.dumps(existing_aspects, ensure_ascii=False), review["id"]),
                )
                stats["updated"] += 1

        conn.commit()
        logger.info(f"バッチ完了: {min(i + batch_size, len(reviews))}/{len(reviews)}")

    # 更新後のアスペクト分布を集計
    after_reviews = cursor.execute("""
        SELECT aspects FROM reviews
        WHERE aspects IS NOT NULL AND aspects != ''
    """).fetchall()

    after_categories: dict[str, int] = {}
    for review in after_reviews:
        try:
            aspects = json.loads(review["aspects"])
            for k in aspects:
                after_categories[k] = after_categories.get(k, 0) + 1
        except (json.JSONDecodeError, TypeError):
            pass

    # レポート出力
    print(f"\n{'='*60}")
    print(f"  Phase 65: 口コミアスペクト拡充 完了レポート")
    print(f"{'='*60}")

    print(f"\n  [更新サマリ]")
    print(f"  {'─'*40}")
    print(f"  口コミ総数:     {stats['total_analyzed']}件")
    print(f"  更新件数:       {stats['updated']}件")
    unique_before = len(before_categories)
    unique_after = len(after_categories)
    print(f"  カテゴリ数:     {unique_before} -> {unique_after}")

    print(f"\n  [新規追加アスペクト内訳]")
    print(f"  {'─'*40}")
    for cat in NEW_ASPECT_KEYWORDS:
        count = stats["new_aspects_added"][cat]
        pos = stats["sentiment_dist"][cat]["positive"]
        neg = stats["sentiment_dist"][cat]["negative"]
        pos_pct = pos / count * 100 if count > 0 else 0
        neg_pct = neg / count * 100 if count > 0 else 0
        label = {"counseling": "カウンセリング", "result": "結果・効果", "aftercare": "アフターケア"}[cat]
        print(f"  {label:12}: {count:>5}件  "
              f"(positive={pos} [{pos_pct:.0f}%] / negative={neg} [{neg_pct:.0f}%])")

    print(f"\n  [全アスペクト分布（更新後）]")
    print(f"  {'─'*40}")
    aspect_labels = {
        "service": "接客・対応",
        "skill": "技術・仕上がり",
        "price": "価格・費用",
        "facility": "施設・環境",
        "wait": "待ち時間",
        "counseling": "カウンセリング",
        "result": "結果・効果",
        "aftercare": "アフターケア",
    }
    for cat, count in sorted(after_categories.items(), key=lambda x: -x[1]):
        label = aspect_labels.get(cat, cat)
        bar = "#" * (count // 50)
        is_new = " [NEW]" if cat in NEW_ASPECT_KEYWORDS else ""
        print(f"  {label:12}: {count:>5}件  {bar}{is_new}")

    print(f"\n{'='*60}\n")

    conn.close()


if __name__ == "__main__":
    main()
