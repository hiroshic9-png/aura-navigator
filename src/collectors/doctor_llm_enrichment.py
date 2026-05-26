"""
医師データLLM強化スクリプト

既存のスクレイプキャッシュ（doctor.html）をClaude APIで再解析し、
ルールベース抽出では取りきれなかった資格・専門分野・経験年数を補完する。

戦略:
- board_certifications が空（'[]'）の医師を対象
- スクレイプキャッシュのdoctor.htmlからHTMLテキストを抽出
- Claude API（haiku）でJSON構造化データに変換
- 既存レコードをUPDATE（既存値は上書きしない、空値のみ補完）

使い方:
  uv run python -m src.collectors.doctor_llm_enrichment --dry-run --limit 5
  uv run python -m src.collectors.doctor_llm_enrichment --execute --limit 50
  uv run python -m src.collectors.doctor_llm_enrichment --execute  # 全件
"""

import argparse
import json
import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

# ============================================================
# 定数・設定
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "aura.db"
SCRAPE_CACHE_DIR = PROJECT_ROOT / "data" / "scrape_cache"

# Claude API設定
CLAUDE_MODEL = "claude-sonnet-4-20250514"
MAX_HTML_CHARS = 8000  # 入力HTMLの最大文字数（コスト制御）
RATE_LIMIT_SECONDS = 0.5  # API呼び出し間隔

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ============================================================
# データクラス
# ============================================================


@dataclass
class DoctorEnrichment:
    """LLMで抽出した医師情報の補完データ"""
    doctor_id: str
    name: str
    specialties: list[str] | None = None
    board_certifications: list[str] | None = None
    experience_years: int | None = None
    graduation_university: str | None = None


# ============================================================
# HTMLテキスト抽出
# ============================================================


def _extract_doctor_section(html: str, doctor_name: str) -> str:
    """
    HTMLから指定医師名の周辺テキストを抽出する。

    doctor.html全体ではなく、対象医師名の前後のテキストだけを
    切り出すことでトークン数を削減する。
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")

    # script/style/nav/footer/headerを除去
    for tag in soup.find_all(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()

    full_text = soup.get_text(separator="\n", strip=True)

    # 医師名の位置を検索
    name_pos = full_text.find(doctor_name)
    if name_pos == -1:
        # 姓のみで検索（名前の区切りが異なる場合）
        surname = doctor_name[:2] if len(doctor_name) >= 2 else doctor_name
        name_pos = full_text.find(surname)
        if name_pos == -1:
            # 見つからない場合は全体テキストの先頭を返す
            return full_text[:MAX_HTML_CHARS]

    # 医師名の前後を切り出し（前200文字〜後3000文字）
    start = max(0, name_pos - 200)
    end = min(len(full_text), name_pos + 3000)
    section = full_text[start:end]

    return section[:MAX_HTML_CHARS]


def _get_cache_clinic_id_map(conn: sqlite3.Connection) -> dict[str, str]:
    """
    doctors.clinic_id → スクレイプキャッシュディレクトリの対応マップを構築。

    Returns:
        {clinic_id: cache_dir_path} の辞書
    """
    cache_map = {}
    if SCRAPE_CACHE_DIR.exists():
        for cache_dir in SCRAPE_CACHE_DIR.iterdir():
            if cache_dir.is_dir() and (cache_dir / "doctor.html").exists():
                cache_map[cache_dir.name] = str(cache_dir / "doctor.html")
    return cache_map


# ============================================================
# Claude API呼び出し
# ============================================================


def _create_extraction_prompt(doctor_name: str, clinic_name: str, html_text: str) -> str:
    """LLMに送るプロンプトを構築する"""
    return f"""以下はクリニック「{clinic_name}」の医師紹介ページから抽出したテキストです。
医師「{doctor_name}」に関する情報を抽出してください。

## 抽出ルール
- 該当医師の情報のみを抽出（他の医師の情報は含めない）
- テキストに明示的に記載されている情報のみ抽出（推測しない）
- 見つからない項目はnullにする

## 出力形式（JSONのみ、他のテキストは不要）
```json
{{
  "specialties": ["美容外科", "形成外科"],
  "board_certifications": ["日本形成外科学会専門医", "日本美容外科学会(JSAPS)専門医"],
  "experience_years": 15,
  "graduation_university": "東京大学医学部"
}}
```

## specialtiesの候補
美容外科, 美容皮膚科, 形成外科, 皮膚科, 眼科, 耳鼻咽喉科, 整形外科, 外科, 内科, 麻酔科

## board_certificationsの例
日本形成外科学会専門医, 日本美容外科学会(JSAPS)専門医, 日本美容外科学会(JSAS)専門医,
日本皮膚科学会専門医, 日本外科学会専門医, 日本麻酔科学会専門医, 日本眼科学会専門医,
日本抗加齢医学会専門医, 日本レーザー医学会専門医, ボトックスビスタ認定医, ジュビダームビスタ認定医

## experience_years
卒業年から逆算しても可。「2005年卒」なら2026-2005=21年

## テキスト
{html_text}"""


def _call_claude(prompt: str, api_key: str) -> dict | None:
    """
    Claude APIを呼び出してJSON応答を取得する。

    Returns:
        パースされたJSON辞書、またはエラー時None
    """
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )

        # レスポンステキストからJSONを抽出
        text = response.content[0].text
        # ```json ... ``` ブロックを抽出
        json_match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # JSONブロックがない場合、テキスト全体をパース試行
            json_str = text.strip()

        result = json.loads(json_str)
        return result

    except json.JSONDecodeError as e:
        logger.warning("JSONパース失敗: %s", e)
        return None
    except Exception as e:
        logger.warning("Claude API呼び出し失敗: %s", e)
        return None


# ============================================================
# DB操作
# ============================================================


def _get_target_doctors(conn: sqlite3.Connection, limit: int | None = None) -> list[tuple]:
    """
    強化対象の医師を取得する。

    対象条件:
    - board_certificationsが空（NULLまたは'[]'）
    - またはspecialtiesが空

    Returns:
        (id, clinic_id, name, title, specialties, board_certifications, experience_years) のリスト
    """
    query = """
        SELECT d.id, d.clinic_id, d.name, d.title, d.specialties,
               d.board_certifications, d.experience_years
        FROM doctors d
        WHERE (d.board_certifications IS NULL OR d.board_certifications = '[]')
           OR (d.specialties IS NULL OR d.specialties = '[]')
           OR d.experience_years IS NULL
        ORDER BY d.clinic_id
    """
    if limit:
        query += f" LIMIT {limit}"

    cursor = conn.execute(query)
    return cursor.fetchall()


def _get_clinic_name(conn: sqlite3.Connection, clinic_id: str) -> str:
    """クリニック名を取得する"""
    cursor = conn.execute("SELECT name FROM clinics WHERE id = ?", (clinic_id,))
    row = cursor.fetchone()
    return row[0] if row else "不明"


def _update_doctor(
    conn: sqlite3.Connection,
    doctor_id: str,
    enrichment: dict,
    existing_specialties: str | None,
    existing_certifications: str | None,
    existing_experience: int | None,
) -> bool:
    """
    医師レコードを補完更新する。

    既存値は上書きしない（空値のみ補完）。

    Returns:
        更新があったかどうか
    """
    updates = []
    params = []

    # specialties の補完
    if (not existing_specialties or existing_specialties == "[]") and enrichment.get("specialties"):
        new_specs = enrichment["specialties"]
        if isinstance(new_specs, list) and len(new_specs) > 0:
            updates.append("specialties = ?")
            params.append(json.dumps(new_specs, ensure_ascii=False))

    # board_certifications の補完
    if (not existing_certifications or existing_certifications == "[]") and enrichment.get("board_certifications"):
        new_certs = enrichment["board_certifications"]
        if isinstance(new_certs, list) and len(new_certs) > 0:
            updates.append("board_certifications = ?")
            params.append(json.dumps(new_certs, ensure_ascii=False))

    # experience_years の補完
    if existing_experience is None and enrichment.get("experience_years"):
        exp = enrichment["experience_years"]
        if isinstance(exp, (int, float)) and 1 <= exp <= 60:
            updates.append("experience_years = ?")
            params.append(int(exp))

    if not updates:
        return False

    # source を llm_enriched に更新（トレーサビリティ）
    updates.append("source = 'llm_enriched'")

    params.append(doctor_id)
    sql = f"UPDATE doctors SET {', '.join(updates)} WHERE id = ?"
    conn.execute(sql, params)
    return True


# ============================================================
# メイン処理
# ============================================================


def run(dry_run: bool = True, limit: int | None = None) -> None:
    """医師データLLM強化のメイン処理"""
    # APIキー確認
    api_key = os.environ.get("AURA_ANTHROPIC_API_KEY", "")
    if not api_key:
        # .envから読み込み
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("AURA_ANTHROPIC_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
                    break

    if not api_key:
        logger.error("APIキーが設定されていません。.envにAURA_ANTHROPIC_API_KEYを設定してください。")
        return

    # モック判定
    use_mock = api_key == "mock" or api_key.startswith("test-")

    conn = sqlite3.connect(str(DB_PATH))
    try:
        # キャッシュマップ構築
        cache_map = _get_cache_clinic_id_map(conn)
        logger.info("スクレイプキャッシュ: %d クリニック分のdoctor.html", len(cache_map))

        # 対象医師取得
        targets = _get_target_doctors(conn, limit)
        logger.info("強化対象: %d名", len(targets))

        if not targets:
            logger.info("強化対象の医師がありません。")
            return

        # 統計カウンター
        stats = {
            "total": len(targets),
            "processed": 0,
            "updated": 0,
            "skipped_no_cache": 0,
            "skipped_no_text": 0,
            "api_errors": 0,
        }

        # 処理ループ
        prev_clinic_id = None
        clinic_name = ""

        for row in targets:
            doctor_id, clinic_id, name, title, existing_specs, existing_certs, existing_exp = row

            # キャッシュの存在確認
            if clinic_id not in cache_map:
                stats["skipped_no_cache"] += 1
                continue

            # クリニック名取得（キャッシュ）
            if clinic_id != prev_clinic_id:
                clinic_name = _get_clinic_name(conn, clinic_id)
                prev_clinic_id = clinic_id

            # doctor.htmlを読み込み
            doctor_html_path = cache_map[clinic_id]
            try:
                html_content = Path(doctor_html_path).read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                logger.warning("HTML読み込み失敗: %s — %s", doctor_html_path, e)
                stats["skipped_no_text"] += 1
                continue

            # 対象医師名の周辺テキストを切り出し
            section_text = _extract_doctor_section(html_content, name)
            if not section_text or len(section_text) < 50:
                stats["skipped_no_text"] += 1
                continue

            # LLM呼び出し
            prompt = _create_extraction_prompt(name, clinic_name, section_text)

            if dry_run:
                logger.info("  [DRY-RUN] %s（%s）— テキスト%d文字を解析予定", name, title or "?", len(section_text))
                # dry-runでも最初の3件はAPIを実際に叩いて結果を確認
                if stats["processed"] < 3 and not use_mock:
                    result = _call_claude(prompt, api_key)
                    if result:
                        logger.info("    → LLM結果: %s", json.dumps(result, ensure_ascii=False)[:200])
                    time.sleep(RATE_LIMIT_SECONDS)
                stats["processed"] += 1
                continue

            # 実行モード
            if use_mock:
                # モック応答
                result = {
                    "specialties": ["美容外科", "形成外科"],
                    "board_certifications": [],
                    "experience_years": None,
                    "graduation_university": None,
                }
            else:
                result = _call_claude(prompt, api_key)
                time.sleep(RATE_LIMIT_SECONDS)

            if not result:
                stats["api_errors"] += 1
                logger.warning("  ✗ %s — API応答なし", name)
                continue

            stats["processed"] += 1

            # DB更新
            updated = _update_doctor(
                conn, doctor_id, result,
                existing_specs, existing_certs, existing_exp,
            )

            if updated:
                stats["updated"] += 1
                certs_str = json.dumps(result.get("board_certifications", []), ensure_ascii=False)
                logger.info("  ✓ %s（%s）— certs=%s, exp=%s",
                           name, title or "?", certs_str[:60], result.get("experience_years"))
            else:
                logger.info("  — %s — 新規情報なし", name)

            # 50件ごとにコミット
            if stats["processed"] % 50 == 0:
                conn.commit()
                logger.info("--- 進捗: %d/%d 処理, %d 更新 ---",
                           stats["processed"], stats["total"], stats["updated"])

        # 最終コミット
        if not dry_run:
            conn.commit()

        # 結果サマリー
        logger.info("=" * 50)
        logger.info("完了サマリー:")
        logger.info("  対象: %d名", stats["total"])
        logger.info("  処理: %d名", stats["processed"])
        logger.info("  更新: %d名", stats["updated"])
        logger.info("  キャッシュなし: %d名", stats["skipped_no_cache"])
        logger.info("  テキスト不足: %d名", stats["skipped_no_text"])
        logger.info("  APIエラー: %d名", stats["api_errors"])
        if dry_run:
            logger.info("  ⚠ DRY-RUNモード — DBは更新されていません")

    finally:
        conn.close()


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="医師データLLM強化")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="実行前確認（DBを変更しない）")
    group.add_argument("--execute", action="store_true", help="実行（DBを更新する）")
    parser.add_argument("--limit", type=int, default=None, help="処理件数の上限")

    args = parser.parse_args()
    run(dry_run=args.dry_run, limit=args.limit)
