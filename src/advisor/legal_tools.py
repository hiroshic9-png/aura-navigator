"""
AURA MVP — 法的行動支援ツール（ギリギリ行動）

美容医療の患者が「自分で行動を起こせる」ようにするための
テンプレートとプロセスガイドを生成する。

法的境界線の原則:
- 弁護士法72条: 法律事件の代理は禁止 → テンプレートの「提供」はOK
- 医師法17条: 診断・処方は禁止 → 「情報整理と質問の武装」はOK
- 3つの鉄則: 断定しない / 代行しない / 専門家に接続する

7つのギリギリ行動:
1. クーリングオフ通知書テンプレート
2. カルテ開示請求書テンプレート
3. 契約書チェックリスト
4. 見積もり価格判定
5. 術後経過チェックリスト
6. クリニック比較チェックリスト
7. 消費者センター相談準備シート
"""

from dataclasses import dataclass
from datetime import datetime, timedelta


# ==========================================
# テンプレート定義
# ==========================================


@dataclass
class LegalTool:
    """法的行動支援ツール"""
    id: str
    title: str
    description: str
    icon: str
    category: str  # "document" | "checklist" | "guide"


# 利用可能なツール一覧
LEGAL_TOOLS = [
    LegalTool(
        id="cooling_off",
        title="クーリングオフ通知書",
        description="契約日から8日以内なら無条件で解約できます。通知書のテンプレートを生成します。",
        icon="📝",
        category="document",
    ),
    LegalTool(
        id="medical_records",
        title="カルテ開示請求書",
        description="自分のカルテを開示請求する権利があります。請求書テンプレートを生成します。",
        icon="📋",
        category="document",
    ),
    LegalTool(
        id="contract_check",
        title="契約書チェックリスト",
        description="契約書にサインする前に確認すべき12のポイント。",
        icon="✅",
        category="checklist",
    ),
    LegalTool(
        id="price_check",
        title="見積もり価格チェック",
        description="提示された見積もりが相場から大きく外れていないかチェックします。",
        icon="💰",
        category="guide",
    ),
    LegalTool(
        id="post_surgery",
        title="術後経過チェックリスト",
        description="術後の経過が正常範囲内かを自己確認するためのガイド。異常時の対処法も。",
        icon="🩹",
        category="checklist",
    ),
    LegalTool(
        id="clinic_compare",
        title="クリニック比較シート",
        description="複数のクリニックを公平に比較するための評価シート。",
        icon="🏥",
        category="checklist",
    ),
    LegalTool(
        id="consumer_center",
        title="消費者センター相談準備",
        description="トラブル時に消費者ホットライン(188)に相談する際の準備シート。",
        icon="📞",
        category="guide",
    ),
]


def get_tools_list() -> list[dict]:
    """利用可能なツール一覧を返す"""
    return [
        {
            "id": t.id,
            "title": t.title,
            "description": t.description,
            "icon": t.icon,
            "category": t.category,
        }
        for t in LEGAL_TOOLS
    ]


# ==========================================
# テンプレート生成
# ==========================================


def generate_cooling_off(
    clinic_name: str = "",
    contract_date: str = "",
    procedure_name: str = "",
    contract_amount: str = "",
) -> dict:
    """
    クーリングオフ通知書テンプレートを生成する。

    特定商取引法に基づくクーリングオフ（8日以内）。
    美容医療は2017年の法改正で特商法の対象に。
    内容証明郵便での送付を推奨。

    Returns:
        テンプレート文書と注意事項
    """
    today = datetime.now().strftime("%Y年%m月%d日")

    # 契約日からの経過日数チェック
    deadline_warning = ""
    if contract_date:
        try:
            # 簡易パース（YYYY-MM-DD or YYYY年MM月DD日）
            clean_date = contract_date.replace("年", "-").replace("月", "-").replace("日", "")
            dt = datetime.strptime(clean_date, "%Y-%m-%d")
            days_elapsed = (datetime.now() - dt).days
            deadline = dt + timedelta(days=8)
            if days_elapsed > 8:
                deadline_warning = (
                    f"⚠ 契約日から{days_elapsed}日が経過しています。"
                    f"クーリングオフ期間（8日間）を超過している可能性があります。"
                    f"ただし、書面不備等がある場合は期間が延長されることがあります。"
                    f"消費者センター(188)にご相談ください。"
                )
            else:
                remaining = 8 - days_elapsed
                deadline_warning = (
                    f"✓ クーリングオフ期限: {deadline.strftime('%Y年%m月%d日')}まで"
                    f"（残り{remaining}日）。早めの発送をおすすめします。"
                )
        except (ValueError, TypeError):
            pass

    template = f"""通知書

{today}

{clinic_name or "【クリニック名を記入】"} 御中

　私は、下記の契約について、特定商取引に関する法律第48条の規定に基づき、
契約を解除（クーリングオフ）いたします。
　つきましては、速やかに支払済みの代金を返還してください。

　　　　　　　　　　記

1. 契約日: {contract_date or "【契約日を記入: 例 2026年5月20日】"}
2. 施術名: {procedure_name or "【施術名を記入: 例 二重埋没法】"}
3. 契約金額: {contract_amount or "【金額を記入: 例 298,000円】"}
4. 支払方法: 【現金 / クレジットカード / 医療ローン】
5. クリニック名: {clinic_name or "【クリニック名】"}
6. クリニック住所: 【クリニックの住所】

　上記のとおり通知いたします。

【あなたの住所】
【あなたの氏名】"""

    return {
        "title": "クーリングオフ通知書",
        "template": template,
        "deadline_warning": deadline_warning,
        "instructions": [
            "この通知書を**内容証明郵便**で送付してください（証拠が残ります）",
            "郵便局の窓口で「内容証明郵便でお願いします」と伝えるだけでOK",
            "同じ文面を3通用意（クリニック宛・郵便局保管・自分用）",
            "クレジットカード払いの場合は、カード会社にも通知書のコピーを送付",
            "医療ローンの場合は、信販会社にも同様に通知が必要",
            "発信日が8日以内であれば有効（届いた日ではなく発信日）",
        ],
        "legal_basis": (
            "特定商取引法第48条（特定継続的役務提供のクーリングオフ）。"
            "美容医療は2017年12月の法改正で「特定継続的役務」に追加された。"
            "書面受領日を含めて8日以内に書面で通知すれば無条件で解約可能。"
        ),
    }


def generate_medical_records_request(
    clinic_name: str = "",
    patient_name: str = "",
    visit_dates: str = "",
) -> dict:
    """
    カルテ開示請求書テンプレートを生成する。

    個人情報保護法に基づく開示請求。
    クリニックは正当な理由なく拒否できない。
    """
    today = datetime.now().strftime("%Y年%m月%d日")

    template = f"""診療録（カルテ）等開示請求書

{today}

{clinic_name or "【クリニック名を記入】"} 御中

　私は、個人情報の保護に関する法律第33条の規定に基づき、
下記の診療録（カルテ）等の開示を請求いたします。

　　　　　　　　　　記

1. 患者氏名: {patient_name or "【あなたの氏名】"}
2. 生年月日: 【あなたの生年月日】
3. 診察日: {visit_dates or "【受診日を記入: 例 2026年4月15日〜5月20日】"}
4. 開示を求める記録:
   ☐ 診療録（カルテ）
   ☐ 手術記録
   ☐ 看護記録
   ☐ 検査結果
   ☐ 術前・術後写真
   ☐ 同意書の写し
   ☐ その他（　　　　　　　　　）

5. 開示方法: ☐ 閲覧 / ☐ コピー交付
6. 受取方法: ☐ 来院 / ☐ 郵送

【あなたの住所】
【あなたの氏名】
【連絡先電話番号】"""

    return {
        "title": "カルテ開示請求書",
        "template": template,
        "instructions": [
            "本人確認書類（運転免許証等）のコピーを添付してください",
            "クリニックは原則2週間〜1ヶ月以内に応じる義務があります",
            "開示手数料がかかる場合があります（通常3,000〜5,000円程度）",
            "拒否された場合は「個人情報保護委員会」に相談できます（03-6457-9849）",
            "術後トラブル時は、必ず写真を自分でも撮っておいてください",
        ],
        "legal_basis": (
            "個人情報保護法第33条（保有個人データの開示）。"
            "本人から請求があった場合、個人情報取扱事業者は遅滞なく開示する義務がある。"
            "正当な理由なく拒否した場合、個人情報保護委員会による是正命令の対象となる。"
        ),
    }


def generate_contract_checklist() -> dict:
    """契約書チェックリストを生成する"""
    return {
        "title": "契約書チェックリスト — サインする前に確認する12のポイント",
        "checklist": [
            {
                "category": "施術内容",
                "items": [
                    "施術名が正式名称で記載されているか（「プチ整形」等の曖昧な名称はNG）",
                    "施術部位が明確に記載されているか",
                    "使用する材料・製剤名が記載されているか（例: ボツリヌス製剤の場合「ボトックスビスタ」等）",
                ],
            },
            {
                "category": "料金",
                "items": [
                    "総額が明記されているか（税込み表示か確認）",
                    "麻酔代・処方薬代は含まれているか",
                    "再施術や修正が必要になった場合の費用は明記されているか",
                    "キャンセル料の条件は明確か",
                ],
            },
            {
                "category": "リスクと保証",
                "items": [
                    "想定されるリスク・合併症が具体的に記載されているか",
                    "保証制度の内容と条件（期間・対象範囲）は明確か",
                    "施術を担当する医師名が明記されているか",
                ],
            },
            {
                "category": "解約と権利",
                "items": [
                    "クーリングオフの記載があるか（特商法により8日間の無条件解約権）",
                    "中途解約の条件と返金ルールが明確か",
                ],
            },
        ],
        "red_flags": [
            "「今日だけの特別価格」「今決めないと枠が埋まる」と急かされる",
            "カウンセラー（非医師）が施術内容を決定している",
            "契約書のコピーをもらえない",
            "「全額前払い」を強く求められる",
            "リスク説明が口頭のみで、書面がない",
            "「他のクリニックに行かないでください」と言われる",
        ],
        "advice": (
            "迷ったら「一度持ち帰って検討します」と言って構いません。"
            "即日施術は2025年の医療法改正で規制が強化されました。"
            "良心的なクリニックは「考える時間」を与えてくれます。"
        ),
    }


def generate_post_surgery_checklist(procedure_category: str = "") -> dict:
    """術後経過チェックリストを生成する"""
    return {
        "title": "術後経過チェックリスト — 正常と異常の見分け方",
        "important_notice": (
            "このチェックリストは一般的な目安です。"
            "少しでも不安な場合は、必ず施術を受けたクリニックに連絡してください。"
        ),
        "normal_signs": [
            {"period": "術後1-3日", "symptoms": [
                "腫れ（ピーク。術後2-3日が最も腫れます）",
                "内出血（青紫色→黄色に変化しながら消えていきます）",
                "軽い痛み（処方された鎮痛剤でコントロール可能な程度）",
                "つっぱり感（特に切開系の施術）",
            ]},
            {"period": "術後1-2週間", "symptoms": [
                "腫れの徐々な減少",
                "内出血の黄色化と消退",
                "傷口周辺の軽いかゆみ（治癒のサイン）",
                "施術部位の一時的な感覚鈍麻",
            ]},
            {"period": "術後1-3ヶ月", "symptoms": [
                "最終的な仕上がりに近づく",
                "傷跡の赤みが徐々にフェード",
                "感覚の回復",
            ]},
        ],
        "warning_signs": [
            {
                "symptom": "39度以上の発熱が続く",
                "urgency": "当日中に連絡",
                "action": "施術クリニックに連絡。つながらない場合は救急外来へ",
            },
            {
                "symptom": "出血が止まらない",
                "urgency": "すぐに連絡",
                "action": "清潔なガーゼで圧迫しながらクリニックに連絡",
            },
            {
                "symptom": "術後3日を過ぎても痛みが増している",
                "urgency": "翌日中に連絡",
                "action": "感染の可能性。施術クリニックの診察を受ける",
            },
            {
                "symptom": "施術部位が異常に熱い・赤い",
                "urgency": "翌日中に連絡",
                "action": "感染や炎症の可能性。クリニックに連絡",
            },
            {
                "symptom": "左右差が2週間経っても明らかに大きい",
                "urgency": "次回診察で相談",
                "action": "腫れの引き方に左右差は普通だが、2週間以上続く場合は相談",
            },
        ],
        "emergency_contacts": [
            {"name": "施術を受けたクリニック", "note": "まず最初に連絡（診療時間外の緊急連絡先も確認しておく）"},
            {"name": "救急安心センター", "number": "#7119", "note": "救急車を呼ぶべきか判断に迷う場合"},
            {"name": "救急車", "number": "119", "note": "呼吸困難・意識障害・大量出血の場合"},
        ],
    }


def generate_consumer_center_prep(
    clinic_name: str = "",
    issue_description: str = "",
) -> dict:
    """消費者センター相談準備シートを生成する"""
    return {
        "title": "消費者センター相談準備シート",
        "hotline": {
            "number": "188",
            "name": "消費者ホットライン（いやや！）",
            "hours": "平日 9:00-17:00（地域により異なる）",
            "note": "188に電話すると、最寄りの消費生活センターにつながります",
        },
        "prepare_before_call": [
            "契約書（コピーでも可）",
            "領収書・クレジットカード明細",
            "施術前後の写真（あれば）",
            "クリニックとのやり取り記録（メール・LINE等）",
            "経緯を時系列でメモしたもの（下記テンプレート参照）",
        ],
        "timeline_template": {
            "title": "経緯メモテンプレート（時系列で記入）",
            "fields": [
                f"相談者: 【あなたの氏名・年齢・連絡先】",
                f"クリニック名: {clinic_name or '【クリニック名】'}",
                f"施術名: 【受けた施術名】",
                f"契約日: 【いつ契約したか】",
                f"施術日: 【いつ施術を受けたか】",
                f"問題発生日: 【いつ問題に気づいたか】",
                f"問題の内容: {issue_description or '【何が問題か具体的に】'}",
                f"クリニックの対応: 【クリニックにどう伝えて、どう対応されたか】",
                f"希望する解決: 【返金 / 無料再施術 / 損害賠償 / 謝罪 等】",
            ],
        },
        "what_to_expect": [
            "消費生活センターは中立的な立場で助言してくれます",
            "必要に応じてクリニックとの間に入って交渉（あっせん）してくれることもあります",
            "相談は無料です",
            "相談内容は「PIO-NET」に記録され、行政処分の判断材料にもなります",
            "弁護士への相談が必要な場合は、法テラス（0570-078374）を紹介されることもあります",
        ],
    }


def generate_clinic_comparison_sheet() -> dict:
    """クリニック比較シートを生成する"""
    return {
        "title": "クリニック比較シート — 3院比較がおすすめ",
        "advice": "最低3院のカウンセリングを受けてから判断することをおすすめします。",
        "comparison_axes": [
            {
                "category": "医師",
                "questions": [
                    "担当医の名前は？（指名できるか）",
                    "担当医の専門医資格は？",
                    "担当医の症例数は？（特にこの施術の経験）",
                    "カウンセラーと施術医は同じか？",
                ],
            },
            {
                "category": "料金",
                "questions": [
                    "提示された総額は？（税込み）",
                    "麻酔代は含まれているか？",
                    "術後の薬代は？",
                    "修正・再施術の場合の費用は？",
                    "分割払いの場合の金利は？",
                ],
            },
            {
                "category": "施術内容",
                "questions": [
                    "使用する製剤・材料は？",
                    "施術時間は？",
                    "想定されるダウンタイムは？",
                    "保証制度の内容と期間は？",
                ],
            },
            {
                "category": "クリニックの姿勢",
                "questions": [
                    "即日施術を勧められたか？（⚠ 要注意）",
                    "リスク説明は十分だったか？",
                    "「考える時間」を与えてくれたか？",
                    "書面での説明はあったか？",
                    "他の選択肢も提示してくれたか？",
                ],
            },
        ],
    }


# ==========================================
# ツール実行ディスパッチャー
# ==========================================


def execute_tool(tool_id: str, params: dict | None = None) -> dict | None:
    """
    指定されたツールを実行する。

    Args:
        tool_id: ツールID
        params: ツール固有のパラメータ

    Returns:
        ツールの実行結果、または不明なツールの場合None
    """
    if params is None:
        params = {}

    handlers = {
        "cooling_off": lambda: generate_cooling_off(**params),
        "medical_records": lambda: generate_medical_records_request(**params),
        "contract_check": lambda: generate_contract_checklist(),
        "price_check": lambda: {"title": "見積もり価格チェック", "note": "チャットで見積もり金額と施術名を教えてください。相場データと比較します。"},
        "post_surgery": lambda: generate_post_surgery_checklist(**params),
        "clinic_compare": lambda: generate_clinic_comparison_sheet(),
        "consumer_center": lambda: generate_consumer_center_prep(**params),
    }

    handler = handlers.get(tool_id)
    if handler:
        return handler()
    return None
