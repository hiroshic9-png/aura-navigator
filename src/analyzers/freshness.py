"""
AURA MVP — データ鮮度・正確性管理エンジン

全てのデータに「いつ・どこから・どう検証されたか」を追跡し、
陳腐化を自動検出する。美容医療情報は患者の意思決定に直結するため、
不正確・古いデータの提供は事業の信頼性を根底から破壊する。

設計原則:
1. 全レコードにデータ来歴（provenance）を付与
2. ソースごとの鮮度ポリシーを定義（厚労省=半年、Google=2週間）
3. 陳腐化レコードを自動検出し、APIレスポンスにフラグ付与
4. クロスソース検証で矛盾を検出
"""

import json
import logging
from datetime import datetime, timedelta
from enum import Enum

from pydantic import BaseModel, Field
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text, select, func
from sqlalchemy.ext.asyncio import AsyncSession

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================
# 鮮度ポリシー定義
# ============================================================


class DataSource(str, Enum):
    """データソース種別"""

    MHLW = "mhlw"  # 厚労省オープンデータ
    GOOGLE = "google"  # Google Maps Places API
    NAVI = "navi"  # AURA Navi（施術知識）
    MANUAL = "manual"  # 手動入力
    AURA_UGC = "aura_ugc"  # AURA独自口コミ


class FreshnessPolicy(BaseModel):
    """データソースごとの鮮度ポリシー"""

    source: DataSource
    max_age_days: int = Field(..., description="データの最大有効期間（日）")
    refresh_interval_days: int = Field(..., description="推奨更新間隔（日）")
    description: str = ""


# ソースごとの鮮度ポリシー
FRESHNESS_POLICIES: dict[str, FreshnessPolicy] = {
    DataSource.MHLW: FreshnessPolicy(
        source=DataSource.MHLW,
        max_age_days=180,  # 厚労省データは半年で陳腐化（年2回更新想定）
        refresh_interval_days=90,  # 3ヶ月ごとに再取得推奨
        description="厚労省医療情報ネットのオープンデータ。半期更新。",
    ),
    DataSource.GOOGLE: FreshnessPolicy(
        source=DataSource.GOOGLE,
        max_age_days=30,  # Google評価は1ヶ月で変動する可能性
        refresh_interval_days=14,  # 2週間ごとに再取得
        description="Google Maps Places API。評価・口コミは頻繁に変動。",
    ),
    DataSource.NAVI: FreshnessPolicy(
        source=DataSource.NAVI,
        max_age_days=365,  # 施術の一般知識は年1回見直し
        refresh_interval_days=180,
        description="AURA Naviの施術知識データ。医学的情報は慎重に更新。",
    ),
    DataSource.MANUAL: FreshnessPolicy(
        source=DataSource.MANUAL,
        max_age_days=90,  # 手動入力は3ヶ月で要再検証
        refresh_interval_days=30,
        description="手動入力・エンリッチメントデータ。定期的な確認が必要。",
    ),
    DataSource.AURA_UGC: FreshnessPolicy(
        source=DataSource.AURA_UGC,
        max_age_days=730,  # UGCは2年間有効
        refresh_interval_days=365,
        description="ユーザー投稿口コミ。投稿自体は変わらないが参照価値は経年劣化。",
    ),
}


# ============================================================
# データ来歴（Provenance）
# ============================================================


class DataProvenance(BaseModel):
    """
    データ来歴: 各レコードの「出どころ」を完全追跡

    全レコードに付与し、「このデータはいつ・どこから・どう検証されたか」を記録。
    """

    source: DataSource = Field(..., description="データソース")
    source_version: str = Field(default="", description="ソースのバージョン（例: '20251201'）")
    source_url: str = Field(default="", description="取得元URL")
    fetched_at: datetime = Field(default_factory=datetime.now, description="取得日時")
    verified_at: datetime | None = Field(None, description="最終検証日時")
    verified_by: str = Field(default="system", description="検証者（system/manual/cross_check）")
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0, description="信頼度スコア（0.0-1.0）"
    )
    notes: str = Field(default="", description="備考")

    def is_stale(self) -> bool:
        """データが陳腐化しているか判定"""
        policy = FRESHNESS_POLICIES.get(self.source)
        if not policy:
            return False
        age = datetime.now() - self.fetched_at
        return age.days > policy.max_age_days

    def needs_refresh(self) -> bool:
        """データの更新が推奨されるか判定"""
        policy = FRESHNESS_POLICIES.get(self.source)
        if not policy:
            return False
        age = datetime.now() - self.fetched_at
        return age.days > policy.refresh_interval_days

    def freshness_status(self) -> str:
        """鮮度ステータスを返却（fresh/aging/stale）"""
        if self.is_stale():
            return "stale"  # 陳腐化: APIレスポンスに警告付与
        if self.needs_refresh():
            return "aging"  # 更新推奨: バックグラウンドで再取得キュー投入
        return "fresh"  # 新鮮: 問題なし

    def days_since_fetch(self) -> int:
        """取得からの経過日数"""
        return (datetime.now() - self.fetched_at).days


# ============================================================
# バリデーションエンジン
# ============================================================


class ValidationResult(BaseModel):
    """バリデーション結果"""

    is_valid: bool = True
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    field_completeness: float = Field(
        default=0.0, ge=0.0, le=1.0, description="フィールド充填率"
    )


class DataValidator:
    """
    データバリデーター

    クリニック・施術データの正確性を複数の観点で検証。
    """

    # クリニックの必須フィールド
    CLINIC_REQUIRED_FIELDS = ["name", "address", "prefecture"]
    # クリニックの推奨フィールド（充填率に影響）
    CLINIC_RECOMMENDED_FIELDS = [
        "name", "address", "prefecture", "city", "lat", "lng",
        "website", "phone", "medical_departments", "mhlw_code",
    ]

    # 施術の必須フィールド
    PROCEDURE_REQUIRED_FIELDS = ["name", "category"]
    # 施術の推奨フィールド
    PROCEDURE_RECOMMENDED_FIELDS = [
        "name", "category", "description", "advertised_price", "real_price",
        "downtime_official", "downtime_real", "risks", "counseling_questions",
    ]

    @staticmethod
    def validate_clinic(data: dict) -> ValidationResult:
        """クリニックデータのバリデーション"""
        result = ValidationResult()

        # 必須フィールド
        for field in DataValidator.CLINIC_REQUIRED_FIELDS:
            if not data.get(field):
                result.is_valid = False
                result.errors.append(f"必須フィールド '{field}' が未入力")

        # 座標の妥当性（東京近辺）
        lat = data.get("lat", 0)
        lng = data.get("lng", 0)
        if lat and lng:
            if not (34.5 <= lat <= 36.5 and 138.5 <= lng <= 140.5):
                result.warnings.append(
                    f"座標が東京都の範囲外: ({lat}, {lng})"
                )

        # 住所の妥当性
        address = data.get("address", "")
        if address and "東京都" not in address and data.get("prefecture") == "東京都":
            result.warnings.append("住所に都道府県名が含まれていない")

        # Webサイトの形式
        website = data.get("website", "")
        if website and not website.startswith(("http://", "https://")):
            result.warnings.append(f"WebサイトURLの形式が不正: {website[:50]}")

        # 充填率
        filled = sum(1 for f in DataValidator.CLINIC_RECOMMENDED_FIELDS if data.get(f))
        result.field_completeness = filled / len(DataValidator.CLINIC_RECOMMENDED_FIELDS)

        if result.field_completeness < 0.5:
            result.warnings.append(
                f"データ充填率が低い: {result.field_completeness:.0%}"
            )

        return result

    @staticmethod
    def validate_procedure(data: dict) -> ValidationResult:
        """施術データのバリデーション"""
        result = ValidationResult()

        for field in DataValidator.PROCEDURE_REQUIRED_FIELDS:
            if not data.get(field):
                result.is_valid = False
                result.errors.append(f"必須フィールド '{field}' が未入力")

        # カテゴリの妥当性
        valid_categories = {"eye", "nose", "skin", "contour"}
        category = data.get("category", "")
        if category and category not in valid_categories:
            result.warnings.append(f"不明なカテゴリ: {category}")

        # 価格の妥当性（広告価格 <= 実勢価格が一般的）
        adv = data.get("advertised_price", {})
        real = data.get("real_price", {})
        if adv and real:
            adv_min = adv.get("min_price", 0) if isinstance(adv, dict) else 0
            real_min = real.get("min_price", 0) if isinstance(real, dict) else 0
            if adv_min and real_min and adv_min > real_min * 1.5:
                result.warnings.append(
                    "広告価格が実勢最低価格の1.5倍超。データ確認推奨"
                )

        # 充填率
        filled = sum(1 for f in DataValidator.PROCEDURE_RECOMMENDED_FIELDS if data.get(f))
        result.field_completeness = filled / len(DataValidator.PROCEDURE_RECOMMENDED_FIELDS)

        return result


# ============================================================
# 鮮度チェッカー
# ============================================================


class FreshnessChecker:
    """
    データ鮮度チェッカー

    DB全体の鮮度状態を監視し、陳腐化レコードを検出する。
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def check_clinic_freshness(self) -> dict:
        """クリニックDBの鮮度レポートを生成"""
        from src.db.database import ClinicTable

        total = await self.db.scalar(select(func.count(ClinicTable.id)))
        now = datetime.now()

        # ソース別の集計
        source_stats = {}
        for source in DataSource:
            count = await self.db.scalar(
                select(func.count(ClinicTable.id)).where(ClinicTable.source == source.value)
            )
            if not count:
                continue

            policy = FRESHNESS_POLICIES.get(source)
            if not policy:
                continue

            # 陳腐化判定（created_atベース — last_verifiedが未設定の場合）
            stale_threshold = now - timedelta(days=policy.max_age_days)
            stale_count = await self.db.scalar(
                select(func.count(ClinicTable.id)).where(
                    ClinicTable.source == source.value,
                    ClinicTable.created_at < stale_threshold,
                )
            )

            refresh_threshold = now - timedelta(days=policy.refresh_interval_days)
            needs_refresh = await self.db.scalar(
                select(func.count(ClinicTable.id)).where(
                    ClinicTable.source == source.value,
                    ClinicTable.created_at < refresh_threshold,
                )
            )

            source_stats[source.value] = {
                "total": count,
                "stale": stale_count or 0,
                "needs_refresh": needs_refresh or 0,
                "fresh": (count or 0) - (needs_refresh or 0),
                "policy": {
                    "max_age_days": policy.max_age_days,
                    "refresh_interval_days": policy.refresh_interval_days,
                },
            }

        return {
            "total_clinics": total or 0,
            "checked_at": now.isoformat(),
            "by_source": source_stats,
        }

    async def get_stale_clinics(self, limit: int = 100) -> list[dict]:
        """陳腐化したクリニックのリストを取得"""
        from src.db.database import ClinicTable

        now = datetime.now()
        results = []

        for source in DataSource:
            policy = FRESHNESS_POLICIES.get(source)
            if not policy:
                continue

            threshold = now - timedelta(days=policy.max_age_days)
            query = (
                select(ClinicTable)
                .where(
                    ClinicTable.source == source.value,
                    ClinicTable.created_at < threshold,
                )
                .limit(limit)
            )
            result = await self.db.execute(query)
            for clinic in result.scalars():
                results.append({
                    "id": clinic.id,
                    "name": clinic.name,
                    "source": clinic.source,
                    "created_at": clinic.created_at.isoformat() if clinic.created_at else None,
                    "days_old": (now - clinic.created_at).days if clinic.created_at else None,
                    "status": "stale",
                })

        return results


# ============================================================
# APIレスポンス用の鮮度メタデータ
# ============================================================


class FreshnessMetadata(BaseModel):
    """APIレスポンスに付与するデータ鮮度メタデータ"""

    source: str = Field(..., description="データソース")
    source_version: str = Field(default="", description="ソースバージョン")
    fetched_at: str = Field(..., description="データ取得日時")
    freshness: str = Field(..., description="鮮度ステータス（fresh/aging/stale）")
    days_old: int = Field(..., description="取得からの経過日数")
    next_refresh: str = Field(default="", description="次回更新推奨日")
    confidence: float = Field(default=1.0, description="信頼度スコア")


def build_freshness_metadata(
    source: str,
    fetched_at: datetime | None,
    source_version: str = "",
) -> FreshnessMetadata:
    """レコードから鮮度メタデータを生成"""
    now = datetime.now()
    fetch_time = fetched_at or now

    provenance = DataProvenance(
        source=DataSource(source) if source in DataSource.__members__.values() else DataSource.MANUAL,
        source_version=source_version,
        fetched_at=fetch_time,
    )

    policy = FRESHNESS_POLICIES.get(provenance.source)
    next_refresh = ""
    if policy:
        next_date = fetch_time + timedelta(days=policy.refresh_interval_days)
        next_refresh = next_date.isoformat()

    return FreshnessMetadata(
        source=source,
        source_version=source_version,
        fetched_at=fetch_time.isoformat(),
        freshness=provenance.freshness_status(),
        days_old=provenance.days_since_fetch(),
        next_refresh=next_refresh,
        confidence=provenance.confidence,
    )
