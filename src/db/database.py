"""
AURA MVP — SQLAlchemyデータベースモデルとセッション管理

設計方針:
- 外部キー制約で参照整合性を保証
- 全テーブルにデータ来歴（provenance）カラム
- 変更監査ログで更新履歴を追跡
- 複合インデックスで検索性能を確保
- SQLiteをメインDBとして使用。PostgreSQL移行を想定した設計
"""

import json
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Index,
    Integer, String, Text, UniqueConstraint, event,
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

from src.config import settings

# 非同期エンジン（外部キー制約を有効化）
async_engine = create_async_engine(settings.database_url, echo=settings.debug)

# SQLite接続時にforeign_keysを有効化
@event.listens_for(async_engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    """SQLiteの外部キー制約を有効にする"""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")  # 並行読み取り性能向上
    cursor.close()


AsyncSessionLocal = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """SQLAlchemy宣言的ベースクラス"""
    pass


# ==========================================
# クリニック
# ==========================================

class ClinicTable(Base):
    """
    クリニックテーブル

    データソース:
    - Layer A: 厚生労働省 医療施設調査（mhlw_code で識別）
    - Layer B: Google Places API（google_place_id で識別）
    - Layer C: AURA独自分析（transparency_score 等）
    """

    __tablename__ = "clinics"
    __table_args__ = (
        # 検索パターンに合わせた複合インデックス
        Index("ix_clinics_city_dept", "city", "is_active"),
        Index("ix_clinics_pref_city", "prefecture", "city"),
        Index("ix_clinics_source_fetched", "source", "fetched_at"),
    )

    id = Column(String(26), primary_key=True)  # ULID
    name = Column(String(200), nullable=False, index=True)
    branch_name = Column(String(100))
    chain_name = Column(String(100), index=True)
    address = Column(Text, nullable=False)
    prefecture = Column(String(10), nullable=False, default="東京都", index=True)
    city = Column(String(50), index=True)
    postal_code = Column(String(10))
    lat = Column(Float)
    lng = Column(Float)
    phone = Column(String(20))
    website = Column(String(500))

    # 厚労省データ（Layer A）
    mhlw_code = Column(String(20), unique=True, index=True)
    medical_departments = Column(Text)  # JSON配列
    doctor_count = Column(Integer)
    medical_corp_name = Column(String(200))
    established_date = Column(String(20))
    bed_count = Column(Integer, default=0)
    facility_standards = Column(Text)  # JSON配列

    # Google Mapsデータ（Layer B）
    google_place_id = Column(String(100), unique=True, index=True)
    google_rating = Column(Float)
    google_review_count = Column(Integer)
    google_photos = Column(Text)  # JSON配列
    opening_hours = Column(Text)  # JSON
    editorial_summary = Column(Text)

    # AURA分析データ（Layer C）
    transparency_score = Column(Float)
    clinic_score = Column(Float)  # 総合スコア（0-100）
    clinic_grade = Column(String(2))  # グレード（A/B/C/D/E）
    clinic_score_breakdown = Column(Text)  # JSON: 各軸のスコア内訳
    price_level = Column(String(20))
    procedures_offered = Column(Text)  # JSON配列
    specialties = Column(Text)  # JSON配列

    # データ来歴（Provenance）
    source = Column(String(20), nullable=False, default="mhlw")
    source_version = Column(String(30), default="")
    fetched_at = Column(DateTime, default=datetime.now)
    verified_at = Column(DateTime)
    verified_by = Column(String(20), default="system")
    confidence = Column(Float, default=1.0)
    publish_status = Column(String(20), default="verified")  # verified / stale / hidden
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # リレーション
    doctors = relationship("DoctorTable", back_populates="clinic", cascade="all, delete-orphan")
    reviews = relationship("ReviewTable", back_populates="clinic", cascade="all, delete-orphan")
    case_photos = relationship("CasePhotoTable", back_populates="clinic", cascade="all, delete-orphan")
    clinic_procedures = relationship("ClinicProcedure", backref="clinic", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        """辞書形式に変換（JSON列をパース）"""
        result = {}
        for column in self.__table__.columns:
            value = getattr(self, column.name)
            if column.name in (
                "medical_departments",
                "facility_standards",
                "google_photos",
                "procedures_offered",
                "specialties",
            ):
                result[column.name] = json.loads(value) if value else []
            elif column.name in ("opening_hours",):
                result[column.name] = json.loads(value) if value else None
            else:
                result[column.name] = value
        return result


# ==========================================
# 医師
# ==========================================

class DoctorTable(Base):
    """医師テーブル"""

    __tablename__ = "doctors"

    id = Column(String(26), primary_key=True)
    clinic_id = Column(
        String(26),
        ForeignKey("clinics.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name = Column(String(100), nullable=False, index=True)
    title = Column(String(50))
    specialties = Column(Text)  # JSON配列
    board_certifications = Column(Text)  # JSON配列
    experience_years = Column(Integer)
    profile_url = Column(String(500))
    photo_url = Column(String(500))  # 医師プロフィール写真URL

    # SNSアカウント（v4: Phase 4で追加）
    instagram_url = Column(String(500))
    twitter_url = Column(String(500))
    tiktok_url = Column(String(500))
    youtube_url = Column(String(500))

    # 信頼性スコア（doctor_scoring.pyで算出）
    trust_score = Column(Float)  # 総合スコア（0-100）
    trust_score_breakdown = Column(Text)  # JSON: 各軸のスコア内訳
    hospital_background = Column(Text)  # 勤務経歴（大学病院・基幹病院等）
    annual_case_count = Column(Integer)  # 年間症例数（公開データがある場合）
    jsaps_certified = Column(Boolean, default=False)  # JSAPS専門医資格

    # データ来歴
    source = Column(String(20), default="manual")
    fetched_at = Column(DateTime, default=datetime.now)
    created_at = Column(DateTime, default=datetime.now)
    is_active = Column(Boolean, default=True)  # 無効化された医師データ（ゴミデータ等）

    # リレーション
    clinic = relationship("ClinicTable", back_populates="doctors")
    case_photos = relationship("CasePhotoTable", back_populates="doctor")


# ==========================================
# 症例写真
# ==========================================

class CasePhotoTable(Base):
    """
    症例写真テーブル

    各クリニック・医師の施術Before/After写真を管理。
    beauty-search スクレイパーで収集したデータを格納する。
    """

    __tablename__ = "case_photos"
    __table_args__ = (
        Index("ix_case_photos_clinic", "clinic_id"),
        Index("ix_case_photos_doctor", "doctor_id"),
        Index("ix_case_photos_category", "category"),
        Index("ix_case_photos_source", "source"),
        Index("ix_case_photos_source_id", "source_case_id"),
    )

    id = Column(String(26), primary_key=True)  # ULID
    clinic_id = Column(
        String(26),
        ForeignKey("clinics.id", ondelete="SET NULL"),
        index=True,
    )
    doctor_id = Column(
        String(26),
        ForeignKey("doctors.id", ondelete="SET NULL"),
        index=True,
    )
    procedure_id = Column(
        String(26),
        ForeignKey("procedures.id", ondelete="SET NULL"),
        index=True,
    )

    # 症例写真データ
    category = Column(String(20), nullable=False)  # eyes/nose/skin/jawline/body/other
    procedure_name = Column(String(200))  # 施術名
    before_image_url = Column(String(500))  # ビフォー画像URL
    after_image_url = Column(String(500))  # アフター画像URL
    source_url = Column(String(500))  # 症例詳細ページURL
    description = Column(Text)  # 症例説明・コメント
    price = Column(String(100))  # 施術価格（表示用文字列）

    # メタデータ
    doctor_name = Column(String(100))  # 担当医師名（名寄せ前の生データ）
    clinic_name = Column(String(200))  # クリニック名（名寄せ前の生データ）
    source_case_id = Column(String(100))  # 元サイトの症例ID

    # データ来歴（Provenance）
    source = Column(String(20), nullable=False)  # sbc/tcb/shinagawa/tribeau
    fetched_at = Column(DateTime, default=datetime.now)
    created_at = Column(DateTime, default=datetime.now)
    is_active = Column(Boolean, default=True)

    # リレーション
    clinic = relationship("ClinicTable", back_populates="case_photos")
    doctor = relationship("DoctorTable", back_populates="case_photos")
    procedure = relationship("ProcedureTable", back_populates="case_photos")


# ==========================================
# 口コミ
# ==========================================

class ReviewTable(Base):
    """口コミテーブル"""

    __tablename__ = "reviews"
    __table_args__ = (
        Index("ix_reviews_clinic_source", "clinic_id", "source"),
        Index("ix_reviews_created", "created_at"),
    )

    id = Column(String(26), primary_key=True)
    clinic_id = Column(
        String(26),
        ForeignKey("clinics.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    procedure_id = Column(
        String(26),
        ForeignKey("procedures.id", ondelete="SET NULL"),
        index=True,
    )
    source = Column(String(20), nullable=False, index=True)  # google/aura/manual
    author_name = Column(String(100))
    text = Column(Text, nullable=False)
    rating = Column(Float)

    # AURA分析
    sentiment_score = Column(Float)
    aspects = Column(Text)  # JSON
    is_spam = Column(Boolean)
    created_at = Column(DateTime)
    analyzed_at = Column(DateTime)

    # Phase 12: 口コミ分析深化
    doctor_id = Column(String(26), ForeignKey("doctors.id", ondelete="SET NULL"), index=True)
    red_flags = Column(Text)  # JSON: レッドフラグカテゴリ配列
    quality_score = Column(Float)  # 口コミ品質スコア 0-100

    # リレーション
    clinic = relationship("ClinicTable", back_populates="reviews")
    procedure = relationship("ProcedureTable", back_populates="reviews")
    doctor = relationship("DoctorTable", backref="reviews")


# ==========================================
# 施術マスタ
# ==========================================

class ProcedureTable(Base):
    """
    施術マスタテーブル

    AURA Naviの施術データをDB化。
    価格・リスク・カウンセリング質問は全てJSON列で格納。
    """

    __tablename__ = "procedures"
    __table_args__ = (
        Index("ix_proc_cat_inv", "category", "invasiveness"),
        UniqueConstraint("name", "category", name="uq_proc_name_cat"),
    )

    id = Column(String(26), primary_key=True)
    name = Column(String(100), nullable=False, index=True)
    category = Column(String(20), nullable=False, index=True)
    category_label = Column(String(20))
    description = Column(Text)
    invasiveness = Column(String(20), default="moderate")
    duration_type = Column(String(20), default="one-time")
    duration = Column(String(50))
    recommended_sessions = Column(Integer)
    matches_concern = Column(Text)  # JSON配列

    # 価格データ
    advertised_price = Column(Text)  # JSON (PriceRange)
    real_price = Column(Text)  # JSON (PriceRange)
    price_gap_note = Column(Text)
    hidden_costs = Column(Text)  # JSON配列

    # ダウンタイム
    downtime_official = Column(String(100))
    downtime_real = Column(String(100))
    recovery_phases = Column(Text)  # JSON配列

    # リスク・適性
    risks = Column(Text)  # JSON配列
    suitable_for = Column(Text)  # JSON配列
    not_suitable_for = Column(Text)  # JSON配列
    counseling_questions = Column(Text)  # JSON配列
    satisfaction = Column(Text)  # JSON: 満足度・後悔データ

    # データ品質管理
    evidence_level = Column(String(30), default="unverified")  # guideline / cross_checked / single_source / unverified
    price_sources = Column(Text)  # JSON: 価格データの出典一覧
    last_verified_date = Column(DateTime)  # 最後に内容を確認した日
    publish_status = Column(String(20), default="draft")  # draft / verified / stale / hidden

    # データ来歴
    source = Column(String(20), default="navi")
    source_version = Column(String(30), default="")
    fetched_at = Column(DateTime, default=datetime.now)
    verified_at = Column(DateTime)
    confidence = Column(Float, default=1.0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # リレーション
    reviews = relationship("ReviewTable", back_populates="procedure")
    clinic_procedures = relationship("ClinicProcedure", backref="procedure", cascade="all, delete-orphan")
    case_photos = relationship("CasePhotoTable", back_populates="procedure")



# ==========================================
# クリニック↔施術 中間テーブル
# ==========================================

class ClinicProcedure(Base):
    """
    クリニック↔施術 中間テーブル

    どのクリニックでどの施術がいくらで受けられるかを管理。
    価格情報の出典と取得日を必ず記録する。
    """

    __tablename__ = "clinic_procedures"
    __table_args__ = (
        UniqueConstraint("clinic_id", "procedure_id", name="uq_clinic_procedure"),
        Index("ix_cp_procedure", "procedure_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    clinic_id = Column(String(26), ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False, index=True)
    procedure_id = Column(String(26), ForeignKey("procedures.id", ondelete="CASCADE"), nullable=False)
    price_advertised = Column(Integer)  # 広告価格（円）
    price_actual = Column(Integer)  # 実際の提示価格（円）
    price_display = Column(String(100))  # 表示用の価格文字列
    source = Column(String(50))  # 価格情報の出典（公式サイト等）
    fetched_at = Column(DateTime, default=datetime.now)
    is_active = Column(Boolean, default=True)


# ==========================================
# 変更監査ログ
# ==========================================

class AuditLog(Base):
    """
    変更監査ログ

    データの追加・更新・削除を全て記録する。
    誰が・いつ・何を・どう変えたかを追跡可能。
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_table_record", "table_name", "record_id"),
        Index("ix_audit_timestamp", "timestamp"),
        Index("ix_audit_action", "action"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    table_name = Column(String(50), nullable=False)
    record_id = Column(String(26), nullable=False)
    action = Column(String(10), nullable=False)  # insert / update / delete
    changed_fields = Column(Text)  # JSON: {"field": {"old": x, "new": y}}
    changed_by = Column(String(50), default="system")
    source = Column(String(20))  # どのデータソースからの変更か
    timestamp = Column(DateTime, nullable=False, default=datetime.now)


# ==========================================
# データバージョン管理
# ==========================================

class DataVersion(Base):
    """
    データバージョン管理

    各データソースの最新バージョンと取得状態を追跡。
    鮮度管理・差分更新の基盤。
    """

    __tablename__ = "data_versions"
    __table_args__ = (
        UniqueConstraint("source", "version_key", name="uq_source_version"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(20), nullable=False, index=True)  # mhlw / google / navi
    version_key = Column(String(50), nullable=False)  # バージョン識別子
    record_count = Column(Integer, default=0)
    status = Column(String(20), default="completed")  # completed / partial / failed
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    error_message = Column(Text)
    metadata_json = Column(Text)  # JSON: 取得パラメータ等


# ==========================================
# セッション・初期化
# ==========================================

async def get_db() -> AsyncSession:
    """DBセッション取得（FastAPI Depends用）"""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    """DB初期化（テーブル作成）"""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
