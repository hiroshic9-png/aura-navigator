"""
AURA MVP — クリニック総合スコアリングエンジン

クリニックの「信頼度」を多軸で定量評価する。
スコアは「情報の充実度と品質」を示す指標であり、
医療技術や治療成果を直接評価するものではない。

5軸構成（0-100）:
  1. 情報透明性 (20pt) — 医師情報・価格・Webサイトの公開度
  2. 口コミ評価 (25pt) — Google評価 + 感情分析
  3. レッドフラグ (25pt) — 圧力販売・トラブル等の減点
  4. 医師品質 (20pt) — 所属医師のtrust_score平均
  5. データ鮮度 (10pt) — 最終検証日からの経過
"""

from dataclasses import dataclass


@dataclass
class ClinicScoreResult:
    """クリニックスコアの結果"""
    total: float
    transparency: float     # 情報透明性 (0-20)
    review_quality: float   # 口コミ評価 (0-25)
    red_flag_penalty: float # レッドフラグ減点 (0-25, 25=問題なし)
    doctor_quality: float   # 医師品質 (0-20)
    freshness: float        # データ鮮度 (0-10)

    def to_dict(self) -> dict:
        """辞書形式で返却"""
        return {
            "total": round(self.total, 1),
            "transparency": round(self.transparency, 1),
            "review_quality": round(self.review_quality, 1),
            "red_flag_penalty": round(self.red_flag_penalty, 1),
            "doctor_quality": round(self.doctor_quality, 1),
            "freshness": round(self.freshness, 1),
        }


def get_clinic_grade(score: float) -> str:
    """スコアからグレードを算出"""
    if score >= 80:
        return "A"
    elif score >= 65:
        return "B"
    elif score >= 50:
        return "C"
    elif score >= 35:
        return "D"
    else:
        return "E"


def get_grade_label(grade: str) -> str:
    """グレードの説明ラベル"""
    labels = {
        "A": "情報が非常に充実",
        "B": "情報が充実",
        "C": "標準的な情報公開",
        "D": "情報がやや不足",
        "E": "情報収集中",
    }
    return labels.get(grade, "情報収集中")


def score_clinic(
    *,
    google_rating: float | None = None,
    google_review_count: int | None = None,
    has_website: bool = False,
    doctor_count: int = 0,
    avg_doctor_trust_score: float | None = None,
    has_certified_doctor: bool = False,
    review_count: int = 0,
    avg_sentiment: float | None = None,
    red_flag_count: int = 0,
    red_flag_ratio: float = 0.0,
    price_data_count: int = 0,
    procedure_count: int = 0,
    days_since_verified: int = 0,
    # Phase 66: v2パラメータ
    price_coverage_ratio: float = 0.0,   # 価格カバー率 (0.0-1.0)
    trend_direction: str | None = None,  # 'improving' / 'stable' / 'declining'
    procedure_diversity: int = 0,         # 提供施術数（カテゴリ横断）
) -> ClinicScoreResult:
    """
    クリニックの総合スコアを算出

    Args:
        google_rating: Google評価（1.0-5.0）
        google_review_count: Google口コミ件数
        has_website: Webサイトの有無
        doctor_count: 所属医師数
        avg_doctor_trust_score: 医師trust_scoreの平均
        has_certified_doctor: 専門医資格保有医師の有無
        review_count: AURA口コミ件数
        avg_sentiment: 口コミ感情分析スコアの平均（-1.0〜1.0）
        red_flag_count: レッドフラグ口コミ数
        red_flag_ratio: レッドフラグ比率（0.0〜1.0）
        price_data_count: 価格データ件数
        procedure_count: 施術データ件数
        days_since_verified: 最終検証日からの経過日数
        price_coverage_ratio: 価格カバー率 (0.0-1.0, Phase 66)
        trend_direction: 口コミトレンド ('improving'/'stable'/'declining', Phase 66)
        procedure_diversity: 提供施術数 (Phase 66)
    """

    # === 1. 情報透明性 (0-20pt) ===
    # 配分: Webサイト5pt + 医師情報8pt + 価格公開度6pt + 施術情報1pt = 20pt
    transparency = 0.0
    # Webサイトあり: +5pt
    if has_website:
        transparency += 5.0
    # 医師情報の公開度: 0-8pt
    if doctor_count > 0:
        transparency += min(doctor_count * 2, 8)
    # 価格公開度: 0-6pt（Phase 66: カバー率ベースに強化）
    if price_coverage_ratio > 0:
        # カバー率を直接反映（90%以上で満点付近）
        transparency += min(price_coverage_ratio * 6.0, 6.0)
    elif price_data_count > 0:
        # フォールバック: 従来の件数ベース（v2パラメータ未指定時）
        transparency += min(price_data_count * 0.5, 4.0)
    # 施術情報: 0-1pt（Phase 66: 価格枠拡大に伴い縮小）
    if procedure_count > 0:
        transparency += min(procedure_count * 0.05, 1.0)
    transparency = min(transparency, 20.0)

    # === 2. 口コミ評価 (0-25pt) ===
    review_quality = 0.0
    # Google評価ベース: 0-15pt
    if google_rating is not None:
        # 3.0未満 = 0pt, 3.0 = 5pt, 4.0 = 10pt, 5.0 = 15pt
        review_quality += max(0, (google_rating - 2.0) * 5)
        review_quality = min(review_quality, 15.0)
    # 口コミ件数ボーナス: 0-5pt
    if google_review_count and google_review_count > 0:
        # 10件で1pt, 50件で3pt, 100件以上で5pt
        review_quality += min(google_review_count / 20, 5.0)
    # 感情分析ボーナス: 0-5pt
    if avg_sentiment is not None and review_count > 0:
        # -1.0〜1.0 → 0-5pt
        review_quality += max(0, (avg_sentiment + 1.0) * 2.5)
    # Phase 66: トレンドボーナス（-2pt 〜 +2pt）
    if trend_direction == "improving":
        review_quality += 2.0
    elif trend_direction == "declining":
        review_quality -= 2.0
    # declining時に負にならないようクリップ
    review_quality = max(0.0, min(review_quality, 25.0))

    # === 3. レッドフラグ減点 (0-25pt, 25=問題なし) ===
    red_flag_penalty = 25.0
    if review_count > 0 and red_flag_count > 0:
        # レッドフラグ比率による減点
        # 10%未満: -2pt, 10-20%: -8pt, 20-30%: -15pt, 30%以上: -25pt
        if red_flag_ratio >= 0.30:
            red_flag_penalty = 0.0
        elif red_flag_ratio >= 0.20:
            red_flag_penalty = 10.0
        elif red_flag_ratio >= 0.10:
            red_flag_penalty = 17.0
        elif red_flag_ratio > 0:
            red_flag_penalty = 23.0
    # 絶対数でも減点（レッドフラグ5件以上は注意）
    if red_flag_count >= 10:
        red_flag_penalty = min(red_flag_penalty, 10.0)
    elif red_flag_count >= 5:
        red_flag_penalty = min(red_flag_penalty, 18.0)

    # === 4. 医師品質 (0-20pt) ===
    doctor_quality = 0.0
    if doctor_count > 0:
        # 医師がいるだけで+5pt
        doctor_quality += 5.0
        # 平均trust_score: 0-10pt
        if avg_doctor_trust_score is not None:
            doctor_quality += min(avg_doctor_trust_score / 10, 10.0)
        # 専門医資格保有: +5pt
        if has_certified_doctor:
            doctor_quality += 5.0
    doctor_quality = min(doctor_quality, 20.0)

    # === 5. データ鮮度 (0-10pt) ===
    freshness = 10.0
    if days_since_verified > 365:
        freshness = 2.0
    elif days_since_verified > 180:
        freshness = 5.0
    elif days_since_verified > 90:
        freshness = 7.0
    elif days_since_verified > 30:
        freshness = 9.0

    total = transparency + review_quality + red_flag_penalty + doctor_quality + freshness

    return ClinicScoreResult(
        total=total,
        transparency=transparency,
        review_quality=review_quality,
        red_flag_penalty=red_flag_penalty,
        doctor_quality=doctor_quality,
        freshness=freshness,
    )
