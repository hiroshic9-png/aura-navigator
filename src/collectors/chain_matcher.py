"""
AURA MVP — チェーンクリニック名寄せマッチャー

大手美容クリニックチェーンの支院名マッチングを改善する。
厚労省データの正式名称とGoogle Mapsの通称を紐付ける。

改善ポイント:
- チェーン名の自動検出と分離（「湘南美容クリニック新宿院」→ chain=湘南美容, branch=新宿院）
- 近距離の同名チェーン院の距離ベースマッチング
- 表記揺れの正規化（全角英数→半角、「ＳＢＣ」→「SBC」等）
"""

import math
import re
from dataclasses import dataclass


# 主要チェーン名と表記揺れパターン
CHAIN_PATTERNS = {
    "湘南美容クリニック": [
        "湘南美容クリニック", "湘南美容外科クリニック",
        "湘南美容外科", "SBC湘南美容クリニック", "ＳＢＣ湘南美容クリニック",
    ],
    "品川美容外科": [
        "品川美容外科", "品川美容外科クリニック",
        "品川スキンクリニック",
    ],
    "TCB東京中央美容外科": [
        "TCB東京中央美容外科", "ＴＣＢ東京中央美容外科",
        "東京中央美容外科",
    ],
    "共立美容外科": [
        "共立美容外科", "共立美容外科クリニック",
    ],
    "聖心美容クリニック": [
        "聖心美容クリニック", "聖心美容外科",
    ],
    "東京美容外科": [
        "東京美容外科", "東京美容外科クリニック",
    ],
    "TAクリニック": [
        "TAクリニック", "ＴＡクリニック",
    ],
    "城本クリニック": [
        "城本クリニック",
    ],
    "高須クリニック": [
        "高須クリニック",
    ],
    "リゼクリニック": [
        "リゼクリニック",
    ],
    "ゴリラクリニック": [
        "ゴリラクリニック",
    ],
    "フレイアクリニック": [
        "フレイアクリニック",
    ],
    "エミナルクリニック": [
        "エミナルクリニック",
    ],
    "レジーナクリニック": [
        "レジーナクリニック",
    ],
    "アリシアクリニック": [
        "アリシアクリニック",
    ],
    "ガーデンクリニック": [
        "ガーデンクリニック",
    ],
    "水の森美容クリニック": [
        "水の森美容クリニック", "水の森美容外科",
    ],
    "もとび美容外科": [
        "もとび美容外科クリニック", "もとび美容外科",
    ],
    "銀座よしえクリニック": [
        "銀座よしえクリニック",
    ],
    "東京形成美容外科": [
        "東京形成美容外科",
    ],
}

# 支院名パターン（院名抽出用）
BRANCH_PATTERN = re.compile(
    r"(.+?)"
    r"(新宿|渋谷|銀座|池袋|品川|六本木|表参道|青山|恵比寿|目黒|上野|秋葉原|"
    r"赤坂|麻布|自由が丘|中目黒|立川|町田|吉祥寺|二子玉川|大崎|五反田|"
    r"有楽町|日本橋|丸の内|蒲田|北千住|錦糸町|豊洲|東京|八王子|"
    r"新橋|浜松町|田町|三軒茶屋|下北沢|代々木|高田馬場|西新宿|"
    r"東新宿|新大久保|中野|荻窪|練馬|板橋|赤羽|王子|巣鴨)"
    r"(.*(院|店|クリニック|オフィス)?)?"
)


@dataclass
class ChainInfo:
    """チェーン識別結果"""
    chain_name: str | None  # 「湘南美容クリニック」等
    branch_name: str | None  # 「新宿院」等
    is_chain: bool


def identify_chain(clinic_name: str) -> ChainInfo:
    """
    クリニック名からチェーン情報を識別する

    Args:
        clinic_name: クリニック名（例: 「湘南美容クリニック新宿院」）

    Returns:
        ChainInfo: チェーン名、支院名、チェーン判定結果
    """
    normalized = _normalize_full(clinic_name)

    # チェーンパターンに一致するか確認
    for chain_name, patterns in CHAIN_PATTERNS.items():
        for pattern in patterns:
            norm_pattern = _normalize_full(pattern)
            if norm_pattern in normalized:
                # 支院名を抽出
                branch = normalized.replace(norm_pattern, "").strip()
                if not branch:
                    branch = None
                return ChainInfo(
                    chain_name=chain_name,
                    branch_name=branch,
                    is_chain=True,
                )

    # 支院パターンで推定
    m = BRANCH_PATTERN.match(normalized)
    if m:
        base = m.group(1)
        area = m.group(2)
        suffix = m.group(3) or ""
        branch = area + suffix
        if len(base) > 2:  # 「品」「東」など短すぎる場合は除外
            return ChainInfo(
                chain_name=base,
                branch_name=branch,
                is_chain=True,
            )

    return ChainInfo(chain_name=None, branch_name=None, is_chain=False)


def _normalize_full(name: str) -> str:
    """クリニック名の完全正規化"""
    # 全角英数→半角
    result = name.translate(str.maketrans(
        'ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ０１２３４５６７８９',
        'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
    ))
    # スペース除去
    result = result.replace("　", "").replace(" ", "")
    # 表記揺れ
    result = result.replace("クリニツク", "クリニック")
    return result


def haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    2点間の距離をメートルで計算（ハバサイン公式）
    """
    R = 6371000  # 地球の半径（メートル）
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def match_by_chain_and_distance(
    google_name: str,
    google_lat: float,
    google_lng: float,
    db_clinics: list,
    max_distance_meters: float = 500.0,
) -> tuple:
    """
    チェーン名+距離ベースのマッチング

    Google Places側のクリニック名をチェーン分析し、
    同一チェーンのDB側クリニックのうち最も近いものをマッチする。

    Args:
        google_name: Google Places側のクリニック名
        google_lat, google_lng: Google Places側の座標
        db_clinics: DB側の全クリニックリスト
        max_distance_meters: 最大マッチ距離（メートル）

    Returns:
        (matched_clinic, distance_meters, match_type) or (None, None, None)
    """
    g_chain = identify_chain(google_name)

    if not g_chain.is_chain or not g_chain.chain_name:
        return None, None, None

    # DB側で同一チェーンのクリニックを検索
    best_match = None
    best_distance = float("inf")

    for clinic in db_clinics:
        db_chain = identify_chain(clinic.name)

        # チェーン名が一致するか
        if not db_chain.is_chain:
            continue

        chain_match = False
        g_norm = _normalize_full(g_chain.chain_name)
        d_norm = _normalize_full(db_chain.chain_name)

        # 完全一致
        if g_norm == d_norm:
            chain_match = True
        # 部分一致（「湘南美容」⊂「湘南美容クリニック」等）
        elif g_norm in d_norm or d_norm in g_norm:
            # 短い方が長い方の50%以上なら一致とみなす
            shorter = min(len(g_norm), len(d_norm))
            longer = max(len(g_norm), len(d_norm))
            if shorter / longer > 0.5:
                chain_match = True

        if not chain_match:
            continue

        # 距離計算
        c_lat = clinic.lat or 0
        c_lng = clinic.lng or 0
        if c_lat == 0 or c_lng == 0:
            continue

        distance = haversine_distance(google_lat, google_lng, c_lat, c_lng)

        if distance < best_distance and distance <= max_distance_meters:
            best_distance = distance
            best_match = clinic

    if best_match:
        return best_match, best_distance, "chain_distance"

    return None, None, None
