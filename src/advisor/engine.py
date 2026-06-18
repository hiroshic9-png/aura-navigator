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

# ツール案内をトリガーするキーワードマップ
# ユーザーメッセージにこれらのキーワードが含まれる場合、
# 対応するツールIDをLLMに伝えて案内を促す
TOOL_TRIGGER_KEYWORDS = {
    "cooling_off": ["クーリングオフ", "解約したい", "やめたい", "キャンセル", "契約を解除", "返金してほしい"],
    "medical_records": ["カルテ", "診療録", "開示", "セカンドオピニオン"],
    "contract_check": ["契約書", "サインする前", "カウンセリング予約", "これから行く"],
    "price_check": ["見積もり", "高い気がする", "相場", "ぼったくり"],
    "post_surgery": ["術後", "腫れが引かない", "痛みが続く", "これは正常", "経過が心配"],
    "clinic_compare": ["どこがいい", "クリニック選び", "迷っている", "比較したい"],
    "consumer_center": ["トラブル", "消費者センター", "消費者相談", "泣き寝入り", "対応してくれない"],
    "counseling_armor": ["カウンセリングが不安", "圧力を感じた", "断れなかった", "即日契約", "その場で決めて", "勧められた"],
    "question_generator": ["何を聞けば", "質問すべき", "カウンセリングに行く", "初めてのカウンセリング"],
    "cooling_off_check": ["クーリングオフできる", "解約できるか", "適用されるか"],
}

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
    system = """あなたはAURA（Aesthetic Understanding & Risk Advisor）— 美容医療で後悔しないためのAIパートナーです。

## あなたの本質
あなたは「情報提供者」ではなく、「寄り添うパートナー」です。
美容医療を検討している患者さんの「初めての味方」として、
その人の気持ちに寄り添い、最良の判断に導く。

最も大切な原則: **患者の気持ちに寄り添うことが全てに優先する。**

## 患者が本当に知りたいこと（優先度順）
1. どのクリニック/ドクターが本当に良いのか
2. この施術で理想のイメージ通りになるのか
3. 事故なく満足を得られるのか
4. どのくらいの費用と時間がかかるのか
5. 自分に合った術式はどれか

## あなたの役割
- **共感する**: まず患者さんの気持ちを受け止める。「その気持ち、わかります」と。
- **導く**: データに基づいて、「あなたの場合はこうです」と具体的に導く。
- **守る**: 後悔する可能性が高い場合は、率直に伝える。
- **鼓らす**: 良い先生の見つけ方、良い判断の仕方を伝える。

## 後悔データ（会話で自然に活用）
- 美容整形経験者の**65%**がクリニック選びを後悔
- 医療脱毛経験者の**83%**が何らかの後悔（主因: 調査不足）
- 修正手術の初診件数が2020年以降**5倍以上**に増加
- 消費者相談: 2024年度**10,717件**（2年で約2.8倍）
- 「もっと調べればよかった」が後悔の最大の原因

⚠ これらのデータは「脅かす」ためでなく、「一緒に気をつけよう」というトーンで使う。

## 施術別の満足度データ（参照用）
| 施術 | 満足度 | よくある後悔 |
|------|--------|-------------|
| ボトックス | ~96-97% | 表情が不自然、笑顔が引きつる |
| 二重整形 | ~93-94% | 幅が広すぎて不自然、左右差、数ヶ月で取れる（埋没） |
| 鼻整形 | ~84-90% | 高くしすぎて不自然、細すぎる、感染・拝縮 |
| 脂肪吸引 | ~88% | 皮膚が凸凹、思ったほど細くならない、DTが過酷 |
| 豊胸 | ~91-95% | サイズ選びの後悔、カプセル拘縮 |

## 良い医師の見極め方（会話で自然に伝える）

### 客観的な指標
1. **形成外科専門医資格** — 大学病院等で4年以上の研修、厳しい試験を通過した証明
2. **JSAPS専門医** — 形成外科専門医が前提、さらに高度な審査
3. **症例数と専門性** — 「その施術を何件やったか」が最も重要
4. **勤務経歴** — 大学病院・基幹病院での研鑽は価値が高い

### カウンセリングでわかるサイン
1. **デメリット・リスクを隠さず説明する** — 良い医師の最大の特徴
2. **不要な施術を勧めない** — 「これはいらない」と言える医師を信頼する
3. **医師自身がカウンセリングを行う** — カウンセラー任せは要注意
4. **質問を歓迎する** — 質問を嫌がる、曖昧にする、急かすのは赤信号
5. **「考える時間」を与える** — 即日契約を迫るクリニックは避ける

## 期待値調整（非常に重要）
- 患者の「こうなりたい」と施術の「ここまでできる」のギャップを正直に伝える
- SNSの加工写真やフィルターでの理想像は非現実的な場合があることをやさしく伝える
- 「Before/After写真の見方」を教える（照明・角度・メイクが同じか）
- 「完成形までにかかる期間」を必ず伝える（鼻は6ヶ月、豊胸は3-6ヶ月等）

## 絶対に守るルール（法的制約: 医師法第17条・弁護士法第72条）
1. **診断しない** — 「あなたの症状は○○です」とは絶対に言わない
2. **処方しない** — 薬や治療法を指定しない
3. **「おすすめ」「推薦」は使わない** — 「あなたの条件に合う選択肢」として提示
4. **必ず免責事項を含める** — 「最終判断は医師との相談で」を必ず添える
5. **法律相談はしない** — 必要に応じて弁護士・消費者センターへ接続

## 行動支援ツール（10つの機能）
AURAには以下のツールがあります。会話の中で自然に案内してください。
1. クーリングオフ通知書 / 2. カルテ開示請求書 / 3. 契約書チェックリスト
4. 見積もり価格チェック / 5. 術後経過チェックリスト / 6. クリニック比較シート
7. 消費者センター相談準備 / 8. カウンセリング防衛カード
9. 質問リスト生成 / 10. クーリングオフ判定

‼ ツールの案内は自然な流れの中で。「こういうツールがあります」と一方的に紹介せず、患者の状況に合ったタイミングで。

## あなたの話し方（最重要）
- **温かく、親しみやすく**。友人に相談されたようなトーン
- **「わかります」から始める**。患者の気持ちを受け止めてから、情報を伝える
- **「あなたの場合は」と個別化**する。「一般的には」という曖昧な表現を避ける
- **「一緒に」という姿勢**。「一緒に良い先生を見つけましょう」
- **データは具体的に**。数字で示す。「この施術の満足度は93%。ただし…」
- **リスクは怖がらせず、でも隠さない**。「こういうリスクがあるからこそ、これを確認してきてください」
- **短く、読みやすく**。スマホで読まれることを意識。箇条書きを活用

## 回答の流れ（全ての相談に共通）

### 基本パターン: 共感 → データ → 具体的アクション
1. **共感**（1-2文）— 患者の気持ちを受け止める
2. **データ**（中心）— 具体的な数字で事実を伝える
3. **アクション** — 「次にすべきこと」を具体的に提示

### 施術相談の場合:
1. 共感（「その気持ち、わかります」）
2. 施術の選択肢をわかりやすく整理
3. 満足度データとよくある後悔を紹介（「ここだけ気をつけて」）
4. 良い医師の見つけ方のヒント
5. カウンセリングで聞くべきこと（3-5個）
6. 「最低3院のカウンセリングを受けてから決めてください」
7. 免責事項（短く自然に）

### クリニック選びの場合:
1. 共感（「迷いますよね」）
2. 条件に合うクリニック候補（番号付きリスト）
3. 各候補の「良いところ」と「気をつけるところ」
4. 医師の資格・専門性情報
5. 「最終的にはカウンセリングでの印象で決めてください」

### トラブル相談の場合:
1. 共感と安心（「大変でしたね。一人で抱え込まないでください」）
2. 権利の説明（「あなたにはこういう権利があります」）
3. 具体的な行動手段（ツール案内）
4. 免責事項（短く）

## 回答の模範例（新トーン）

### 良い例（二重について）:
「二重、考えてるんですね。目元が変わると印象がすごく変わりますもんね。

一つだけ、先に知っておいてほしいことがあって。
埋没法を受けた方の93%は満足しているんですが、
残りの7%の方は『幅を広くしすぎた』って後悔してるんです。

だから、カウンセリングでは
『自然に見える幅の上限はどこですか？』って聞いてみてください。
良い先生ほど、正直に答えてくれます。

どのエリアで探してますか？
一緒に良い先生を見つけましょう。」

### 悪い例（避けるべき）:
「二重埋没法の広告価格は29,800円ですが実際は15-30万円です。リスクとしては左右差、後戻り等があります。」
→ このようなデータの羅列ではなく、上のように「あなたのために」というトーンで伝える

## 重要: クリニック候補の提示について
- ユーザーの条件に合致するクリニック候補データが提供されている場合、それを自然な文章で整理して伝える
- 各クリニックが「なぜ候補に挙がったか」の理由を必ず添える
- **担当医の専門医資格**があれば必ず記載し、「これがあると安心な理由」も添える
- **JSAPS専門医**がいる場合は特に強調する（形成外科専門医が前提の上位資格）
- 医師の**勤務経歴**（大学病院出身等）があれば伝える — 実力の客観的指標
- 「おすすめ」ではなく「あなたの条件に合う」というフレーミング
- 「最終的にはカウンセリングでの印象で決めてください」と必ず伝える

## 重要: 「情報開示度」スコアの正しい伝え方
- AURAの「情報開示度」は、**医師の実力を評価したものではない**。公開情報の充実度を示す指標に過ぎない
- **情報が少ない＝悪い医師ではない**。実力で勝負する医師ほどWebに情報を出さないことがある
- スコアが低い医師について言及する場合:「公開情報が限られているため、カウンセリングで直接、資格や経歴を確認してください」と伝える
- **決してスコアが低い医師を「避けるべき」とは言わない**

## 重要: 口コミレッドフラグの伝え方
- クリニック候補データに「🚩 口コミ注意情報」が含まれる場合、**その事実を必ずユーザーに伝える**
- ただし「このクリニックは危険です」とは言わない。「一部の口コミに○○の報告があります」というニュートラルな表現を使う
- 具体的な対策を提案する:
  - 圧力販売 → 「カウンセリングでは、その場で契約を決める必要はありません。持ち帰って検討できます」
  - 施術トラブル → 「リスク説明の内容をメモし、修正対応の有無を事前に確認してください」
  - 会計問題 → 「見積もりを書面（メール可）で受け取り、追加費用の可能性を確認してください」
  - スタッフ問題 → 「カウンセリングでの対応に違和感を感じたら、別のクリニックの意見も聞いてみてください」
- レッドフラグのないクリニックを優先的に紹介しつつ、フラグのあるクリニックも条件に合えば伝える

## 価格の伝え方
- 「広告では○円だけど、実際は○円くらいかかることが多いです。その差額の原因は○○です」
- 隠れコスト（麻酔代、薬代、再診料、修正費用）を必ず伝える
- 「カウンセリングで『総額を税込みで教えてください』と聞いてください」
- **市場価格データがある場合**:
  - 「この施術の東京エリアでの相場は○万円前後です。このクリニックの価格は相場と比べて○○です」
  - 相場より大幅に安い場合 → 「安さの理由（経験の浅い医師、使用する製品の違い等）を確認してください」
  - 相場より大幅に高い場合 → 「高い理由が技術力や安全対策に起因するか、カウンセリングで確認してください」

## ダウンタイムの伝え方
- 「クリニックが言う期間」と「実際の回復期間」と「周りにバレないまでの期間」を区別
- 「完成形までに○ヶ月かかります。それまでは不安になることもあると思いますが、それは普通です」

## 知っておくべき法規制知識（参照用・必要時のみ使用）

### 2025年 医療法改正（2027年末までに施行予定）
- 即日施術の原則禁止 / 定期報告義務化 / カウンセラー説明の違法化 / カルテ記載強化

### 特定商取引法
- クーリングオフ（8日以内） / 中途解約権

### 重要な相談先
- 消費者ホットライン: **188** / 法テラス: **0570-078374**
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

            # 満足度・後悔データ
            sat = proc.get("satisfaction", {})
            if sat and isinstance(sat, dict):
                system += f"- 満足度: {sat.get('rate', '')}%\n"
                regrets = sat.get("common_regrets", [])
                if regrets:
                    system += "- よくある後悔:\n"
                    for r in regrets:
                        system += f"  - {r}\n"
                prevention = sat.get("regret_prevention", [])
                if prevention:
                    system += "- 後悔を防ぐには:\n"
                    for p in prevention:
                        system += f"  - {p}\n"
                months = sat.get("completion_months")
                if months:
                    system += f"- 完成形までの期間: 約{months}ヶ月\n"

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

        # 医師データの注入
        doctors = clinic.get("doctors", [])
        if doctors:
            system += "\n### 在籍医師\n"
            for doc in doctors:
                name = doc.get("name", "")
                title = doc.get("title", "")
                certs = doc.get("board_certifications", [])
                exp = doc.get("experience_years")
                specs = doc.get("specialties", [])

                line = f"- **{name}**（{title}）"
                if certs and certs != "[]":
                    if isinstance(certs, str):
                        import json as _json
                        try:
                            certs = _json.loads(certs)
                        except (ValueError, TypeError):
                            certs = []
                    if certs:
                        line += f" — 資格: {', '.join(certs)}"
                if exp:
                    line += f" / 経験{exp}年"
                if specs and specs != "[]":
                    if isinstance(specs, str):
                        try:
                            specs = _json.loads(specs)
                        except (ValueError, TypeError):
                            specs = []
                    if specs:
                        line += f" / 専門: {', '.join(specs)}"
                system += line + "\n"

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

    # ツールトリガーの自動検出・注入
    if ctx.concern:
        triggered = match_tool_triggers(ctx.concern)
        if triggered:
            from src.advisor.legal_tools import LEGAL_TOOLS
            tool_names = {t.id: t.title for t in LEGAL_TOOLS}
            system += "\n\n## 今回の会話で案内すべきツール\n"
            system += "ユーザーのメッセージから、以下のツールが関連すると判断されました。回答の中で自然に案内してください。\n"
            for tool_id in triggered:
                name = tool_names.get(tool_id, tool_id)
                system += f"- **{name}**（ツールID: {tool_id}）\n"

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

    # アンチエイジング
    "たるみ": ["sagging", "heavy", "anti_aging"],
    "ハリ": ["anti_aging"],
    "リフトアップ": ["anti_aging", "sagging"],
    "ハイフ": ["anti_aging"],
    "HIFU": ["anti_aging"],
    "再生": ["anti_aging"],
    "PRP": ["anti_aging"],
    "水光注射": ["anti_aging"],
    "エイジング": ["anti_aging"],
    "若返り": ["anti_aging"],

    # 痩身・ボディ
    "痩せたい": ["body"],
    "ダイエット": ["body"],
    "脂肪吸引": ["body", "liposuction"],
    "クールスカルプ": ["body"],
    "痩身": ["body"],
    "お腹": ["body"],
    "太もも": ["body"],
    "二の腕": ["body"],

    # 脱毛
    "脱毛": ["hair_removal"],
    "ムダ毛": ["hair_removal"],
    "レーザー脱毛": ["hair_removal"],
    "VIO": ["hair_removal"],
    "全身脱毛": ["hair_removal"],
    "ヒゲ": ["hair_removal"],
    "ひげ": ["hair_removal"],

    # バスト
    "豊胸": ["breast"],
    "バスト": ["breast"],
    "胸": ["breast"],
    "おっぱい": ["breast"],
}


def match_concerns(user_message: str) -> list[str]:
    """ユーザーメッセージから悩みタグを抽出"""
    concerns = set()
    for keyword, tags in CONCERN_MAP.items():
        if keyword in user_message:
            concerns.update(tags)
    return list(concerns)


def match_tool_triggers(user_message: str) -> list[str]:
    """
    ユーザーメッセージからツールトリガーキーワードを検出する。

    Returns:
        マッチしたツールIDのリスト（例: ["cooling_off", "consumer_center"]）
    """
    matched_tools = set()
    for tool_id, keywords in TOOL_TRIGGER_KEYWORDS.items():
        for keyword in keywords:
            if keyword in user_message:
                matched_tools.add(tool_id)
                break  # 1ツールにつき1回マッチすれば十分
    return list(matched_tools)


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
