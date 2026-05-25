"""
AURA MVP データモデル — 施術知識

既存AURA Navi（28施術）のデータ構造を正規化。
施術の一般的情報・価格帯・リスク・ダウンタイム・カウンセリング質問を管理。
"""

from pydantic import BaseModel, Field
from ulid import ULID


def generate_id() -> str:
    """ULIDベースのユニークID生成"""
    return str(ULID())


class PriceRange(BaseModel):
    """価格帯"""

    min_price: int = Field(..., description="最低価格（円）")
    max_price: int = Field(..., description="最高価格（円）")
    typical_price: int | None = Field(None, description="一般的な価格（円）")
    note: str | None = Field(None, description="価格備考")


class HiddenCost(BaseModel):
    """隠れコスト"""

    name: str = Field(..., description="費用名（麻酔費、アフターケア費等）")
    estimated_range: str | None = Field(None, description="概算範囲")
    is_common: bool = Field(default=True, description="一般的に発生するか")


class Risk(BaseModel):
    """リスク情報"""

    name: str = Field(..., description="リスク名")
    severity: str = Field(default="moderate", description="深刻度（mild/moderate/severe）")
    frequency: str | None = Field(None, description="発生頻度")
    description: str | None = Field(None, description="詳細説明")


class RecoveryPhase(BaseModel):
    """回復フェーズ（術後ケアタイムライン）"""

    phase_name: str = Field(..., description="フェーズ名（直後、1日目、1週間等）")
    day_start: int = Field(..., description="開始日（術後0日目=0）")
    day_end: int | None = Field(None, description="終了日")
    symptoms: list[str] = Field(default_factory=list, description="予想される症状")
    dos: list[str] = Field(default_factory=list, description="やるべきこと")
    donts: list[str] = Field(default_factory=list, description="避けるべきこと")


class Procedure(BaseModel):
    """施術データモデル（AURA Navi data.js準拠）"""

    id: str = Field(default_factory=generate_id)
    name: str = Field(..., description="施術名")
    category: str = Field(..., description="カテゴリ（eye/nose/skin/contour）")
    category_label: str = Field(default="", description="カテゴリ表示名（目元/鼻/肌/輪郭）")
    description: str | None = Field(None, description="施術の概要説明")

    # 施術特性
    invasiveness: str = Field(
        default="moderate", description="侵襲度（non-invasive/minimal/moderate/high）"
    )
    duration_type: str = Field(
        default="one-time", description="施術タイプ（one-time/series/maintenance）"
    )
    duration: str | None = Field(None, description="施術時間")
    recommended_sessions: int | None = Field(None, description="推奨回数（シリーズ施術の場合）")

    # 対象・悩み
    matches_concern: list[str] = Field(default_factory=list, description="対応する悩み")

    # 価格情報（AURA最大の差別化ポイント）
    advertised_price: PriceRange | None = Field(None, description="広告価格")
    real_price: PriceRange | None = Field(None, description="実勢価格")
    price_gap_note: str | None = Field(None, description="価格乖離の説明")
    hidden_costs: list[HiddenCost] = Field(default_factory=list, description="隠れコスト一覧")

    # ダウンタイム（AURA独自：公式 vs リアル）
    downtime_official: str | None = Field(None, description="公式ダウンタイム")
    downtime_real: str | None = Field(None, description="リアルダウンタイム")
    recovery_phases: list[RecoveryPhase] = Field(
        default_factory=list, description="回復フェーズ（タイムライン）"
    )

    # リスク・適性
    risks: list[Risk] = Field(default_factory=list, description="リスク一覧")
    suitable_for: list[str] = Field(default_factory=list, description="向いている人")
    not_suitable_for: list[str] = Field(default_factory=list, description="向いていない人")

    # カウンセリング支援
    counseling_questions: list[str] = Field(
        default_factory=list, description="カウンセリングで聞くべき質問"
    )


class ProcedureCategory(BaseModel):
    """施術カテゴリ"""

    id: str = Field(..., description="カテゴリID（eye/nose/skin/contour）")
    label: str = Field(..., description="表示名")
    description: str | None = None
    icon: str | None = None
    procedure_count: int = 0


PROCEDURE_CATEGORIES = [
    ProcedureCategory(id="eye", label="目元", description="二重・目の下・眉下等", procedure_count=8),
    ProcedureCategory(id="nose", label="鼻", description="鼻筋・小鼻・鼻先等", procedure_count=6),
    ProcedureCategory(
        id="skin", label="肌", description="シミ・しわ・毛穴・たるみ等", procedure_count=8
    ),
    ProcedureCategory(
        id="contour",
        label="輪郭・小顔",
        description="エラ・あご・頬・フェイスライン",
        procedure_count=6,
    ),
]
