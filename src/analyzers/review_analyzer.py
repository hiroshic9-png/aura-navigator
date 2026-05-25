"""
AURA MVP — 口コミ感情分析エンジン

口コミテキストに対して感情分析・アスペクト抽出・スパム判定を実行する。
外部APIやML依存なし。キーワードベースで軽量かつ高速に動作。

分析内容:
1. 感情スコア (sentiment_score: -1.0〜+1.0)
   - ポジティブ/ネガティブキーワードの出現比率で算出
2. アスペクト抽出 (aspects: JSON)
   - service/price/skill/wait/facility の5軸で口コミを分類
3. スパム判定 (is_spam: Boolean)
   - テンプレ口コミ・極端に短い口コミを検出

使い方:
    # 全件分析
    python -m src.analyzers.review_analyzer

    # 最初の10件のみ
    python -m src.analyzers.review_analyzer --limit 10

    # 統計表示
    python -m src.analyzers.review_analyzer --stats
"""

import argparse
import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select, func

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ============================================================
# キーワード辞書
# ============================================================

# 感情分析用キーワード（各キーワードの重みは均等: +1 or -1）
POSITIVE_KEYWORDS: list[str] = [
    # 接客・態度
    "丁寧", "親切", "安心", "優しい", "やさしい", "笑顔", "感じが良い", "感じがいい",
    "話しやすい", "寄り添", "気さく", "温かい", "あたたかい",
    # 結果・品質
    "満足", "きれい", "綺麗", "自然", "上手", "仕上がり", "完璧", "理想",
    "良かった", "よかった", "素晴らしい", "すばらしい", "最高",
    # 信頼・推奨
    "おすすめ", "お勧め", "信頼", "安い", "納得", "リピート", "また行",
    "また通", "紹介したい",
    # 環境・快適性
    "快適", "清潔", "おしゃれ", "居心地", "リラックス",
    # 説明・カウンセリング
    "分かりやすい", "わかりやすい", "説明が丁寧", "相談しやすい",
    "しっかり説明", "カウンセリングが丁寧",
]

NEGATIVE_KEYWORDS: list[str] = [
    # 営業・勧誘
    "強引", "押し売り", "しつこい", "勧誘", "無理やり", "契約させ",
    "高額なコースを勧め", "断りにくい",
    # 不満・後悔
    "後悔", "最悪", "不快", "失敗", "ひどい", "最低", "がっかり",
    "裏切られ", "騙され", "だまされ",
    # 対応の悪さ
    "感じ悪い", "感じが悪い", "雑", "適当", "冷たい", "つめたい",
    "たらい回し", "無愛想", "態度が悪い", "横柄",
    # 待ち時間
    "待たされ", "待ち時間が長い", "予約が取れ",
    # 価格
    "高い", "高すぎ", "ぼったくり", "追加料金", "想定以上",
    # 技術
    "下手", "左右差", "不自然", "腫れ", "痛い", "傷跡",
    # 感情
    "怒り", "怒って", "泣い", "不安になっ", "信用できない",
    "二度と行かない", "候えない",
]


# ============================================================
# アスペクト定義（5軸）
# ============================================================

# 各アスペクトのポジティブ/ネガティブキーワード
ASPECT_KEYWORDS: dict[str, dict[str, list[str]]] = {
    "service": {
        "positive": [
            "丁寧", "親切", "優しい", "やさしい", "笑顔", "感じが良い", "感じがいい",
            "話しやすい", "寄り添", "気さく", "温かい", "あたたかい",
            "相談しやすい", "カウンセリングが丁寧", "説明が丁寧",
            "分かりやすい", "わかりやすい", "しっかり説明",
            "対応が良い", "対応がいい", "スタッフ",
        ],
        "negative": [
            "感じ悪い", "感じが悪い", "冷たい", "つめたい", "無愛想",
            "態度が悪い", "横柄", "たらい回し", "雑", "適当",
            "強引", "押し売り", "しつこい", "勧誘", "無理やり",
            "契約させ", "断りにくい", "対応が悪い",
        ],
    },
    "price": {
        "positive": [
            "安い", "リーズナブル", "コスパ", "お手頃", "良心的",
            "納得", "適正", "手頃", "お値打ち",
        ],
        "negative": [
            "高い", "高すぎ", "ぼったくり", "追加料金", "想定以上",
            "高額", "値段", "コスパが悪い", "割高",
        ],
    },
    "skill": {
        "positive": [
            "上手", "きれい", "綺麗", "自然", "仕上がり", "完璧",
            "理想", "技術", "腕がいい", "腕が良い", "素晴らしい",
            "すばらしい", "ダウンタイムが短い",
        ],
        "negative": [
            "下手", "左右差", "不自然", "失敗", "腫れ", "痛い",
            "傷跡", "ひどい", "やり直し", "修正",
        ],
    },
    "wait": {
        "positive": [
            "スムーズ", "すぐに案内", "待ち時間が短い", "時間通り",
            "予約が取りやすい", "待たずに",
        ],
        "negative": [
            "待たされ", "待ち時間が長い", "予約が取れ", "予約取れ",
            "遅い", "長時間待", "いつまでも待",
        ],
    },
    "facility": {
        "positive": [
            "清潔", "おしゃれ", "きれいな院内", "綺麗な院内",
            "居心地", "リラックス", "快適", "広い", "個室",
            "プライバシー",
        ],
        "negative": [
            "汚い", "古い", "狭い", "うるさい", "暗い",
            "プライバシーがない", "丸見え",
        ],
    },
}


# ============================================================
# スパム判定パターン
# ============================================================

# 情報量が極端に少ないテンプレ口コミ（完全一致 or ほぼ一致で判定）
SPAM_TEMPLATE_PATTERNS: list[str] = [
    r"^よかった[。です]*$",
    r"^良かった[。です]*$",
    r"^また行きたい[。です]*$",
    r"^おすすめ[。です]*$",
    r"^お勧め[。です]*$",
    r"^いい感じ[。です]*$",
    r"^よかったです[。]*$",
    r"^良かったです[。]*$",
    r"^満足[。です]*$",
    r"^普通[。です]*$",
    r"^特になし[。]*$",
    r"^ありがとうございました[。]*$",
    r"^.{1,5}でした[。]*$",  # 「良いでした」等のごく短文
]

# スパム判定の最小テキスト長
MIN_TEXT_LENGTH = 10


# ============================================================
# 分析結果データクラス
# ============================================================


@dataclass
class ReviewAnalysisResult:
    """個別口コミの分析結果"""

    review_id: str
    sentiment_score: float
    aspects: dict[str, str]
    is_spam: bool
    positive_count: int = 0
    negative_count: int = 0
    matched_positive: list[str] = field(default_factory=list)
    matched_negative: list[str] = field(default_factory=list)


@dataclass
class AnalysisStats:
    """分析全体の統計情報"""

    total_reviews: int = 0
    analyzed_count: int = 0
    spam_count: int = 0
    avg_sentiment: float = 0.0
    positive_count: int = 0  # スコア > 0.2
    neutral_count: int = 0   # -0.2 <= スコア <= 0.2
    negative_count: int = 0  # スコア < -0.2
    aspect_distribution: dict[str, int] = field(default_factory=dict)
    top_positive_keywords: list[tuple[str, int]] = field(default_factory=list)
    top_negative_keywords: list[tuple[str, int]] = field(default_factory=list)


# ============================================================
# 感情分析エンジン本体
# ============================================================


class ReviewAnalyzer:
    """
    口コミ感情分析エンジン

    キーワードマッチングベースで口コミテキストの感情スコア、
    アスペクト分類、スパム判定を実行する。
    """

    def __init__(self):
        """分析エンジンの初期化"""
        # テンプレパターンを事前コンパイル
        self._spam_patterns = [re.compile(p) for p in SPAM_TEMPLATE_PATTERNS]

    def analyze(self, review_id: str, text: str, rating: float | None = None) -> ReviewAnalysisResult:
        """
        口コミ1件を分析する

        Args:
            review_id: 口コミID
            text: 口コミ本文
            rating: 口コミ評価（1-5、あれば）

        Returns:
            ReviewAnalysisResult: 分析結果
        """
        # スパム判定（先に実行: スパムでも感情スコアは算出する）
        is_spam = self._detect_spam(text, rating)

        # 感情スコア算出
        sentiment_score, pos_count, neg_count, matched_pos, matched_neg = (
            self._calculate_sentiment(text)
        )

        # アスペクト抽出
        aspects = self._extract_aspects(text)

        return ReviewAnalysisResult(
            review_id=review_id,
            sentiment_score=sentiment_score,
            aspects=aspects,
            is_spam=is_spam,
            positive_count=pos_count,
            negative_count=neg_count,
            matched_positive=matched_pos,
            matched_negative=matched_neg,
        )

    def _calculate_sentiment(
        self, text: str
    ) -> tuple[float, int, int, list[str], list[str]]:
        """
        感情スコアを算出する

        計算式: (ポジ数 - ネガ数) / (ポジ数 + ネガ数 + 1)
        スコア範囲: -1.0 〜 +1.0

        Args:
            text: 口コミ本文

        Returns:
            (スコア, ポジ数, ネガ数, マッチしたポジキーワード, マッチしたネガキーワード)
        """
        matched_positive = []
        matched_negative = []

        for keyword in POSITIVE_KEYWORDS:
            if keyword in text:
                matched_positive.append(keyword)

        for keyword in NEGATIVE_KEYWORDS:
            if keyword in text:
                matched_negative.append(keyword)

        pos_count = len(matched_positive)
        neg_count = len(matched_negative)

        # スコア計算: (ポジ数 - ネガ数) / (ポジ数 + ネガ数 + 1)
        score = (pos_count - neg_count) / (pos_count + neg_count + 1)

        # -1.0〜+1.0 にクランプ（理論的には範囲内だが安全のため）
        score = max(-1.0, min(1.0, score))

        return score, pos_count, neg_count, matched_positive, matched_negative

    def _extract_aspects(self, text: str) -> dict[str, str]:
        """
        アスペクト（評価軸）を抽出する

        5軸: service, price, skill, wait, facility
        各軸でポジティブ/ネガティブキーワードの出現を確認し、
        優勢な方向性を判定する。

        Args:
            text: 口コミ本文

        Returns:
            検出されたアスペクトと方向性の辞書
            例: {"service": "positive", "price": "negative"}
        """
        aspects: dict[str, str] = {}

        for aspect_name, keywords in ASPECT_KEYWORDS.items():
            pos_hits = sum(1 for kw in keywords["positive"] if kw in text)
            neg_hits = sum(1 for kw in keywords["negative"] if kw in text)

            # いずれかのキーワードがヒットした場合のみアスペクトを記録
            if pos_hits > 0 or neg_hits > 0:
                if pos_hits >= neg_hits:
                    aspects[aspect_name] = "positive"
                else:
                    aspects[aspect_name] = "negative"

        return aspects

    def _detect_spam(self, text: str, rating: float | None = None) -> bool:
        """
        スパム（低品質口コミ）を判定する

        以下のいずれかに該当する場合にスパムと判定:
        1. テキストが10文字未満
        2. テンプレ的な定型口コミ（情報量が極端に少ない）
        3. 評価なしでテキストなし（空データ）

        Args:
            text: 口コミ本文
            rating: 口コミ評価（1-5、あれば）

        Returns:
            スパム判定結果
        """
        # テキストが空 or 極端に短い
        stripped = text.strip() if text else ""
        if len(stripped) < MIN_TEXT_LENGTH:
            return True

        # 評価なしでテキストなし
        if not stripped and rating is None:
            return True

        # テンプレ口コミ判定
        for pattern in self._spam_patterns:
            if pattern.match(stripped):
                return True

        return False


# ============================================================
# DB操作
# ============================================================


async def analyze_reviews(limit: int | None = None) -> AnalysisStats:
    """
    reviewsテーブルの口コミを分析してDB更新する

    Args:
        limit: 分析対象の最大件数（Noneで全件）

    Returns:
        AnalysisStats: 分析統計
    """
    from src.db.database import AsyncSessionLocal, ReviewTable

    analyzer = ReviewAnalyzer()
    stats = AnalysisStats()

    # キーワード出現カウント用
    keyword_counter_pos: dict[str, int] = {}
    keyword_counter_neg: dict[str, int] = {}
    sentiment_scores: list[float] = []

    async with AsyncSessionLocal() as session:
        # 分析対象の口コミを取得
        query = select(ReviewTable)
        if limit is not None:
            query = query.limit(limit)

        result = await session.execute(query)
        reviews = result.scalars().all()

        stats.total_reviews = len(reviews)

        if stats.total_reviews == 0:
            logger.info("分析対象の口コミがありません。")
            return stats

        logger.info(f"分析開始: {stats.total_reviews}件の口コミ")

        for review in reviews:
            text = review.text or ""
            rating = review.rating

            # 分析実行
            analysis = analyzer.analyze(
                review_id=review.id, text=text, rating=rating
            )

            # DB更新
            review.sentiment_score = analysis.sentiment_score
            review.aspects = json.dumps(analysis.aspects, ensure_ascii=False)
            review.is_spam = analysis.is_spam
            review.analyzed_at = datetime.now()

            # 統計集計
            stats.analyzed_count += 1
            sentiment_scores.append(analysis.sentiment_score)

            if analysis.is_spam:
                stats.spam_count += 1

            if analysis.sentiment_score > 0.2:
                stats.positive_count += 1
            elif analysis.sentiment_score < -0.2:
                stats.negative_count += 1
            else:
                stats.neutral_count += 1

            # アスペクト分布
            for aspect_name in analysis.aspects:
                stats.aspect_distribution[aspect_name] = (
                    stats.aspect_distribution.get(aspect_name, 0) + 1
                )

            # キーワード出現カウント
            for kw in analysis.matched_positive:
                keyword_counter_pos[kw] = keyword_counter_pos.get(kw, 0) + 1
            for kw in analysis.matched_negative:
                keyword_counter_neg[kw] = keyword_counter_neg.get(kw, 0) + 1

        await session.commit()
        logger.info(f"分析完了: {stats.analyzed_count}件をDB更新")

    # 統計の最終計算
    if sentiment_scores:
        stats.avg_sentiment = sum(sentiment_scores) / len(sentiment_scores)

    # 上位キーワード（最大10件）
    stats.top_positive_keywords = sorted(
        keyword_counter_pos.items(), key=lambda x: x[1], reverse=True
    )[:10]
    stats.top_negative_keywords = sorted(
        keyword_counter_neg.items(), key=lambda x: x[1], reverse=True
    )[:10]

    return stats


async def show_stats() -> AnalysisStats:
    """
    分析済み口コミの統計を表示する（DB更新なし）

    既にanalyzed_atが設定されている口コミの統計を集計して返す。
    """
    from src.db.database import AsyncSessionLocal, ReviewTable

    stats = AnalysisStats()

    async with AsyncSessionLocal() as session:
        # 全口コミ数
        total = await session.scalar(select(func.count(ReviewTable.id)))
        stats.total_reviews = total or 0

        if stats.total_reviews == 0:
            logger.info("口コミデータがありません。")
            return stats

        # 分析済み件数
        analyzed = await session.scalar(
            select(func.count(ReviewTable.id)).where(
                ReviewTable.analyzed_at.isnot(None)
            )
        )
        stats.analyzed_count = analyzed or 0

        if stats.analyzed_count == 0:
            logger.info("分析済みの口コミがありません。まず分析を実行してください。")
            return stats

        # 分析済み口コミを取得して統計計算
        result = await session.execute(
            select(ReviewTable).where(ReviewTable.analyzed_at.isnot(None))
        )
        reviews = result.scalars().all()

        sentiment_scores: list[float] = []
        for review in reviews:
            score = review.sentiment_score
            if score is not None:
                sentiment_scores.append(score)
                if score > 0.2:
                    stats.positive_count += 1
                elif score < -0.2:
                    stats.negative_count += 1
                else:
                    stats.neutral_count += 1

            if review.is_spam:
                stats.spam_count += 1

            # アスペクト集計
            if review.aspects:
                try:
                    aspects = json.loads(review.aspects)
                    for aspect_name in aspects:
                        stats.aspect_distribution[aspect_name] = (
                            stats.aspect_distribution.get(aspect_name, 0) + 1
                        )
                except (json.JSONDecodeError, TypeError):
                    pass

        if sentiment_scores:
            stats.avg_sentiment = sum(sentiment_scores) / len(sentiment_scores)

    return stats


# ============================================================
# 表示ユーティリティ
# ============================================================


def print_analysis_stats(stats: AnalysisStats, is_existing: bool = False) -> None:
    """
    分析統計を見やすく表示する

    Args:
        stats: 分析統計データ
        is_existing: True=既存統計の表示、False=今回の分析結果
    """
    label = "口コミ分析 統計レポート" if is_existing else "口コミ感情分析 実行結果"

    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")

    if stats.total_reviews == 0:
        print("  分析対象の口コミがありません。")
        print(f"{'='*60}\n")
        return

    print(f"\n  📊 基本統計")
    print(f"  {'─'*40}")
    print(f"  口コミ総数:       {stats.total_reviews}件")
    print(f"  分析済み:         {stats.analyzed_count}件")
    print(f"  スパム判定:       {stats.spam_count}件")

    if stats.analyzed_count > 0:
        spam_rate = stats.spam_count / stats.analyzed_count * 100
        print(f"  スパム率:         {spam_rate:.1f}%")

    print(f"\n  💭 感情分析")
    print(f"  {'─'*40}")
    print(f"  平均スコア:       {stats.avg_sentiment:+.3f}")
    print(f"  ポジティブ:       {stats.positive_count}件 (スコア > +0.2)")
    print(f"  ニュートラル:     {stats.neutral_count}件 (-0.2 ≦ スコア ≦ +0.2)")
    print(f"  ネガティブ:       {stats.negative_count}件 (スコア < -0.2)")

    if stats.analyzed_count > 0:
        # 感情分布バー
        pos_pct = stats.positive_count / stats.analyzed_count * 100
        neu_pct = stats.neutral_count / stats.analyzed_count * 100
        neg_pct = stats.negative_count / stats.analyzed_count * 100
        print(f"  分布:             😊{pos_pct:.0f}% / 😐{neu_pct:.0f}% / 😞{neg_pct:.0f}%")

    if stats.aspect_distribution:
        print(f"\n  🔍 アスペクト分布")
        print(f"  {'─'*40}")
        aspect_labels = {
            "service": "接客・対応  (service)",
            "price": "価格・コスパ (price)",
            "skill": "技術・仕上がり(skill)",
            "wait": "待ち時間    (wait)",
            "facility": "施設・環境  (facility)",
        }
        for aspect_key in ["service", "skill", "price", "wait", "facility"]:
            count = stats.aspect_distribution.get(aspect_key, 0)
            label = aspect_labels.get(aspect_key, aspect_key)
            bar = "█" * min(count, 30)
            print(f"  {label}: {count:>4}件 {bar}")

    if stats.top_positive_keywords:
        print(f"\n  ✅ 頻出ポジティブキーワード")
        print(f"  {'─'*40}")
        for kw, count in stats.top_positive_keywords[:5]:
            print(f"  「{kw}」: {count}回")

    if stats.top_negative_keywords:
        print(f"\n  ❌ 頻出ネガティブキーワード")
        print(f"  {'─'*40}")
        for kw, count in stats.top_negative_keywords[:5]:
            print(f"  「{kw}」: {count}回")

    print(f"\n{'='*60}\n")


# ============================================================
# CLI エントリポイント
# ============================================================


def main():
    """CLIエントリポイント"""
    parser = argparse.ArgumentParser(
        description="AURA MVP 口コミ感情分析エンジン",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # 全件分析してDB更新
  python -m src.analyzers.review_analyzer

  # 最初の10件のみ分析
  python -m src.analyzers.review_analyzer --limit 10

  # 分析済みデータの統計を表示（DB更新なし）
  python -m src.analyzers.review_analyzer --stats
        """,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="分析対象の最大件数（デフォルト: 全件）",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="分析済みデータの統計を表示（分析は実行しない）",
    )
    args = parser.parse_args()

    if args.stats:
        # 統計表示モード
        stats = asyncio.run(show_stats())
        print_analysis_stats(stats, is_existing=True)
    else:
        # 分析実行モード
        stats = asyncio.run(analyze_reviews(limit=args.limit))
        print_analysis_stats(stats, is_existing=False)


if __name__ == "__main__":
    main()
