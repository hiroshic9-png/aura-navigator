"""
AURA MVP — クリニック検索API

東京の美容クリニックを検索・比較するためのAPIエンドポイント。
"""

import json
from collections import Counter
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import Integer, exists, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import ClinicProcedure, ClinicTable, get_db
from src.utils.normalize import normalize_query

router = APIRouter()


@router.get("/")
async def search_clinics(
    q: str | None = Query(None, description="フリーワード検索（クリニック名、住所等）"),
    city: str | None = Query(None, description="市区町村フィルタ（例: 新宿区）"),
    department: str | None = Query(None, description="診療科目フィルタ（美容外科/形成外科/美容皮膚科）"),
    grade: str | None = Query(None, description="AURAグレードフィルタ（A/B/C/D/E）"),
    min_rating: float | None = Query(None, ge=1.0, le=5.0, description="最低Google評価"),
    has_website: bool | None = Query(None, description="Webサイトの有無"),
    price_min: int | None = Query(None, ge=0, description="最低価格（円）"),
    price_max: int | None = Query(None, ge=0, description="最高価格（円）"),
    sort_by: str = Query("score", description="ソート基準（score/name/rating/review_count）"),
    page: int = Query(1, ge=1, description="ページ番号"),
    per_page: int = Query(20, ge=1, le=100, description="1ページあたりの件数"),
    db: AsyncSession = Depends(get_db),
):
    """
    クリニック検索

    東京都内の美容クリニックを条件指定で検索。
    厚労省オープンデータ + Google Maps APIの統合データから結果を返却。
    """
    query = select(ClinicTable).where(ClinicTable.is_active == True)

    # フリーワード検索
    if q:
        q = normalize_query(q)
        query = query.where(
            or_(
                ClinicTable.name.contains(q),
                ClinicTable.address.contains(q),
                ClinicTable.chain_name.contains(q),
            )
        )

    # 市区町村フィルタ
    if city:
        query = query.where(ClinicTable.city == city)

    # 診療科目フィルタ
    if department:
        query = query.where(ClinicTable.medical_departments.contains(department))

    # Google評価フィルタ
    if min_rating is not None:
        query = query.where(ClinicTable.google_rating >= min_rating)

    # Webサイト有無
    if has_website is not None:
        if has_website:
            query = query.where(ClinicTable.website != "", ClinicTable.website.isnot(None))
        else:
            query = query.where(
                or_(ClinicTable.website == "", ClinicTable.website.is_(None))
            )

    # グレードフィルタ
    if grade:
        query = query.where(ClinicTable.clinic_grade == grade)

    # 価格帯フィルタ（clinic_procedures内に指定範囲の施術があるクリニックに絞込）
    if price_min is not None or price_max is not None:
        price_condition = (
            (ClinicProcedure.clinic_id == ClinicTable.id)
            & (ClinicProcedure.is_active == True)
            & (ClinicProcedure.price_advertised.isnot(None))
            & (ClinicProcedure.price_advertised > 0)
        )
        if price_min is not None:
            price_condition = price_condition & (ClinicProcedure.price_advertised >= price_min)
        if price_max is not None:
            price_condition = price_condition & (ClinicProcedure.price_advertised <= price_max)
        query = query.where(exists().where(price_condition))


    if sort_by == "score":
        query = query.order_by(ClinicTable.clinic_score.desc().nullslast())
    elif sort_by == "rating":
        query = query.order_by(ClinicTable.google_rating.desc().nullslast())
    elif sort_by == "review_count":
        query = query.order_by(ClinicTable.google_review_count.desc().nullslast())
    else:
        query = query.order_by(ClinicTable.name)

    # 総数取得
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)

    # ページング
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)

    result = await db.execute(query)
    clinics = result.scalars().all()

    # Phase 62: リスト用の軽量トレンドデータをバッチ取得（N+1回避）
    clinic_trends = await _batch_trend_directions(
        [c.id for c in clinics], db
    )

    clinic_list = []
    for c in clinics:
        item = _format_clinic(c, list_mode=True)
        trend_dir = clinic_trends.get(c.id)
        if trend_dir:
            item["recent_trend"] = {"direction": trend_dir}
        clinic_list.append(item)

    return {
        "clinics": clinic_list,
        "total": total or 0,
        "page": page,
        "per_page": per_page,
        "total_pages": ((total or 0) + per_page - 1) // per_page,
        "data_freshness": {
            "source": "mhlw",
            "source_version": "20251201",
            "note": "厚労省医療情報ネット 2025年12月1日時点データ",
        },
    }


@router.get("/stats")
async def clinic_stats(db: AsyncSession = Depends(get_db)):
    """
    クリニックDB統計情報

    区別・診療科別の集計データを返却。
    """
    # 総数
    total = await db.scalar(select(func.count(ClinicTable.id)))

    # 区別集計
    city_result = await db.execute(
        select(ClinicTable.city, func.count(ClinicTable.id))
        .where(ClinicTable.city != "", ClinicTable.city.isnot(None))
        .group_by(ClinicTable.city)
        .order_by(func.count(ClinicTable.id).desc())
        .limit(25)
    )
    by_city = [{"city": row[0], "count": row[1]} for row in city_result.all()]

    # Webサイト有無
    with_website = await db.scalar(
        select(func.count(ClinicTable.id)).where(
            ClinicTable.website != "", ClinicTable.website.isnot(None)
        )
    )

    # 座標有無
    with_coords = await db.scalar(
        select(func.count(ClinicTable.id)).where(
            ClinicTable.lat != 0, ClinicTable.lng != 0
        )
    )

    # Google評価あり
    with_rating = await db.scalar(
        select(func.count(ClinicTable.id)).where(ClinicTable.google_rating.isnot(None))
    )

    # 鮮度チェック
    from src.analyzers.freshness import FreshnessChecker
    checker = FreshnessChecker(db)
    freshness_report = await checker.check_clinic_freshness()

    # グレード分布
    grade_result = await db.execute(
        select(ClinicTable.clinic_grade, func.count(ClinicTable.id))
        .where(ClinicTable.clinic_grade.isnot(None))
        .group_by(ClinicTable.clinic_grade)
    )
    grade_dist = {r[0]: r[1] for r in grade_result.all()}

    # チェーン統計
    chain_count = await db.scalar(
        select(func.count(func.distinct(ClinicTable.chain_name)))
        .where(ClinicTable.chain_name.isnot(None), ClinicTable.chain_name != "")
    ) or 0
    chain_clinics = await db.scalar(
        select(func.count(ClinicTable.id))
        .where(ClinicTable.chain_name.isnot(None), ClinicTable.chain_name != "")
    ) or 0

    return {
        "total": total or 0,
        "with_website": with_website or 0,
        "with_coordinates": with_coords or 0,
        "with_google_rating": with_rating or 0,
        "by_city": by_city,
        "grade_distribution": grade_dist,
        "chain_stats": {
            "chain_count": chain_count,
            "chain_clinics": chain_clinics,
            "independent_clinics": (total or 0) - chain_clinics,
        },
        "data_source": "mhlw_opendata_20251201",
        "freshness": freshness_report,
    }


@router.get("/chain-analysis")
async def chain_analysis(db: AsyncSession = Depends(get_db)):
    """
    チェーン別分析

    大手チェーン/個人院の評価・スコア比較データを返却。
    「チェーンだから安心」「個人院だから不安」という誤解を
    データで解消するための客観比較。
    """
    # チェーン別統計
    chain_result = await db.execute(
        select(
            ClinicTable.chain_name,
            func.count(ClinicTable.id).label("count"),
            func.avg(ClinicTable.google_rating).label("avg_rating"),
            func.avg(ClinicTable.clinic_score).label("avg_score"),
            func.avg(ClinicTable.google_review_count).label("avg_reviews"),
        )
        .where(ClinicTable.is_active == True)
        .where(ClinicTable.chain_name.isnot(None), ClinicTable.chain_name != "")
        .group_by(ClinicTable.chain_name)
        .having(func.count(ClinicTable.id) >= 2)
        .order_by(func.count(ClinicTable.id).desc())
    )
    chains = []
    for r in chain_result.all():
        chains.append({
            "chain_name": r[0],
            "clinic_count": r[1],
            "avg_google_rating": round(r[2], 2) if r[2] else None,
            "avg_clinic_score": round(r[3], 1) if r[3] else None,
            "avg_review_count": int(r[4]) if r[4] else 0,
        })

    # 個人院平均
    ind_result = await db.execute(
        select(
            func.count(ClinicTable.id),
            func.avg(ClinicTable.google_rating),
            func.avg(ClinicTable.clinic_score),
            func.avg(ClinicTable.google_review_count),
        )
        .where(ClinicTable.is_active == True)
        .where(or_(ClinicTable.chain_name.is_(None), ClinicTable.chain_name == ""))
    )
    ind = ind_result.one()

    return {
        "chains": chains,
        "independent": {
            "clinic_count": ind[0] or 0,
            "avg_google_rating": round(ind[1], 2) if ind[1] else None,
            "avg_clinic_score": round(ind[2], 1) if ind[2] else None,
            "avg_review_count": int(ind[3]) if ind[3] else 0,
        },
        "note": "チェーン/個人院の区別は客観比較のためであり、優劣の判断ではありません。",
    }

@router.get("/area-stats")
async def get_area_stats(db: AsyncSession = Depends(get_db)):
    """
    エリア統計API

    区（city）別にクリニック数・評価・医師・口コミ等の統計データを返却。
    上位15エリア（クリニック数降順）を返す。
    """
    from src.db.database import DoctorTable, ReviewTable, ClinicProcedure, ProcedureTable

    # === 基本統計: クリニック数・平均評価・平均透明性スコア（city別） ===
    base_stats_result = await db.execute(
        select(
            ClinicTable.city,
            func.count(ClinicTable.id).label("clinic_count"),
            func.avg(ClinicTable.google_rating).label("avg_rating"),
            func.avg(ClinicTable.transparency_score).label("avg_transparency"),
        )
        .where(ClinicTable.is_active == True)
        .where(ClinicTable.city.isnot(None))
        .where(ClinicTable.city != "")
        .group_by(ClinicTable.city)
        .order_by(func.count(ClinicTable.id).desc())
        .limit(15)
    )
    base_stats = base_stats_result.all()

    if not base_stats:
        return {"areas": [], "total_areas": 0}

    # 対象エリア名リスト
    target_cities = [row.city for row in base_stats]

    # === 医師統計: 医師数・JSAPS会員数（city別） ===
    doctor_stats_result = await db.execute(
        select(
            ClinicTable.city,
            func.count(DoctorTable.id).label("doctor_count"),
            func.sum(
                func.cast(DoctorTable.jsaps_certified, Integer)
            ).label("jsaps_count"),
        )
        .join(DoctorTable, DoctorTable.clinic_id == ClinicTable.id)
        .where(ClinicTable.city.in_(target_cities))
        .where(ClinicTable.is_active == True)
        .group_by(ClinicTable.city)
    )
    doctor_stats_map = {}
    for row in doctor_stats_result.all():
        doctor_stats_map[row.city] = {
            "doctor_count": row.doctor_count or 0,
            "jsaps_count": row.jsaps_count or 0,
        }

    # === 口コミ統計: 口コミ数・平均感情スコア・レッドフラグ数（city別） ===
    review_stats_result = await db.execute(
        select(
            ClinicTable.city,
            func.count(ReviewTable.id).label("review_count"),
            func.avg(ReviewTable.sentiment_score).label("avg_sentiment"),
        )
        .join(ReviewTable, ReviewTable.clinic_id == ClinicTable.id)
        .where(ClinicTable.city.in_(target_cities))
        .where(ClinicTable.is_active == True)
        .where(ReviewTable.is_spam != True)
        .group_by(ClinicTable.city)
    )
    review_stats_map = {}
    for row in review_stats_result.all():
        review_stats_map[row.city] = {
            "review_count": row.review_count or 0,
            "avg_sentiment": round(row.avg_sentiment, 3) if row.avg_sentiment is not None else None,
        }

    # レッドフラグ数（red_flagsフィールドがNULLでない口コミの件数をカウント）
    red_flag_result = await db.execute(
        select(
            ClinicTable.city,
            func.count(ReviewTable.id).label("red_flag_count"),
        )
        .join(ReviewTable, ReviewTable.clinic_id == ClinicTable.id)
        .where(ClinicTable.city.in_(target_cities))
        .where(ClinicTable.is_active == True)
        .where(ReviewTable.is_spam != True)
        .where(ReviewTable.red_flags.isnot(None))
        .where(ReviewTable.red_flags != "[]")
        .group_by(ClinicTable.city)
    )
    red_flag_map = {}
    for row in red_flag_result.all():
        red_flag_map[row.city] = row.red_flag_count or 0

    # === 上位施術（city別、上位3件） ===
    proc_result = await db.execute(
        select(
            ClinicTable.city,
            ProcedureTable.name,
            func.count(ClinicProcedure.id).label("proc_count"),
        )
        .join(ClinicProcedure, ClinicProcedure.clinic_id == ClinicTable.id)
        .join(ProcedureTable, ClinicProcedure.procedure_id == ProcedureTable.id)
        .where(ClinicTable.city.in_(target_cities))
        .where(ClinicTable.is_active == True)
        .where(ClinicProcedure.is_active == True)
        .group_by(ClinicTable.city, ProcedureTable.name)
        .order_by(ClinicTable.city, func.count(ClinicProcedure.id).desc())
    )
    proc_rows = proc_result.all()

    # city別に上位3施術を集計
    top_procs_map: dict[str, list[str]] = {}
    for row in proc_rows:
        city_procs = top_procs_map.setdefault(row.city, [])
        if len(city_procs) < 3:
            city_procs.append(row.name)

    # === レスポンス組み立て ===
    areas = []
    for row in base_stats:
        city = row.city
        doc_stats = doctor_stats_map.get(city, {"doctor_count": 0, "jsaps_count": 0})
        rev_stats = review_stats_map.get(city, {"review_count": 0, "avg_sentiment": None})

        areas.append({
            "city": city,
            "clinic_count": row.clinic_count,
            "avg_rating": round(row.avg_rating, 2) if row.avg_rating is not None else None,
            "avg_transparency": round(row.avg_transparency, 1) if row.avg_transparency is not None else None,
            "doctor_count": doc_stats["doctor_count"],
            "jsaps_count": doc_stats["jsaps_count"],
            "review_count": rev_stats["review_count"],
            "avg_sentiment": rev_stats["avg_sentiment"],
            "red_flag_count": red_flag_map.get(city, 0),
            "top_procedures": top_procs_map.get(city, []),
        })

    return {
        "areas": areas,
        "total_areas": len(areas),
    }


@router.get("/{clinic_id}")
async def get_clinic(clinic_id: str, db: AsyncSession = Depends(get_db)):
    """
    クリニック詳細取得

    指定IDのクリニック詳細情報を返却。医師情報・施術データも含む。
    """
    # ルーティング競合防止: 固定パスと衝突する場合は404
    _RESERVED_PATHS = {"compare", "by-procedure", "stats", "area-stats", "nearby", "suggest"}
    if clinic_id in _RESERVED_PATHS:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="クリニックが見つかりません")

    result = await db.execute(select(ClinicTable).where(ClinicTable.id == clinic_id))
    clinic = result.scalar_one_or_none()

    if not clinic:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="クリニックが見つかりません")

    data = _format_clinic(clinic, detail=True)

    # 医師情報を取得
    from src.db.database import DoctorTable
    doc_result = await db.execute(
        select(DoctorTable)
        .where(DoctorTable.clinic_id == clinic_id)
        .order_by(DoctorTable.title.desc())
    )
    doctors = doc_result.scalars().all()
    from src.analyzers.doctor_scoring import get_trust_level
    data["doctors"] = [
        {
            "name": d.name,
            "title": d.title or "",
            "specialties": json.loads(d.specialties) if d.specialties else [],
            "certifications": json.loads(d.board_certifications) if d.board_certifications else [],
            "experience_years": d.experience_years,
            "profile_url": d.profile_url,
            "trust_score": d.trust_score,
            "hospital_background": getattr(d, "hospital_background", None),
            "jsaps_certified": getattr(d, "jsaps_certified", False) or False,
            "trust_level": get_trust_level(d.trust_score) if d.trust_score is not None else "情報収集中",
        }
        for d in doctors
    ]

    # 施術データを取得
    from src.db.database import ClinicProcedure, ProcedureTable
    cp_result = await db.execute(
        select(ClinicProcedure, ProcedureTable.name, ProcedureTable.category)
        .join(ProcedureTable, ClinicProcedure.procedure_id == ProcedureTable.id)
        .where(ClinicProcedure.clinic_id == clinic_id)
        .where(ClinicProcedure.is_active == True)
    )
    procedures = cp_result.all()

    # Phase 15: 施術別に市場価格統計を付与
    # N+1回避: 全施術の価格データを一括取得
    proc_ids = list(set(row[0].procedure_id for row in procedures if row[0].procedure_id))
    market_stats = {}
    if proc_ids:
        import statistics
        from src.analyzers.price_intelligence import get_price_label, format_price
        prices_result = await db.execute(
            select(
                ClinicProcedure.procedure_id,
                ClinicProcedure.price_advertised,
            )
            .where(ClinicProcedure.procedure_id.in_(proc_ids))
            .where(ClinicProcedure.price_advertised.isnot(None))
            .where(ClinicProcedure.price_advertised > 0)
            .order_by(ClinicProcedure.procedure_id, ClinicProcedure.price_advertised)
        )
        # 施術IDごとに価格リストを集約
        from collections import defaultdict
        price_map = defaultdict(list)
        for pid, price in prices_result.all():
            price_map[pid].append(price)
        # メディアン・サンプル数を事前計算
        for pid, prices in price_map.items():
            if len(prices) >= 3:
                median = int(statistics.median(prices))
                market_stats[pid] = {"median": median, "sample_count": len(prices)}

    # 価格ソースの日本語ラベルマッピング
    PRICE_SOURCE_LABELS = {
        'website_scrape': '公式サイト',
        'chain_inference': 'チェーン参考',
        'department_inference': '診療科推定',
        'estimated': '統計推定',
    }

    proc_list = []
    for row in procedures:
        source_raw = row[0].source or 'unknown'
        proc_data = {
            "name": row[1],
            "category": row[2],
            "source": source_raw,
            "price_advertised": row[0].price_advertised,
            "price_source": source_raw,
            "price_source_label": PRICE_SOURCE_LABELS.get(source_raw, source_raw),
        }
        # 価格表示フォーマットを追加
        if row[0].price_advertised and row[0].price_advertised > 0:
            proc_data["price_display"] = f"\u00a5{row[0].price_advertised:,}"
        # 市場価格対比を計算（事前取得データを使用）
        if row[0].price_advertised and row[0].price_advertised > 0:
            stats = market_stats.get(row[0].procedure_id)
            if stats:
                from src.analyzers.price_intelligence import get_price_label, format_price
                ctx = get_price_label(row[0].price_advertised, stats["median"])
                proc_data["market_context"] = {
                    "label": ctx.label,
                    "icon": ctx.icon,
                    "median": stats["median"],
                    "median_display": format_price(stats["median"]),
                    "sample_count": stats["sample_count"],
                }
        proc_list.append(proc_data)
    data["procedures"] = proc_list

    # 口コミを取得（最新20件、スパムを除外）
    from src.db.database import ReviewTable
    rev_result = await db.execute(
        select(ReviewTable)
        .where(ReviewTable.clinic_id == clinic_id)
        .where(ReviewTable.is_spam != True)
        .order_by(ReviewTable.created_at.desc())
        .limit(20)
    )
    reviews = rev_result.scalars().all()
    data["reviews"] = [
        {
            "text": r.text or "",
            "rating": r.rating,
            "author": r.author_name or "",
            "sentiment": r.sentiment_score,
            "quality_score": r.quality_score,
            "red_flags": json.loads(r.red_flags) if r.red_flags else [],
            "date": r.created_at.strftime("%Y-%m-%d") if r.created_at else None,
        }
        for r in reviews
    ]

    # 口コミ感情分析サマリー（全口コミ対象）
    all_rev_result = await db.execute(
        select(
            func.count(ReviewTable.id),
            func.avg(ReviewTable.sentiment_score),
        )
        .where(ReviewTable.clinic_id == clinic_id)
        .where(ReviewTable.is_spam != True)
    )
    summary_row = all_rev_result.one()
    total_reviews = summary_row[0] or 0
    avg_sentiment = summary_row[1]

    # ポジ/ネガ/ニュートラル件数 + 星分布
    pos_count = 0
    neg_count = 0
    neu_count = 0
    aspect_counts = {}
    star_dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    if total_reviews > 0:
        sentiment_result = await db.execute(
            select(ReviewTable.sentiment_score, ReviewTable.aspects, ReviewTable.rating)
            .where(ReviewTable.clinic_id == clinic_id)
            .where(ReviewTable.is_spam != True)
        )
        for row in sentiment_result.all():
            score = row[0]
            if score is not None:
                if score > 0.2:
                    pos_count += 1
                elif score < -0.2:
                    neg_count += 1
                else:
                    neu_count += 1
            # 星分布
            rating = row[2]
            if rating is not None:
                star_key = min(5, max(1, round(rating)))
                star_dist[star_key] = star_dist.get(star_key, 0) + 1
            # アスペクト集計
            if row[1]:
                try:
                    aspects = json.loads(row[1])
                    for asp in aspects:
                        aspect_counts[asp] = aspect_counts.get(asp, 0) + 1
                except (json.JSONDecodeError, TypeError):
                    pass

    # 平均星評価を算出
    total_rated = sum(star_dist.values())
    avg_rating = None
    if total_rated > 0:
        avg_rating = round(sum(k * v for k, v in star_dist.items()) / total_rated, 1)

    data["review_summary"] = {
        "total": total_reviews,
        "avg_sentiment": round(avg_sentiment, 3) if avg_sentiment is not None else None,
        "positive": pos_count,
        "neutral": neu_count,
        "negative": neg_count,
        "aspects": aspect_counts,
        "star_distribution": star_dist,
        "avg_rating": avg_rating,
    }

    # Phase 12: レッドフラグ集計
    flag_result = await db.execute(
        select(ReviewTable.red_flags)
        .where(ReviewTable.clinic_id == clinic_id)
        .where(ReviewTable.red_flags.isnot(None))
        .where(ReviewTable.is_spam != True)
    )
    flag_categories: dict[str, int] = {}
    for row in flag_result.all():
        try:
            flags = json.loads(row[0])
            for f in flags:
                cat = f.get("category", "unknown")
                flag_categories[cat] = flag_categories.get(cat, 0) + 1
        except (json.JSONDecodeError, TypeError):
            pass
    if flag_categories:
        data["review_summary"]["red_flags"] = flag_categories

    # Phase 12: 平均品質スコア
    quality_result = await db.execute(
        select(func.avg(ReviewTable.quality_score))
        .where(ReviewTable.clinic_id == clinic_id)
        .where(ReviewTable.quality_score.isnot(None))
        .where(ReviewTable.is_spam != True)
    )
    avg_quality = quality_result.scalar()
    if avg_quality is not None:
        data["review_summary"]["avg_quality"] = round(avg_quality, 1)

    # Phase 12: 時系列トレンド（直近6ヶ月 vs 全期間）
    from datetime import datetime, timedelta
    six_months_ago = datetime.now() - timedelta(days=180)
    recent_result = await db.execute(
        select(
            func.count(ReviewTable.id),
            func.avg(ReviewTable.sentiment_score),
        )
        .where(ReviewTable.clinic_id == clinic_id)
        .where(ReviewTable.is_spam != True)
        .where(ReviewTable.created_at >= six_months_ago)
    )
    recent_row = recent_result.one()
    recent_count = recent_row[0] or 0
    recent_avg = recent_row[1]
    if recent_count >= 2 and avg_sentiment is not None and recent_avg is not None:
        diff = recent_avg - avg_sentiment
        if diff > 0.15:
            trend = "improving"
        elif diff < -0.15:
            trend = "declining"
        else:
            trend = "stable"
        data["review_summary"]["recent_trend"] = {
            "direction": trend,
            "recent_avg": round(recent_avg, 3),
            "recent_count": recent_count,
        }

    # data_completeness を実データで更新
    has_google_reviews = data["data_completeness"]["has_google_reviews"]
    has_doctor_info = len(doctors) > 0
    total_procs = len(procedures)
    priced_procs = sum(1 for row in procedures if row[0].price_advertised and row[0].price_advertised > 0)
    price_coverage = round(priced_procs / total_procs, 2) if total_procs > 0 else 0.0

    # level判定: high=全あり, medium=一部あり, low=ほとんどなし
    completeness_score = sum([
        has_google_reviews,
        has_doctor_info,
        price_coverage >= 0.5,
    ])
    if completeness_score >= 3:
        level = "high"
    elif completeness_score >= 1:
        level = "medium"
    else:
        level = "low"

    data["data_completeness"] = {
        "has_google_reviews": has_google_reviews,
        "has_doctor_info": has_doctor_info,
        "price_coverage": price_coverage,
        "level": level,
    }

    # 症例写真を取得（clinic_idで紐付いたものを最大10件）
    from src.db.database import CasePhotoTable
    cp_result = await db.execute(
        select(CasePhotoTable)
        .where(CasePhotoTable.clinic_id == clinic_id)
        .where(CasePhotoTable.is_active == True)
        .where(CasePhotoTable.before_image_url.isnot(None))
        .order_by(CasePhotoTable.created_at.desc())
        .limit(10)
    )
    case_photos = cp_result.scalars().all()
    if case_photos:
        data["case_photos"] = [
            {
                "id": p.id,
                "before_image_url": p.before_image_url,
                "after_image_url": p.after_image_url,
                "procedure_name": p.procedure_name,
                "description": p.description,
                "price": p.price,
                "source": p.source,
                "source_url": p.source_url,
                "doctor_name": p.doctor_name,
            }
            for p in case_photos
        ]
        data["case_photo_count"] = len(case_photos)

    return data


# ==========================================
# Phase 63: 構造化データ(JSON-LD) SEO強化
# ==========================================


@router.get("/{clinic_id}/jsonld")
async def get_clinic_jsonld(clinic_id: str, db: AsyncSession = Depends(get_db)):
    """
    クリニック構造化データ（JSON-LD）

    Schema.org MedicalClinic型のJSON-LDを動的生成する。
    Googleリッチリザルト対応のため、name, address, geo,
    aggregateRating, medicalSpecialty, availableService を返却。
    """
    from fastapi import HTTPException
    from src.db.database import ClinicProcedure, ProcedureTable

    result = await db.execute(select(ClinicTable).where(ClinicTable.id == clinic_id))
    clinic = result.scalar_one_or_none()
    if not clinic:
        raise HTTPException(status_code=404, detail="クリニックが見つかりません")

    # 基本構造
    jsonld: dict = {
        "@context": "https://schema.org",
        "@type": "MedicalClinic",
        "name": clinic.name,
        "url": clinic.website or "",
        "telephone": clinic.phone or "",
    }

    # 住所（PostalAddress型）
    if clinic.address:
        jsonld["address"] = {
            "@type": "PostalAddress",
            "streetAddress": clinic.address,
            "addressLocality": clinic.city or "",
            "addressRegion": "東京都",
            "addressCountry": "JP",
        }

    # 地理座標（GeoCoordinates型）
    if clinic.lat and clinic.lng and clinic.lat != 0 and clinic.lng != 0:
        jsonld["geo"] = {
            "@type": "GeoCoordinates",
            "latitude": clinic.lat,
            "longitude": clinic.lng,
        }

    # 集約評価（AggregateRating型）
    if clinic.google_rating and clinic.google_review_count:
        jsonld["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": round(clinic.google_rating, 1),
            "bestRating": 5,
            "worstRating": 1,
            "reviewCount": clinic.google_review_count,
        }

    # 診療科目（medicalSpecialty）
    departments = json.loads(clinic.medical_departments) if clinic.medical_departments else []
    # Schema.org MedicalSpecialtyへのマッピング
    _SPECIALTY_MAP = {
        "美容外科": "PlasticSurgery",
        "形成外科": "PlasticSurgery",
        "美容皮膚科": "Dermatology",
        "皮膚科": "Dermatology",
    }
    specialties = []
    for dept in departments:
        mapped = _SPECIALTY_MAP.get(dept)
        if mapped and mapped not in specialties:
            specialties.append(mapped)
    if specialties:
        jsonld["medicalSpecialty"] = (
            specialties[0] if len(specialties) == 1 else specialties
        )

    # 対応施術（上位5件、availableService型）
    proc_result = await db.execute(
        select(ProcedureTable.name, ClinicProcedure.price_advertised)
        .join(ProcedureTable, ClinicProcedure.procedure_id == ProcedureTable.id)
        .where(ClinicProcedure.clinic_id == clinic_id)
        .where(ClinicProcedure.is_active == True)
        .order_by(ClinicProcedure.price_advertised.desc().nullslast())
        .limit(5)
    )
    proc_rows = proc_result.all()
    if proc_rows:
        services = []
        for row in proc_rows:
            service: dict = {
                "@type": "MedicalProcedure",
                "name": row[0],
            }
            if row[1] and row[1] > 0:
                service["offers"] = {
                    "@type": "Offer",
                    "price": str(row[1]),
                    "priceCurrency": "JPY",
                }
            services.append(service)
        jsonld["availableService"] = services

    return jsonld


# ==========================================
# Phase 55: 類似クリニック推薦API
# ==========================================

# グレード順序マッピング（隣接グレード判定用）
_GRADE_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}


@router.get("/{clinic_id}/similar")
async def get_similar_clinics(clinic_id: str, db: AsyncSession = Depends(get_db)):
    """
    類似クリニック推薦 v2

    同エリア・近いグレード・近い評価・価格帯・口コミ感情・共通施術を基に
    多次元スコアリングし、上位4件の類似クリニックを返却する。
    同一チェーンは除外。

    Phase 68: 価格帯近接・口コミ感情近接・カテゴリ重み付けで精度向上。
    """
    from fastapi import HTTPException
    from src.db.database import ClinicProcedure, ProcedureTable, ReviewTable

    # 対象クリニックを取得
    result = await db.execute(select(ClinicTable).where(ClinicTable.id == clinic_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="クリニックが見つかりません")

    target_grade = target.clinic_grade or ""
    target_grade_idx = _GRADE_ORDER.get(target_grade)
    target_rating = target.google_rating

    # 対象クリニックの施術IDセットを取得
    proc_result = await db.execute(
        select(ClinicProcedure.procedure_id)
        .where(ClinicProcedure.clinic_id == clinic_id)
        .where(ClinicProcedure.is_active == True)
    )
    target_proc_ids = set(r[0] for r in proc_result.all())

    # 候補クリニックを取得（自身を除外、アクティブのみ）
    candidates_query = (
        select(ClinicTable)
        .where(ClinicTable.is_active == True)
        .where(ClinicTable.id != clinic_id)
    )

    # 同じチェーンを除外（チェーン名がある場合）
    if target.chain_name and target.chain_name.strip():
        candidates_query = candidates_query.where(
            or_(
                ClinicTable.chain_name.is_(None),
                ClinicTable.chain_name == "",
                ClinicTable.chain_name != target.chain_name,
            )
        )

    # グレードフィルタ: ±1グレード範囲に絞る（パフォーマンス最適化）
    if target_grade_idx is not None:
        adjacent_grades = [
            g for g, idx in _GRADE_ORDER.items()
            if abs(idx - target_grade_idx) <= 1
        ]
        candidates_query = candidates_query.where(
            ClinicTable.clinic_grade.in_(adjacent_grades)
        )

    result = await db.execute(candidates_query)
    candidates = result.scalars().all()

    if not candidates:
        return {"similar_clinics": []}

    # 候補クリニックの施術IDを一括取得（N+1回避）
    candidate_ids = [c.id for c in candidates]
    all_clinic_ids = candidate_ids + [clinic_id]

    cp_result = await db.execute(
        select(ClinicProcedure.clinic_id, ClinicProcedure.procedure_id)
        .where(ClinicProcedure.clinic_id.in_(candidate_ids))
        .where(ClinicProcedure.is_active == True)
    )
    # クリニックごとの施術IDセットを構築
    candidate_procs: dict[str, set[str]] = {}
    for row in cp_result.all():
        candidate_procs.setdefault(row[0], set()).add(row[1])

    # Phase 68: 施術IDごとのカテゴリを一括取得（カテゴリ重み付け用）
    all_proc_ids = set(target_proc_ids)
    for procs in candidate_procs.values():
        all_proc_ids.update(procs)
    proc_categories: dict[str, str] = {}
    if all_proc_ids:
        cat_result = await db.execute(
            select(ProcedureTable.id, ProcedureTable.category)
            .where(ProcedureTable.id.in_(list(all_proc_ids)))
        )
        for row in cat_result.all():
            proc_categories[row[0]] = row[1] or ""

    # Phase 68: 平均価格を一括取得（N+1回避）
    avg_price_result = await db.execute(
        select(
            ClinicProcedure.clinic_id,
            func.avg(ClinicProcedure.price_advertised),
        )
        .where(ClinicProcedure.clinic_id.in_(all_clinic_ids))
        .where(ClinicProcedure.price_advertised.isnot(None))
        .where(ClinicProcedure.price_advertised > 0)
        .group_by(ClinicProcedure.clinic_id)
    )
    avg_prices: dict[str, float] = {}
    for row in avg_price_result.all():
        avg_prices[row[0]] = float(row[1])

    target_avg_price = avg_prices.get(clinic_id, 0)

    # Phase 68: 平均感情スコアを一括取得（N+1回避）
    avg_sentiment_result = await db.execute(
        select(
            ReviewTable.clinic_id,
            func.avg(ReviewTable.sentiment_score),
        )
        .where(ReviewTable.clinic_id.in_(all_clinic_ids))
        .where(ReviewTable.sentiment_score.isnot(None))
        .where(ReviewTable.is_spam != True)
        .group_by(ReviewTable.clinic_id)
    )
    avg_sentiments: dict[str, float] = {}
    for row in avg_sentiment_result.all():
        avg_sentiments[row[0]] = float(row[1])

    target_sentiment = avg_sentiments.get(clinic_id)

    # 対象クリニックの施術カテゴリセット（カテゴリ一致判定用）
    target_proc_categories = set(
        proc_categories.get(pid, "") for pid in target_proc_ids
    )
    target_proc_categories.discard("")

    # スコアリング
    scored: list[tuple[float, object, list[str]]] = []
    for c in candidates:
        score = 0.0
        reasons = []

        # 同じcity: +3点
        if c.city and target.city and c.city == target.city:
            score += 3
            reasons.append("同じエリア")

        # グレード比較
        c_grade_idx = _GRADE_ORDER.get(c.clinic_grade or "")
        if target_grade_idx is not None and c_grade_idx is not None:
            grade_diff = abs(target_grade_idx - c_grade_idx)
            if grade_diff == 0:
                score += 2
                reasons.append("同グレード")
            elif grade_diff == 1:
                score += 1
                reasons.append("近いグレード")

        # Phase 68: 価格帯近接: +2点（30%以内の差）
        c_avg_price = avg_prices.get(c.id, 0)
        if target_avg_price > 0 and c_avg_price > 0:
            price_ratio = min(target_avg_price, c_avg_price) / max(target_avg_price, c_avg_price)
            if price_ratio >= 0.7:
                score += 2
                reasons.append("価格帯が近い")

        # Phase 68: 口コミ感情近接: +1点（差が0.3未満）
        c_sentiment = avg_sentiments.get(c.id)
        if target_sentiment is not None and c_sentiment is not None:
            if abs(target_sentiment - c_sentiment) < 0.3:
                score += 1
                reasons.append("口コミ評価が近い")

        # Google評価差が0.5以内: +1点
        if target_rating and c.google_rating:
            if abs(target_rating - c.google_rating) <= 0.5:
                score += 1
                reasons.append("評価が近い")

        # Phase 68: 強化版 共通施術スコアリング（カテゴリ一致は+1.5, 単純一致は+1, max 4）
        c_procs = candidate_procs.get(c.id, set())
        shared = target_proc_ids & c_procs
        if shared:
            proc_score = 0.0
            for pid in shared:
                cat = proc_categories.get(pid, "")
                # カテゴリが対象クリニックの施術カテゴリに含まれていればボーナス
                if cat and cat in target_proc_categories:
                    proc_score += 1.5
                else:
                    proc_score += 1.0
            proc_score = min(proc_score, 4.0)
            score += proc_score
            reasons.append("共通施術あり")

        if score > 0:
            scored.append((score, c, reasons))

    # スコア降順でソート、上位4件を取得
    scored.sort(key=lambda x: x[0], reverse=True)
    top4 = scored[:4]

    similar_clinics = []
    for score_val, c, reasons in top4:
        item = {
            "id": c.id,
            "name": c.name,
            "city": c.city,
            "clinic_grade": c.clinic_grade,
            "clinic_score": c.clinic_score,
            "google_rating": c.google_rating,
            "google_review_count": c.google_review_count,
            "editorial_summary": c.editorial_summary,
            "similarity_reasons": reasons,
        }
        # Phase 68: 平均価格を付与
        c_price = avg_prices.get(c.id)
        if c_price and c_price > 0:
            item["avg_price"] = int(c_price)
        similar_clinics.append(item)

    return {"similar_clinics": similar_clinics}


def _format_clinic(clinic: ClinicTable, detail: bool = False, list_mode: bool = False) -> dict:
    """クリニックデータのフォーマット

    list_mode=True の場合、一覧表示に不要なフィールドを省略してレスポンスサイズを削減する。
    """
    data = {
        "id": clinic.id,
        "name": clinic.name,
        "chain_name": clinic.chain_name,
        "address": clinic.address,
        "city": clinic.city,
        "lat": clinic.lat,
        "lng": clinic.lng,
        "google_rating": clinic.google_rating,
        "google_review_count": clinic.google_review_count,
        "transparency_score": clinic.transparency_score,
        "clinic_score": clinic.clinic_score,
        "clinic_grade": clinic.clinic_grade,
        "editorial_summary": clinic.editorial_summary,
        "departments": json.loads(clinic.medical_departments) if clinic.medical_departments else [],
    }

    # 美容クリニック判定（一般診療のみの場合は is_beauty_only = False）
    depts = data["departments"]
    beauty_depts = {"美容皮膚科", "美容外科", "形成外科"}
    data["is_beauty_only"] = any(d in beauty_depts for d in depts)

    # 一覧表示では不要なフィールドを追加（詳細・通常モード時のみ）
    if not list_mode:
        data.update({
            "branch_name": clinic.branch_name,
            "website": clinic.website,
            "data_quality": {
                "source": "厚生労働省 医療情報ネット" if (clinic.source or "") == "mhlw" else (clinic.source or "不明"),
                "data_date": "2025-12-01",
                "publish_status": getattr(clinic, "publish_status", "verified") or "verified",
            },
        })

    # データ充実度（data_completeness）判定
    has_google_reviews = bool(clinic.google_review_count and clinic.google_review_count > 0)
    if list_mode:
        # リスト用: 軽量版（has_google_reviews + level のみ）
        # level は Google口コミの有無だけで簡易判定
        list_level = "high" if has_google_reviews else "low"
        data["data_completeness"] = {
            "has_google_reviews": has_google_reviews,
            "level": list_level,
        }
    else:
        # 通常/詳細モード: has_doctor_info と price_coverage は
        # DB参照が必要なため、呼び出し元で上書きする想定でプレースホルダを設定
        data["data_completeness"] = {
            "has_google_reviews": has_google_reviews,
            "has_doctor_info": False,
            "price_coverage": 0.0,
            "level": "low",
        }

    # 一覧表示用のサムネイル（写真がある場合、1枚目の参照キーを返す）
    photos_raw = json.loads(clinic.google_photos) if clinic.google_photos else []
    if photos_raw and len(photos_raw) > 0:
        data["thumbnail_ref"] = photos_raw[0]

    if detail:
        from src.analyzers.freshness import build_freshness_metadata
        freshness = build_freshness_metadata(
            source=clinic.source,
            fetched_at=getattr(clinic, 'fetched_at', None) or clinic.created_at,
            source_version=getattr(clinic, 'source_version', '') or '',
        )
        data.update({
            "phone": clinic.phone,
            "mhlw_code": clinic.mhlw_code,
            "medical_corp_name": clinic.medical_corp_name,
            "doctor_count": clinic.doctor_count,
            "google_place_id": clinic.google_place_id,
            "opening_hours": json.loads(clinic.opening_hours) if clinic.opening_hours else None,
            "editorial_summary": clinic.editorial_summary,
            "photos": json.loads(clinic.google_photos) if clinic.google_photos else [],
            "data_provenance": {
                "source": clinic.source,
                "source_version": getattr(clinic, 'source_version', ''),
                "fetched_at": (getattr(clinic, 'fetched_at', None) or clinic.created_at).isoformat() if (getattr(clinic, 'fetched_at', None) or clinic.created_at) else None,
                "verified_at": clinic.verified_at.isoformat() if getattr(clinic, 'verified_at', None) else None,
                "confidence": getattr(clinic, 'confidence', 1.0),
                "publish_status": getattr(clinic, 'publish_status', 'verified'),
                "freshness": freshness.freshness,
                "days_old": freshness.days_old,
            },
        })

        # スコアブレークダウンの追加
        if clinic.clinic_score_breakdown:
            try:
                data["clinic_score_breakdown"] = json.loads(clinic.clinic_score_breakdown)
            except (json.JSONDecodeError, TypeError):
                data["clinic_score_breakdown"] = {}

    return data


@router.get("/{clinic_id}/photo")
async def get_clinic_photo(
    clinic_id: str,
    ref: str = Query(..., description="Google Photosの参照キー"),
    maxwidth: int = Query(600, ge=100, le=1600, description="最大幅"),
):
    """
    クリニック写真プロキシ

    Google Places Photo APIのphoto_referenceを使って画像を取得し、
    バイナリとして返却する。APIキーをフロントエンドに露出させない。
    """
    import httpx
    from fastapi.responses import Response

    from src.config import settings

    if not settings.google_maps_api_key:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Google Maps APIキー未設定")

    # Google Places Photo API（レガシー）
    photo_url = (
        f"https://maps.googleapis.com/maps/api/place/photo"
        f"?maxwidth={maxwidth}"
        f"&photo_reference={ref}"
        f"&key={settings.google_maps_api_key}"
    )

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
            resp = await client.get(photo_url)
            if resp.status_code == 200:
                content_type = resp.headers.get("content-type", "image/jpeg")
                return Response(
                    content=resp.content,
                    media_type=content_type,
                    headers={
                        "Cache-Control": "public, max-age=86400",  # 24時間キャッシュ
                    },
                )
            else:
                from fastapi import HTTPException
                raise HTTPException(status_code=resp.status_code, detail="写真取得に失敗")
    except httpx.TimeoutException:
        from fastapi import HTTPException
        raise HTTPException(status_code=504, detail="写真取得タイムアウト")


# ==========================================
# Phase 16: クリニック比較API
# ==========================================

@router.get("/compare/side-by-side")
async def compare_clinics(
    ids: str = Query(..., description="比較するクリニックIDをカンマ区切り（2-4件）"),
    db: AsyncSession = Depends(get_db),
):
    """
    クリニック比較（サイドバイサイド）

    2-4クリニックのデータを並べて比較可能な形式で返却。
    評価・価格・医師・透明性スコア・口コミを横並び表示用に構造化。
    """
    from fastapi import HTTPException
    from src.db.database import DoctorTable, ClinicProcedure, ProcedureTable, ReviewTable

    id_list = [i.strip() for i in ids.split(",")]
    if len(id_list) < 2 or len(id_list) > 4:
        raise HTTPException(status_code=400, detail="比較は2〜4クリニックで指定してください")

    result = await db.execute(
        select(ClinicTable).where(ClinicTable.id.in_(id_list))
    )
    clinics = result.scalars().all()

    if len(clinics) < 2:
        raise HTTPException(status_code=404, detail="指定したクリニックが見つかりません")

    comparisons = []
    for clinic in clinics:
        # 医師数・JSAPS医師数
        doc_result = await db.execute(
            select(DoctorTable).where(DoctorTable.clinic_id == clinic.id)
        )
        doctors = doc_result.scalars().all()
        jsaps_count = sum(1 for d in doctors if getattr(d, "jsaps_certified", False))
        avg_trust = None
        trust_scores = [d.trust_score for d in doctors if d.trust_score is not None]
        if trust_scores:
            avg_trust = round(sum(trust_scores) / len(trust_scores), 1)

        # 施術数・価格データ数
        proc_result = await db.execute(
            select(func.count(ClinicProcedure.id))
            .where(ClinicProcedure.clinic_id == clinic.id)
            .where(ClinicProcedure.is_active == True)
        )
        proc_count = proc_result.scalar() or 0

        price_result = await db.execute(
            select(func.count(ClinicProcedure.id))
            .where(ClinicProcedure.clinic_id == clinic.id)
            .where(ClinicProcedure.price_advertised.isnot(None))
            .where(ClinicProcedure.price_advertised > 0)
        )
        price_count = price_result.scalar() or 0

        # 口コミ統計
        review_result = await db.execute(
            select(
                func.count(ReviewTable.id),
                func.avg(ReviewTable.quality_score),
            )
            .where(ReviewTable.clinic_id == clinic.id)
            .where(ReviewTable.is_spam != True)
        )
        rev_row = review_result.one()

        comparisons.append({
            "id": clinic.id,
            "name": clinic.name,
            "city": clinic.city,
            "address": clinic.address,
            "google_rating": clinic.google_rating,
            "google_review_count": clinic.google_review_count,
            "transparency_score": clinic.transparency_score,
            "departments": json.loads(clinic.medical_departments) if clinic.medical_departments else [],
            "website": clinic.website,
            "doctor_count": len(doctors),
            "jsaps_doctor_count": jsaps_count,
            "avg_trust_score": avg_trust,
            "procedure_count": proc_count,
            "price_data_count": price_count,
            "review_count": rev_row[0] or 0,
            "avg_review_quality": round(rev_row[1], 1) if rev_row[1] else None,
        })

    return {
        "clinics": comparisons,
        "count": len(comparisons),
    }


# ==========================================
# Phase 16: 施術特化型クリニック検索
# ==========================================

@router.get("/by-procedure/{procedure_id}")
async def clinics_by_procedure(
    procedure_id: str,
    city: str | None = Query(None, description="市区町村フィルタ"),
    sort_by: str = Query("price", description="ソート基準（price/rating/transparency）"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """
    施術特化型クリニック検索

    特定の施術を提供するクリニックを価格順・評価順で表示。
    ユーザーが「この施術をやりたい」から入るフローに対応。
    """
    from fastapi import HTTPException
    from src.db.database import ClinicProcedure, ProcedureTable
    from src.analyzers.price_intelligence import get_price_label, format_price

    # 施術マスタを確認
    proc_result = await db.execute(
        select(ProcedureTable).where(ProcedureTable.id == procedure_id)
    )
    procedure = proc_result.scalar_one_or_none()
    if not procedure:
        raise HTTPException(status_code=404, detail="施術が見つかりません")

    # この施術を提供するクリニックを取得
    query = (
        select(ClinicProcedure, ClinicTable)
        .join(ClinicTable, ClinicProcedure.clinic_id == ClinicTable.id)
        .where(ClinicProcedure.procedure_id == procedure_id)
        .where(ClinicProcedure.is_active == True)
        .where(ClinicTable.is_active == True)
    )

    if city:
        query = query.where(ClinicTable.city == city)

    # ソート
    if sort_by == "price":
        query = query.order_by(
            ClinicProcedure.price_advertised.asc().nullslast()
        )
    elif sort_by == "rating":
        query = query.order_by(ClinicTable.google_rating.desc().nullslast())
    elif sort_by == "transparency":
        query = query.order_by(ClinicTable.transparency_score.desc().nullslast())
    else:
        query = query.order_by(ClinicProcedure.price_advertised.asc().nullslast())

    # ページネーション
    total_result = await db.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = total_result.scalar() or 0

    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)
    rows = await db.execute(query)

    # 中央値の算出（相場対比用）
    median = None
    all_prices_result = await db.execute(
        select(ClinicProcedure.price_advertised)
        .where(ClinicProcedure.procedure_id == procedure_id)
        .where(ClinicProcedure.price_advertised.isnot(None))
        .where(ClinicProcedure.price_advertised > 0)
        .order_by(ClinicProcedure.price_advertised)
    )
    all_prices = [r[0] for r in all_prices_result.all()]
    if len(all_prices) >= 3:
        import statistics
        median = int(statistics.median(all_prices))

    clinics = []
    for row in rows:
        cp = row[0]
        clinic = row[1]
        item = {
            "clinic_id": clinic.id,
            "clinic_name": clinic.name,
            "city": clinic.city,
            "address": clinic.address,
            "google_rating": clinic.google_rating,
            "google_review_count": clinic.google_review_count,
            "transparency_score": clinic.transparency_score,
            "price": cp.price_advertised,
            "price_display": format_price(cp.price_advertised) if cp.price_advertised else None,
            "source": cp.source,
        }
        # 相場対比
        if cp.price_advertised and cp.price_advertised > 0 and median:
            ctx = get_price_label(cp.price_advertised, median)
            item["market_context"] = {
                "label": ctx.label,
                "icon": ctx.icon,
            }
        clinics.append(item)

    return {
        "procedure": {
            "id": procedure.id,
            "name": procedure.name,
            "category": procedure.category,
        },
        "clinics": clinics,
        "total": total,
        "page": page,
        "per_page": per_page,
        "market_median": median,
        "market_median_display": format_price(median) if median else None,
    }


# ==========================================
# Phase 29: 口コミ要約API
# ==========================================

# アスペクトキーの日本語ラベルマッピング
_ASPECT_LABELS: dict[str, str] = {
    "service": "接客・対応",
    "price": "価格・費用",
    "skill": "施術の質",
    "wait": "待ち時間",
    "facility": "清潔感",
}

# ハイライト抽出用キーワード（ポジティブ）
_HIGHLIGHT_POSITIVE_KEYWORDS: list[str] = [
    "丁寧なカウンセリング", "カウンセリングが丁寧", "説明が丁寧",
    "しっかり説明", "清潔な院内", "清潔", "きれい", "綺麗",
    "仕上がりが自然", "自然", "痛みが少ない", "ダウンタイムが短い",
    "スタッフが親切", "親切", "丁寧", "安心",
    "価格が良心的", "コスパ", "リーズナブル",
    "アフターケアが充実", "予約が取りやすい",
    "プライバシーに配慮", "個室", "居心地が良い",
]

# ハイライト抽出用キーワード（ネガティブ）
_HIGHLIGHT_NEGATIVE_KEYWORDS: list[str] = [
    "待ち時間が長い", "待たされ", "予約が取れない",
    "追加費用の説明不足", "追加料金", "想定以上",
    "強引な勧誘", "押し売り", "断りにくい",
    "スタッフの態度が悪い", "態度が悪い", "冷たい",
    "仕上がりが不自然", "不自然", "左右差",
    "アフターケアが不十分", "説明不足", "説明がない",
    "院内が清潔でない", "狭い", "プライバシーがない",
]


@router.get("/{clinic_id}/review-summary")
async def get_clinic_review_summary(
    clinic_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    クリニック口コミ要約API

    LLMを使わず、DBの分析済みデータ（sentiment_score, aspects,
    red_flags, quality_score, rating）から統計的にサマリーを生成する。
    口コミが0件でも空のサマリーを返す（404にしない）。
    """
    from src.db.database import ReviewTable

    # クリニック情報を取得
    clinic_result = await db.execute(
        select(ClinicTable).where(ClinicTable.id == clinic_id)
    )
    clinic = clinic_result.scalar_one_or_none()

    if not clinic:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="クリニックが見つかりません")

    # 全口コミを取得（スパム除外）
    reviews_result = await db.execute(
        select(ReviewTable)
        .where(ReviewTable.clinic_id == clinic_id)
        .where(ReviewTable.is_spam != True)
    )
    reviews = reviews_result.scalars().all()

    total_reviews = len(reviews)

    # 口コミ0件の場合は空のサマリー
    if total_reviews == 0:
        return {
            "clinic_id": clinic_id,
            "clinic_name": clinic.name,
            "total_reviews": 0,
            "avg_rating": None,
            "sentiment_distribution": {"positive": 0, "neutral": 0, "negative": 0},
            "topics": [],
            "highlights": {"strengths": [], "concerns": []},
            "red_flag_summary": {"total": 0, "categories": {}},
            "quality_distribution": {"high": 0, "standard": 0, "low": 0},
            "trend": None,
        }

    # === 平均評価 ===
    ratings = [r.rating for r in reviews if r.rating is not None]
    avg_rating = round(sum(ratings) / len(ratings), 1) if ratings else None

    # === 感情分布（パーセンテージ） ===
    pos_count = 0
    neu_count = 0
    neg_count = 0
    for r in reviews:
        if r.sentiment_score is not None:
            if r.sentiment_score > 0.2:
                pos_count += 1
            elif r.sentiment_score < -0.2:
                neg_count += 1
            else:
                neu_count += 1

    scored_total = pos_count + neu_count + neg_count
    if scored_total > 0:
        sentiment_distribution = {
            "positive": round(pos_count / scored_total * 100),
            "neutral": round(neu_count / scored_total * 100),
            "negative": round(neg_count / scored_total * 100),
        }
    else:
        sentiment_distribution = {"positive": 0, "neutral": 0, "negative": 0}

    # === トピック分析（aspectsカラムから集計） ===
    aspect_sentiments: dict[str, list[float]] = {}
    aspect_counts: dict[str, int] = {}

    for r in reviews:
        aspects_data = None
        if r.aspects:
            try:
                aspects_data = json.loads(r.aspects)
            except (json.JSONDecodeError, TypeError):
                pass

        if aspects_data and isinstance(aspects_data, dict):
            for aspect_key, sentiment_label in aspects_data.items():
                aspect_counts[aspect_key] = aspect_counts.get(aspect_key, 0) + 1
                # sentimentラベルを数値化して平均化用に蓄積
                if r.sentiment_score is not None:
                    aspect_sentiments.setdefault(aspect_key, []).append(r.sentiment_score)
        elif not aspects_data and r.text:
            # aspectsが空の場合、テキストからキーワードマッチで分類
            _classify_text_aspects(r.text, r.sentiment_score, aspect_counts, aspect_sentiments)

    # トピックリスト構築（出現回数降順）
    topics = []
    for aspect_key, count in sorted(aspect_counts.items(), key=lambda x: x[1], reverse=True):
        label = _ASPECT_LABELS.get(aspect_key, aspect_key)
        scores = aspect_sentiments.get(aspect_key, [])
        avg_sent = round(sum(scores) / len(scores), 2) if scores else 0.0
        pct = round(count / total_reviews * 100)
        topics.append({
            "topic": label,
            "count": count,
            "avg_sentiment": avg_sent,
            "percentage": pct,
        })

    # === ハイライト抽出 ===
    strengths = _extract_highlights(reviews, positive=True)
    concerns = _extract_highlights(reviews, positive=False)

    # === レッドフラグ集計 ===
    red_flag_categories: dict[str, int] = {}
    red_flag_total = 0
    for r in reviews:
        if r.red_flags:
            try:
                flags = json.loads(r.red_flags)
                if flags:
                    red_flag_total += 1
                    for f in flags:
                        cat = f.get("category", "unknown") if isinstance(f, dict) else str(f)
                        red_flag_categories[cat] = red_flag_categories.get(cat, 0) + 1
            except (json.JSONDecodeError, TypeError):
                pass

    red_flag_summary = {
        "total": red_flag_total,
        "categories": red_flag_categories,
    }

    # === 品質スコア分布 ===
    quality_scores = [r.quality_score for r in reviews if r.quality_score is not None]
    if quality_scores:
        high_count = sum(1 for qs in quality_scores if qs >= 70)
        low_count = sum(1 for qs in quality_scores if qs < 40)
        standard_count = len(quality_scores) - high_count - low_count
        total_qs = len(quality_scores)
        quality_distribution = {
            "high": round(high_count / total_qs * 100, 1),
            "standard": round(standard_count / total_qs * 100, 1),
            "low": round(low_count / total_qs * 100, 1),
        }
    else:
        quality_distribution = {"high": 0, "standard": 0, "low": 0}

    # === トレンド分析（直近3ヶ月 vs それ以前） ===
    trend = _calculate_trend(reviews)

    return {
        "clinic_id": clinic_id,
        "clinic_name": clinic.name,
        "total_reviews": total_reviews,
        "avg_rating": avg_rating,
        "sentiment_distribution": sentiment_distribution,
        "topics": topics,
        "highlights": {
            "strengths": strengths,
            "concerns": concerns,
        },
        "red_flag_summary": red_flag_summary,
        "quality_distribution": quality_distribution,
        "trend": trend,
    }


def _classify_text_aspects(
    text: str,
    sentiment_score: float | None,
    aspect_counts: dict[str, int],
    aspect_sentiments: dict[str, list[float]],
) -> None:
    """
    テキストからキーワードマッチでアスペクトを分類する

    aspectsカラムが空の口コミに対して使用する。
    review_analyzer.pyのASPECT_KEYWORDSと同じ分類軸を使用。
    """
    from src.analyzers.review_analyzer import ASPECT_KEYWORDS

    for aspect_key, keywords in ASPECT_KEYWORDS.items():
        all_keywords = keywords.get("positive", []) + keywords.get("negative", [])
        if any(kw in text for kw in all_keywords):
            aspect_counts[aspect_key] = aspect_counts.get(aspect_key, 0) + 1
            if sentiment_score is not None:
                aspect_sentiments.setdefault(aspect_key, []).append(sentiment_score)


def _extract_highlights(reviews: list, positive: bool = True) -> list[str]:
    """
    ハイライト（強み / 懸念点）を抽出する

    sentiment_scoreが高い/低い口コミからキーワードマッチで頻出フレーズを抽出。
    上位5件を返す。
    """
    keywords = _HIGHLIGHT_POSITIVE_KEYWORDS if positive else _HIGHLIGHT_NEGATIVE_KEYWORDS
    threshold = 0.1 if positive else -0.1

    matched_keywords: list[str] = []
    for r in reviews:
        if r.sentiment_score is None or not r.text:
            continue

        # ポジティブ: スコアが閾値以上 / ネガティブ: スコアが閾値以下
        if positive and r.sentiment_score < threshold:
            continue
        if not positive and r.sentiment_score > threshold:
            continue

        for kw in keywords:
            if kw in r.text:
                matched_keywords.append(kw)

    # 頻出順に上位5件（重複なし）
    counter = Counter(matched_keywords)
    seen = set()
    result = []
    for kw, _ in counter.most_common():
        if kw not in seen and len(result) < 5:
            seen.add(kw)
            result.append(kw)
    return result


async def _batch_trend_directions(
    clinic_ids: list[str], db: AsyncSession
) -> dict[str, str]:
    """リスト表示用にトレンド方向をバッチ計算する（N+1回避）

    直近3ヶ月 vs それ以前の平均ratingを比較して
    improving / stable / declining を判定する。
    クリニックIDをキー、方向を値とした辞書を返す。
    データ不足のクリニックは結果に含めない。
    """
    if not clinic_ids:
        return {}

    from src.db.database import ReviewTable

    three_months_ago = datetime.now() - timedelta(days=90)

    # 直近3ヶ月の平均ratingをクリニック単位で取得
    recent_result = await db.execute(
        select(
            ReviewTable.clinic_id,
            func.avg(ReviewTable.rating).label("avg_rating"),
            func.count(ReviewTable.id).label("cnt"),
        )
        .where(ReviewTable.clinic_id.in_(clinic_ids))
        .where(ReviewTable.is_spam != True)
        .where(ReviewTable.rating.isnot(None))
        .where(ReviewTable.created_at >= three_months_ago)
        .group_by(ReviewTable.clinic_id)
    )
    recent_map = {
        row.clinic_id: (row.avg_rating, row.cnt) for row in recent_result.all()
    }

    # 3ヶ月より前の平均ratingをクリニック単位で取得
    older_result = await db.execute(
        select(
            ReviewTable.clinic_id,
            func.avg(ReviewTable.rating).label("avg_rating"),
            func.count(ReviewTable.id).label("cnt"),
        )
        .where(ReviewTable.clinic_id.in_(clinic_ids))
        .where(ReviewTable.is_spam != True)
        .where(ReviewTable.rating.isnot(None))
        .where(ReviewTable.created_at < three_months_ago)
        .group_by(ReviewTable.clinic_id)
    )
    older_map = {
        row.clinic_id: (row.avg_rating, row.cnt) for row in older_result.all()
    }

    # 方向を判定（各期間2件以上必要）
    trends: dict[str, str] = {}
    for cid in clinic_ids:
        recent = recent_map.get(cid)
        older = older_map.get(cid)
        if not recent or not older:
            continue
        if recent[1] < 2 or older[1] < 2:
            continue
        diff = recent[0] - older[0]
        if diff > 0.3:
            trends[cid] = "improving"
        elif diff < -0.3:
            trends[cid] = "declining"
        else:
            trends[cid] = "stable"

    return trends


def _calculate_trend(reviews: list) -> dict | None:

    """
    口コミの時系列トレンドを分析する

    直近3ヶ月 vs それ以前の平均ratingを比較して
    improving / stable / declining を判定する。
    """
    three_months_ago = datetime.now() - timedelta(days=90)

    recent_ratings = []
    older_ratings = []

    for r in reviews:
        if r.rating is None:
            continue
        # timezone-aware/naiveの混在に対応
        created = r.created_at
        if created and created.tzinfo is not None:
            created = created.replace(tzinfo=None)
        if created and created >= three_months_ago:
            recent_ratings.append(r.rating)
        else:
            older_ratings.append(r.rating)

    # 比較に十分なデータがない場合はNone
    if len(recent_ratings) < 2 or len(older_ratings) < 2:
        return None

    recent_avg = round(sum(recent_ratings) / len(recent_ratings), 1)
    older_avg = round(sum(older_ratings) / len(older_ratings), 1)

    diff = recent_avg - older_avg
    if diff > 0.3:
        direction = "improving"
    elif diff < -0.3:
        direction = "declining"
    else:
        direction = "stable"

    return {
        "direction": direction,
        "recent_avg": recent_avg,
        "older_avg": older_avg,
    }
