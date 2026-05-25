"""
AURA MVP データモデル — クリニック

美容クリニックの基本情報・医師情報・施術メニューを管理するスキーマ。
厚労省オープンデータ + Google Maps APIの2層構造に対応。
"""

from datetime import datetime

from pydantic import BaseModel, Field
from ulid import ULID


def generate_id() -> str:
    """ULIDベースのユニークID生成"""
    return str(ULID())


# ============================================================
# クリニック
# ============================================================


class ClinicBase(BaseModel):
    """クリニックの基本情報"""

    name: str = Field(..., description="クリニック名")
    branch_name: str | None = Field(None, description="院名（新宿院、渋谷院等）")
    chain_name: str | None = Field(None, description="チェーン名（湘南美容/品川/TCB等）")
    address: str = Field(..., description="住所")
    prefecture: str = Field(default="東京都", description="都道府県")
    city: str | None = Field(None, description="市区町村")
    postal_code: str | None = Field(None, description="郵便番号")
    lat: float | None = Field(None, description="緯度")
    lng: float | None = Field(None, description="経度")
    phone: str | None = Field(None, description="電話番号")
    website: str | None = Field(None, description="ウェブサイト")


class ClinicMhlwData(BaseModel):
    """厚労省データ由来の情報（Layer A: 公的データ基盤）"""

    mhlw_code: str | None = Field(None, description="医療機関コード")
    medical_departments: list[str] = Field(default_factory=list, description="標榜診療科目")
    doctor_count: int | None = Field(None, description="医師数")
    medical_corp_name: str | None = Field(None, description="開設者名（医療法人名等）")
    established_date: str | None = Field(None, description="開設日")
    bed_count: int | None = Field(None, description="病床数")
    facility_standards: list[str] = Field(default_factory=list, description="施設基準")


class ClinicGoogleData(BaseModel):
    """Google Maps API由来の情報（Layer B: エンリッチメント）"""

    google_place_id: str | None = Field(None, description="Google Place ID")
    google_rating: float | None = Field(None, ge=1.0, le=5.0, description="Google評価（1-5）")
    google_review_count: int | None = Field(None, ge=0, description="Google口コミ件数")
    google_photos: list[str] = Field(default_factory=list, description="写真URL（最大10枚）")
    opening_hours: dict | None = Field(None, description="営業時間")
    editorial_summary: str | None = Field(None, description="概要文")


class ClinicAnalysis(BaseModel):
    """AURA独自の分析データ"""

    transparency_score: float | None = Field(
        None, ge=0.0, le=100.0, description="透明性スコア（0-100）"
    )
    price_level: str | None = Field(None, description="価格帯（low/mid/high/premium）")
    procedures_offered: list[str] = Field(default_factory=list, description="対応施術カテゴリ")
    specialties: list[str] = Field(default_factory=list, description="専門分野")


class Clinic(ClinicBase):
    """クリニック完全データモデル（3層統合）"""

    id: str = Field(default_factory=generate_id, description="クリニックID（ULID）")
    # 厚労省データ
    mhlw: ClinicMhlwData = Field(default_factory=ClinicMhlwData)
    # Google Mapsデータ
    google: ClinicGoogleData = Field(default_factory=ClinicGoogleData)
    # AURA分析データ
    analysis: ClinicAnalysis = Field(default_factory=ClinicAnalysis)
    # メタデータ
    source: str = Field(default="mhlw", description="データソース（mhlw/google/manual）")
    last_verified: datetime | None = Field(None, description="最終検証日")
    is_active: bool = Field(default=True, description="アクティブフラグ")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class ClinicSummary(BaseModel):
    """クリニック一覧表示用サマリー"""

    id: str
    name: str
    branch_name: str | None = None
    chain_name: str | None = None
    address: str
    city: str | None = None
    google_rating: float | None = None
    google_review_count: int | None = None
    transparency_score: float | None = None
    price_level: str | None = None
    procedures_offered: list[str] = []
    lat: float | None = None
    lng: float | None = None


# ============================================================
# 医師
# ============================================================


class Doctor(BaseModel):
    """医師情報"""

    id: str = Field(default_factory=generate_id)
    clinic_id: str = Field(..., description="所属クリニックID")
    name: str = Field(..., description="医師名")
    title: str | None = Field(None, description="肩書き（院長、副院長等）")
    specialties: list[str] = Field(default_factory=list, description="専門分野")
    board_certifications: list[str] = Field(
        default_factory=list, description="専門医資格（形成外科専門医等）"
    )
    experience_years: int | None = Field(None, description="経験年数")
    profile_url: str | None = Field(None, description="プロフィールURL")


# ============================================================
# 口コミ
# ============================================================


class Review(BaseModel):
    """口コミデータ"""

    id: str = Field(default_factory=generate_id)
    clinic_id: str = Field(..., description="対象クリニックID")
    procedure_id: str | None = Field(None, description="施術ID")
    source: str = Field(..., description="データソース（google/aura/manual）")
    author_name: str | None = Field(None, description="投稿者名")
    text: str = Field(..., description="口コミ本文")
    rating: float | None = Field(None, ge=1.0, le=5.0, description="評価")
    # AURA分析結果
    sentiment_score: float | None = Field(None, ge=-1.0, le=1.0, description="感情スコア")
    aspects: dict | None = Field(None, description="アスペクト別評価")
    is_spam: bool | None = Field(None, description="スパム判定")
    created_at: datetime | None = None
    analyzed_at: datetime | None = None


# ============================================================
# API レスポンス
# ============================================================


class ClinicSearchResponse(BaseModel):
    """クリニック検索レスポンス"""

    clinics: list[ClinicSummary]
    total: int
    page: int = 1
    per_page: int = 20


class ClinicDetailResponse(BaseModel):
    """クリニック詳細レスポンス"""

    clinic: Clinic
    doctors: list[Doctor] = []
    reviews: list[Review] = []
    similar_clinics: list[ClinicSummary] = []
