"""
AURA MVP -- P1-1: 口コミアスペクト分析バグ修正スクリプト

rating >= 4.0 かつ sentiment_score > 0.3 なのに aspects に "negative" が
含まれるレコードを抽出し、テキスト内の否定表現を考慮して判定を修正する。

主な原因:
  「痛みもそれほどありませんでした」のような否定形が
  ネガティブキーワード「痛み」にヒットして negative と誤判定されている。

修正ロジック:
  ネガティブキーワードの前後に否定表現がある場合、
  そのカテゴリの判定を "positive" に反転する。

実行:
    .venv/bin/python scripts/fix_aspects_p1.py
"""

import json
import re
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "aura.db"

# 否定表現パターン（キーワードの前後に出現する可能性がある）
NEGATION_PATTERNS = [
    "ない",
    "なく",
    "なかった",
    "せん",
    "ません",
    "ありません",
    "ありませんでした",
    "それほど",
    "そこまで",
    "さほど",
    "あまり",
    "ほとんど",
    "全く",
    "まったく",
    "感じず",
    "感じません",
    "なさそう",
]

# アスペクト別ネガティブキーワード（enrich_aspects_phase65.py と対応）
NEGATIVE_KEYWORDS_BY_ASPECT: dict[str, list[str]] = {
    "result": [
        "効果なし", "変化なし", "変わらない", "不自然",
        "腫れ", "痛み", "内出血", "ダウンタイムが長",
        "左右差", "失敗", "やり直し", "修正",
        "傷跡", "凹凸", "引きつり", "しこり",
    ],
    "counseling": [
        "圧力", "勧誘", "押し売り", "しつこい", "強引",
        "説明がない", "説明不足", "聞いてくれない", "急かされ",
        "カウンセラー任せ", "流れ作業", "話を聞かない",
        "質問できない", "断りにくい", "営業感",
    ],
    "aftercare": [
        "アフターケアがない", "フォローなし", "放置",
        "術後の対応が悪い", "連絡がつかない",
        "保証がない", "追加費用", "再診料",
        "経過を見てくれない", "術後放置",
    ],
    "service": [
        "態度が悪い", "不愛想", "冷たい", "雑",
        "投げやり", "失礼", "不親切",
    ],
    "skill": [
        "下手", "雑", "痛い", "失敗", "不自然",
    ],
    "facility": [
        "狭い", "古い", "汚い", "暗い", "寒い",
    ],
}

# 否定表現の検索範囲（キーワードの前後何文字を検索するか）
NEGATION_SEARCH_WINDOW = 15


def has_negation_context(text: str, keyword: str) -> bool:
    """
    テキスト内でキーワードが否定的文脈で使われているか判定する。

    キーワードの出現位置の前後NEGATION_SEARCH_WINDOW文字以内に
    否定表現がある場合、否定文脈と判定する。

    Args:
        text: 口コミテキスト
        keyword: ネガティブキーワード

    Returns:
        否定文脈で使われている場合 True
    """
    # キーワードがテキストに含まれない場合はFalse
    idx = text.find(keyword)
    if idx == -1:
        return False

    # 全出現位置をチェック
    positions = []
    start = 0
    while True:
        pos = text.find(keyword, start)
        if pos == -1:
            break
        positions.append(pos)
        start = pos + 1

    for pos in positions:
        # キーワード前後の文脈を取得
        window_start = max(0, pos - NEGATION_SEARCH_WINDOW)
        window_end = min(len(text), pos + len(keyword) + NEGATION_SEARCH_WINDOW)
        context = text[window_start:window_end]

        # 否定表現があるかチェック
        for neg_pattern in NEGATION_PATTERNS:
            if neg_pattern in context:
                return True

    return False


def should_flip_to_positive(text: str, aspect_name: str) -> bool:
    """
    あるアスペクトのnegative判定を positive に反転すべきか判定する。

    テキスト内のネガティブキーワード全てが否定文脈で使われている場合、
    そのアスペクトは実際にはポジティブと判断する。

    Args:
        text: 口コミテキスト
        aspect_name: アスペクト名

    Returns:
        positive に反転すべき場合 True
    """
    neg_keywords = NEGATIVE_KEYWORDS_BY_ASPECT.get(aspect_name, [])
    if not neg_keywords:
        return False

    # テキストに含まれるネガティブキーワードを列挙
    found_keywords = [kw for kw in neg_keywords if kw in text]
    if not found_keywords:
        # キーワードが見つからない場合（別ロジックで判定された可能性）
        # 高ratingかつ高sentimentなので positive に修正
        return True

    # 全てのキーワードが否定文脈か確認
    all_negated = all(
        has_negation_context(text, kw) for kw in found_keywords
    )

    return all_negated


def main():
    """口コミアスペクト分析バグ修正のメイン処理"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 修正前の統計
    total_reviews = cursor.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    total_with_aspects = cursor.execute(
        "SELECT COUNT(*) FROM reviews WHERE aspects IS NOT NULL AND aspects != ''"
    ).fetchone()[0]
    total_negative = cursor.execute(
        "SELECT COUNT(*) FROM reviews WHERE aspects LIKE '%negative%'"
    ).fetchone()[0]

    print(f"\n{'='*60}")
    print(f"  P1-1: 口コミアスペクト分析バグ修正")
    print(f"{'='*60}")
    print(f"\n  [修正前の統計]")
    print(f"  {'─'*40}")
    print(f"  口コミ総数:                  {total_reviews}")
    print(f"  アスペクト付き:              {total_with_aspects}")
    print(f"  negative含むレコード:        {total_negative}")

    # 修正対象: rating >= 4.0 かつ sentiment > 0.3 かつ aspectsにnegativeあり
    candidates = cursor.execute(
        """
        SELECT id, text, rating, sentiment_score, aspects
        FROM reviews
        WHERE rating >= 4.0
          AND sentiment_score > 0.3
          AND aspects LIKE '%negative%'
        ORDER BY rating DESC, sentiment_score DESC
        """
    ).fetchall()

    print(f"  修正候補数 (rating>=4.0 & sentiment>0.3 & negative): {len(candidates)}")

    # 修正実行
    stats = {
        "analyzed": 0,
        "fixed": 0,
        "aspects_flipped": 0,
        "skipped": 0,
        "by_aspect": {},
    }
    fixed_examples = []

    for review in candidates:
        stats["analyzed"] += 1
        text = review["text"]
        review_id = review["id"]

        try:
            aspects = json.loads(review["aspects"])
        except (json.JSONDecodeError, TypeError):
            stats["skipped"] += 1
            continue

        if not isinstance(aspects, dict):
            stats["skipped"] += 1
            continue

        # negative なアスペクトを検出
        modified = False
        for aspect_name, sentiment in list(aspects.items()):
            if sentiment != "negative":
                continue

            # 否定文脈を確認
            if should_flip_to_positive(text, aspect_name):
                aspects[aspect_name] = "positive"
                modified = True
                stats["aspects_flipped"] += 1
                stats["by_aspect"][aspect_name] = (
                    stats["by_aspect"].get(aspect_name, 0) + 1
                )

        if modified:
            cursor.execute(
                "UPDATE reviews SET aspects = ? WHERE id = ?",
                (json.dumps(aspects, ensure_ascii=False), review_id),
            )
            stats["fixed"] += 1

            # 最初の5件を例として記録
            if len(fixed_examples) < 5:
                short_text = text[:80].replace("\n", " ") + "..."
                fixed_examples.append({
                    "rating": review["rating"],
                    "sentiment": review["sentiment_score"],
                    "text": short_text,
                    "aspects_after": aspects,
                })

    conn.commit()

    # 修正後の統計
    after_negative = cursor.execute(
        "SELECT COUNT(*) FROM reviews WHERE aspects LIKE '%negative%'"
    ).fetchone()[0]
    after_candidates = cursor.execute(
        """
        SELECT COUNT(*) FROM reviews
        WHERE rating >= 4.0
          AND sentiment_score > 0.3
          AND aspects LIKE '%negative%'
        """
    ).fetchone()[0]

    # レポート出力
    print(f"\n  [修正結果]")
    print(f"  {'─'*40}")
    print(f"  分析対象:          {stats['analyzed']}件")
    print(f"  修正されたレコード: {stats['fixed']}件")
    print(f"  反転アスペクト数:  {stats['aspects_flipped']}件")
    print(f"  スキップ:          {stats['skipped']}件")

    print(f"\n  [アスペクト別反転数]")
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
    for aspect, count in sorted(
        stats["by_aspect"].items(), key=lambda x: -x[1]
    ):
        label = aspect_labels.get(aspect, aspect)
        print(f"  {label:16}: {count}件  negative -> positive")

    print(f"\n  [修正例（最大5件）]")
    print(f"  {'─'*40}")
    for i, example in enumerate(fixed_examples, 1):
        print(
            f"  {i}. rating={example['rating']}, "
            f"sentiment={example['sentiment']:.2f}"
        )
        print(f"     \"{example['text']}\"")
        print(f"     aspects: {json.dumps(example['aspects_after'], ensure_ascii=False)}")
        print()

    print(f"  [修正前後比較]")
    print(f"  {'─'*40}")
    print(
        f"  negative含むレコード: {total_negative} -> {after_negative} "
        f"(変化: {after_negative - total_negative:+d})"
    )
    print(
        f"  誤判定候補 (rating>=4 & sentiment>0.3): "
        f"{len(candidates)} -> {after_candidates} "
        f"(変化: {after_candidates - len(candidates):+d})"
    )

    print(f"\n{'='*60}\n")

    conn.close()


if __name__ == "__main__":
    main()
