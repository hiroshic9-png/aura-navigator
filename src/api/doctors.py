"""
AURA MVP — 医師情報API

医師の信頼性スコア、検索、統計を提供するAPIエンドポイント。
「どの先生が信頼できるか」を客観的データで患者に提示する。
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.analyzers.doctor_scoring import (
    get_trust_level,
    score_doctor_from_record,
)
from src.db.database import ClinicTable, DoctorTable, get_db
from src.utils.normalize import normalize_query

router = APIRouter()


def _format_doctor(doc: DoctorTable, clinic_info: dict | None = None) -> dict:
    """医師データのフォーマット"""
    # 信頼性スコア算出（未算出の場合はリアルタイム計算）
    if doc.trust_score is not None:
        score = doc.trust_score
    else:
        result = score_doctor_from_record(doc)
        score = result.total

    trust_level = get_trust_level(score)

    certifications = []
    if doc.board_certifications:
        try:
            certifications = json.loads(doc.board_certifications)
        except (json.JSONDecodeError, TypeError):
            certifications = []

    specialties = []
    if doc.specialties:
        try:
            specialties = json.loads(doc.specialties)
        except (json.JSONDecodeError, TypeError):
            specialties = []

    data = {
        "id": doc.id,
        "name": doc.name,
        "title": doc.title or "",
        "specialties": specialties,
        "certifications": certifications,
        "experience_years": doc.experience_years,
        "profile_url": doc.profile_url,
        "photo_url": getattr(doc, "photo_url", None),
        "trust_score": score,
        "trust_level": trust_level,
        "clinic_id": doc.clinic_id,
        "hospital_background": getattr(doc, "hospital_background", None),
        "jsaps_certified": getattr(doc, "jsaps_certified", False) or False,
    }

    if clinic_info:
        data["clinic"] = clinic_info

    return data


def _format_doctor_detail(doc: DoctorTable, clinic_info: dict | None = None) -> dict:
    """医師の詳細データフォーマット（スコア内訳付き）"""
    data = _format_doctor(doc, clinic_info=clinic_info)

    # スコア内訳を追加
    if doc.trust_score_breakdown:
        try:
            data["trust_score_breakdown"] = json.loads(doc.trust_score_breakdown)
        except (json.JSONDecodeError, TypeError):
            result = score_doctor_from_record(doc)
            data["trust_score_breakdown"] = result.to_dict()
    else:
        result = score_doctor_from_record(doc)
        data["trust_score_breakdown"] = result.to_dict()

    # 追加情報
    data["hospital_background"] = doc.hospital_background
    data["annual_case_count"] = doc.annual_case_count
    data["jsaps_certified"] = doc.jsaps_certified or False

    # SNSリンク（v4: Phase 4）
    data["sns"] = {
        "instagram": getattr(doc, "instagram_url", None),
        "twitter": getattr(doc, "twitter_url", None),
        "tiktok": getattr(doc, "tiktok_url", None),
        "youtube": getattr(doc, "youtube_url", None),
    }

    # データ品質ノート
    data["data_quality_note"] = _build_quality_note(data)

    return data


def _build_quality_note(data: dict) -> str:
    """データ品質に関する注記を生成"""
    score = data.get("trust_score", 0)
    if score >= 70:
        return "この医師の公開情報は充実しています。"
    elif score >= 40:
        return ("一部の情報は確認できますが、カウンセリング時に資格・経歴を"
                "直接確認されることをお勧めします。")
    elif score >= 20:
        return ("公開情報が限られています。スコアは「情報の開示度」を示す指標であり、"
                "医師の能力や技術を評価するものではありません。"
                "カウンセリングで直接お確かめください。")
    else:
        return "情報収集中です。カウンセリングで詳しくお聞きください。"


@router.get("/stats")
async def doctor_stats(db: AsyncSession = Depends(get_db)):
    """
    医師DB統計

    資格保有率、経験年数分布、スコア分布などの統計データ。
    """
    total = await db.scalar(select(func.count(DoctorTable.id))) or 0

    # 資格保有者数
    with_certs = await db.scalar(
        select(func.count(DoctorTable.id)).where(
            DoctorTable.board_certifications.isnot(None),
            DoctorTable.board_certifications != "",
            DoctorTable.board_certifications != "[]",
        )
    ) or 0

    # 経験年数あり
    with_experience = await db.scalar(
        select(func.count(DoctorTable.id)).where(
            DoctorTable.experience_years.isnot(None),
            DoctorTable.experience_years > 0,
        )
    ) or 0

    # スコア算出済み
    with_score = await db.scalar(
        select(func.count(DoctorTable.id)).where(
            DoctorTable.trust_score.isnot(None),
        )
    ) or 0

    # 平均スコア
    avg_score = await db.scalar(
        select(func.avg(DoctorTable.trust_score)).where(
            DoctorTable.trust_score.isnot(None),
        )
    )

    return {
        "total": total,
        "with_certifications": with_certs,
        "certification_rate": round(with_certs / total * 100, 1) if total > 0 else 0,
        "with_experience_years": with_experience,
        "with_trust_score": with_score,
        "avg_trust_score": round(avg_score, 1) if avg_score else None,
        "note": "スコアは「情報の開示度」を示す指標です。スコアが低い＝悪い医師ではありません。",
    }


@router.get("/search")
async def search_doctors(
    q: str = Query(..., min_length=1, description="検索キーワード（名前・資格・専門分野）"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """
    医師検索

    名前、資格、専門分野でフリーワード検索。
    """
    q = normalize_query(q)
    query = (
        select(DoctorTable)
        .where(
            DoctorTable.is_active != 0,
            or_(
                DoctorTable.name.contains(q),
                DoctorTable.board_certifications.contains(q),
                DoctorTable.specialties.contains(q),
            )
        )
        .order_by(DoctorTable.trust_score.desc().nullslast(), DoctorTable.name)
    )

    # 総数
    count_q = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_q) or 0

    # ページング
    offset = (page - 1) * per_page
    result = await db.execute(query.offset(offset).limit(per_page))
    doctors = result.scalars().all()

    # クリニック情報を一括取得
    clinic_ids = list({d.clinic_id for d in doctors if d.clinic_id})
    clinic_map = {}
    if clinic_ids:
        clinic_result = await db.execute(
            select(ClinicTable).where(ClinicTable.id.in_(clinic_ids))
        )
        for c in clinic_result.scalars().all():
            clinic_map[c.id] = {"id": c.id, "name": c.name, "city": c.city, "google_rating": c.google_rating}

    return {
        "doctors": [_format_doctor(d, clinic_info=clinic_map.get(d.clinic_id)) for d in doctors],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.get("/by-clinic/{clinic_id}")
async def doctors_by_clinic(
    clinic_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    クリニック別医師一覧

    指定クリニックに所属する全医師をスコア順で返却。
    """
    # クリニック存在確認
    clinic = await db.scalar(
        select(ClinicTable).where(ClinicTable.id == clinic_id)
    )
    if not clinic:
        raise HTTPException(status_code=404, detail="クリニックが見つかりません")

    result = await db.execute(
        select(DoctorTable)
        .where(DoctorTable.clinic_id == clinic_id)
        .order_by(DoctorTable.trust_score.desc().nullslast(), DoctorTable.title.desc())
    )
    doctors = result.scalars().all()

    return {
        "clinic": {
            "id": clinic.id,
            "name": clinic.name,
            "city": clinic.city,
        },
        "doctors": [_format_doctor(d) for d in doctors],
        "total": len(doctors),
    }


@router.get("/{doctor_id}")
async def get_doctor(doctor_id: str, db: AsyncSession = Depends(get_db)):
    """
    医師詳細取得

    信頼性スコアの内訳、勤務経歴、年間症例数を含む全情報を返却。
    """
    result = await db.execute(
        select(DoctorTable).where(DoctorTable.id == doctor_id)
    )
    doctor = result.scalar_one_or_none()

    if not doctor:
        raise HTTPException(status_code=404, detail="医師が見つかりません")

    # クリニック情報を取得
    clinic_info = None
    if doctor.clinic_id:
        clinic = await db.scalar(
            select(ClinicTable).where(ClinicTable.id == doctor.clinic_id)
        )
        if clinic:
            clinic_info = {"id": clinic.id, "name": clinic.name, "city": clinic.city, "google_rating": clinic.google_rating}

    return _format_doctor_detail(doctor, clinic_info=clinic_info)


@router.get("/")
async def list_doctors(
    city: str | None = Query(None, description="エリアフィルタ（例: 新宿区）"),
    has_certification: bool | None = Query(None, description="専門医資格保有者のみ"),
    min_score: float | None = Query(None, ge=0, le=100, description="最低情報開示スコア"),
    show_all: bool = Query(False, description="情報収集中の医師も含めて全件表示"),
    sort_by: str = Query("score", description="ソート基準（score/name/experience）"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """
    医師一覧取得

    デフォルトでは情報確認済み（スコア20以上 or 資格情報あり）の医師のみ表示。
    show_all=true で全医師を表示。
    """
    query = select(DoctorTable).where(DoctorTable.is_active != 0).join(ClinicTable, DoctorTable.clinic_id == ClinicTable.id)

    # デフォルト: 情報確認済みの医師のみ（情報収集中の洪水を防止）
    if not show_all and min_score is None:
        query = query.where(
            or_(
                DoctorTable.trust_score >= 20,
                # trust_score未算出でも資格情報があれば表示
                DoctorTable.board_certifications.isnot(None),
                DoctorTable.board_certifications != "",
                DoctorTable.board_certifications != "[]",
            )
        )

    # エリアフィルタ
    if city:
        query = query.where(ClinicTable.city == city)

    # 専門医資格フィルタ
    if has_certification is True:
        query = query.where(
            DoctorTable.board_certifications.isnot(None),
            DoctorTable.board_certifications != "",
            DoctorTable.board_certifications != "[]",
        )

    # 最低スコアフィルタ
    if min_score is not None:
        query = query.where(DoctorTable.trust_score >= min_score)

    # ソート
    if sort_by == "experience":
        query = query.order_by(DoctorTable.experience_years.desc().nullslast())
    elif sort_by == "name":
        query = query.order_by(DoctorTable.name)
    else:  # score（デフォルト）
        query = query.order_by(DoctorTable.trust_score.desc().nullslast(), DoctorTable.name)

    # 総数
    count_q = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_q) or 0

    # ページング
    offset = (page - 1) * per_page
    result = await db.execute(query.offset(offset).limit(per_page))
    doctors = result.scalars().all()

    # クリニック情報を一括取得
    clinic_ids = list({d.clinic_id for d in doctors if d.clinic_id})
    clinic_map = {}
    if clinic_ids:
        clinic_result = await db.execute(
            select(ClinicTable).where(ClinicTable.id.in_(clinic_ids))
        )
        for c in clinic_result.scalars().all():
            clinic_map[c.id] = {"id": c.id, "name": c.name, "city": c.city, "google_rating": c.google_rating}

    return {
        "doctors": [_format_doctor(d, clinic_info=clinic_map.get(d.clinic_id)) for d in doctors],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
        "note": "スコアは「情報の透明性」を示す指標です。スコアが低い＝悪い医師ではありません。",
    }
