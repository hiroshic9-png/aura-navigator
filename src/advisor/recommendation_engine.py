"""
AURA MVP — パーソナライズド推薦エンジン

ユーザーの条件（悩み・エリア・予算・DT制約・優先度）に基づいて
クリニックをスコアリングし、根拠付きの候補リストを返す。

設計思想:
- 「推薦」ではなく「条件マッチに基づく選択支援」
- 医師法17条・72条の制約内で、ユーザーが最も欲しい情報を返す
- 全ての候補に「なぜこの候補が選ばれたか」の根拠を付与
"""

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import ClinicTable, ProcedureTable, ClinicProcedure, DoctorTable, ReviewTable, CasePhotoTable

logger = logging.getLogger(__name__)


# ==========================================
# ユーザー条件モデル
# ==========================================

class UserPriority(str, Enum):
    """ユーザーの優先事項"""
    QUALITY = "quality"      # 品質・安全性重視
    PRICE = "price"          # コスト重視
    CONVENIENCE = "convenience"  # 利便性（場所・DT）重視
    BALANCED = "balanced"    # バランス型


@dataclass
class UserConditions:
    """ユーザーの条件（インテークで収集）"""
    concern_tags: list[str] = field(default_factory=list)  # 悩みタグ（例: ["double"]）
    concern_text: str = ""           # 悩みの原文（例: "二重にしたい"）
    area: str | None = None          # エリア（例: "渋谷区"）
    budget: int | None = None        # 予算（円）
    downtime_days: int | None = None # 確保可能DT（日数）
    age_range: str | None = None     # 年代
    priority: UserPriority = UserPriority.BALANCED
    previous_procedures: list[str] = field(default_factory=list)


# ==========================================
# マッチ結果モデル
# ==========================================

@dataclass
class ProcedureMatch:
    """マッチした施術"""
    procedure_id: str
    name: str
    category: str
    invasiveness: str
    price_display: str = ""
    dt_real: str = ""
    budget_fit: bool = True     # 予算内か
    dt_fit: bool = True         # DT条件に合うか


@dataclass
class ClinicMatch:
    """マッチしたクリニック"""
    clinic_id: str
    name: str
    address: str
    city: str | None
    google_rating: float | None
    google_review_count: int | None
    departments: list[str]
    procedures: list[ProcedureMatch]
    doctors: list[dict]              # 在籍医師（簡易情報）
    match_score: float = 0.0         # 総合スコア（0-100）
    match_reasons: list[str] = field(default_factory=list)  # 選ばれた理由
    cautions: list[str] = field(default_factory=list)       # 注意点
    has_specialist: bool = False     # 専門医在籍
    google_place_id: str | None = None
    thumbnail_ref: str | None = None
    website: str | None = None
    transparency_score: float | None = None  # AURA透明性スコア
    review_summary: dict | None = None       # 口コミ分析サマリー（将来用）
    case_photo_count: int = 0                # 症例写真件数


@dataclass
class RecommendationResult:
    """推薦結果"""
    user_conditions: UserConditions
    matched_procedures: list[dict]    # マッチした施術の一般情報
    clinic_matches: list[ClinicMatch] # スコア順のクリニック候補
    total_candidates: int             # 候補総数（フィルタ前）
    summary: str                      # 条件サマリーテキスト


# ==========================================
# エリアマッチング
# ==========================================

# エリアキーワード → 区名マッピング
AREA_MAP = {
    # 主要エリア名
    "渋谷": "渋谷区", "新宿": "新宿区", "銀座": "中央区",
    "池袋": "豊島区", "品川": "品川区", "表参道": "渋谷区",
    "六本木": "港区", "恵比寿": "渋谷区", "原宿": "渋谷区",
    "青山": "港区", "赤坂": "港区", "麻布": "港区",
    "有楽町": "千代田区", "丸の内": "千代田区", "秋葉原": "千代田区",
    "日本橋": "中央区", "上野": "台東区", "浅草": "台東区",
    "自由が丘": "目黒区", "中目黒": "目黒区", "目黒": "目黒区",
    "吉祥寺": "武蔵野市", "立川": "立川市", "町田": "町田市",
    "八王子": "八王子市", "二子玉川": "世田谷区", "三軒茶屋": "世田谷区",
    # 区名そのまま
    "渋谷区": "渋谷区", "新宿区": "新宿区", "中央区": "中央区",
    "港区": "港区", "豊島区": "豊島区", "千代田区": "千代田区",
    "品川区": "品川区", "目黒区": "目黒区", "世田谷区": "世田谷区",
    "台東区": "台東区", "文京区": "文京区", "江東区": "江東区",
    "大田区": "大田区", "杉並区": "杉並区", "練馬区": "練馬区",
    "板橋区": "板橋区", "北区": "北区", "荒川区": "荒川区",
    "足立区": "足立区", "葛飾区": "葛飾区", "江戸川区": "江戸川区",
    "墨田区": "墨田区", "中野区": "中野区",
}

# 隣接エリア（近い区）
ADJACENT_AREAS = {
    "渋谷区": ["港区", "目黒区", "世田谷区", "新宿区"],
    "新宿区": ["渋谷区", "豊島区", "中野区", "千代田区"],
    "中央区": ["千代田区", "港区", "江東区", "台東区"],
    "港区": ["渋谷区", "中央区", "千代田区", "品川区"],
    "豊島区": ["新宿区", "板橋区", "北区", "文京区"],
    "千代田区": ["中央区", "港区", "新宿区", "文京区", "台東区"],
    "品川区": ["港区", "目黒区", "大田区"],
    "目黒区": ["渋谷区", "品川区", "世田谷区"],
    "世田谷区": ["渋谷区", "目黒区", "杉並区"],
    "台東区": ["千代田区", "文京区", "墨田区", "荒川区"],
    "文京区": ["千代田区", "豊島区", "台東区", "新宿区"],
}


def resolve_area(area_text: str) -> tuple[str | None, list[str]]:
    """
    エリアテキストを区名に解決し、隣接エリアも返す

    Returns:
        (primary_city, adjacent_cities)
    """
    if not area_text:
        return None, []

    # 直接マッチ
    for keyword, city in AREA_MAP.items():
        if keyword in area_text:
            adjacent = ADJACENT_AREAS.get(city, [])
            return city, adjacent

    return None, []


# ==========================================
# 予算パースング
# ==========================================

def parse_budget(text: str) -> int | None:
    """予算テキストを円に変換"""
    if not text:
        return None

    import re
    text = text.replace(",", "").replace("、", "").replace(" ", "")

    # 「15万」「15万円」パターン
    m = re.search(r"(\d+(?:\.\d+)?)\s*万", text)
    if m:
        return int(float(m.group(1)) * 10000)

    # 「150000」「150000円」パターン
    m = re.search(r"(\d{4,})", text)
    if m:
        return int(m.group(1))

    # 「15」（万単位と推定）
    m = re.search(r"^(\d{1,3})$", text.replace("円", ""))
    if m:
        val = int(m.group(1))
        if val < 1000:
            return val * 10000  # 万単位と推定
        return val

    return None


# ==========================================
# DT日数パース
# ==========================================

def parse_downtime_days(text: str) -> int | None:
    """DTテキストを日数に変換"""
    if not text:
        return None

    import re
    text = text.replace(" ", "")

    # 「3日」「3日間」パターン
    m = re.search(r"(\d+)\s*日", text)
    if m:
        return int(m.group(1))

    # 「1週間」パターン
    m = re.search(r"(\d+)\s*週", text)
    if m:
        return int(m.group(1)) * 7

    # 「なし」「取れない」パターン
    if any(kw in text for kw in ["なし", "取れない", "ない", "0"]):
        return 0

    return None


def estimate_dt_days(dt_real_text: str) -> int | None:
    """施術のリアルDTテキストから日数を推定"""
    if not dt_real_text:
        return None

    import re
    text = dt_real_text

    # 「1-2週間」→ 平均を取る
    m = re.search(r"(\d+)[〜\-~](\d+)\s*週", text)
    if m:
        return (int(m.group(1)) + int(m.group(2))) * 7 // 2

    # 「3-5日」パターン
    m = re.search(r"(\d+)[〜\-~](\d+)\s*日", text)
    if m:
        return (int(m.group(1)) + int(m.group(2))) // 2

    # 「2週間」パターン
    m = re.search(r"(\d+)\s*週", text)
    if m:
        return int(m.group(1)) * 7

    # 「5日」パターン
    m = re.search(r"(\d+)\s*日", text)
    if m:
        return int(m.group(1))

    # 「1ヶ月」「1か月」パターン
    m = re.search(r"(\d+)\s*[ヶか]\s*月", text)
    if m:
        return int(m.group(1)) * 30

    return None


# ==========================================
# スコアリングエンジン
# ==========================================
# 口コミ Time Decay（時間減衰）
# ==========================================


def time_decay_weight(review_date, half_life_days=365):
    """
    口コミの鮮度に基づく重みを算出（指数減衰）

    半減期365日: 1年前の口コミは重み0.5、2年前は0.25...
    新しい口コミほど重みが大きくなる。

    Args:
        review_date: 口コミの投稿日時（datetime）
        half_life_days: 半減期（日数）、デフォルト365日

    Returns:
        0.0〜1.0 の重み値
    """
    if not review_date:
        return 0.5  # 日付不明の場合は中間値
    # timezoneが設定されていない場合はUTCとみなす
    if review_date.tzinfo is None:
        review_date = review_date.replace(tzinfo=timezone.utc)
    days_ago = (datetime.now(timezone.utc) - review_date).days
    if days_ago < 0:
        days_ago = 0
    return math.exp(-0.693 * days_ago / half_life_days)


# ==========================================

def calculate_quality_score(
    google_rating: float | None,
    google_review_count: int | None,
    has_specialist: bool,
    departments: list[str],
    transparency_score: float | None = None,
    review_sentiment: float | None = None,
    review_data: list[dict] | None = None,
    case_photo_count: int = 0,
) -> float:
    """
    品質スコアを算出（0-100）

    構成（7軸）:
    - Google評価: 最大30pt（4.5以上=30, 4.0=22, 3.5=15, 3.0=8, なし=11）
    - 口コミ件数: 最大18pt（100件以上=18, 50件=12, 10件=4）
    - 口コミ評判: 最大10pt（感情スコア-1.0〜+1.0を正規化、時間減衰適用）
    - 専門医在籍: 13pt
    - 診療科の幅: 最大14pt（美容外科+形成外科=14, 美容外科のみ=9）
    - 透明性スコア: 最大5pt（AURA独自指標、情報開示度を反映）
    - 症例写真充実度: 最大8pt（DEC-0044: 症例写真起点への構造転換）

    Args:
        review_data: 口コミデータのリスト [{"sentiment_score": float, "created_at": datetime}, ...]
                     指定された場合、review_sentimentの代わりに時間減衰加重平均を使用
        case_photo_count: クリニックに紐付いた症例写真の件数
    """
    score = 0.0

    # Google評価
    if google_rating is not None:
        if google_rating >= 4.5:
            score += 30
        elif google_rating >= 4.0:
            score += 22
        elif google_rating >= 3.5:
            score += 15
        elif google_rating >= 3.0:
            score += 8
        else:
            score += 3
    else:
        score += 11

    # 口コミ件数（信頼性の指標）
    if google_review_count is not None and google_review_count > 0:
        review_score = min(18, math.log(google_review_count + 1) * 3.5)
        score += review_score
    else:
        score += 3

    # 口コミ評判（感情スコア） — Time Decay対応
    effective_sentiment = review_sentiment
    if review_data:
        # 時間減衰加重平均を算出
        weighted_sum = 0.0
        weight_total = 0.0
        for rv in review_data:
            sentiment = rv.get("sentiment_score")
            if sentiment is not None:
                w = time_decay_weight(rv.get("created_at"))
                weighted_sum += sentiment * w
                weight_total += w
        if weight_total > 0:
            effective_sentiment = weighted_sum / weight_total

    if effective_sentiment is not None:
        # -1.0〜+1.0 → 0〜10pt に正規化
        sentiment_pt = max(0, min(10, (effective_sentiment + 1.0) * 5))
        score += sentiment_pt
    else:
        score += 5  # 未取得の場合は中間値

    # 専門医在籍
    if has_specialist:
        score += 13

    # 診療科の幅
    dept_set = set(departments)
    if "美容外科" in dept_set and "形成外科" in dept_set:
        score += 14  # 両方 = 最も信頼性高い
    elif "形成外科" in dept_set:
        score += 11
    elif "美容外科" in dept_set:
        score += 9
    elif "美容皮膚科" in dept_set:
        score += 7

    # 透明性スコア（参考情報として低い重みで反映）
    # 注: 情報開示度がマッチングを過度に左右しないよう抑制（15pt→5pt）
    if transparency_score is not None and transparency_score > 0:
        score += min(5, transparency_score * 0.05)
    else:
        score += 2

    # 症例写真充実度（DEC-0044: 症例写真起点への構造転換）
    # 症例写真が多いクリニック = ユーザーが施術結果を確認しやすい = 情報価値が高い
    if case_photo_count >= 100:
        score += 8
    elif case_photo_count >= 50:
        score += 6
    elif case_photo_count >= 20:
        score += 4
    elif case_photo_count >= 5:
        score += 2

    return min(100, score)


def calculate_match_score(
    quality_score: float,
    area_match: str,       # "exact" / "adjacent" / "none"
    budget_fit: bool,
    dt_fit: bool,
    priority: UserPriority,
) -> float:
    """
    総合マッチスコアを算出（0-100）

    重みはユーザーの優先度で変動:
    - quality: 品質60% エリア20% 予算10% DT10%
    - price: 品質20% エリア20% 予算40% DT20%
    - convenience: 品質20% エリア40% 予算10% DT30%
    - balanced: 品質35% エリア25% 予算20% DT20%
    """
    weights = {
        UserPriority.QUALITY:      {"quality": 0.60, "area": 0.20, "budget": 0.10, "dt": 0.10},
        UserPriority.PRICE:        {"quality": 0.20, "area": 0.20, "budget": 0.40, "dt": 0.20},
        UserPriority.CONVENIENCE:  {"quality": 0.20, "area": 0.40, "budget": 0.10, "dt": 0.30},
        UserPriority.BALANCED:     {"quality": 0.35, "area": 0.25, "budget": 0.20, "dt": 0.20},
    }
    w = weights[priority]

    # 各軸のスコア（0-100）
    area_score = {"exact": 100, "adjacent": 60, "none": 20}.get(area_match, 20)
    budget_score = 100 if budget_fit else 30
    dt_score = 100 if dt_fit else 20

    total = (
        quality_score * w["quality"]
        + area_score * w["area"]
        + budget_score * w["budget"]
        + dt_score * w["dt"]
    )
    return round(total, 1)


# ==========================================
# 根拠文生成
# ==========================================

def generate_match_reasons(
    clinic: ClinicTable,
    departments: list[str],
    quality_score: float,
    area_match: str,
    budget_fit: bool,
    dt_fit: bool,
    has_specialist: bool,
    matched_proc_names: list[str],
    transparency_score: float | None = None,
) -> list[str]:
    """マッチ理由の自然言語テキストを生成"""
    reasons = []

    # エリア
    if area_match == "exact":
        reasons.append(f"{clinic.city}に所在")
    elif area_match == "adjacent":
        reasons.append(f"近隣エリア（{clinic.city}）に所在")

    # 評価
    if clinic.google_rating and clinic.google_rating >= 4.5:
        count_text = f"（{clinic.google_review_count}件の口コミ）" if clinic.google_review_count else ""
        reasons.append(f"Google評価 ★{clinic.google_rating:.1f}{count_text}")
    elif clinic.google_rating and clinic.google_rating >= 4.0:
        count_text = f"（{clinic.google_review_count}件）" if clinic.google_review_count else ""
        reasons.append(f"Google評価 ★{clinic.google_rating:.1f}{count_text}")

    # 専門医
    if has_specialist:
        reasons.append("形成外科専門医が在籍")

    # 診療科
    if "美容外科" in departments and "形成外科" in departments:
        reasons.append("美容外科と形成外科の両方を標榜")

    # 透明性スコア
    if transparency_score is not None and transparency_score >= 40:
        reasons.append(f"情報開示度が高い（{transparency_score:.0f}pt）")

    # 対応施術
    if matched_proc_names:
        proc_text = "・".join(matched_proc_names[:3])
        reasons.append(f"対応施術: {proc_text}")

    # 予算
    if budget_fit:
        reasons.append("予算内の施術あり")

    # DT
    if dt_fit:
        reasons.append("希望のダウンタイム内で対応可能")

    return reasons


# レッドフラグカテゴリのラベル・深刻度定義
RED_FLAG_LABELS = {
    "pressure_sales": {
        "label": "圧力販売",
        "mild": "圧力販売に関する口コミが{count}件あります",
        "severe": "強引な勧誘の報告が{count}件あります。断る準備をしてカウンセリングに臨んでください",
        "threshold": 3,  # この件数以上で深刻表現に切り替え
    },
    "treatment_trouble": {
        "label": "施術トラブル",
        "mild": "施術結果への不満が{count}件報告されています",
        "severe": "施術結果への不満が{count}件報告されています。詳細を確認してください",
        "threshold": 2,  # 施術トラブルは深刻度が高いため閾値低め
    },
    "staff_issue": {
        "label": "スタッフ対応",
        "mild": "スタッフ対応に関する指摘が{count}件あります",
        "severe": "スタッフ対応に関する苦情が{count}件あります。事前にカウンセリングの対応を見極めてください",
        "threshold": 3,
    },
    "billing_issue": {
        "label": "会計トラブル",
        "mild": "料金に関する指摘が{count}件あります",
        "severe": "料金に関するトラブルの報告が{count}件あります。見積もりを書面で確認してください",
        "threshold": 2,
    },
}


def generate_cautions(
    clinic: ClinicTable,
    departments: list[str],
    google_rating: float | None,
    google_review_count: int | None,
    review_summary: dict | None = None,
) -> list[str]:
    """
    注意点を生成（口コミ分析データ・レッドフラグ詳細分析を含む）

    レッドフラグはカテゴリ別に件数を集計し、深刻度に応じて文面を変える:
    - pressure_sales: 圧力販売
    - treatment_trouble: 施術トラブル（深刻度高）
    - staff_issue: スタッフ対応問題
    - billing_issue: 会計トラブル（深刻度高）
    """
    cautions = []

    if google_rating is not None and google_rating < 3.5:
        cautions.append(f"Google評価が★{google_rating:.1f}とやや低め。口コミの内容を確認されることをおすすめします")

    if google_review_count is not None and google_review_count < 10:
        cautions.append("口コミ件数が少ないため、評価の信頼性は参考程度です")

    if not google_rating:
        cautions.append("Googleの評価データがありません（新しいクリニック、または非掲載の可能性）")

    # 口コミ分析に基づく注意点
    if review_summary:
        avg_sentiment = review_summary.get("avg_sentiment")
        if avg_sentiment is not None and avg_sentiment < 0:
            cautions.append("口コミの評判がやや厳しめです。具体的な内容を事前にご確認ください")

        # ネガティブアスペクトの検出
        top_aspects = review_summary.get("top_aspects", [])
        for aspect in top_aspects:
            if "待ち時間" in aspect:
                cautions.append("待ち時間に関する指摘が複数あります")
                break

        # レッドフラグに基づく注意事項（カテゴリ別・深刻度別）
        red_flags = review_summary.get("red_flags", {})
        for category, count in red_flags.items():
            if count < 1:
                continue
            config = RED_FLAG_LABELS.get(category)
            if config:
                threshold = config["threshold"]
                if count >= threshold:
                    cautions.append(config["severe"].format(count=count))
                else:
                    cautions.append(config["mild"].format(count=count))
            else:
                # 未定義カテゴリの場合は汎用メッセージ
                cautions.append(f"口コミに「{category}」に関する指摘が{count}件あります")

    return cautions


# ==========================================
# メイン推薦ロジック
# ==========================================

async def recommend_clinics(
    db: AsyncSession,
    conditions: UserConditions,
    max_results: int = 5,
) -> RecommendationResult:
    """
    条件に基づくクリニック推薦を実行

    1. 悩みタグから関連施術を特定
    2. その施術に対応するクリニックを抽出（clinic_procedures経由）
    3. 各クリニックをスコアリング
    4. 根拠付きで上位候補を返す
    """

    # === Step 1: 悩みタグ → 関連施術 ===
    proc_result = await db.execute(select(ProcedureTable))
    all_procedures = proc_result.scalars().all()

    matched_procedures = []
    for proc in all_procedures:
        try:
            proc_concerns = json.loads(proc.matches_concern or "[]")
        except (json.JSONDecodeError, TypeError):
            proc_concerns = []

        if any(tag in proc_concerns for tag in conditions.concern_tags):
            # DT適合チェック
            dt_days = estimate_dt_days(proc.downtime_real or "")
            dt_fit = True
            if conditions.downtime_days is not None and dt_days is not None:
                dt_fit = dt_days <= conditions.downtime_days

            # 予算適合チェック（施術マスタの一般価格帯）
            budget_fit = True
            if conditions.budget is not None:
                try:
                    real_price = json.loads(proc.real_price or "{}")
                    min_price = real_price.get("min_price", 0) if isinstance(real_price, dict) else 0
                    if min_price > 0:
                        budget_fit = conditions.budget >= min_price
                except (json.JSONDecodeError, TypeError):
                    pass

            # 価格表示テキスト
            price_display = ""
            try:
                adv = json.loads(proc.advertised_price or "{}")
                price_display = adv.get("display", "") if isinstance(adv, dict) else ""
            except (json.JSONDecodeError, TypeError):
                pass

            matched_procedures.append(ProcedureMatch(
                procedure_id=proc.id,
                name=proc.name,
                category=proc.category,
                invasiveness=proc.invasiveness or "",
                price_display=price_display,
                dt_real=proc.downtime_real or "",
                budget_fit=budget_fit,
                dt_fit=dt_fit,
            ))

    if not matched_procedures:
        return RecommendationResult(
            user_conditions=conditions,
            matched_procedures=[],
            clinic_matches=[],
            total_candidates=0,
            summary="お悩みに合致する施術が見つかりませんでした。",
        )

    # === Step 2: 施術に対応するクリニック抽出 ===
    proc_ids = [p.procedure_id for p in matched_procedures]

    # clinic_proceduresテーブルから対応クリニックを取得
    cp_result = await db.execute(
        select(ClinicProcedure)
        .where(ClinicProcedure.procedure_id.in_(proc_ids))
        .where(ClinicProcedure.is_active == True)
    )
    clinic_procedures = cp_result.scalars().all()

    # クリニックID → 対応施術IDのマッピング（source情報も保持）
    clinic_proc_map: dict[str, list[str]] = {}
    clinic_proc_sources: dict[str, set[str]] = {}  # クリニックの施術データソース
    clinic_proc_prices: dict[str, dict[str, int | None]] = {}  # 施術別価格
    for cp in clinic_procedures:
        clinic_proc_map.setdefault(cp.clinic_id, []).append(cp.procedure_id)
        clinic_proc_sources.setdefault(cp.clinic_id, set()).add(cp.source or "unknown")
        # 価格情報（website_scrapeの場合はclinic_procedures側の価格を使用）
        if cp.price_advertised:
            clinic_proc_prices.setdefault(cp.clinic_id, {})[cp.procedure_id] = cp.price_advertised

    if not clinic_proc_map:
        return RecommendationResult(
            user_conditions=conditions,
            matched_procedures=[_proc_to_dict(p) for p in matched_procedures],
            clinic_matches=[],
            total_candidates=0,
            summary="関連施術はありますが、対応クリニックのデータがまだ紐付けされていません。",
        )

    # クリニック情報取得
    clinic_ids = list(clinic_proc_map.keys())
    clinic_result = await db.execute(
        select(ClinicTable)
        .where(ClinicTable.id.in_(clinic_ids))
        .where(ClinicTable.is_active == True)
    )
    clinics = clinic_result.scalars().all()

    # 医師データ取得
    doctor_result = await db.execute(
        select(DoctorTable).where(DoctorTable.clinic_id.in_(clinic_ids))
    )
    doctors = doctor_result.scalars().all()
    doctor_map: dict[str, list[DoctorTable]] = {}
    for doc in doctors:
        doctor_map.setdefault(doc.clinic_id, []).append(doc)

    # 口コミ集計データ取得（クリニック別の平均感情スコア+上位アスペクト）
    review_result = await db.execute(
        select(
            ReviewTable.clinic_id,
            func.avg(ReviewTable.sentiment_score).label("avg_sentiment"),
            func.count(ReviewTable.id).label("review_count"),
            func.avg(ReviewTable.quality_score).label("avg_quality"),
        )
        .where(ReviewTable.clinic_id.in_(clinic_ids))
        .where(ReviewTable.is_spam != True)
        .where(ReviewTable.analyzed_at.isnot(None))
        .group_by(ReviewTable.clinic_id)
    )
    review_stats_map: dict[str, dict] = {}
    for row in review_result:
        review_stats_map[row.clinic_id] = {
            "avg_sentiment": row.avg_sentiment,
            "review_count": row.review_count,
            "avg_quality": round(row.avg_quality, 1) if row.avg_quality else None,
        }

    # Time Decay用: 口コミ個別データ取得（sentiment_score + created_at）
    review_detail_result = await db.execute(
        select(
            ReviewTable.clinic_id,
            ReviewTable.sentiment_score,
            ReviewTable.created_at,
        )
        .where(ReviewTable.clinic_id.in_(clinic_ids))
        .where(ReviewTable.is_spam != True)
        .where(ReviewTable.sentiment_score.isnot(None))
    )
    clinic_review_data: dict[str, list[dict]] = {}
    for row in review_detail_result:
        clinic_review_data.setdefault(row.clinic_id, []).append({
            "sentiment_score": row.sentiment_score,
            "created_at": row.created_at,
        })

    # 口コミアスペクト集計（上位アスペクトを取得）
    aspect_result = await db.execute(
        select(ReviewTable.clinic_id, ReviewTable.aspects)
        .where(ReviewTable.clinic_id.in_(clinic_ids))
        .where(ReviewTable.is_spam != True)
        .where(ReviewTable.aspects.isnot(None))
    )
    clinic_aspects: dict[str, dict[str, int]] = {}
    aspect_labels = {
        "service": "接客◎", "skill": "技術◎", "price": "コスパ◎",
        "wait": "待ち時間△", "facility": "施設◎",
    }
    for row in aspect_result:
        try:
            aspects = json.loads(row.aspects) if row.aspects else {}
            for aspect_name, direction in aspects.items():
                if direction == "positive":
                    clinic_aspects.setdefault(row.clinic_id, {}).setdefault(aspect_name, 0)
                    clinic_aspects[row.clinic_id][aspect_name] += 1
        except (json.JSONDecodeError, TypeError):
            pass

    # Phase 12: クリニック別レッドフラグ集計
    red_flag_result = await db.execute(
        select(ReviewTable.clinic_id, ReviewTable.red_flags)
        .where(ReviewTable.clinic_id.in_(clinic_ids))
        .where(ReviewTable.red_flags.isnot(None))
        .where(ReviewTable.is_spam != True)
    )
    clinic_red_flags: dict[str, dict[str, int]] = {}
    for row in red_flag_result:
        try:
            flags = json.loads(row.red_flags) if row.red_flags else []
            for f in flags:
                cat = f.get("category", "unknown")
                clinic_red_flags.setdefault(row.clinic_id, {}).setdefault(cat, 0)
                clinic_red_flags[row.clinic_id][cat] += 1
        except (json.JSONDecodeError, TypeError):
            pass

    # 症例写真件数の一括取得（DEC-0044: 症例写真起点への構造転換）
    photo_count_result = await db.execute(
        select(
            CasePhotoTable.clinic_id,
            func.count(CasePhotoTable.id).label("photo_count"),
        )
        .where(CasePhotoTable.clinic_id.in_(clinic_ids))
        .where(CasePhotoTable.is_active == True)
        .where(CasePhotoTable.before_image_url.isnot(None))
        .group_by(CasePhotoTable.clinic_id)
    )
    clinic_photo_counts: dict[str, int] = {}
    for row in photo_count_result:
        clinic_photo_counts[row.clinic_id] = row.photo_count

    # === Step 3: エリア解決 ===
    primary_city, adjacent_cities = resolve_area(conditions.area or "")

    # === Step 4: スコアリング ===
    total_candidates = len(clinics)
    clinic_matches: list[ClinicMatch] = []

    # 施術IDからProcedureMatchを逆引き
    proc_match_map = {p.procedure_id: p for p in matched_procedures}

    for clinic in clinics:
        # 診療科
        try:
            departments = json.loads(clinic.medical_departments or "[]")
        except (json.JSONDecodeError, TypeError):
            departments = []

        # このクリニックが対応する施術
        clinic_proc_ids = clinic_proc_map.get(clinic.id, [])
        clinic_procs = [proc_match_map[pid] for pid in clinic_proc_ids if pid in proc_match_map]

        if not clinic_procs:
            continue

        # 医師
        clinic_doctors = doctor_map.get(clinic.id, [])
        has_specialist = any(
            "形成外科" in (doc.board_certifications or "")
            for doc in clinic_doctors
        )

        # 医師の質を品質スコアに追加反映（specialties/experience_years活用）
        doctor_quality_bonus = 0
        for doc in clinic_doctors:
            # 経験年数ボーナス（最大5pt）
            if doc.experience_years and doc.experience_years >= 10:
                doctor_quality_bonus = max(doctor_quality_bonus, 5)
            elif doc.experience_years and doc.experience_years >= 5:
                doctor_quality_bonus = max(doctor_quality_bonus, 3)
            # 専門分野が明記されている（最大3pt）
            if doc.specialties and doc.specialties != "[]":
                doctor_quality_bonus = min(doctor_quality_bonus + 2, 8)
            # trust_scoreが高い（最大4pt）
            if doc.trust_score and doc.trust_score >= 60:
                doctor_quality_bonus = min(doctor_quality_bonus + 4, 12)

        # エリアマッチ
        area_match = "none"
        if primary_city:
            if clinic.city == primary_city:
                area_match = "exact"
            elif clinic.city in adjacent_cities:
                area_match = "adjacent"

        # 予算・DT適合（施術単位のフラグを集約）
        any_budget_fit = any(p.budget_fit for p in clinic_procs)
        any_dt_fit = any(p.dt_fit for p in clinic_procs)

        # 口コミセンチメント
        review_stats = review_stats_map.get(clinic.id)
        review_sentiment = review_stats["avg_sentiment"] if review_stats else None

        # Time Decay用口コミデータ
        rv_data = clinic_review_data.get(clinic.id)

        # 品質スコア
        quality_score = calculate_quality_score(
            clinic.google_rating,
            clinic.google_review_count,
            has_specialist,
            departments,
            transparency_score=clinic.transparency_score,
            review_sentiment=review_sentiment,
            review_data=rv_data,
            case_photo_count=clinic_photo_counts.get(clinic.id, 0),
        )
        # 医師データはUIの参考情報として保持するが、マッチスコアには影響させない
        # 理由: 情報が多い医師＝良い医師ではない（情報開示バイアスの防止）
        # doctor_quality_bonus は ClinicMatch.doctors に含めて表示用に使う

        # 施術マッチングボーナス（+15pt）
        # ユーザーの希望施術に対応するクリニックにボーナスを付与
        procedure_match_bonus = 0
        if clinic_proc_ids:  # clinic_proceduresテーブルに紐付けがある
            procedure_match_bonus = 15

        # 総合スコア
        match_score = calculate_match_score(
            quality_score + procedure_match_bonus, area_match,
            any_budget_fit, any_dt_fit,
            conditions.priority,
        )

        # 根拠文
        matched_proc_names = [p.name for p in clinic_procs]
        # データソース情報を追加
        sources = clinic_proc_sources.get(clinic.id, set())
        has_website_data = "website_scrape" in sources
        has_chain_data = "chain_inference" in sources
        reasons = generate_match_reasons(
            clinic, departments, quality_score,
            area_match, any_budget_fit, any_dt_fit,
            has_specialist, matched_proc_names,
            transparency_score=clinic.transparency_score,
        )
        # データソースに応じた理由を追加
        if has_website_data:
            reasons.append("公式サイトで施術メニュー確認済み")
        elif has_chain_data:
            reasons.append("同系列院のメニューデータあり")
        # 症例写真充実度を理由に追加
        photo_cnt = clinic_photo_counts.get(clinic.id, 0)
        if photo_cnt >= 50:
            reasons.append(f"症例写真 {photo_cnt}件（施術結果を確認できます）")
        elif photo_cnt >= 10:
            reasons.append(f"症例写真 {photo_cnt}件あり")
        # 口コミサマリー（cautionsより先に生成）
        review_summary = None
        if review_stats:
            top_aspects = []
            aspects_data = clinic_aspects.get(clinic.id, {})
            sorted_aspects = sorted(aspects_data.items(), key=lambda x: x[1], reverse=True)
            for aspect_name, count in sorted_aspects[:3]:
                if count >= 2:  # 2件以上言及されたアスペクトのみ
                    label = aspect_labels.get(aspect_name, aspect_name)
                    top_aspects.append(label)
            review_summary = {
                "avg_sentiment": round(review_stats["avg_sentiment"], 2),
                "review_count": review_stats["review_count"],
                "avg_quality": review_stats.get("avg_quality"),
                "top_aspects": top_aspects,
            }
            # レッドフラグがあれば追加
            flags = clinic_red_flags.get(clinic.id, {})
            if flags:
                review_summary["red_flags"] = flags

        cautions = generate_cautions(
            clinic, departments,
            clinic.google_rating, clinic.google_review_count,
            review_summary=review_summary,
        )

        # 写真参照キー
        thumbnail_ref = None
        try:
            photos = json.loads(clinic.google_photos or "[]")
            if photos:
                thumbnail_ref = photos[0]
        except (json.JSONDecodeError, TypeError):
            pass

        # 医師情報（trust_score・資格・勤務経歴・JSAPSを含む強化版）
        doctor_info = []
        # Phase 14: マッチした施術のカテゴリを収集
        matched_categories = set()
        for pm in clinic_procs:
            for mp in matched_procedures:
                if mp.procedure_id == pm["procedure_id"]:
                    matched_categories.add(mp.category)
                    break

        has_specialist_for_procedure = False
        for doc in clinic_doctors:
            doc_dict = {
                "name": doc.name,
                "title": doc.title,
                "experience_years": doc.experience_years,
                "trust_score": doc.trust_score,
                "hospital_background": getattr(doc, "hospital_background", None),
                "jsaps_certified": getattr(doc, "jsaps_certified", False) or False,
            }
            # 情報開示レベルを付与
            from src.analyzers.doctor_scoring import get_trust_level
            if doc.trust_score is not None:
                doc_dict["trust_level"] = get_trust_level(doc.trust_score)
            if doc.board_certifications:
                try:
                    certs = json.loads(doc.board_certifications)
                    doc_dict["certifications"] = certs
                except (json.JSONDecodeError, TypeError):
                    doc_dict["certifications"] = []
            if doc.specialties:
                try:
                    specs = json.loads(doc.specialties)
                    doc_dict["specialties"] = specs
                except (json.JSONDecodeError, TypeError):
                    doc_dict["specialties"] = []

            # Phase 14: 医師×施術 専門性マッピング
            from src.analyzers.doctor_specialty import estimate_doctor_specialties, match_doctor_to_procedure_category
            doc_specialty = estimate_doctor_specialties(
                doctor_id=getattr(doc, "id", ""),
                doctor_name=doc.name or "",
                certifications=doc_dict.get("certifications", []),
                specialties=doc_dict.get("specialties", []),
                jsaps_certified=doc_dict.get("jsaps_certified", False),
                hospital_background=getattr(doc, "hospital_background", None),
            )
            if doc_specialty.matched_categories:
                doc_dict["specialty_categories"] = list(doc_specialty.matched_categories)
                doc_dict["specialty_confidence"] = doc_specialty.confidence
                # マッチした施術カテゴリとの交差判定
                for cat in matched_categories:
                    if match_doctor_to_procedure_category(doc_specialty, cat):
                        has_specialist_for_procedure = True
                        break

            doctor_info.append(doc_dict)

        # 専門医理由を追加
        if has_specialist_for_procedure:
            reasons.append("この施術の専門医が在籍")

        clinic_matches.append(ClinicMatch(
            clinic_id=clinic.id,
            name=clinic.name,
            address=clinic.address,
            city=clinic.city,
            google_rating=clinic.google_rating,
            google_review_count=clinic.google_review_count,
            departments=departments,
            procedures=clinic_procs,
            doctors=doctor_info,
            match_score=match_score,
            match_reasons=reasons,
            cautions=cautions,
            has_specialist=has_specialist,
            google_place_id=clinic.google_place_id,
            thumbnail_ref=thumbnail_ref,
            website=clinic.website,
            transparency_score=clinic.transparency_score,
            review_summary=review_summary,
            case_photo_count=clinic_photo_counts.get(clinic.id, 0),
        ))

    # === Step 5: ソート & トリミング ===
    # エリア指定がある場合: exact > adjacent > none の順、同一エリア内はスコア順
    if primary_city:
        def sort_key(m: ClinicMatch):
            area_priority = 0
            if m.city == primary_city:
                area_priority = 2
            elif m.city in adjacent_cities:
                area_priority = 1
            return (-area_priority, -m.match_score)
        clinic_matches.sort(key=sort_key)
    else:
        clinic_matches.sort(key=lambda m: -m.match_score)

    # 上位N件に絞る
    top_matches = clinic_matches[:max_results]

    # === Step 6: 条件サマリー生成 ===
    summary = _build_summary(conditions, matched_procedures, total_candidates, len(top_matches))

    return RecommendationResult(
        user_conditions=conditions,
        matched_procedures=[_proc_to_dict(p) for p in matched_procedures],
        clinic_matches=top_matches,
        total_candidates=total_candidates,
        summary=summary,
    )


def _proc_to_dict(p: ProcedureMatch) -> dict:
    """ProcedureMatchを辞書に変換"""
    return {
        "name": p.name,
        "category": p.category,
        "invasiveness": p.invasiveness,
        "price_display": p.price_display,
        "dt_real": p.dt_real,
        "budget_fit": p.budget_fit,
        "dt_fit": p.dt_fit,
    }


def _build_summary(
    conditions: UserConditions,
    procedures: list[ProcedureMatch],
    total_candidates: int,
    shown: int,
) -> str:
    """条件サマリーテキストを生成"""
    parts = []

    if conditions.concern_text:
        parts.append(f"お悩み: {conditions.concern_text}")
    if conditions.area:
        parts.append(f"エリア: {conditions.area}")
    if conditions.budget:
        if conditions.budget >= 10000:
            parts.append(f"ご予算: {conditions.budget // 10000}万円")
        else:
            parts.append(f"ご予算: {conditions.budget:,}円")
    if conditions.downtime_days is not None:
        parts.append(f"ダウンタイム: {conditions.downtime_days}日")

    condition_text = " / ".join(parts) if parts else "（条件未指定）"

    proc_names = [p.name for p in procedures]
    proc_text = "・".join(proc_names[:4])
    if len(proc_names) > 4:
        proc_text += f" 他{len(proc_names) - 4}件"

    return (
        f"【条件】{condition_text}\n"
        f"関連施術: {proc_text}\n"
        f"候補クリニック: {total_candidates}院中 {shown}院を表示"
    )


# ==========================================
# LLMコンテキスト生成（システムプロンプト注入用）
# ==========================================

def build_recommendation_context(result: RecommendationResult) -> str:
    """
    推薦結果をLLMのシステムプロンプトに注入するテキストに変換

    LLMはこのコンテキストを参照して、パーソナライズされた回答を生成する。
    """
    if not result.clinic_matches:
        return ""

    ctx = "\n\n## ユーザーの条件に合致するクリニック候補\n\n"
    ctx += f"{result.summary}\n\n"

    for i, match in enumerate(result.clinic_matches[:5], 1):
        ctx += f"### 候補{i}: {match.name}\n"
        ctx += f"- 所在地: {match.address}\n"

        if match.google_rating:
            review_text = f"（{match.google_review_count}件の口コミ）" if match.google_review_count else ""
            ctx += f"- Google評価: ★{match.google_rating:.1f}{review_text}\n"

        if match.departments:
            ctx += f"- 診療科: {', '.join(match.departments)}\n"

        if match.procedures:
            proc_names = [p.name for p in match.procedures]
            ctx += f"- 対応施術: {', '.join(proc_names)}\n"

            # Phase 14: 価格相場対比をコンテキストに注入
            for p in match.procedures:
                if p.price_display:
                    ctx += f"  - {p.name}: {p.price_display}\n"

        if match.doctors:
            for doc in match.doctors[:3]:
                cert_text = ""
                if doc.get("certifications"):
                    cert_text = f"（{', '.join(doc['certifications'][:2])}）"
                exp_text = ""
                if doc.get("experience_years"):
                    exp_text = f" / 経験{doc['experience_years']}年"
                spec_text = ""
                if doc.get("specialties"):
                    spec_text = f" / 専門: {', '.join(doc['specialties'][:2])}"
                bg_text = ""
                if doc.get("hospital_background"):
                    bg_text = f" / 経歴: {doc['hospital_background'][:30]}"
                jsaps_text = ""
                if doc.get("jsaps_certified"):
                    jsaps_text = " [JSAPS専門医]"
                score_text = ""
                if doc.get("trust_score") and doc["trust_score"] >= 20:
                    score_text = f" [情報開示{doc['trust_score']:.0f}pt]"
                ctx += f"- 医師: {doc.get('title', '')} {doc['name']}{cert_text}{exp_text}{spec_text}{bg_text}{jsaps_text}{score_text}\n"
            # 医師情報が不足している場合の注意書き
            low_info_docs = [d for d in match.doctors if not d.get("trust_score") or d["trust_score"] < 20]
            if low_info_docs:
                ctx += f"- 一部の医師の公開情報が限られています。カウンセリングで資格・経歴を直接確認してください\n"

        if match.match_reasons:
            ctx += f"- 選出理由: {' / '.join(match.match_reasons)}\n"

        if match.cautions:
            ctx += f"- 注意点: {' / '.join(match.cautions)}\n"

        # 透明性スコア
        if match.transparency_score is not None and match.transparency_score >= 30:
            ctx += f"- AURA情報開示スコア: {match.transparency_score:.0f}/100\n"

        # 口コミ分析サマリー
        if match.review_summary:
            aspects = match.review_summary.get("top_aspects", [])
            if aspects:
                aspect_text = ", ".join(aspects[:3])
                ctx += f"- 口コミ傾向: {aspect_text}\n"

            # レッドフラグ警告をLLMコンテキストに注入
            red_flags = match.review_summary.get("red_flags", {})
            if red_flags:
                flag_labels = {
                    "pressure_sales": "圧力販売",
                    "treatment_trouble": "施術トラブル",
                    "staff_issue": "スタッフ対応問題",
                    "billing_issue": "会計トラブル",
                }
                flag_parts = [f"{flag_labels.get(k, k)}({v}件)" for k, v in red_flags.items()]
                ctx += f"- [注意] 口コミ注意情報: {', '.join(flag_parts)}\n"

        # 症例写真件数
        if match.case_photo_count > 0:
            ctx += f"- 症例写真: {match.case_photo_count}件\n"

        ctx += "\n"

    return ctx
