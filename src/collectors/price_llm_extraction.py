"""
AURA MVP — LLMベースの施術メニュー価格抽出

スクレイプキャッシュのmenu.htmlからClaude APIで価格データを抽出し、
clinic_proceduresテーブルの価格フィールドを更新する。

ターゲット:
- 268件のmenu.htmlキャッシュ
- 28施術カテゴリとの照合
- price_advertised（広告価格）とprice_display（表示用文字列）を更新
"""

import asyncio
import json
import logging
import os
import re
import sqlite3
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# パス（プロジェクトルートから解決）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "aura.db"
CACHE_DIR = PROJECT_ROOT / "data" / "scrape_cache"


def get_procedures() -> list[dict]:
    """施術マスターを取得"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, name, category FROM procedures ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_clinics_with_cache() -> list[dict]:
    """menu.htmlキャッシュがあるクリニックを取得"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # キャッシュディレクトリをスキャン
    cache_clinic_ids = set()
    if CACHE_DIR.exists():
        for d in CACHE_DIR.iterdir():
            if d.is_dir() and (d / "menu.html").exists():
                cache_clinic_ids.add(d.name)

    if not cache_clinic_ids:
        conn.close()
        return []

    # DBのクリニックと照合
    placeholders = ",".join(["?"] * len(cache_clinic_ids))
    rows = conn.execute(
        f"SELECT id, name FROM clinics WHERE id IN ({placeholders})",
        list(cache_clinic_ids),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def extract_text_from_html(html: str, max_chars: int = 15000) -> str:
    """HTMLからテキストを抽出（LLMに渡す用）"""
    # scriptとstyleを除去
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # タグを除去
    text = re.sub(r"<[^>]+>", " ", html)
    # 連続空白を圧縮
    text = re.sub(r"\s+", " ", text).strip()
    # 長さ制限
    if len(text) > max_chars:
        text = text[:max_chars] + "..."
    return text


def build_extraction_prompt(clinic_name: str, menu_text: str, procedures: list[dict]) -> str:
    """価格抽出用のプロンプトを構築"""
    proc_list = "\n".join([f"- {p['name']} (ID: {p['id']})" for p in procedures])

    return f"""以下は「{clinic_name}」のメニューページから抽出したテキストです。
このテキストから施術の価格情報を読み取り、JSONで返してください。

## 抽出対象の施術リスト
{proc_list}

## ルール
1. 上記リストに含まれる施術に対応するメニューの最低価格を抽出してください
2. 施術名が完全一致しなくても、同じ施術と判断できれば対応させてください（例: 「埋没法」→「二重埋没法」）
3. 価格は税込の数値（円）で返してください
4. 価格が見つからない施術は含めないでください
5. 「〜円」「○万円」「¥xxx,xxx」など様々な表記に対応してください
6. キャンペーン価格ではなく、通常価格を抽出してください（ただしキャンペーン価格しかなければそれを使用）

## 出力形式（JSON配列）
```json
[
  {{"procedure_id": "...", "price": 29800, "price_display": "29,800円〜", "notes": "片目の価格"}},
  ...
]
```

## メニューテキスト
{menu_text}"""


async def extract_prices_with_llm(clinic_name: str, menu_text: str, procedures: list[dict]) -> list[dict]:
    """Claude APIで価格を抽出"""
    try:
        import anthropic
    except ImportError:
        logger.error("anthropicライブラリが未インストール")
        return []

    api_key = os.environ.get("AURA_ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.error("AURA_ANTHROPIC_API_KEY が未設定")
        return []

    client = anthropic.Anthropic(api_key=api_key)
    prompt = build_extraction_prompt(clinic_name, menu_text, procedures)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )

        text = response.content[0].text

        # JSONを抽出
        json_match = re.search(r"\[.*\]", text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        else:
            logger.warning(f"{clinic_name}: JSONが見つからない")
            return []

    except Exception as e:
        logger.error(f"{clinic_name}: API呼び出しエラー: {e}")
        return []


def update_prices(clinic_id: str, prices: list[dict]) -> int:
    """抽出した価格をDBに反映"""
    conn = sqlite3.connect(DB_PATH)
    updated = 0

    for p in prices:
        proc_id = p.get("procedure_id", "")
        price = p.get("price")
        display = p.get("price_display", "")

        if not proc_id or not price:
            continue

        # 既存レコードを更新（価格が未設定のもののみ）
        cursor = conn.execute(
            """UPDATE clinic_procedures
               SET price_advertised = ?, price_display = ?
               WHERE clinic_id = ? AND procedure_id = ?
               AND (price_advertised IS NULL OR price_advertised = 0)""",
            (price, display, clinic_id, proc_id),
        )
        if cursor.rowcount > 0:
            updated += cursor.rowcount

    conn.commit()
    conn.close()
    return updated


async def main():
    """メイン処理"""
    procedures = get_procedures()
    clinics = get_clinics_with_cache()

    logger.info(f"施術マスター: {len(procedures)}件")
    logger.info(f"menu.htmlキャッシュ付きクリニック: {len(clinics)}件")

    if not clinics:
        logger.info("処理対象なし")
        return

    total_updated = 0
    total_extracted = 0
    errors = 0

    for i, clinic in enumerate(clinics):
        clinic_id = clinic["id"]
        clinic_name = clinic["name"]

        # menu.html読み込み
        menu_path = CACHE_DIR / clinic_id / "menu.html"
        if not menu_path.exists():
            continue

        html = menu_path.read_text(encoding="utf-8", errors="replace")
        menu_text = extract_text_from_html(html)

        if len(menu_text) < 100:
            logger.info(f"[{i+1}/{len(clinics)}] {clinic_name}: テキストが短すぎる、スキップ")
            continue

        logger.info(f"[{i+1}/{len(clinics)}] {clinic_name} ({len(menu_text)}文字)")

        # LLM抽出
        prices = await extract_prices_with_llm(clinic_name, menu_text, procedures)

        if prices:
            updated = update_prices(clinic_id, prices)
            total_extracted += len(prices)
            total_updated += updated
            logger.info(f"  → {len(prices)}件抽出, {updated}件更新")
        else:
            errors += 1
            logger.info(f"  → 抽出失敗")

        # レート制限（1秒間隔）
        await asyncio.sleep(1.0)

    logger.info(f"\n=== 完了 ===")
    logger.info(f"処理: {len(clinics)}クリニック")
    logger.info(f"抽出: {total_extracted}件")
    logger.info(f"DB更新: {total_updated}件")
    logger.info(f"エラー: {errors}件")

    # 更新後の統計
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("""
        SELECT
          COUNT(*) as total,
          SUM(CASE WHEN price_advertised > 0 THEN 1 ELSE 0 END) as has_price,
          ROUND(100.0 * SUM(CASE WHEN price_advertised > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) as pct
        FROM clinic_procedures
    """).fetchone()
    conn.close()
    logger.info(f"価格充填率: {row[1]}/{row[0]} ({row[2]}%)")


if __name__ == "__main__":
    asyncio.run(main())
