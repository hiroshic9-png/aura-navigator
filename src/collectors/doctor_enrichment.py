"""
クリニック公式サイトからの医師情報抽出スクリプト（C-1）

クリニックのウェブサイトを解析し、医師の名前・肩書き・専門分野・
資格情報を抽出して doctors テーブルに保存する。

抽出ロジック:
- リンクテキストから医師情報ページを自動検出
- ルールベースで「院長」「副院長」等の肩書き、漢字名、資格を検出
- 「経歴」「略歴」セクションから経歴情報を抽出

キャッシュ戦略:
- Phase Bのスクレイプキャッシュ（data/scrape_cache/{clinic_id}/）を優先利用
- キャッシュがない場合はhttpxで直接取得（フォールバック）

使い方:
  uv run python -m src.collectors.doctor_enrichment --dry-run --limit 3
  uv run python -m src.collectors.doctor_enrichment --execute --limit 10
"""

import argparse
import json
import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from ulid import ULID

# ============================================================
# 定数・設定
# ============================================================

# プロジェクトルート
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "aura.db"
SCRAPE_CACHE_DIR = PROJECT_ROOT / "data" / "scrape_cache"

# レート制限（秒/リクエスト）
RATE_LIMIT_SECONDS = 3.0

# HTTPクライアント設定
HTTP_TIMEOUT = 15.0
USER_AGENT = (
    "Mozilla/5.0 (compatible; AURA-MVP/0.1; "
    "+https://github.com/aura-mvp) medical-info-research"
)

# 医師情報ページ検出キーワード
DOCTOR_PAGE_KEYWORDS = [
    "ドクター紹介",
    "ドクター",
    "医師紹介",
    "医師一覧",
    "スタッフ紹介",
    "スタッフ",
    "院長紹介",
    "院長挨拶",
    "院長あいさつ",
    "院長プロフィール",
    "医師経歴",
    "担当医師",
    "doctor",
    "staff",
    "about",
    "greeting",
    "profile",
]

# 肩書きパターン
TITLE_PATTERNS = [
    ("総院長", "総院長"),
    ("院長", "院長"),
    ("副院長", "副院長"),
    ("理事長", "理事長"),
    ("顧問", "顧問"),
    ("非常勤医師", "非常勤"),
    ("非常勤", "非常勤"),
    ("常勤医師", "常勤"),
    ("常勤", "常勤"),
    ("医師", "医師"),
    ("医長", "医長"),
    ("部長", "部長"),
    ("ドクター", "医師"),
]

# 専門分野キーワード
SPECIALTY_KEYWORDS = [
    "美容外科",
    "美容皮膚科",
    "形成外科",
    "皮膚科",
    "眼科",
    "耳鼻咽喉科",
    "整形外科",
    "外科",
    "内科",
    "麻酔科",
    "脂肪吸引",
    "豊胸",
    "二重",
    "鼻整形",
    "アンチエイジング",
    "レーザー治療",
    "注入治療",
    "スキンケア",
]

# 資格キーワード（board_certifications検出用）
CERTIFICATION_KEYWORDS = [
    "日本形成外科学会専門医",
    "日本形成外科学会",
    "形成外科専門医",
    "日本美容外科学会専門医",
    "日本美容外科学会",
    "美容外科専門医",
    "日本美容外科学会（JSAPS）専門医",
    "日本美容外科学会（JSAS）専門医",
    "日本皮膚科学会専門医",
    "皮膚科専門医",
    "日本外科学会専門医",
    "外科専門医",
    "日本麻酔科学会専門医",
    "麻酔科専門医",
    "日本眼科学会専門医",
    "日本耳鼻咽喉科学会専門医",
    "日本整形外科学会専門医",
    "日本抗加齢医学会専門医",
    "日本レーザー医学会専門医",
    "日本頭蓋顎顔面外科学会専門医",
    "ボトックスビスタ認定医",
    "ジュビダームビスタ認定医",
    "サーマクール認定医",
    "日本医師会認定産業医",
]

# ============================================================
# ログ設定
# ============================================================

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
class ExtractedDoctor:
    """抽出された医師情報"""

    name: str
    title: str | None = None
    specialties: list[str] = field(default_factory=list)
    board_certifications: list[str] = field(default_factory=list)
    experience_years: int | None = None
    profile_url: str | None = None
    raw_text: str = ""  # デバッグ用の元テキスト


# ============================================================
# HTML取得
# ============================================================


def _load_cached_html(clinic_id: str, filename: str = "index.html") -> str | None:
    """
    Phase BのスクレイプキャッシュからHTMLを読み込む。

    Args:
        clinic_id: クリニックID（ULID）
        filename: キャッシュファイル名

    Returns:
        HTML文字列、キャッシュがなければNone
    """
    cache_path = SCRAPE_CACHE_DIR / clinic_id / filename
    if cache_path.exists():
        logger.debug("キャッシュヒット: %s", cache_path)
        return cache_path.read_text(encoding="utf-8", errors="replace")
    return None


def _fetch_url(url: str, client: httpx.Client) -> str | None:
    """
    URLからHTMLを取得する（レート制限付き）。

    Args:
        url: 取得先URL
        client: httpxクライアント

    Returns:
        HTML文字列、取得失敗時はNone
    """
    try:
        # robots.txt簡易チェック
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        try:
            robots_resp = client.get(robots_url, timeout=5.0)
            if robots_resp.status_code == 200:
                robots_text = robots_resp.text.lower()
                # 簡易チェック: User-agent: * の Disallow に該当しないか
                if "disallow: /" in robots_text and "allow:" not in robots_text:
                    logger.warning("robots.txtで全ページ禁止: %s", parsed.netloc)
                    return None
        except httpx.HTTPError:
            pass  # robots.txt取得失敗は無視して続行

        time.sleep(RATE_LIMIT_SECONDS)
        response = client.get(url, follow_redirects=True, timeout=HTTP_TIMEOUT)
        response.raise_for_status()

        # HTMLコンテンツかチェック
        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type and "application/xhtml" not in content_type:
            logger.warning("非HTMLコンテンツ: %s (%s)", url, content_type)
            return None

        return response.text
    except httpx.HTTPError as e:
        logger.warning("HTTP取得失敗: %s — %s", url, e)
        return None
    except Exception as e:
        logger.error("予期しないエラー: %s — %s", url, e)
        return None


# ============================================================
# 医師情報ページ検出
# ============================================================


def _find_doctor_page_urls(base_url: str, html: str) -> list[str]:
    """
    トップページのHTMLから医師情報ページのURLを検出する。

    リンクテキストおよびURL文字列にDOCTOR_PAGE_KEYWORDSが含まれるかで判定。

    Args:
        base_url: クリニックのベースURL
        html: トップページのHTML

    Returns:
        医師情報ページの候補URLリスト（重複除去済み）
    """
    soup = BeautifulSoup(html, "lxml")
    found_urls: list[str] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        link_text = anchor.get_text(strip=True).lower()
        href_lower = href.lower()

        # キーワードマッチ
        matched = False
        for keyword in DOCTOR_PAGE_KEYWORDS:
            if keyword in link_text or keyword in href_lower:
                matched = True
                break

        if not matched:
            continue

        # 絶対URLに変換
        absolute_url = urljoin(base_url, href)

        # 外部リンクを除外
        base_domain = urlparse(base_url).netloc
        link_domain = urlparse(absolute_url).netloc
        if base_domain and link_domain and base_domain != link_domain:
            # サブドメインは許可
            if not link_domain.endswith(f".{base_domain}"):
                continue

        # 重複除去
        normalized = absolute_url.rstrip("/")
        if normalized not in seen:
            seen.add(normalized)
            found_urls.append(absolute_url)

    return found_urls


# ============================================================
# 医師情報抽出
# ============================================================


# 漢字名パターン: 2〜4文字の漢字姓 + 空白 + 1〜4文字の漢字名（フルネーム）
_KANJI_NAME_PATTERN = re.compile(
    r"(?:^|(?<=[\s　「【（(：:・]))([一-龥]{2,4})\s*([一-龥]{1,4})(?=$|[\s　」】）)）])",
)

# 肩書き + 名前パターン（例: 「院長 山田太郎」「副院長：佐藤花子」）
_TITLE_NAME_PATTERN = re.compile(
    r"(総院長|院長|副院長|理事長|顧問|医師|医長|部長|ドクター)"
    r"[\s　：:・]*"
    r"([一-龥]{2,4})\s*([一-龥]{1,4})"
)

# 経験年数パターン（例: 「経験20年」「臨床歴15年」）
_EXPERIENCE_PATTERN = re.compile(
    r"(?:経験|臨床歴?|実績|キャリア)\s*(\d{1,3})\s*年"
)

# 卒業年パターン（例: 「平成10年 東京大学卒業」「2005年 慶應義塾大学医学部卒」）
_GRADUATION_YEAR_PATTERN = re.compile(
    r"(?:昭和|平成|令和)?\s*(\d{1,4})\s*年\s*(?:\d{1,2}月\s*)?.*(?:卒業|卒|修了)"
)


def _extract_doctors_from_html(html: str, page_url: str) -> list[ExtractedDoctor]:
    """
    HTMLから医師情報をルールベースで抽出する。

    抽出フロー:
    1. ページ全体のテキストから肩書き+名前パターンを検出
    2. 各医師のセクションを特定
    3. セクション内から資格・専門分野・経歴を抽出

    Args:
        html: 医師情報ページのHTML
        page_url: ページURL

    Returns:
        抽出された医師情報のリスト
    """
    soup = BeautifulSoup(html, "lxml")

    # script/style/navを除去してクリーンテキスト取得
    for tag in soup.find_all(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    doctors: list[ExtractedDoctor] = []
    seen_names: set[str] = set()

    # ---- 方法1: 構造化要素（見出し+後続コンテンツ）から抽出 ----
    _extract_from_headings(soup, page_url, doctors, seen_names)

    # ---- 方法2: テキスト全体からパターンマッチ ----
    full_text = soup.get_text(separator="\n")
    _extract_from_fulltext(full_text, page_url, doctors, seen_names)

    return doctors


def _extract_from_headings(
    soup: BeautifulSoup,
    page_url: str,
    doctors: list[ExtractedDoctor],
    seen_names: set[str],
) -> None:
    """
    見出しタグ（h1〜h4）とその後続コンテンツから医師情報を抽出する。

    クリニックサイトでは「院長 山田太郎」のような見出しの後に
    経歴や資格が列挙されるパターンが多い。
    """
    headings = soup.find_all(["h1", "h2", "h3", "h4"])

    for heading in headings:
        heading_text = heading.get_text(strip=True)

        # 見出しに医師名パターンがあるかチェック
        match = _TITLE_NAME_PATTERN.search(heading_text)
        if not match:
            # 肩書きだけの見出しの場合、直後の要素に名前がないか
            has_title_keyword = any(t[0] in heading_text for t in TITLE_PATTERNS)
            if not has_title_keyword:
                continue

            # 直後のテキスト要素から名前を探す
            next_text = _get_following_text(heading, max_chars=500)
            match = _TITLE_NAME_PATTERN.search(next_text)
            if not match:
                name_match = _KANJI_NAME_PATTERN.search(next_text[:100])
                if name_match:
                    full_name = name_match.group(1) + name_match.group(2)
                    title = _detect_title(heading_text)
                    section_text = next_text
                else:
                    continue
            else:
                title = match.group(1)
                full_name = match.group(2) + match.group(3)
                section_text = _get_following_text(heading, max_chars=2000)
        else:
            title = match.group(1)
            full_name = match.group(2) + match.group(3)
            section_text = _get_following_text(heading, max_chars=2000)

        # 重複チェック
        if full_name in seen_names:
            continue
        # 明らかに人名でないパターンの除外
        if _is_likely_not_person_name(full_name):
            continue

        seen_names.add(full_name)

        # セクションテキストから詳細情報を抽出
        specialties = _extract_specialties(section_text)
        certifications = _extract_certifications(section_text)
        experience_years = _extract_experience_years(section_text)

        # 肩書きを正規化
        normalized_title = _normalize_title(title)

        doctors.append(
            ExtractedDoctor(
                name=full_name,
                title=normalized_title,
                specialties=specialties,
                board_certifications=certifications,
                experience_years=experience_years,
                profile_url=page_url,
                raw_text=section_text[:500],
            )
        )


def _extract_from_fulltext(
    text: str,
    page_url: str,
    doctors: list[ExtractedDoctor],
    seen_names: set[str],
) -> None:
    """
    ページ全体のテキストからパターンマッチで医師情報を抽出する。

    見出しベースの抽出で漏れた医師を補完する。
    """
    # 肩書き+名前パターンでの一括検出
    for match in _TITLE_NAME_PATTERN.finditer(text):
        title = match.group(1)
        full_name = match.group(2) + match.group(3)

        if full_name in seen_names:
            continue
        if _is_likely_not_person_name(full_name):
            continue

        seen_names.add(full_name)

        # マッチ位置の前後テキストからコンテキスト取得
        start = max(0, match.start() - 100)
        end = min(len(text), match.end() + 1500)
        context = text[start:end]

        specialties = _extract_specialties(context)
        certifications = _extract_certifications(context)
        experience_years = _extract_experience_years(context)

        doctors.append(
            ExtractedDoctor(
                name=full_name,
                title=_normalize_title(title),
                specialties=specialties,
                board_certifications=certifications,
                experience_years=experience_years,
                profile_url=page_url,
                raw_text=context[:500],
            )
        )


# ============================================================
# 抽出ヘルパー
# ============================================================


def _get_following_text(element, max_chars: int = 2000) -> str:
    """
    指定要素の後続テキストを取得する。

    次の同レベルの見出しタグまでのコンテンツを収集。
    """
    parts: list[str] = []
    total_chars = 0

    for sibling in element.next_siblings:
        if hasattr(sibling, "name") and sibling.name in ("h1", "h2", "h3", "h4"):
            break
        text = sibling.get_text(separator="\n", strip=True) if hasattr(sibling, "get_text") else str(sibling).strip()
        if text:
            parts.append(text)
            total_chars += len(text)
            if total_chars >= max_chars:
                break

    return "\n".join(parts)


def _detect_title(text: str) -> str:
    """テキストから肩書きを検出する"""
    for keyword, label in TITLE_PATTERNS:
        if keyword in text:
            return label
    return "医師"


def _normalize_title(title: str) -> str:
    """肩書きを正規化する"""
    for keyword, label in TITLE_PATTERNS:
        if keyword == title or keyword in title:
            return label
    return title


def _extract_specialties(text: str) -> list[str]:
    """テキストから専門分野キーワードを抽出する"""
    found: list[str] = []
    seen: set[str] = set()
    for keyword in SPECIALTY_KEYWORDS:
        if keyword in text and keyword not in seen:
            found.append(keyword)
            seen.add(keyword)
    return found


def _extract_certifications(text: str) -> list[str]:
    """テキストから資格キーワードを抽出する"""
    found: list[str] = []
    seen: set[str] = set()
    for keyword in CERTIFICATION_KEYWORDS:
        if keyword in text and keyword not in seen:
            found.append(keyword)
            seen.add(keyword)

    # 重複除去: 「形成外科専門医」と「日本形成外科学会専門医」が両方ある場合、後者を優先
    _deduplicate_certifications(found)
    return found


def _deduplicate_certifications(certs: list[str]) -> None:
    """
    資格リストの重複を除去する（破壊的操作）。

    短い表記（「形成外科専門医」）と長い表記（「日本形成外科学会専門医」）が
    両方ある場合、長い表記のみを残す。
    """
    to_remove: set[str] = set()
    for i, cert_a in enumerate(certs):
        for j, cert_b in enumerate(certs):
            if i != j and cert_a in cert_b and len(cert_a) < len(cert_b):
                to_remove.add(cert_a)

    for item in to_remove:
        while item in certs:
            certs.remove(item)


def _extract_experience_years(text: str) -> int | None:
    """
    テキストから経験年数を抽出する。

    直接的な「経験XX年」表記と、卒業年からの逆算の2パターンに対応。
    """
    # 直接表記
    match = _EXPERIENCE_PATTERN.search(text)
    if match:
        years = int(match.group(1))
        if 1 <= years <= 60:
            return years

    # 卒業年からの逆算
    match = _GRADUATION_YEAR_PATTERN.search(text)
    if match:
        year_str = match.group(1)
        year_num = int(year_str)

        # 和暦→西暦変換
        before_match = text[:match.start() + 20]
        if "令和" in before_match:
            year_num = 2018 + year_num
        elif "平成" in before_match:
            year_num = 1988 + year_num
        elif "昭和" in before_match:
            year_num = 1925 + year_num
        elif year_num < 100:
            # 2桁数字の場合は西暦下2桁とみなす
            year_num = 1900 + year_num if year_num > 50 else 2000 + year_num

        current_year = datetime.now().year
        experience = current_year - year_num
        if 1 <= experience <= 60:
            return experience

    return None


def _is_likely_not_person_name(name: str) -> bool:
    """
    人名でない可能性が高い文字列を判定する。

    クリニック名や施術名などの誤検出を防ぐフィルター。
    """
    # 長すぎる・短すぎる
    if len(name) < 2 or len(name) > 8:
        return True

    # 施術・設備・業務・一般語を含む名前を除外
    noise_words = [
        # 医療施設
        "クリニック", "医院", "病院", "美容", "整形",
        # 施術・治療関連
        "手術", "施術", "治療", "注射", "注入", "切開", "吸引",
        "レーザー", "ボトックス", "ヒアルロン", "水光",
        # ビジネス・広告
        "カウンセリング", "無料", "相談", "料金", "価格",
        "割引", "キャンペーン", "通常", "特別", "初回",
        "採用", "応募", "求人",
        # コンテンツ
        "症例", "写真", "実績", "紹介", "案内", "一覧",
        "詳細", "情報", "予約", "営業", "診療", "受付",
        # 地名
        "東京", "大阪", "名古屋", "福岡", "横浜",
        "渋谷", "新宿", "銀座", "池袋", "品川",
        # 資格・経歴の断片
        "免許", "資格", "所属", "略歴", "経歴", "卒業",
        "就任", "取得", "認定", "修了", "研修",
        "入局", "開業", "開院", "設立",
        # 年号
        "平成", "令和", "昭和", "西暦",
        # 製品・素材
        "韓国製", "国産", "輸入",
        # スタッフ・組織
        "看護", "事務", "受付", "スタッフ",
        "会長", "理事", "加入", "管理",
        "体制", "複数", "在籍", "常勤", "非常勤",
        # 勤務・スケジュール
        "出勤", "勤務", "曜日", "午前", "午後",
        "休診", "土曜", "日曜", "祝日",
        # その他の一般語
        "執刀", "部分", "全体", "顔出", "公開",
        "保険", "自費", "外来", "電話", "問合",
        "対応", "当院", "挨拶", "教育", "指導", "技術",
        # 診療科名
        "皮膚", "形成", "外科", "内科", "泌尿器",
        "眼科", "耳鼻",
        # 学会・資格名
        "学会", "専門医", "指導医", "博士", "医学",
        "医療", "法人", "社団", "会員", "機関",
        "診察", "制度", "年月", "年度",
    ]
    for word in noise_words:
        if word in name:
            return True

    # 全て同じ文字
    if len(set(name)) <= 1:
        return True

    return False


# ============================================================
# DB操作
# ============================================================


def _get_clinics_with_website(
    conn: sqlite3.Connection,
    limit: int | None = None,
) -> list[tuple[str, str, str, str]]:
    """
    ウェブサイトURLがあるクリニック一覧を取得する。

    Returns:
        (id, name, website, prefecture) のタプルリスト
    """
    query = (
        "SELECT id, name, website, prefecture FROM clinics "
        "WHERE website IS NOT NULL AND website != '' AND is_active = 1 "
        "ORDER BY created_at"
    )
    if limit:
        query += f" LIMIT {limit}"

    cursor = conn.execute(query)
    return cursor.fetchall()


def _get_existing_doctor_names(
    conn: sqlite3.Connection,
    clinic_id: str,
) -> set[str]:
    """指定クリニックの既存医師名を取得（重複INSERT防止）"""
    cursor = conn.execute(
        "SELECT name FROM doctors WHERE clinic_id = ?",
        (clinic_id,),
    )
    return {row[0] for row in cursor.fetchall()}


def _insert_doctor(
    conn: sqlite3.Connection,
    clinic_id: str,
    doctor: ExtractedDoctor,
) -> str:
    """
    医師レコードをdoctorsテーブルにINSERTする。

    Returns:
        生成されたレコードID（ULID）
    """
    doctor_id = str(ULID())
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """
        INSERT INTO doctors (
            id, clinic_id, name, title, specialties,
            board_certifications, experience_years, profile_url,
            source, fetched_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            doctor_id,
            clinic_id,
            doctor.name,
            doctor.title,
            json.dumps(doctor.specialties, ensure_ascii=False),
            json.dumps(doctor.board_certifications, ensure_ascii=False),
            doctor.experience_years,
            doctor.profile_url,
            "website_scrape",
            now,
            now,
        ),
    )
    return doctor_id


# ============================================================
# メイン処理
# ============================================================


def process_clinic(
    clinic_id: str,
    clinic_name: str,
    website: str,
    client: httpx.Client,
    conn: sqlite3.Connection,
    dry_run: bool = True,
) -> list[ExtractedDoctor]:
    """
    1クリニックの医師情報を抽出・保存する。

    Args:
        clinic_id: クリニックID
        clinic_name: クリニック名
        website: クリニックURL
        client: HTTPクライアント
        conn: DB接続
        dry_run: Trueの場合はDB書き込みしない

    Returns:
        抽出された医師情報リスト
    """
    logger.info("処理中: %s (%s)", clinic_name, website)

    # 1. トップページのHTML取得（キャッシュ優先）
    top_html = _load_cached_html(clinic_id)
    if top_html:
        logger.info("  📦 キャッシュからトップページ読み込み")
    else:
        logger.info("  🌐 トップページを直接取得")
        top_html = _fetch_url(website, client)

    if not top_html:
        logger.warning("  ⚠ トップページの取得に失敗しました")
        return []

    # 2. 医師情報ページのURL検出
    doctor_urls = _find_doctor_page_urls(website, top_html)
    logger.info("  🔍 医師情報ページ候補: %d件", len(doctor_urls))

    # 3. トップページ自体も含めてHTMLを解析対象にする
    all_htmls: list[tuple[str, str]] = [(website, top_html)]

    for url in doctor_urls[:5]:  # 最大5ページまで
        # キャッシュチェック（ファイル名はURLパスから生成）
        url_path = urlparse(url).path.strip("/").replace("/", "_") or "doctor"
        cached = _load_cached_html(clinic_id, f"{url_path}.html")
        if cached:
            all_htmls.append((url, cached))
            logger.info("  📦 キャッシュ: %s", url_path)
        else:
            page_html = _fetch_url(url, client)
            if page_html:
                all_htmls.append((url, page_html))
                logger.info("  🌐 取得: %s", url)

    # 4. 全ページから医師情報を抽出
    all_doctors: list[ExtractedDoctor] = []
    seen_names: set[str] = set()

    for page_url, html in all_htmls:
        extracted = _extract_doctors_from_html(html, page_url)
        for doc in extracted:
            if doc.name not in seen_names:
                seen_names.add(doc.name)
                all_doctors.append(doc)

    logger.info("  👨‍⚕️ 抽出医師数: %d名", len(all_doctors))

    # 5. DB保存（dry-runでなければ）
    if not dry_run and all_doctors:
        existing_names = _get_existing_doctor_names(conn, clinic_id)
        inserted_count = 0

        for doctor in all_doctors:
            if doctor.name in existing_names:
                logger.info("    ⏭ スキップ（既存）: %s", doctor.name)
                continue

            doctor_id = _insert_doctor(conn, clinic_id, doctor)
            inserted_count += 1
            logger.info(
                "    ✅ INSERT: %s (%s) → %s",
                doctor.name,
                doctor.title or "不明",
                doctor_id,
            )

        conn.commit()
        logger.info("  💾 %d名をDBに保存", inserted_count)

    # 結果表示
    for doc in all_doctors:
        certs_str = ", ".join(doc.board_certifications) if doc.board_certifications else "なし"
        logger.info(
            "    %s | %s | 資格: %s | 経験: %s年",
            doc.name,
            doc.title or "不明",
            certs_str,
            doc.experience_years or "不明",
        )

    return all_doctors


def main() -> None:
    """CLI エントリーポイント"""
    parser = argparse.ArgumentParser(
        description="クリニック公式サイトから医師情報を抽出する（C-1）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="DB書き込みを行わない（デフォルト: False）",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="DB書き込みを実行する",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="処理するクリニック数の上限",
    )
    parser.add_argument(
        "--clinic-id",
        type=str,
        default=None,
        help="特定のクリニックIDのみ処理",
    )
    args = parser.parse_args()

    # --dry-run も --execute も指定なしの場合はdry-run扱い
    dry_run = not args.execute or args.dry_run

    mode_label = "🔍 dry-runモード" if dry_run else "🚀 実行モード"
    print(f"{'=' * 60}")
    print(f"  AURA C-1: 医師情報抽出スクリプト")
    print(f"  モード: {mode_label}")
    print(f"  DB: {DB_PATH}")
    print(f"  キャッシュ: {SCRAPE_CACHE_DIR}")
    print(f"{'=' * 60}")
    print()

    if not DB_PATH.exists():
        logger.error("データベースが見つかりません: %s", DB_PATH)
        return

    conn = sqlite3.connect(str(DB_PATH))

    try:
        # 対象クリニック取得
        if args.clinic_id:
            cursor = conn.execute(
                "SELECT id, name, website, prefecture FROM clinics WHERE id = ?",
                (args.clinic_id,),
            )
            clinics = cursor.fetchall()
        else:
            clinics = _get_clinics_with_website(conn, limit=args.limit)

        logger.info("対象クリニック数: %d件", len(clinics))
        print()

        # 統計
        total_doctors = 0
        clinics_with_doctors = 0
        all_certifications: dict[str, int] = {}

        with httpx.Client(
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            timeout=HTTP_TIMEOUT,
        ) as client:
            for i, (cid, name, website, prefecture) in enumerate(clinics, 1):
                print(f"--- [{i}/{len(clinics)}] ---")
                doctors = process_clinic(
                    clinic_id=cid,
                    clinic_name=name,
                    website=website,
                    client=client,
                    conn=conn,
                    dry_run=dry_run,
                )

                if doctors:
                    clinics_with_doctors += 1
                    total_doctors += len(doctors)
                    for doc in doctors:
                        for cert in doc.board_certifications:
                            all_certifications[cert] = all_certifications.get(cert, 0) + 1

                print()

        # サマリー表示
        print(f"{'=' * 60}")
        print("  処理結果サマリー")
        print(f"{'=' * 60}")
        print(f"  処理クリニック数: {len(clinics)}")
        print(f"  医師検出クリニック数: {clinics_with_doctors}")
        print(f"  抽出医師総数: {total_doctors}")
        print()

        if all_certifications:
            print("  検出された資格:")
            for cert, count in sorted(
                all_certifications.items(), key=lambda x: -x[1]
            ):
                print(f"    {cert}: {count}名")
            print()

        if dry_run:
            print("ℹ️  dry-runモードのため、DBへの書き込みは行いませんでした。")
            print("   実行するには: --execute オプションを付けてください。")
        else:
            # 事後検証
            cursor = conn.execute("SELECT COUNT(*) FROM doctors WHERE source = 'website_scrape'")
            db_count = cursor.fetchone()[0]
            print(f"  DB内の website_scrape 医師レコード数: {db_count}")
        print()

    finally:
        conn.close()

    print("✅ 完了")


if __name__ == "__main__":
    main()
