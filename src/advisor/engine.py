"""
AURA MVP — AIアドバイザーエンジン

美容医療の「患者の味方」として、クリニック・施術データと
カウンセリング質問テンプレートを組み合わせた対話型アドバイザー。

法的制約:
- 医師法第17条: 医療行為の禁止（診断・処方はしない）
- 医師法第72条: 医業類似行為の禁止
- 境界線「C」: 規制範囲内での行動支援

設計原則:
- 「こうすべき」ではなく「こう聞くべき」
- 施術の推薦ではなく、情報の整理と質問の武装
- データに基づく事実提示 + リスクの可視化
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ==========================================
# 法的制約定義
# ==========================================

class LegalBoundary(str, Enum):
    """法的制約の境界線"""
    ALLOWED = "allowed"          # 情報提供・質問支援 → OK
    RECOMMENDATION = "recommendation"  # 条件ベースの選択支援 → 推薦エンジン起動
    CAUTION = "caution"          # グレーゾーン → 注意喚起付きで提供
    PROHIBITED = "prohibited"    # 診断・処方 → 絶対禁止


# 絶対禁止パターン（医師法に直接抵触する医療行為のみ）
PROHIBITED_PATTERNS = [
    "診断して",
    "処方して",
    "薬を出して",
    "治療して",
    "手術して",
]

# 注意喚起が必要なパターン
CAUTION_PATTERNS = [
    "副作用",
    "合併症",
    "後遺症",
    "失敗",
    "訴訟",
    "返金",
]

LEGAL_DISCLAIMER = """
---
*この情報は一般的な知識の整理であり、医学的な診断や施術の推薦ではありません。*
*最終的な判断は、必ず担当の医師とご相談の上で行ってください。*
"""


# ==========================================
# コンテキストビルダー
# ==========================================

class AdvisorContext(BaseModel):
    """アドバイザーが使用するコンテキスト"""

    # ユーザーの状況
    concern: str = ""  # 悩み（例: "目を大きくしたい"）
    budget_range: str = ""  # 予算帯（例: "10万以内"）
    downtime_available: str = ""  # DT確保可能期間（例: "3日"）
    previous_procedures: list[str] = Field(default_factory=list)
    age_range: str = ""  # 年代

    # 関連施術データ
    matched_procedures: list[dict] = Field(default_factory=list)

    # 関連クリニックデータ（オプション）
    target_clinic: dict | None = None

    # 会話履歴
    conversation_history: list[dict] = Field(default_factory=list)

    # 法的制約
    legal_boundary: LegalBoundary = LegalBoundary.ALLOWED


def build_system_prompt(ctx: AdvisorContext, recommendation_context: str = "") -> str:
    """
    システムプロンプトを構築

    AURAの人格・法的制約・データコンテキストを統合。
    recommendation_contextが渡された場合、推薦結果をコンテキストに注入。
    """
    system = """あなたはAURA（Aesthetic Understanding & Risk Advisor）— 美容医療の「患者の味方」AIアドバイザーです。

## あなたの役割
- 美容医療を検討している患者さんに、**偏りのない情報**を提供する
- ユーザーの条件（悩み・エリア・予算・DT制約）に合致する**クリニック候補と施術の選択肢**を、根拠と共に提示する
- クリニックのカウンセリングで**聞くべき質問**を武装させる
- 広告価格と実勢価格の**乖離**を教える
- **リスク**と**ダウンタイムの真実**を隠さず伝える
- 患者さんが**情報格差のない状態**で医師と対話できるようにする

## 絶対に守るルール（法的制約: 医師法第17条・第72条）
1. **診断しない** — 「あなたの症状は○○です」とは絶対に言わない
2. **処方しない** — 薬や治療法を指定しない
3. **「おすすめ」「推薦」という言葉は使わない** — 代わりに「条件に合致する選択肢」「データに基づく候補」として提示する
4. **必ず免責事項を含める** — 「最終判断は医師との相談で」を必ず添える

## 重要: クリニック候補の提示について
- ユーザーの条件に合致するクリニック候補データが提供されている場合、それを自然な文章で整理して伝える
- 各クリニックが「なぜ候補に挙がったか」の理由を必ず添える
- 「おすすめ」ではなく「あなたの条件に合致する」というフレーミングで提示する
- クリニック候補は必ず番号付きリストで見やすく整理する
- 注意点がある場合は率直に伝える

## あなたの話し方
- 敬語で丁寧に、でも堅すぎない親しみやすいトーン
- 難しい医学用語は使わず、分かりやすく説明
- 「〜してください」ではなく「〜を確認されるとよいかもしれません」
- リスクは隠さないが、過度に脅さない
- データに基づく事実と、個人的な意見を明確に区別

## 回答の質についての重要な指示
- 「一般的にこうです」という曖昧な表現は使わない。必ずデータから具体的な数字で答える
- 比較質問には必ず「よいところ / 気になるところ / こんな人に向いている」の3軸で比較する
- 価格の質問には「広告では○○円だが、実際は○○円かかる。その差額の原因は○○」まで説明する
- リスクの質問には「よくあるリスク / 稀だが重大なリスク / 医師に確認すべきこと」の3段階で整理する
- DTの質問には「クリニックが言う期間 / 実際の回復期間 / 周囲にバレないまでの期間」を区別する
- 「そもそもどういう施術か」の説明を、知らない人でもわかるように、たとえを交えて簡潔に行う

## 回答の構成（クリニック候補提示時）
1. **条件の確認**（あなたの条件を整理しました）
2. **関連施術の整理**（条件に合う施術の比較）
3. **クリニック候補**（番号付きリスト + 選出理由）
4. **カウンセリングで聞くべき質問**（3-5個）
5. **免責事項**

## 回答の構成（一般的な相談時）
1. **悩みへの共感**（1-2文）
2. **関連する施術の整理**（選択肢の提示）
3. **価格の真実**（広告価格と実勢価格の差、隠れコスト）
4. **知っておくべきリスク**（TOP3のリスク）
5. **カウンセリングで聞くべき質問**（3-5個）
6. **免責事項**

## 回答の模範例

### 良い回答例（二重についての質問）:
「二重の施術は主に2つあります。

**埋没法** — 糸でまぶたを留めて二重を作る方法です。
- よいところ: 施術時間が短く（15-30分）、腫れが引くのが1週間程度と早い。やり直しがきく
- 気になるところ: 広告では「29,800円」だが、実際は片目の価格で両目だと倍、さらに保証プランを勧められることが多く、総額15-30万円程度
- こんな人に向いている: 初めての施術、自然な変化を求める方、DTをあまり取れない方

**切開法** — まぶたを切開して二重のラインを作る方法です。
- よいところ: 半永久的で戻りにくい。まぶたの脂肪やたるみも同時に取れる
- 気になるところ: DTが2週間〜1ヶ月。傷跡が完全に消えるまでに3ヶ月程度。価格は20-40万円
- こんな人に向いている: まぶたが厚い方、元に戻らない仕上がりを求める方」

### 悪い回答例（避けるべき）:
「二重の施術についてご案内します。二重埋没法は体への負担は軽いです。広告価格は29,800円です。実際の価格は異なります。」
→ このようなデータの羅列ではなく、上のように「つまりどういうことか」を解説する
"""

    # 施術データのコンテキスト注入（全項目）
    if ctx.matched_procedures:
        system += "\n\n## 参照すべき施術データ\n"
        for proc in ctx.matched_procedures:
            system += f"\n### {proc.get('name', '')}\n"

            # 施術の説明文
            description = proc.get("description", "")
            if description:
                system += f"- 説明: {description}\n"

            system += f"- カテゴリ: {proc.get('category_label', '')}\n"
            system += f"- 侵襲度: {proc.get('invasiveness', '')}\n"
            system += f"- 持続期間: {proc.get('duration', '')}\n"

            # 向き・不向き
            suitable = proc.get("suitable_for", [])
            if suitable:
                system += f"- 向いている人: {', '.join(suitable)}\n"
            not_suitable = proc.get("not_suitable_for", [])
            if not_suitable:
                system += f"- 向いていない人: {', '.join(not_suitable)}\n"

            # 推奨回数
            sessions = proc.get("recommended_sessions", "")
            if sessions:
                system += f"- 推奨回数: {sessions}\n"

            # 価格（全項目）
            pricing = proc.get("pricing", {})
            if pricing:
                adv = pricing.get("advertised", {})
                real = pricing.get("real", {})
                system += f"- 広告価格: {adv.get('display', '不明') if isinstance(adv, dict) else adv}\n"
                system += f"- 実勢価格: {real.get('display', '不明') if isinstance(real, dict) else real}\n"
                gap = pricing.get("gap_warning", "")
                if gap:
                    system += f"- 価格ギャップ警告: {gap}\n"
                # 隠れコストは全件表示
                hidden = pricing.get("hidden_costs", [])
                if hidden:
                    system += "- 隠れコスト:\n"
                    for cost in hidden:
                        system += f"  - {cost}\n"

            # DT（全情報）
            dt = proc.get("downtime", {})
            if dt:
                system += f"- DT（クリニック公式）: {dt.get('official', '')}\n"
                system += f"- DT（実際の回復）: {dt.get('real', '')}\n"
                social = dt.get("social_recovery", "")
                if social:
                    system += f"- DT（周囲にバレないまで）: {social}\n"

            # 回復段階
            phases = proc.get("recovery_phases", [])
            if phases:
                system += "- 回復段階:\n"
                for phase in phases:
                    if isinstance(phase, dict):
                        system += f"  - {phase.get('period', '')}: {phase.get('description', '')}\n"
                    else:
                        system += f"  - {phase}\n"

            # リスク（全件表示）
            risks = proc.get("risks", [])
            if risks:
                system += "- リスク（全件）:\n"
                for r in risks:
                    system += f"  - {r}\n"

            # カウンセリング質問（全件表示）
            questions = proc.get("counseling_questions", [])
            if questions:
                system += "- カウンセリングで聞くべき質問（全件）:\n"
                for q in questions:
                    system += f"  - {q}\n"

    # クリニックデータのコンテキスト注入
    if ctx.target_clinic:
        clinic = ctx.target_clinic
        system += f"\n\n## 参照すべきクリニックデータ\n"
        system += f"- 名称: {clinic.get('name', '')}\n"
        system += f"- 所在地: {clinic.get('address', '')}\n"
        system += f"- 診療科: {clinic.get('medical_departments', '')}\n"
        prov = clinic.get("data_provenance", {})
        if prov:
            system += f"- データ鮮度: {prov.get('freshness', 'unknown')}\n"

    # ユーザーの状況コンテキスト
    if ctx.concern or ctx.budget_range or ctx.downtime_available:
        system += "\n\n## ユーザーの状況\n"
        if ctx.concern:
            system += f"- 悩み: {ctx.concern}\n"
        if ctx.budget_range:
            system += f"- 予算: {ctx.budget_range}\n"
        if ctx.downtime_available:
            system += f"- DT確保可能: {ctx.downtime_available}\n"
        if ctx.age_range:
            system += f"- 年代: {ctx.age_range}\n"
        if ctx.previous_procedures:
            system += f"- 過去の施術: {', '.join(ctx.previous_procedures)}\n"

    # 推薦エンジンの結果コンテキスト注入
    if recommendation_context:
        system += recommendation_context

    return system


def check_legal_boundary(user_message: str) -> tuple[LegalBoundary, str | None]:
    """
    ユーザーメッセージの法的制約チェック

    Returns:
        (boundary, redirect_message)
        - ALLOWED: そのまま回答可能
        - RECOMMENDATION: 推薦リクエスト → 推薦エンジン起動
        - CAUTION: 注意喚起を添えて回答
        - PROHIBITED: 回答を拒否し、リダイレクトメッセージを返す
    """
    # 絶対禁止パターンチェック（医療行為のみ）
    for pattern in PROHIBITED_PATTERNS:
        if pattern in user_message:
            return (
                LegalBoundary.PROHIBITED,
                f"申し訳ございません。AURAでは医学的な診断や処方はできません（医師法第17条の制約）。\n\n"
                f"代わりに、以下のことでお力になれます：\n"
                f"- あなたの条件に合った**クリニック候補**の提示\n"
                f"- 関連する**施術の選択肢**と**それぞれのメリット・デメリット**の整理\n"
                f"- 各施術の**広告価格と実勢価格の差**\n"
                f"- カウンセリングで**聞くべき質問リスト**\n\n"
                f"具体的にどのような悩み（例: 目元、鼻、肌 等）についてお知りになりたいですか？"
            )

    # 推薦リクエスト検出
    from src.advisor.intake import is_recommendation_request
    if is_recommendation_request(user_message):
        return (LegalBoundary.RECOMMENDATION, None)

    # 注意喚起パターンチェック
    for pattern in CAUTION_PATTERNS:
        if pattern in user_message:
            return (
                LegalBoundary.CAUTION,
                None,
            )

    return (LegalBoundary.ALLOWED, None)


# ==========================================
# 悩み → 施術マッチング
# ==========================================

# 悩みキーワード → concern タグのマッピング
CONCERN_MAP = {
    # 目元
    "二重": ["double"],
    "一重": ["double"],
    "奥二重": ["double"],
    "目を大きく": ["bigger", "double"],
    "目が小さい": ["bigger", "double"],
    "目元": ["double", "bigger", "heavy", "kuma"],
    "まぶた": ["double", "heavy"],
    "クマ": ["kuma"],
    "くま": ["kuma"],
    "たるみ": ["sagging", "heavy"],
    "まぶたが重い": ["heavy"],

    # 鼻
    "鼻を高く": ["height"],
    "鼻筋": ["height"],
    "団子鼻": ["tip"],
    "鼻先": ["tip"],
    "小鼻": ["nostril"],
    "鼻の穴": ["nostril"],
    "鼻": ["height", "tip", "overall"],

    # 肌
    "シミ": ["spots"],
    "しみ": ["spots"],
    "くすみ": ["spots"],
    "肝斑": ["spots"],
    "ニキビ": ["pores"],
    "にきび": ["pores"],
    "毛穴": ["pores"],
    "しわ": ["wrinkles"],
    "シワ": ["wrinkles"],
    "ほうれい線": ["wrinkles", "sagging"],

    # 輪郭
    "小顔": ["jaw", "overall_contour"],
    "エラ": ["jaw"],
    "えら": ["jaw"],
    "フェイスライン": ["overall_contour", "sagging"],
    "二重あご": ["double_chin"],
    "あご": ["chin_shape", "double_chin"],
    "顎": ["chin_shape", "double_chin"],
    "頬": ["cheek"],
}


def match_concerns(user_message: str) -> list[str]:
    """ユーザーメッセージから悩みタグを抽出"""
    concerns = set()
    for keyword, tags in CONCERN_MAP.items():
        if keyword in user_message:
            concerns.update(tags)
    return list(concerns)


# ==========================================
# モックLLMレスポンス生成
# ==========================================

# FAQ定型パターン — よくある定型質問への対応
_FAQ_PATTERNS = {
    "痛い": (
        "施術の痛みについてですね。\n\n"
        "痛みの感じ方は施術によって大きく異なります。\n\n"
        "- **注射系**（ヒアルロン酸、ボトックス等）: チクッとする程度。麻酔クリームを塗れば、ほとんど感じない方が多いです\n"
        "- **埋没法**: 局所麻酔の注射が一番痛いポイント。施術中はほぼ無痛\n"
        "- **切開系**: 術中は麻酔で無痛。術後の痛みは鎮痛剤でコントロール可能\n"
        "- **レーザー系**: ゴムで弾かれるような感覚。部位によって差があります\n\n"
        "カウンセリングで「麻酔の種類」と「術後の痛みのピークはいつか」を確認しておくと安心です。"
    ),
    "何歳から": (
        "年齢についてですね。\n\n"
        "法的には18歳未満は親権者の同意が必要です。\n\n"
        "- **美容注射**（ボトックス、ヒアルロン酸）: 20代後半〜が多いですが、年齢制限は特にありません\n"
        "- **二重整形**: 10代後半〜20代前半が最も多い年代です\n"
        "- **アンチエイジング系**: 30代〜が一般的ですが「早めの予防」として20代から始める方もいます\n\n"
        "年齢よりも「顔の成長が落ち着いているか」「自分の意思で決めているか」が重要なポイントです。"
    ),
    "何回": (
        "通院回数についてですね。\n\n"
        "施術の種類によって大きく異なります。\n\n"
        "- **1回完結型**（二重埋没、切開、鼻整形など外科系）: 施術は1回。経過観察で1-2回通院\n"
        "- **複数回型**（レーザートーニング、ダーマペンなど）: 3-5回がワンクール。月1回ペース\n"
        "- **定期メンテナンス型**（ヒアルロン酸、ボトックス）: 効果の持続は3-6ヶ月。継続的に通う必要あり\n\n"
        "カウンセリングでは「トータルで何回通うのか」と「維持するための費用」を必ず聞いてください。"
    ),
    "バレる": (
        "周囲にバレるかどうか、気になりますよね。\n\n"
        "「バレやすさ」は施術の種類とダウンタイムの取り方次第です。\n\n"
        "- **バレにくい施術**: ボトックス、ヒアルロン酸（少量）、レーザートーニング → 当日〜翌日から普通に過ごせる\n"
        "- **工夫次第**: 二重埋没 → 腫れが引くまで3-7日。メガネやマスクでカバーする方が多い\n"
        "- **しっかりDTが必要**: 切開系 → 2週間〜1ヶ月。長期休暇に合わせる方がほとんど\n\n"
        "「周囲にバレないまでの期間」はクリニック公式のDTより長くなるのが一般的です。"
    ),
    "失敗": (
        "失敗のリスクについて、率直にお伝えしますね。\n\n"
        "**よくあるトラブル**:\n"
        "- 仕上がりが思っていたイメージと違う（左右差、不自然さ）\n"
        "- 広告の症例写真と実際の仕上がりのギャップ\n"
        "- 想定より腫れが長引く\n\n"
        "**稀だが重大なリスク**:\n"
        "- 感染症、神経損傷、血管閉塞（フィラー注入時）\n"
        "- 修正手術が必要になるケース\n\n"
        "**リスクを下げるポイント**:\n"
        "- 症例写真だけでなく「その医師の経験年数」「年間施術件数」を確認\n"
        "- 保証制度の内容と適用条件を事前に確認\n"
        "- 「やり直しの場合の費用」をカウンセリングで必ず質問する"
    ),
}


def generate_mock_response(ctx: AdvisorContext, user_message: str) -> str:
    """
    APIキーが無い場合のモックレスポンス生成

    実際のLLMを使わず、テンプレートベースで
    構造化されたアドバイスを生成する。

    改善点:
    - 複数施術の比較分析（よいところ / 気になるところ / こんな人に）
    - 価格の文脈化（差額の原因まで説明）
    - FAQ定型パターン対応
    - 自然な共感表現
    - フォローアップサジェスト
    """
    concerns = match_concerns(user_message)
    procedures = ctx.matched_procedures

    # FAQ定型パターンに該当するかチェック
    for keyword, faq_response in _FAQ_PATTERNS.items():
        if keyword in user_message:
            response = faq_response + "\n"
            # 施術データがあれば補足情報を追加
            if procedures:
                response += f"\n現在のご相談内容に関連する施術データもありますので、具体的な施術名を教えていただければ詳しくお伝えできます。\n"
            response += LEGAL_DISCLAIMER
            return response

    if not procedures:
        return (
            "ご相談ありがとうございます。\n\n"
            "お悩みの内容をもう少し具体的に教えていただけますか？\n"
            "例えば：\n"
            "- **目元**：二重にしたい、目を大きくしたい、クマが気になる\n"
            "- **鼻**：鼻を高くしたい、団子鼻を直したい\n"
            "- **肌**：シミ・くすみ、毛穴、ニキビ跡\n"
            "- **輪郭**：小顔になりたい、エラが気になる\n\n"
            "具体的な悩みを教えていただければ、関連する施術の選択肢、"
            "価格の真実、リスク、カウンセリングで聞くべき質問をお伝えできます。"
        )

    # 構造化レスポンス生成
    response_parts = []

    # --- 1. 共感（自然な導入） ---
    concern_short = user_message[:30].rstrip("。、！!？?")
    response_parts.append(
        f"ご相談ありがとうございます。\n\n"
        f"「{concern_short}」をお考えなんですね。"
        f"大事なお顔のことですから、しっかり情報を整理してお伝えしますね。\n"
    )

    # --- 2. 施術の比較分析 ---
    is_comparison = len(procedures) >= 2
    if is_comparison:
        response_parts.append("## 関連する施術の比較\n")
        response_parts.append(
            "条件に合う施術を「よいところ / 気になるところ / こんな人に向いている」の3軸で整理しました。\n"
        )
    else:
        response_parts.append("## 関連する施術\n")

    for proc in procedures[:4]:
        name = proc.get("name", "")
        inv = proc.get("invasiveness", "")
        dur = proc.get("duration", "")
        description = proc.get("description", "")
        inv_label = {
            "low": "体への負担は軽い",
            "medium": "やや負担あり",
            "high": "体への負担が大きい",
        }.get(inv, inv)

        pricing = proc.get("pricing", {})
        adv = pricing.get("advertised", {})
        real = pricing.get("real", {})
        adv_d = adv.get("display", "") if isinstance(adv, dict) else ""
        real_d = real.get("display", "") if isinstance(real, dict) else ""
        gap_warning = pricing.get("gap_warning", "")
        hidden_costs = pricing.get("hidden_costs", [])

        dt = proc.get("downtime", {})
        risks = proc.get("risks", [])
        suitable = proc.get("suitable_for", [])

        response_parts.append(f"### {name}\n")

        # 施術の簡潔な説明
        if description:
            response_parts.append(f"{description}\n\n")

        # よいところ
        good_points = []
        good_points.append(inv_label)
        if dur:
            good_points.append(f"効果の持続: {dur}")
        suitable_text = ", ".join(suitable[:3]) if suitable else ""
        response_parts.append(f"**よいところ**: {'. '.join(good_points)}\n")

        # 気になるところ（価格の文脈化）
        concerns_list = []
        if adv_d and real_d:
            # 差額の原因まで説明
            price_text = f"広告では {adv_d} だが、実際は {real_d}"
            if gap_warning:
                price_text += f"。{gap_warning}"
            concerns_list.append(price_text)
        if hidden_costs:
            concerns_list.append(f"隠れコスト: {', '.join(hidden_costs)}")
        if dt.get("real"):
            concerns_list.append(f"回復に {dt['real']} かかる")
        if concerns_list:
            response_parts.append(f"**気になるところ**: {'. '.join(concerns_list)}\n")

        # こんな人に向いている
        if suitable:
            response_parts.append(f"**こんな人に向いている**: {', '.join(suitable)}\n")

        # 不向きな人
        not_suitable = proc.get("not_suitable_for", [])
        if not_suitable:
            response_parts.append(f"**向いていない場合**: {', '.join(not_suitable)}\n")

        response_parts.append("")

    # --- 3. 価格の真実（まとめ） ---
    has_price_gap = any(
        proc.get("pricing", {}).get("gap_warning") for proc in procedures[:4]
    )
    if has_price_gap:
        response_parts.append("## 価格について知っておくこと\n")
        for proc in procedures[:4]:
            pricing = proc.get("pricing", {})
            adv = pricing.get("advertised", {})
            real = pricing.get("real", {})
            adv_d = adv.get("display", "") if isinstance(adv, dict) else ""
            real_d = real.get("display", "") if isinstance(real, dict) else ""
            gap = pricing.get("gap_warning", "")
            hidden = pricing.get("hidden_costs", [])

            if adv_d and real_d and gap:
                response_parts.append(f"**{proc.get('name', '')}**: 広告 {adv_d} → 実際 {real_d}\n")
                response_parts.append(f"差額の理由: {gap}\n")
                if hidden:
                    response_parts.append(f"追加で発生しやすい費用: {', '.join(hidden)}\n")
                response_parts.append("")

    # --- 4. 主要リスク（3段階整理） ---
    response_parts.append("## 知っておきたいリスク\n")
    for proc in procedures[:2]:
        risks = proc.get("risks", [])
        if risks:
            response_parts.append(f"**{proc.get('name', '')}**:\n")
            # リスクを段階的に整理
            if len(risks) >= 3:
                response_parts.append(f"- よくあるリスク: {risks[0]}\n")
                response_parts.append(f"- 稀だが重大なリスク: {risks[1]}\n")
                response_parts.append(f"- 医師に確認すべきこと: {risks[2]}\n")
                for r in risks[3:]:
                    response_parts.append(f"- {r}\n")
            else:
                for r in risks:
                    response_parts.append(f"- {r}\n")
            response_parts.append("")

    # --- 5. DT情報（3区分） ---
    has_dt = any(proc.get("downtime", {}).get("real") for proc in procedures[:4])
    if has_dt:
        response_parts.append("## ダウンタイムの真実\n")
        for proc in procedures[:4]:
            dt = proc.get("downtime", {})
            if dt.get("official") or dt.get("real"):
                response_parts.append(f"**{proc.get('name', '')}**:\n")
                if dt.get("official"):
                    response_parts.append(f"- クリニック公式: {dt['official']}\n")
                if dt.get("real"):
                    response_parts.append(f"- 実際の回復: {dt['real']}\n")
                social = dt.get("social_recovery", "")
                if social:
                    response_parts.append(f"- 周囲にバレないまで: {social}\n")
                response_parts.append("")

    # --- 6. カウンセリング質問 ---
    response_parts.append("## カウンセリングで聞いておくこと\n")
    response_parts.append(
        "以下を確認しておくと、納得して判断しやすくなります。\n"
    )
    q_count = 0
    for proc in procedures[:3]:
        questions = proc.get("counseling_questions", [])
        for q in questions:
            q_count += 1
            response_parts.append(f"{q_count}. {q}\n")
        if questions:
            response_parts.append("")

    # --- 7. 免責事項 ---
    response_parts.append(LEGAL_DISCLAIMER)

    # --- 8. フォローアップサジェスト ---
    response_parts.append(
        "\n他に気になることがあれば、何でも聞いてくださいね。"
        "「痛みはどのくらい？」「何回通うの？」といった質問にもお答えできます。"
    )

    return "\n".join(response_parts)


# ==========================================
# セッション管理
# ==========================================

class ConversationSession(BaseModel):
    """会話セッション"""

    session_id: str
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    context: AdvisorContext = Field(default_factory=AdvisorContext)
    messages: list[dict] = Field(default_factory=list)  # {"role": "user"|"assistant", "content": str}
    is_active: bool = True


# インメモリセッションストア（MVP用）
_sessions: dict[str, ConversationSession] = {}


def get_or_create_session(session_id: str) -> ConversationSession:
    """セッション取得・作成"""
    if session_id not in _sessions:
        _sessions[session_id] = ConversationSession(session_id=session_id)
    return _sessions[session_id]


def cleanup_old_sessions(max_age_hours: int = 24):
    """古いセッションの削除"""
    now = datetime.now()
    to_delete = []
    for sid, session in _sessions.items():
        created = datetime.fromisoformat(session.created_at)
        if (now - created).total_seconds() > max_age_hours * 3600:
            to_delete.append(sid)
    for sid in to_delete:
        del _sessions[sid]
