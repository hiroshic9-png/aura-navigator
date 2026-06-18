"""
AURA MVP — 医師信頼性スコア算出エンジン v4

5軸・100点満点で医師の信頼性を客観的にスコアリング。
公開情報（専門医資格・勤務経歴・経験年数等）に基づき算出する。

v4変更点 (DEC-0044 反映):
  - 症例実績を 15pt → 25pt に拡大（症例写真件数を直接反映）
  - データ充実度を 10pt → 15pt に拡大（写真URL・口コミ紐付きを加味）
  - 専門医資格を 30pt → 25pt に縮小
  - 勤務経歴を 25pt → 20pt に縮小
  - 経験年数を 20pt → 15pt に縮小（天井効果解消のため段階細分化）

重要: スコアは「おすすめ」の序列ではなく、「情報の透明性」を示す指標。
スコアが低い＝悪い医師ではなく、公開情報が少ない可能性もある。
"""

import json
from dataclasses import dataclass, field


@dataclass
class TrustScoreBreakdown:
    """信頼性スコアの内訳 (v4)"""
    certification: float = 0.0    # 専門医資格（25pt満点）
    background: float = 0.0       # 勤務経歴（20pt満点）
    experience: float = 0.0       # 経験年数（15pt満点）
    case_volume: float = 0.0      # 症例実績（25pt満点）
    data_completeness: float = 0.0  # データ充実度（15pt満点）

    @property
    def total(self) -> float:
        """総合スコアを算出"""
        return round(
            self.certification + self.background + self.experience +
            self.case_volume + self.data_completeness, 1
        )

    def to_dict(self) -> dict:
        """辞書形式に変換"""
        return {
            "total": self.total,
            "certification": {"score": self.certification, "max": 25, "label": "専門医資格"},
            "background": {"score": self.background, "max": 20, "label": "勤務経歴"},
            "experience": {"score": self.experience, "max": 15, "label": "経験年数"},
            "case_volume": {"score": self.case_volume, "max": 25, "label": "症例実績"},
            "data_completeness": {"score": self.data_completeness, "max": 15, "label": "データ充実度"},
        }

    def to_json(self) -> str:
        """JSON文字列に変換（DB保存用）"""
        return json.dumps(self.to_dict(), ensure_ascii=False)


# 形成外科専門医に関連するキーワード
_PLASTIC_SURGERY_KEYWORDS = [
    "形成外科専門医",
    "形成外科",
    "日本形成外科学会",
]

# JSAPS（日本美容外科学会）に関連するキーワード
_JSAPS_KEYWORDS = [
    "JSAPS",
    "日本美容外科学会専門医",
    "美容外科専門医",
    "日本美容外科学会",
]

# その他の関連専門医資格
_OTHER_CERTIFICATIONS = {
    "皮膚科専門医": 8,
    "眼科専門医": 5,
    "耳鼻咽喉科専門医": 5,
    "口腔外科専門医": 5,
    "麻酔科専門医": 3,
    "外科専門医": 3,
}

# 大学病院・基幹病院キーワード
_UNIVERSITY_HOSPITAL_KEYWORDS = [
    "大学病院", "大学医学部", "大学附属",
    "東大", "京大", "慶應", "慶応", "東京大学",
    "京都大学", "大阪大学", "名古屋大学",
    "北海道大学", "東北大学", "九州大学",
    "医学部", "医学研究科",
]

_MAJOR_HOSPITAL_KEYWORDS = [
    "国立", "県立", "市立", "都立",
    "がんセンター", "医療センター",
    "基幹病院", "総合病院",
    "虎の門", "聖路加", "慈恵",
]


def calculate_trust_score(
    board_certifications: list[str] | str | None = None,
    jsaps_certified: bool = False,
    hospital_background: str | None = None,
    experience_years: int | None = None,
    annual_case_count: int | None = None,
    profile_url: str | None = None,
    specialties: list[str] | str | None = None,
    title: str | None = None,
    # v4 新パラメータ
    case_photos_count: int = 0,
    has_photo_url: bool = False,
    linked_review_count: int = 0,
) -> TrustScoreBreakdown:
    """
    医師の信頼性スコアを算出する (v4)

    Args:
        board_certifications: 専門医資格のリスト
        jsaps_certified: JSAPS専門医資格の有無
        hospital_background: 勤務経歴テキスト
        experience_years: 経験年数
        annual_case_count: 年間症例数
        profile_url: プロフィールURL
        specialties: 専門分野のリスト
        title: 肩書き
        case_photos_count: 症例写真件数（v4新規）
        has_photo_url: 医師写真URLの有無（v4新規）
        linked_review_count: 紐付き口コミ件数（v4新規）

    Returns:
        TrustScoreBreakdown: 各軸のスコア内訳
    """
    breakdown = TrustScoreBreakdown()

    # JSON文字列のパース
    if isinstance(board_certifications, str):
        try:
            board_certifications = json.loads(board_certifications)
        except (json.JSONDecodeError, TypeError):
            board_certifications = []
    if not board_certifications:
        board_certifications = []

    if isinstance(specialties, str):
        try:
            specialties = json.loads(specialties)
        except (json.JSONDecodeError, TypeError):
            specialties = []
    if not specialties:
        specialties = []

    # ==========================================
    # 軸1: 専門医資格（25pt満点） ← v3: 30pt
    # ==========================================
    cert_score = 0.0
    cert_text = " ".join(board_certifications)

    # 形成外科専門医（15pt）
    has_plastic = any(kw in cert_text for kw in _PLASTIC_SURGERY_KEYWORDS)
    if has_plastic:
        cert_score += 15.0

    # JSAPS専門医（10pt）— 形成外科専門医が前提の上位資格
    has_jsaps = jsaps_certified or any(kw in cert_text for kw in _JSAPS_KEYWORDS)
    if has_jsaps:
        cert_score += 10.0

    # その他の関連資格（最大8pt、形成外科がない場合の代替評価）
    if not has_plastic:
        other_score = 0.0
        for cert_name, points in _OTHER_CERTIFICATIONS.items():
            if cert_name in cert_text:
                other_score = max(other_score, points)
        cert_score += min(other_score, 12.0)

    breakdown.certification = min(cert_score, 25.0)

    # ==========================================
    # 軸2: 勤務経歴（20pt満点） ← v3: 25pt
    # ==========================================
    bg_score = 0.0
    bg_text = (hospital_background or "").strip()

    if bg_text:
        # 大学病院での勤務（12pt）
        if any(kw in bg_text for kw in _UNIVERSITY_HOSPITAL_KEYWORDS):
            bg_score += 12.0
        # 基幹病院での勤務（8pt）
        if any(kw in bg_text for kw in _MAJOR_HOSPITAL_KEYWORDS):
            bg_score += 8.0
    else:
        # 肩書きから推定（院長なら一定の経験がある可能性）
        if title and ("院長" in title or "理事長" in title):
            bg_score += 4.0

    breakdown.background = min(bg_score, 20.0)

    # ==========================================
    # 軸3: 経験年数（15pt満点） ← v3: 20pt
    # 天井効果解消: 段階を細分化して分散を広げる
    # ==========================================
    if experience_years is not None and experience_years > 0:
        if experience_years >= 25:
            breakdown.experience = 15.0
        elif experience_years >= 20:
            breakdown.experience = 13.0
        elif experience_years >= 15:
            breakdown.experience = 11.0
        elif experience_years >= 10:
            breakdown.experience = 9.0
        elif experience_years >= 7:
            breakdown.experience = 7.0
        elif experience_years >= 5:
            breakdown.experience = 5.0
        elif experience_years >= 3:
            breakdown.experience = 3.0
        else:
            breakdown.experience = 1.0

    # ==========================================
    # 軸4: 症例実績（25pt満点） ← v3: 15pt
    # v4: 症例写真件数を直接反映（DEC-0044）
    # ==========================================
    case_score = 0.0

    # v4: 症例写真件数（最大15pt）
    if case_photos_count > 0:
        if case_photos_count >= 100:
            case_score += 15.0
        elif case_photos_count >= 50:
            case_score += 12.0
        elif case_photos_count >= 20:
            case_score += 9.0
        elif case_photos_count >= 5:
            case_score += 6.0
        else:
            case_score += 3.0

    # 年間症例数（従来データ、最大10pt）
    if annual_case_count is not None and annual_case_count > 0:
        if annual_case_count >= 1000:
            case_score += 10.0
        elif annual_case_count >= 500:
            case_score += 8.0
        elif annual_case_count >= 200:
            case_score += 6.0
        elif annual_case_count >= 100:
            case_score += 4.0
        elif annual_case_count >= 50:
            case_score += 2.0

    breakdown.case_volume = min(case_score, 25.0)

    # ==========================================
    # 軸5: データ充実度（15pt満点） ← v3: 10pt
    # v4: 写真URLや口コミ紐付きも加味
    # ==========================================
    completeness = 0.0

    # プロフィールURLがある（3pt）
    if profile_url:
        completeness += 3.0

    # v4: 医師写真URLがある（2pt）
    if has_photo_url:
        completeness += 2.0

    # 資格情報がある（2pt）
    if board_certifications:
        completeness += 2.0

    # 専門分野が明記されている（2pt）
    if specialties:
        completeness += 2.0

    # 経験年数が公開されている（1pt）
    if experience_years is not None:
        completeness += 1.0

    # 勤務経歴がある（2pt）
    if bg_text:
        completeness += 2.0

    # v4: 口コミ紐付き（1pt）
    if linked_review_count > 0:
        completeness += 1.0

    breakdown.data_completeness = min(completeness, 15.0)

    return breakdown


def get_trust_level(score: float) -> dict:
    """
    スコアから信頼レベルを判定する

    Returns:
        {level, label, color, description}
    """
    if score >= 70:
        return {
            "level": "high",
            "label": "情報充実",
            "color": "#4CAF50",
            "description": "専門医資格・経歴が確認でき、公開情報が充実しています",
        }
    elif score >= 40:
        return {
            "level": "medium",
            "label": "一部確認済み",
            "color": "#FF9800",
            "description": "一部の情報は確認できますが、カウンセリングで詳しく確認することをお勧めします",
        }
    elif score >= 20:
        return {
            "level": "low",
            "label": "情報限定",
            "color": "#9E9E9E",
            "description": "公開情報が限られています。カウンセリングで資格・経歴を直接確認してください",
        }
    else:
        return {
            "level": "pending",
            "label": "情報収集中",
            "color": "#BDBDBD",
            "description": "情報収集中です。カウンセリングで詳しくお聞きください",
        }


def score_doctor_from_record(doctor, case_photos_count: int = 0) -> TrustScoreBreakdown:
    """
    DoctorTableレコードからスコアを算出するヘルパー (v4)

    Args:
        doctor: DoctorTableインスタンス
        case_photos_count: 当該医師の症例写真件数

    Returns:
        TrustScoreBreakdown
    """
    return calculate_trust_score(
        board_certifications=doctor.board_certifications,
        jsaps_certified=getattr(doctor, "jsaps_certified", False) or False,
        hospital_background=getattr(doctor, "hospital_background", None),
        experience_years=doctor.experience_years,
        annual_case_count=getattr(doctor, "annual_case_count", None),
        profile_url=doctor.profile_url,
        specialties=doctor.specialties,
        title=doctor.title,
        case_photos_count=case_photos_count,
        has_photo_url=bool(doctor.photo_url),
        linked_review_count=0,  # TODO: 口コミ紐付きが実装されたら反映
    )
