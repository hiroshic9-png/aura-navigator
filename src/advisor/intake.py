"""
AURA MVP — インテークエンジン（条件ヒアリング）

ユーザーのメッセージから条件を段階的に抽出し、
必要な情報が揃った時点で推薦エンジンを自動起動する。

フロー:
1. ユーザーが悩みを伝える（「二重にしたい」）
2. 不足条件をヒアリング（エリア・予算・DT）
3. 全条件が揃ったら推薦エンジン起動
4. パーソナライズされた候補を提示

設計方針:
- LLMに頼らず、ルールベースで高速抽出
- 最大2往復の補完質問で条件を揃える
- ヒアリングは自然で押し付けがましくない
"""

import re
from dataclasses import dataclass, field
from enum import Enum

from src.advisor.engine import match_concerns, CONCERN_MAP
from src.advisor.recommendation_engine import (
    UserConditions, UserPriority,
    resolve_area, parse_budget, parse_downtime_days,
)


class IntakeState(str, Enum):
    """インテークの進行状態"""
    INITIAL = "initial"           # 初回（悩みの特定前）
    CONCERN_IDENTIFIED = "concern_identified"  # 悩みは特定済み、他の条件待ち
    READY = "ready"               # 全条件揃った → 推薦実行可能
    COMPLETED = "completed"       # 推薦済み


@dataclass
class IntakeSession:
    """インテークセッション（条件の蓄積状態）"""
    state: IntakeState = IntakeState.INITIAL
    conditions: UserConditions = field(default_factory=UserConditions)
    missing_fields: list[str] = field(default_factory=list)  # まだ聞いていない項目
    asked_count: int = 0  # 補完質問を何回したか


# ==========================================
# 条件抽出ルール
# ==========================================

# エリアキーワード抽出
AREA_KEYWORDS = [
    "渋谷", "新宿", "銀座", "池袋", "品川", "表参道",
    "六本木", "恵比寿", "原宿", "青山", "赤坂", "麻布",
    "有楽町", "丸の内", "秋葉原", "日本橋", "上野", "浅草",
    "自由が丘", "中目黒", "目黒", "吉祥寺", "立川", "町田",
    "八王子", "二子玉川", "三軒茶屋",
    # 区名
    "渋谷区", "新宿区", "中央区", "港区", "豊島区", "千代田区",
    "品川区", "目黒区", "世田谷区", "台東区", "文京区",
    "江東区", "大田区", "杉並区", "練馬区",
]

# 予算パターン
BUDGET_PATTERNS = [
    r"(\d+)\s*万\s*(円|以内|くらい|ぐらい|程度|まで)?",
    r"(\d{4,})\s*(円|以内|くらい|ぐらい|程度|まで)?",
    r"予算\s*(\d+)",
]

# DT日数パターン
DT_PATTERNS = [
    r"(\d+)\s*日\s*(休|取|間)?",
    r"(\d+)\s*週間?",
    r"(休み?|休暇|仕事|DT|ダウンタイム).*?(\d+)\s*(日|週)",
]

# 優先度キーワード
PRIORITY_KEYWORDS = {
    UserPriority.QUALITY: ["安全", "上手", "うまい", "技術", "専門医", "実績", "信頼"],
    UserPriority.PRICE: ["安い", "安く", "コスパ", "費用", "お手頃", "リーズナブル"],
    UserPriority.CONVENIENCE: ["近い", "駅近", "通いやすい", "アクセス"],
}


def extract_conditions_from_message(message: str, existing: UserConditions) -> UserConditions:
    """
    ユーザーメッセージから条件を抽出し、既存条件にマージする

    既に設定済みの条件は上書きしない（ユーザーが明示的に変更した場合のみ更新）
    """
    conditions = UserConditions(
        concern_tags=list(existing.concern_tags),
        concern_text=existing.concern_text,
        area=existing.area,
        budget=existing.budget,
        downtime_days=existing.downtime_days,
        age_range=existing.age_range,
        priority=existing.priority,
        previous_procedures=list(existing.previous_procedures),
    )

    # 悩みタグ抽出
    new_concerns = match_concerns(message)
    if new_concerns:
        conditions.concern_tags = list(set(conditions.concern_tags + new_concerns))
        if not conditions.concern_text:
            conditions.concern_text = message[:50]

    # エリア抽出
    for keyword in AREA_KEYWORDS:
        if keyword in message:
            conditions.area = keyword
            break

    # 予算抽出
    budget = parse_budget(message)
    if budget:
        conditions.budget = budget

    # DT日数抽出
    dt = parse_downtime_days(message)
    if dt is not None:
        conditions.downtime_days = dt
    # 「3日休める」のような表現
    m = re.search(r"(\d+)\s*日.*(休|取)", message)
    if m and conditions.downtime_days is None:
        conditions.downtime_days = int(m.group(1))

    # 年代抽出
    m = re.search(r"(\d{2})\s*代", message)
    if m:
        conditions.age_range = f"{m.group(1)}代"

    # 優先度抽出
    for priority, keywords in PRIORITY_KEYWORDS.items():
        if any(kw in message for kw in keywords):
            conditions.priority = priority
            break

    return conditions


def assess_intake_state(conditions: UserConditions) -> tuple[IntakeState, list[str]]:
    """
    条件の充足度を評価し、次に聞くべき項目を返す

    必須: 悩みタグ（最低1つ）
    推奨: エリア、予算、DT
    オプション: 年代、優先度
    """
    if not conditions.concern_tags:
        return IntakeState.INITIAL, ["concern"]

    missing = []
    if not conditions.area:
        missing.append("area")
    if conditions.budget is None:
        missing.append("budget")
    if conditions.downtime_days is None:
        missing.append("downtime")

    if not missing:
        return IntakeState.READY, []

    # 悩みは特定できたが、他の条件が不足
    return IntakeState.CONCERN_IDENTIFIED, missing


def generate_followup_question(
    conditions: UserConditions,
    missing: list[str],
    asked_count: int,
) -> str | None:
    """
    不足条件に対する補完質問を生成

    - 最大2回まで質問（それ以上は押し付けがましい）
    - 2回聞いても揃わなければ、揃っている条件だけで推薦実行
    """
    if asked_count >= 2:
        # 2回聞いたら、ある条件だけで進む
        return None

    # 悩みに応じたカスタムテキスト
    concern_name = _get_concern_display(conditions.concern_tags)

    if asked_count == 0:
        # 初回: まとめて聞く（自然な会話として）
        questions = []
        if "area" in missing:
            questions.append("エリアのご希望はありますか？（例: 渋谷、新宿、銀座など）")
        if "budget" in missing:
            questions.append("ご予算はどのくらいをお考えですか？")
        if "downtime" in missing:
            questions.append("お仕事や学校のお休みはどのくらい取れますか？")

        if not questions:
            return None

        intro = f"{concern_name}についてですね。\n"
        intro += "よりあなたに合った情報をお伝えするために、いくつか教えてください。\n\n"

        numbered = "\n".join(f"{'①②③④⑤'[i]} {q}" for i, q in enumerate(questions))
        return intro + numbered

    else:
        # 2回目: まだ足りない項目だけ聞く
        if "area" in missing:
            return "エリアのご希望を教えていただけますか？ 特になければ、東京都内全域でお探しします。"
        if "budget" in missing:
            return "ご予算のイメージを教えていただけますか？ 特になければ、幅広い価格帯でお探しします。"
        if "downtime" in missing:
            return "お休みが取れる日数を教えていただけますか？ 特になければ、全ての施術を含めてお探しします。"

    return None


def _get_concern_display(concern_tags: list[str]) -> str:
    """悩みタグの表示名を生成"""
    # concern_tagsを日本語に変換
    tag_labels = {
        "double": "二重", "bigger": "目を大きく", "heavy": "まぶたの重み",
        "kuma": "クマ", "sagging": "たるみ",
        "height": "鼻を高く", "tip": "鼻先", "nostril": "小鼻", "overall": "鼻全体",
        "spots": "シミ・くすみ", "pores": "毛穴", "wrinkles": "しわ",
        "jaw": "エラ・小顔", "overall_contour": "輪郭", "double_chin": "二重あご",
        "chin_shape": "あご", "cheek": "頬",
    }
    labels = [tag_labels.get(t, t) for t in concern_tags[:3]]
    return "・".join(labels) if labels else "お悩み"


# ==========================================
# 推薦トリガー検出
# ==========================================

# ユーザーがクリニック推薦を求めている表現
RECOMMENDATION_TRIGGERS = [
    "どの施術がいい",
    "どこのクリニックがおすすめ",
    "おすすめ",
    "私にはどれが合う",
    "どこがいい",
    "いいクリニック",
    "良いクリニック",
    "上手な",
    "教えて",
    "探して",
    "クリニック",
    "選び方",
    "どう選べば",
    "合っている",
    "合ってる",
    "ぴったり",
]


def is_recommendation_request(message: str) -> bool:
    """ユーザーのメッセージが推薦リクエストか判定"""
    # 悩みキーワード + 推薦トリガーの組み合わせ
    has_concern = bool(match_concerns(message))
    has_trigger = any(trigger in message for trigger in RECOMMENDATION_TRIGGERS)

    # 推薦トリガーがあれば推薦モードへ
    if has_trigger:
        return True

    # 悩みキーワードのみでも、エリアや予算が含まれていれば推薦と判定
    has_area = any(kw in message for kw in AREA_KEYWORDS)
    has_budget = bool(parse_budget(message))

    if has_concern and (has_area or has_budget):
        return True

    return False
