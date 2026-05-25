"""
AURA MVP — 価格分析エンジン

「広告価格と実勢価格の乖離」を定量化し、
患者が騙されやすい施術・クリニックを可視化する。

分析軸:
1. 施術別 — 広告価格の「盛り度」ランキング
2. 隠れコスト — 表示価格に含まれない追加費用の総額推定
3. 累計コスト — 一時的施術の年間維持費用計算
"""

import json
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field


class PriceGapAnalysis(BaseModel):
    """広告価格 vs 実勢価格の乖離分析"""

    procedure_name: str
    category: str

    # 広告価格
    advertised_display: str = ""
    advertised_min: int | None = None

    # 実勢価格
    real_display: str = ""
    real_min: int | None = None
    real_max: int | None = None

    # 乖離分析
    gap_ratio: float | None = Field(None, description="乖離倍率（実勢最低 / 広告最低）")
    gap_category: str = Field("", description="乖離カテゴリ（mild/moderate/severe/extreme）")
    gap_warning: str = ""

    # 隠れコスト
    hidden_costs: list[str] = Field(default_factory=list)
    hidden_cost_count: int = 0
    estimated_hidden_total: int | None = Field(None, description="隠れコスト推定合計（円）")

    # 累計コスト（一時的施術のみ）
    is_temporary: bool = False
    annual_maintenance_cost: int | None = Field(None, description="年間維持費用推定（円）")
    three_year_total: int | None = Field(None, description="3年間の総費用推定（円）")


class TransparencyScore(BaseModel):
    """クリニック透明性スコア"""

    clinic_id: str
    clinic_name: str
    score: float = Field(0.0, ge=0.0, le=100.0, description="透明性スコア（0-100）")

    # 個別スコア
    has_website: bool = False
    website_score: float = 0.0  # 0-20
    data_completeness: float = 0.0  # 0-20
    department_diversity: float = 0.0  # 0-15
    mhlw_registered: bool = False
    mhlw_score: float = 0.0  # 0-15
    google_presence: float = 0.0  # 0-15
    coordinate_accuracy: float = 0.0  # 0-15

    # 判定
    grade: str = ""  # A/B/C/D/F
    flags: list[str] = Field(default_factory=list)


def extract_price_number(text: str) -> int | None:
    """
    価格テキストから最低金額（円）を抽出

    '7万〜15万円' → 70000
    '4,800円〜' → 4800
    '1回 5,190円〜' → 5190
    '68,000円〜' → 68000
    '200,000〜350,000円' → 200000
    """
    if not text:
        return None

    # JSON文字列の場合はパース
    if text.startswith("{"):
        try:
            data = json.loads(text)
            if "min_price" in data:
                return data["min_price"]
            text = data.get("display", "")
        except (json.JSONDecodeError, TypeError):
            pass

    if not text:
        return None

    # Step 1: カンマ区切りの数値+円（68,000円、200,000円 等）を先に試行
    nums_yen = re.findall(r"([\d,]+)\s*円", text)
    if nums_yen:
        try:
            val = int(nums_yen[0].replace(",", ""))
            if val >= 100:
                return val
        except ValueError:
            pass

    # Step 2: 「万」単位（7万〜15万円、3万〜10万円 等）
    m = re.search(r"([\d,.]+)\s*万", text)
    if m:
        try:
            val = float(m.group(1).replace(",", ""))
            return int(val * 10000)
        except ValueError:
            pass

    # Step 3: 純粋な数値のみ（フォールバック）
    nums = re.findall(r"([\d,]+)", text)
    if nums:
        try:
            val = int(nums[0].replace(",", ""))
            if val >= 100:
                return val
        except ValueError:
            pass

    return None


def estimate_hidden_costs(costs: list[str]) -> int:
    """
    隠れコストリストから推定合計金額を算出

    '笑気麻酔 3,000〜5,000円' → 中央値4,000円で計算
    """
    total = 0
    for cost in costs:
        nums = re.findall(r"([\d,]+)\s*(?:円|万)", cost)
        if nums:
            values = []
            for n in nums:
                val = int(n.replace(",", ""))
                if "万" in cost and val < 1000:
                    val *= 10000
                values.append(val)
            if values:
                # 中央値を採用
                total += sum(values) // len(values)
    return total


def classify_gap(ratio: float | None) -> str:
    """乖離倍率からカテゴリを判定"""
    if ratio is None:
        return "unknown"
    if ratio <= 2.0:
        return "mild"  # 2倍以内 — まあ許容範囲
    if ratio <= 5.0:
        return "moderate"  # 2-5倍 — 注意が必要
    if ratio <= 10.0:
        return "severe"  # 5-10倍 — 重大な乖離
    return "extreme"  # 10倍超 — 極めて悪質


GAP_LABELS = {
    "mild": "📗 許容範囲（2倍以内）",
    "moderate": "📙 要注意（2〜5倍）",
    "severe": "📕 重大な乖離（5〜10倍）",
    "extreme": "🚨 極めて悪質（10倍超）",
    "unknown": "❓ 判定不能",
}


def analyze_procedure_price(proc_data: dict) -> PriceGapAnalysis:
    """施術データから価格乖離分析を実行"""
    adv_price = proc_data.get("advertised_price", "")
    real_price = proc_data.get("real_price", "")

    # JSON文字列の場合はパース
    if isinstance(adv_price, str) and adv_price.startswith("{"):
        try:
            adv_data = json.loads(adv_price)
            adv_display = adv_data.get("display", "")
            adv_min = adv_data.get("min_price") or extract_price_number(adv_display)
        except (json.JSONDecodeError, TypeError):
            adv_display = adv_price
            adv_min = extract_price_number(adv_price)
    else:
        adv_display = adv_price if isinstance(adv_price, str) else ""
        adv_min = extract_price_number(adv_display)

    if isinstance(real_price, str) and real_price.startswith("{"):
        try:
            real_data = json.loads(real_price)
            real_display = real_data.get("display", "")
            real_min = real_data.get("min_price") or extract_price_number(real_display)
            real_max = real_data.get("max_price")
        except (json.JSONDecodeError, TypeError):
            real_display = real_price
            real_min = extract_price_number(real_price)
            real_max = None
    else:
        real_display = real_price if isinstance(real_price, str) else ""
        real_min = extract_price_number(real_display)
        real_max = None

    # 乖離倍率
    gap_ratio = None
    if adv_min and real_min and adv_min > 0:
        gap_ratio = round(real_min / adv_min, 1)

    # 隠れコスト
    hidden_raw = proc_data.get("hidden_costs", "[]")
    if isinstance(hidden_raw, str):
        try:
            hidden_costs = json.loads(hidden_raw)
        except (json.JSONDecodeError, TypeError):
            hidden_costs = []
    else:
        hidden_costs = hidden_raw or []

    estimated_hidden = estimate_hidden_costs(hidden_costs) if hidden_costs else None

    # 累計コスト（一時的施術）
    duration_type = proc_data.get("duration_type", "")
    is_temporary = duration_type in ("temporary", "semi_permanent")

    annual_cost = None
    three_year = None
    if is_temporary and real_min:
        # 推奨セッション数と頻度から年間コスト推定
        sessions = proc_data.get("recommended_sessions")
        if sessions and isinstance(sessions, int):
            annual_cost = real_min * sessions
            three_year = annual_cost * 3
        elif duration_type == "temporary":
            # 一時的な施術は年2-3回の維持を想定
            annual_cost = real_min * 2
            three_year = annual_cost * 3

    return PriceGapAnalysis(
        procedure_name=proc_data.get("name", ""),
        category=proc_data.get("category", ""),
        advertised_display=adv_display,
        advertised_min=adv_min,
        real_display=real_display,
        real_min=real_min,
        real_max=real_max,
        gap_ratio=gap_ratio,
        gap_category=classify_gap(gap_ratio),
        gap_warning=proc_data.get("price_gap_note", ""),
        hidden_costs=hidden_costs,
        hidden_cost_count=len(hidden_costs),
        estimated_hidden_total=estimated_hidden,
        is_temporary=is_temporary,
        annual_maintenance_cost=annual_cost,
        three_year_total=three_year,
    )


def calculate_transparency_score(clinic_data: dict) -> TransparencyScore:
    """
    クリニックの透明性スコアを算出

    スコア配分（合計100点）:
    - Webサイトの有無: 20点
    - データ充填率: 20点
    - 診療科の多様性: 15点
    - 厚労省登録: 15点
    - Google Maps存在: 15点
    - 座標精度: 15点
    """
    score = TransparencyScore(
        clinic_id=clinic_data.get("id", ""),
        clinic_name=clinic_data.get("name", ""),
    )

    flags = []

    # 1. Webサイト（20点）
    website = clinic_data.get("website", "")
    if website and website.strip():
        score.has_website = True
        score.website_score = 20.0
    else:
        flags.append("Webサイト未登録 — 情報開示の意思が低い可能性")

    # 2. データ充填率（20点）
    check_fields = [
        "name", "address", "city", "phone", "website",
        "lat", "lng", "medical_departments", "mhlw_code",
    ]
    filled = sum(1 for f in check_fields if clinic_data.get(f))
    completeness = filled / len(check_fields)
    score.data_completeness = round(completeness * 20, 1)
    if completeness < 0.5:
        flags.append(f"データ充填率が低い ({completeness:.0%})")

    # 3. 診療科の多様性（15点）
    depts_raw = clinic_data.get("medical_departments", "[]")
    if isinstance(depts_raw, str):
        try:
            depts = json.loads(depts_raw)
        except (json.JSONDecodeError, TypeError):
            depts = []
    else:
        depts = depts_raw or []

    beauty_depts = {"美容外科", "美容皮膚科", "形成外科"}
    dept_count = len(set(depts) & beauty_depts)
    score.department_diversity = min(dept_count * 5, 15)

    # 形成外科があると信頼度UP（保険診療の基盤がある）
    if "形成外科" in depts:
        score.department_diversity = min(score.department_diversity + 3, 15)

    # 4. 厚労省登録（15点）
    mhlw_code = clinic_data.get("mhlw_code", "")
    if mhlw_code:
        score.mhlw_registered = True
        score.mhlw_score = 15.0
    else:
        flags.append("厚労省医療情報ネット未登録")

    # 5. Google Maps存在（15点）
    google_rating = clinic_data.get("google_rating")
    google_reviews = clinic_data.get("google_review_count", 0)
    if google_rating:
        score.google_presence = 10.0
        if google_reviews and google_reviews >= 10:
            score.google_presence = 15.0
        elif google_reviews and google_reviews >= 5:
            score.google_presence = 12.5

    # 6. 座標精度（15点）
    lat = clinic_data.get("lat", 0)
    lng = clinic_data.get("lng", 0)
    if lat and lng and lat != 0 and lng != 0:
        score.coordinate_accuracy = 15.0
        # 東京都の範囲チェック
        if not (35.0 <= lat <= 36.0 and 139.0 <= lng <= 140.5):
            score.coordinate_accuracy = 10.0
            flags.append("座標が東京都の一般的範囲外")

    # 合計スコア
    total = (
        score.website_score
        + score.data_completeness
        + score.department_diversity
        + score.mhlw_score
        + score.google_presence
        + score.coordinate_accuracy
    )
    score.score = round(total, 1)

    # グレード判定
    if total >= 85:
        score.grade = "A"
    elif total >= 70:
        score.grade = "B"
    elif total >= 55:
        score.grade = "C"
    elif total >= 40:
        score.grade = "D"
    else:
        score.grade = "F"

    score.flags = flags

    return score
