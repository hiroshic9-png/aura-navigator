"""
AURA MVP — 医師×施術 専門性マッピングエンジン

医師の専門分野・資格・経歴から得意施術カテゴリを推定する。
推薦エンジンで「この施術の専門医がいます」を表示するために使用。

マッピングルール:
- 形成外科専門医 → eye, nose, contour（外科系施術全般）
- 皮膚科専門医 → skin, anti_aging（レーザー/注入系）
- JSAPS専門医 → eye, nose, contour, breast, body（美容外科全般）
- 専門分野キーワード → カテゴリ直接マッピング
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ============================================================
# 資格→施術カテゴリ マッピング
# ============================================================

# 資格・専門医からの推定
CERT_TO_CATEGORIES: dict[str, list[str]] = {
    # 形成外科系 → 外科的美容施術
    "形成外科専門医": ["eye", "nose", "contour", "breast", "body"],
    "形成外科": ["eye", "nose", "contour"],
    # 皮膚科系 → 非侵襲的美容施術
    "皮膚科専門医": ["skin", "anti_aging", "hair_removal"],
    "皮膚科": ["skin", "anti_aging"],
    # 美容外科系
    "美容外科専門医": ["eye", "nose", "contour", "breast", "body", "anti_aging"],
    "美容外科": ["eye", "nose", "contour", "anti_aging"],
    # JSAPS（美容外科の上位資格）
    "JSAPS": ["eye", "nose", "contour", "breast", "body", "anti_aging"],
    # その他
    "眼科専門医": ["eye"],
    "眼科": ["eye"],
    "外科専門医": ["body", "breast", "contour"],
    "麻酔科専門医": [],  # 直接の施術カテゴリはないが安全面で重要
}

# 専門分野キーワードからの推定
SPECIALTY_TO_CATEGORIES: dict[str, list[str]] = {
    "二重": ["eye"],
    "目元": ["eye"],
    "眼瞼": ["eye"],
    "鼻": ["nose"],
    "隆鼻": ["nose"],
    "鼻翼": ["nose"],
    "輪郭": ["contour"],
    "小顔": ["contour"],
    "リフト": ["contour", "anti_aging"],
    "フェイスライン": ["contour"],
    "豊胸": ["breast"],
    "バスト": ["breast"],
    "脂肪吸引": ["body"],
    "ボディ": ["body"],
    "痩身": ["body"],
    "レーザー": ["skin", "hair_removal"],
    "注入": ["skin", "anti_aging"],
    "ヒアルロン酸": ["anti_aging", "contour"],
    "ボトックス": ["anti_aging", "contour"],
    "脱毛": ["hair_removal"],
    "ピーリング": ["skin"],
    "シミ": ["skin"],
    "ニキビ": ["skin"],
    "アンチエイジング": ["anti_aging"],
    "エイジングケア": ["anti_aging"],
    "再生医療": ["anti_aging", "skin"],
}


@dataclass
class DoctorSpecialty:
    """医師の推定施術専門性"""
    doctor_id: str
    doctor_name: str
    matched_categories: set[str] = field(default_factory=set)
    confidence: str = "low"  # low/medium/high
    match_sources: list[str] = field(default_factory=list)


def estimate_doctor_specialties(
    doctor_id: str,
    doctor_name: str,
    certifications: list[str] | None = None,
    specialties: list[str] | None = None,
    jsaps_certified: bool = False,
    hospital_background: str | None = None,
) -> DoctorSpecialty:
    """
    医師の資格・専門分野・経歴から得意施術カテゴリを推定する

    Args:
        doctor_id: 医師ID
        doctor_name: 医師名
        certifications: 資格リスト（例: ["形成外科専門医", "皮膚科専門医"]）
        specialties: 専門分野リスト（例: ["美容外科", "二重"]）
        jsaps_certified: JSAPS認定フラグ
        hospital_background: 勤務経歴テキスト

    Returns:
        DoctorSpecialty: 推定された専門性
    """
    result = DoctorSpecialty(doctor_id=doctor_id, doctor_name=doctor_name)
    certs = certifications or []
    specs = specialties or []

    # 1. JSAPS認定
    if jsaps_certified:
        result.matched_categories.update(CERT_TO_CATEGORIES["JSAPS"])
        result.match_sources.append("JSAPS専門医")

    # 2. 資格からの推定
    for cert in certs:
        for key, categories in CERT_TO_CATEGORIES.items():
            if key in cert:
                result.matched_categories.update(categories)
                result.match_sources.append(f"資格:{cert}")
                break

    # 3. 専門分野からの推定
    for spec in specs:
        for keyword, categories in SPECIALTY_TO_CATEGORIES.items():
            if keyword in spec:
                result.matched_categories.update(categories)
                result.match_sources.append(f"専門:{spec}")
                break

    # 4. 経歴からの推定（キーワードベース）
    if hospital_background:
        bg = hospital_background
        for keyword, categories in SPECIALTY_TO_CATEGORIES.items():
            if keyword in bg:
                result.matched_categories.update(categories)
                result.match_sources.append(f"経歴:{keyword}")

    # 信頼度判定
    source_types = set()
    for s in result.match_sources:
        if s.startswith("JSAPS"):
            source_types.add("jsaps")
        elif s.startswith("資格:"):
            source_types.add("cert")
        elif s.startswith("専門:"):
            source_types.add("spec")
        elif s.startswith("経歴:"):
            source_types.add("bg")

    if "jsaps" in source_types or len(source_types) >= 2:
        result.confidence = "high"
    elif "cert" in source_types or "spec" in source_types:
        result.confidence = "medium"
    elif source_types:
        result.confidence = "low"

    return result


def match_doctor_to_procedure_category(
    doctor_specialty: DoctorSpecialty,
    procedure_category: str,
) -> bool:
    """医師がこの施術カテゴリの専門家かどうかを判定"""
    return procedure_category in doctor_specialty.matched_categories


# ============================================================
# 専門分野×施術カテゴリ 親和度マッピング（Phase 67）
# ============================================================

SPECIALTY_PROCEDURE_MAP: dict[str, dict[str, float]] = {
    # --- 外科系 ---
    "形成外科": {
        "nose": 1.0,          # 鼻施術は形成外科のコア
        "eye": 0.9,           # 目元施術
        "contour": 0.9,       # 輪郭形成
        "breast": 0.8,        # 豊胸
        "body": 0.7,          # 痩身・脂肪吸引
        "anti_aging": 0.5,    # アンチエイジング（外科的アプローチ）
        "skin": 0.3,          # 肌施術（非主領域）
    },
    "美容外科": {
        "eye": 1.0,
        "nose": 1.0,
        "contour": 0.9,
        "breast": 0.9,
        "body": 0.8,
        "anti_aging": 0.7,
        "skin": 0.4,
    },
    "形成外科専門医": {
        "nose": 1.0,
        "eye": 0.95,
        "contour": 0.95,
        "breast": 0.85,
        "body": 0.75,
        "anti_aging": 0.5,
        "skin": 0.3,
    },
    "美容外科専門医": {
        "eye": 1.0,
        "nose": 1.0,
        "contour": 0.95,
        "breast": 0.95,
        "body": 0.85,
        "anti_aging": 0.75,
        "skin": 0.5,
    },
    # --- 皮膚科系 ---
    "美容皮膚科": {
        "skin": 1.0,          # 肌施術がコア
        "anti_aging": 0.9,    # アンチエイジング
        "hair_removal": 0.8,  # 脱毛
        "eye": 0.4,           # 目元（注入系のみ）
        "contour": 0.3,       # 輪郭（ヒアルロン酸等）
    },
    "皮膚科": {
        "skin": 0.8,
        "anti_aging": 0.7,
        "hair_removal": 0.6,
    },
    "皮膚科専門医": {
        "skin": 0.9,
        "anti_aging": 0.75,
        "hair_removal": 0.7,
    },
    # --- 眼科系 ---
    "眼科": {
        "eye": 0.7,
    },
    "眼科専門医": {
        "eye": 0.8,
    },
    # --- 外科系その他 ---
    "外科": {
        "body": 0.6,
        "breast": 0.5,
        "contour": 0.4,
    },
    "外科専門医": {
        "body": 0.7,
        "breast": 0.6,
        "contour": 0.5,
    },
    # --- JSAPS（上位資格） ---
    "JSAPS": {
        "eye": 1.0,
        "nose": 1.0,
        "contour": 1.0,
        "breast": 1.0,
        "body": 0.9,
        "anti_aging": 0.8,
        "skin": 0.5,
        "hair_removal": 0.3,
    },
    "JSAPS専門医": {
        "eye": 1.0,
        "nose": 1.0,
        "contour": 1.0,
        "breast": 1.0,
        "body": 0.9,
        "anti_aging": 0.8,
        "skin": 0.5,
        "hair_removal": 0.3,
    },
    # --- その他 ---
    "麻酔科": {
        # 直接の施術マッチはないが、安全性に貢献
    },
    "麻酔科専門医": {},
}

# 施術名キーワードから追加ブーストを与えるマッピング
_PROCEDURE_NAME_KEYWORDS: dict[str, list[str]] = {
    "eye": ["二重", "目元", "目もと", "眼瞼", "まぶた", "目頭", "涙袋"],
    "nose": ["鼻", "隆鼻", "鼻翼", "鼻先", "小鼻"],
    "contour": ["輪郭", "小顔", "エラ", "フェイスライン", "リフト"],
    "breast": ["豊胸", "バスト", "胸"],
    "body": ["脂肪吸引", "痩身", "ボディ", "ダイエット"],
    "skin": ["レーザー", "ピーリング", "シミ", "ニキビ", "毛穴", "肌"],
    "anti_aging": ["アンチエイジング", "エイジング", "ヒアルロン酸", "ボトックス", "しわ", "たるみ"],
    "hair_removal": ["脱毛", "医療脱毛"],
}


def match_doctor_to_procedure(
    doctor_specialties: list[str] | str | None,
    procedure_category: str,
    procedure_name: str = "",
) -> float:
    """
    医師の専門分野と施術カテゴリの親和度スコアを算出する

    Args:
        doctor_specialties: 医師の専門分野リスト（JSON文字列またはlist）
        procedure_category: 施術カテゴリ（eye/nose/skin/contour等）
        procedure_name: 施術名（キーワードブーストに使用）

    Returns:
        0.0〜1.0 のマッチスコア
        - 1.0: 完全一致（専門分野のコア施術）
        - 0.8+: 高親和度
        - 0.5+: 関連分野
        - 0.0: 専門分野データなし or 関連なし
    """
    # specialtiesのパース
    specs = _parse_specialties(doctor_specialties)
    if not specs:
        return 0.0

    best_score = 0.0

    for spec in specs:
        # 完全一致のマッピングを探す
        if spec in SPECIALTY_PROCEDURE_MAP:
            score = SPECIALTY_PROCEDURE_MAP[spec].get(procedure_category, 0.0)
            best_score = max(best_score, score)
            continue

        # 部分一致: マッピングキーが専門分野に含まれるか
        for map_key, cat_scores in SPECIALTY_PROCEDURE_MAP.items():
            if map_key in spec or spec in map_key:
                score = cat_scores.get(procedure_category, 0.0)
                # 部分一致は0.9倍にやや減衰させる
                best_score = max(best_score, score * 0.9)

    # 施術名キーワードによる微調整（最大+0.05）
    if procedure_name and best_score > 0:
        keywords = _PROCEDURE_NAME_KEYWORDS.get(procedure_category, [])
        for kw in keywords:
            if kw in procedure_name:
                best_score = min(1.0, best_score + 0.05)
                break

    return round(best_score, 2)


def _parse_specialties(value: list[str] | str | None) -> list[str]:
    """専門分野データをリストにパースする（JSON文字列/list/None対応）"""
    if value is None:
        return []
    if isinstance(value, list):
        return [s.strip() for s in value if isinstance(s, str) and s.strip()]
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return []
        # JSON配列形式を試す
        if value.startswith("["):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return [s.strip() for s in parsed if isinstance(s, str) and s.strip()]
            except (json.JSONDecodeError, TypeError):
                pass
        # カンマ区切りのフォールバック
        return [s.strip() for s in value.split(",") if s.strip()]
    return []


def get_specialty_match_label(score: float) -> str | None:
    """
    マッチスコアからユーザー向けラベルを返す

    Args:
        score: match_doctor_to_procedure()の返値

    Returns:
        "専門分野一致" (>=0.8) / "関連分野" (>=0.5) / None (それ以下)
    """
    if score >= 0.8:
        return "専門分野一致"
    elif score >= 0.5:
        return "関連分野"
    return None
