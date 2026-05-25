"""
AURA MVP — AURA Navi 施術データ移行スクリプト

data.js（JavaScript）から28施術データを抽出し、
来歴データ付きでSQLiteに投入する。

データソース: projects/aura-navi/js/data.js (v1.1)
施術数: 28（目元8 + 鼻6 + 肌8 + 輪郭6）
"""

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from ulid import ULID


def parse_data_js(filepath: str) -> list[dict]:
    """
    data.js（JavaScript配列）をパースしてPython辞書リストに変換

    Node.jsを使ってJavaScriptを直接評価し、JSON出力する。
    正規表現ベースのJS→JSON変換は文字列内のクォート問題で破綻するため、
    JavaScriptエンジンに任せるのが最も堅牢。
    """
    import subprocess
    import tempfile

    # Node.jsスクリプトを生成して実行
    node_script = f"""
const fs = require('fs');
const vm = require('vm');
const content = fs.readFileSync('{filepath}', 'utf-8');

// constをvarに変換してグローバルスコープで実行
const modified = content.replace(/^const\\s+/gm, 'var ');
vm.runInThisContext(modified);

// JSON出力
console.log(JSON.stringify(PROCEDURES));
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
        f.write(node_script)
        temp_path = f.name

    try:
        result = subprocess.run(
            ["node", temp_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Node.js実行エラー: {result.stderr}")

        procedures = json.loads(result.stdout)
    finally:
        Path(temp_path).unlink(missing_ok=True)

    return procedures


def convert_to_db_row(proc: dict) -> tuple:
    """
    Navi施術データをDBレコード形式に変換

    Naviのフラットなフィールドを、AURAのスキーマに合わせて
    構造化JSONに変換する。
    """
    now = datetime.now()

    # カテゴリラベルのマッピング
    category_labels = {
        "eye": "目元",
        "nose": "鼻",
        "skin": "肌",
        "contour": "輪郭・小顔",
    }

    # 価格データの構造化
    def parse_price_range(text: str) -> dict:
        """
        '7万〜15万円' → {'display': '7万〜15万円', 'min_price': 70000, 'max_price': 150000}
        '68,000円〜' → {'display': '68,000円〜', 'min_price': 68000}
        """
        if not text:
            return {}
        result = {"display": text}
        prices = []

        # Step 1: カンマ区切りの円表記（68,000円、200,000〜350,000円 等）
        yen_nums = re.findall(r"([\d,]+)\s*円", text)
        for n in yen_nums:
            try:
                val = int(n.replace(",", ""))
                if val >= 100:
                    prices.append(val)
            except ValueError:
                pass

        # Step 2: 「万」単位（7万、15万 等）
        if not prices:
            man_nums = re.findall(r"([\d,.]+)\s*万", text)
            for n in man_nums:
                try:
                    val = float(n.replace(",", ""))
                    prices.append(int(val * 10000))
                except ValueError:
                    pass

        # Step 3: 円が見つからなかった場合のカンマ区切り数値+万の混在処理
        # 例: '1回 5,190円〜' — Step 1 でカバー済み

        # real_price_min がJS側にある場合はそちらを使う（元データの信頼性が高い）
        rpm = proc.get("real_price_min")
        if rpm and isinstance(rpm, (int, float)) and rpm > 0:
            if not prices or min(prices) != rpm:
                prices.append(int(rpm))

        if prices:
            result["min_price"] = min(prices)
            result["max_price"] = max(prices)

        return result

    # duration_type → recommended_sessions の正規化
    recommended = proc.get("recommended_sessions")
    if isinstance(recommended, str):
        # "5〜10回（2〜4週間隔）" → 数値のみ抽出（最初の数値）
        nums = re.findall(r"(\d+)", recommended)
        recommended_int = int(nums[0]) if nums else None
    elif isinstance(recommended, int):
        recommended_int = recommended
    else:
        recommended_int = None

    return (
        str(ULID()),  # id
        proc.get("name", ""),  # name
        proc.get("category", ""),  # category
        category_labels.get(proc.get("category", ""), ""),  # category_label
        "",  # description（将来的に追加）
        proc.get("invasiveness", "moderate"),  # invasiveness
        proc.get("duration_type", "one-time"),  # duration_type
        proc.get("duration", ""),  # duration
        recommended_int,  # recommended_sessions
        json.dumps(proc.get("matches_concern", []), ensure_ascii=False),  # matches_concern
        # 価格データ
        json.dumps(parse_price_range(proc.get("advertised_price", "")), ensure_ascii=False),
        json.dumps(parse_price_range(proc.get("real_price_range", "")), ensure_ascii=False),
        proc.get("price_gap_note", ""),  # price_gap_note
        json.dumps(proc.get("hidden_costs", []), ensure_ascii=False),  # hidden_costs
        # ダウンタイム
        proc.get("downtime_official", ""),  # downtime_official
        proc.get("downtime_real", ""),  # downtime_real
        json.dumps([], ensure_ascii=False),  # recovery_phases（AURA Naviの術後ケアデータから後日マージ）
        # リスク・適性
        json.dumps(proc.get("risks", []), ensure_ascii=False),  # risks
        json.dumps(proc.get("good_for", []), ensure_ascii=False),  # suitable_for
        json.dumps(proc.get("not_good_for", []), ensure_ascii=False),  # not_suitable_for
        json.dumps(proc.get("counseling_questions", []), ensure_ascii=False),  # counseling_questions
        # データ来歴
        "navi",  # source
        "1.1",  # source_version（AURA Navi v1.1）
        now.isoformat(),  # fetched_at
        now.isoformat(),  # verified_at（移行時に検証済み扱い）
        1.0,  # confidence（Navi作成時に複数ソースで検証済み）
        now.isoformat(),  # created_at
        now.isoformat(),  # updated_at
    )


def main():
    """メイン実行"""
    data_js_path = Path(__file__).parent.parent.parent.parent.parent / "aura-navi" / "js" / "data.js"
    db_path = Path(__file__).parent.parent.parent / "data" / "aura.db"

    print(f"📖 data.js読み込み: {data_js_path}")
    procedures = parse_data_js(str(data_js_path))
    print(f"✅ {len(procedures)}施術をパース完了")

    # カテゴリ別集計
    from collections import Counter
    cats = Counter(p.get("category", "unknown") for p in procedures)
    for cat, count in sorted(cats.items()):
        label = {"eye": "目元", "nose": "鼻", "skin": "肌", "contour": "輪郭"}.get(cat, cat)
        print(f"   {label}: {count}施術")

    # DB投入
    print(f"\n💾 DB投入: {db_path}")
    conn = sqlite3.connect(str(db_path))

    rows = [convert_to_db_row(p) for p in procedures]

    conn.executemany("""
        INSERT OR REPLACE INTO procedures (
            id, name, category, category_label, description,
            invasiveness, duration_type, duration, recommended_sessions, matches_concern,
            advertised_price, real_price, price_gap_note, hidden_costs,
            downtime_official, downtime_real, recovery_phases,
            risks, suitable_for, not_suitable_for, counseling_questions,
            source, source_version, fetched_at, verified_at, confidence,
            created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, rows)

    conn.commit()

    # 検証
    total = conn.execute("SELECT COUNT(*) FROM procedures").fetchone()[0]
    categories = conn.execute(
        "SELECT category_label, COUNT(*) FROM procedures GROUP BY category_label ORDER BY COUNT(*) DESC"
    ).fetchall()

    # 充填率チェック
    filled_check = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN advertised_price != '' AND advertised_price != '{}' THEN 1 ELSE 0 END) as has_adv_price,
            SUM(CASE WHEN real_price != '' AND real_price != '{}' THEN 1 ELSE 0 END) as has_real_price,
            SUM(CASE WHEN price_gap_note != '' THEN 1 ELSE 0 END) as has_gap_note,
            SUM(CASE WHEN risks != '[]' THEN 1 ELSE 0 END) as has_risks,
            SUM(CASE WHEN counseling_questions != '[]' THEN 1 ELSE 0 END) as has_questions,
            SUM(CASE WHEN downtime_real != '' THEN 1 ELSE 0 END) as has_dt_real
        FROM procedures
    """).fetchone()

    conn.close()

    print(f"\n✅ DB投入完了: {total}施術")
    for label, count in categories:
        print(f"   {label}: {count}施術")

    print(f"\n📊 データ品質チェック:")
    fields = ["広告価格", "実勢価格", "価格ギャップ注意", "リスク情報", "質問リスト", "リアルDT"]
    values = filled_check[1:]
    for field, val in zip(fields, values):
        pct = (val / filled_check[0]) * 100
        status = "✅" if pct == 100 else "⚠️"
        print(f"   {status} {field}: {val}/{filled_check[0]} ({pct:.0f}%)")


if __name__ == "__main__":
    main()
