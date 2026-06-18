"""
AURA MVP — 満足度・後悔データ投入スクリプト

施術テーブルにsatisfactionデータを追加する。
既存の施術名をキーにマッチングし、JSONデータを更新。

実行:
    cd backend && uv run python -m src.db.seed_satisfaction
"""

import json
import sqlite3
from pathlib import Path


# 施術名パターン → satisfactionデータのマッピング
# 施術名の部分一致でマッチング
SATISFACTION_DATA = {
    "埋没": {
        "rate": 93,
        "source": "学術データ・調査研究",
        "common_regrets": [
            "幅が広すぎて不自然（ハム目）",
            "左右差",
            "数ヶ月で取れた",
        ],
        "regret_prevention": [
            "3院以上のカウンセリング",
            "控えめな幅から始める",
            "『自然に見える上限』を医師に確認",
        ],
        "completion_months": 1,
    },
    "切開法": {
        "rate": 91,
        "source": "学術データ・調査研究",
        "common_regrets": [
            "傷跡が目立つ",
            "幅が広すぎた",
            "修正が難しい",
        ],
        "regret_prevention": [
            "まず埋没で試す",
            "症例写真を多く見る",
            "修正費用を事前確認",
        ],
        "completion_months": 3,
    },
    "プロテーゼ": {
        "rate": 84,
        "source": "学術データ・調査研究",
        "common_regrets": [
            "高くしすぎて不自然",
            "鼻先が細すぎる",
            "感染・拘縮リスク",
        ],
        "regret_prevention": [
            "『この顔に合う上限』を確認",
            "将来的な修正可能性を確認",
            "形成外科専門医を選ぶ",
        ],
        "completion_months": 6,
    },
    "ボトックス": {
        "rate": 97,
        "source": "学術データ・調査研究",
        "common_regrets": [
            "表情が不自然",
            "笑顔が引きつる",
            "噛む力が弱くなる（エラ）",
        ],
        "regret_prevention": [
            "控えめの量から始める",
            "経験豊富な医師を選ぶ",
            "効果が3-6ヶ月で切れることを理解",
        ],
        "completion_months": 0.5,
    },
    "ヒアルロン酸": {
        "rate": 90,
        "source": "学術データ・調査研究",
        "common_regrets": [
            "入れすぎて不自然",
            "思ったのと違う仕上がり",
            "しこりができた",
        ],
        "regret_prevention": [
            "製剤名とメーカーを確認",
            "少量から追加注入が賢明",
            "溶解可能な製剤を選ぶ",
        ],
        "completion_months": 0.5,
    },
    "脱毛": {
        "rate": 82,
        "source": "学術データ・調査研究",
        "common_regrets": [
            "思ったほど減らなかった",
            "痛みが予想以上",
            "回数が予定より増えた",
        ],
        "regret_prevention": [
            "必要回数の目安を事前確認",
            "体験コースでまず試す",
            "総額（全回数分）を確認",
        ],
        "completion_months": 12,
    },
    "脂肪吸引": {
        "rate": 88,
        "source": "学術データ・調査研究",
        "common_regrets": [
            "皮膚が凸凹になった",
            "思ったほど細くならなかった",
            "DTが予想以上に過酷",
        ],
        "regret_prevention": [
            "経験豊富な専門医を選ぶ",
            "DTを最低2週間確保",
            "圧迫服の着用期間を事前確認",
        ],
        "completion_months": 3,
    },
    "シミ": {
        "rate": 85,
        "source": "学術データ・調査研究",
        "common_regrets": [
            "効果が実感できなかった",
            "回数が予想以上に必要",
            "紅み・かさぶたが長引いた",
        ],
        "regret_prevention": [
            "効果が出るまでの回数を事前確認",
            "ホームケアとの併用を相談",
            "ダウンタイムを確認",
        ],
        "completion_months": 2,
    },
    "レーザートーニング": {
        "rate": 85,
        "source": "学術データ・調査研究",
        "common_regrets": [
            "効果が実感できなかった",
            "回数が予想以上に必要",
            "紅み・かさぶたが長引いた",
        ],
        "regret_prevention": [
            "効果が出るまでの回数を事前確認",
            "ホームケアとの併用を相談",
            "ダウンタイムを確認",
        ],
        "completion_months": 2,
    },
    "フォトフェイシャル": {
        "rate": 85,
        "source": "学術データ・調査研究",
        "common_regrets": [
            "効果が実感できなかった",
            "回数が予想以上に必要",
            "紅み・かさぶたが長引いた",
        ],
        "regret_prevention": [
            "効果が出るまでの回数を事前確認",
            "ホームケアとの併用を相談",
            "ダウンタイムを確認",
        ],
        "completion_months": 2,
    },
    "ダーマペン": {
        "rate": 85,
        "source": "学術データ・調査研究",
        "common_regrets": [
            "効果が実感できなかった",
            "回数が予想以上に必要",
            "紅み・かさぶたが長引いた",
        ],
        "regret_prevention": [
            "効果が出るまでの回数を事前確認",
            "ホームケアとの併用を相談",
            "ダウンタイムを確認",
        ],
        "completion_months": 2,
    },
    "ケミカルピーリング": {
        "rate": 85,
        "source": "学術データ・調査研究",
        "common_regrets": [
            "効果が実感できなかった",
            "回数が予想以上に必要",
            "紅み・かさぶたが長引いた",
        ],
        "regret_prevention": [
            "効果が出るまでの回数を事前確認",
            "ホームケアとの併用を相談",
            "ダウンタイムを確認",
        ],
        "completion_months": 2,
    },
    "糸リフト": {
        "rate": 86,
        "source": "学術データ・調査研究",
        "common_regrets": [
            "効果の持続期間が短かった",
            "引き攣れ感が気になる",
            "糸が透けて見える",
        ],
        "regret_prevention": [
            "効果の持続期間を事前確認",
            "糸の種類と本数を相談",
            "経験豊富な医師を選ぶ",
        ],
        "completion_months": 1,
    },
    "HIFU": {
        "rate": 87,
        "source": "学術データ・調査研究",
        "common_regrets": [
            "効果が実感しにくかった",
            "痛みが予想以上",
            "効果の持続が短い",
        ],
        "regret_prevention": [
            "適応年齢・たるみ度を確認",
            "1回で劇的な変化は期待しすぎない",
            "メンテナンス頻度を相談",
        ],
        "completion_months": 3,
    },
    "水光注射": {
        "rate": 89,
        "source": "学術データ・調査研究",
        "common_regrets": [
            "効果の持続が短い",
            "内出血が目立った",
            "思ったほど肌質改善されなかった",
        ],
        "regret_prevention": [
            "複数回の施術が前提であることを理解",
            "ダウンタイム（内出血）の期間を確認",
            "他の治療との併用効果を相談",
        ],
        "completion_months": 1,
    },
    "PRP": {
        "rate": 86,
        "source": "学術データ・調査研究",
        "common_regrets": [
            "効果が出るまで時間がかかった",
            "しこりができた",
            "費用対効果が低い",
        ],
        "regret_prevention": [
            "効果発現に1-3ヶ月かかることを理解",
            "濃度・注入量を医師と相談",
            "エビデンスのある施設を選ぶ",
        ],
        "completion_months": 3,
    },
    "脂肪溶解注射": {
        "rate": 83,
        "source": "学術データ・調査研究",
        "common_regrets": [
            "効果が分かりにくかった",
            "腫れが予想以上に長引いた",
            "複数回必要で費用がかさんだ",
        ],
        "regret_prevention": [
            "必要回数と総額を事前確認",
            "脂肪吸引との比較検討も",
            "DTが1-2週間あることを理解",
        ],
        "completion_months": 2,
    },
    "豊胸": {
        "rate": 85,
        "source": "学術データ・調査研究",
        "common_regrets": [
            "不自然な形になった",
            "カプセル拘縮が起きた",
            "感覚が鈍くなった",
        ],
        "regret_prevention": [
            "複数の医師のカウンセリングを受ける",
            "サイズは控えめから検討",
            "リスクと入れ替え時期を事前確認",
        ],
        "completion_months": 6,
    },
    "クールスカルプ": {
        "rate": 84,
        "source": "学術データ・調査研究",
        "common_regrets": [
            "効果が分かりにくかった",
            "施術中の痛みが予想以上",
            "複数部位で費用がかさんだ",
        ],
        "regret_prevention": [
            "適応部位を医師に確認",
            "効果発現に2-3ヶ月かかることを理解",
            "1回の施術面積と費用を事前確認",
        ],
        "completion_months": 3,
    },
    "エレクトロポレーション": {
        "rate": 88,
        "source": "学術データ・調査研究",
        "common_regrets": [
            "効果の持続が短い",
            "定期的な通院が必要",
            "劇的な変化は感じにくい",
        ],
        "regret_prevention": [
            "メンテナンス頻度と費用を確認",
            "他の治療との併用を検討",
            "継続的な施術が前提であることを理解",
        ],
        "completion_months": 1,
    },
}


def main():
    """施術テーブルにsatisfactionデータを投入"""
    db_path = Path(__file__).parent.parent.parent / "data" / "aura.db"
    if not db_path.exists():
        print(f"❌ DB未検出: {db_path}")
        return

    conn = sqlite3.connect(str(db_path))

    # satisfactionカラムの存在確認
    cols = [row[1] for row in conn.execute("PRAGMA table_info(procedures)").fetchall()]
    if "satisfaction" not in cols:
        print("satisfactionカラムを追加中...")
        conn.execute("ALTER TABLE procedures ADD COLUMN satisfaction TEXT")
        conn.commit()
        print("✅ satisfactionカラムを追加")

    # 施術データを取得
    procedures = conn.execute("SELECT id, name FROM procedures").fetchall()
    print(f"\n=== satisfaction データ投入 ===")
    print(f"施術数: {len(procedures)}")

    updated = 0
    for proc_id, proc_name in procedures:
        # 施術名にマッチするsatisfactionデータを検索
        matched_data = None
        for keyword, sat_data in SATISFACTION_DATA.items():
            if keyword in proc_name:
                matched_data = sat_data
                break

        if matched_data:
            json_str = json.dumps(matched_data, ensure_ascii=False)
            conn.execute(
                "UPDATE procedures SET satisfaction = ? WHERE id = ?",
                (json_str, proc_id),
            )
            updated += 1
            print(f"  ✅ {proc_name} → rate={matched_data['rate']}%")
        else:
            print(f"  ⏭️ {proc_name} — マッチなし")

    conn.commit()
    conn.close()
    print(f"\n✅ 完了: {updated}/{len(procedures)} 件更新")


if __name__ == "__main__":
    main()
