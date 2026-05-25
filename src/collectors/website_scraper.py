"""
公式サイト解析エンジン — AURA MVP Phase 2 B-1

クリニック公式サイトから施術メニュー・価格情報をスクレイピングし、
clinic_procedures テーブルに反映する3段階パイプライン。

パイプライン:
  Step 1: HTML取得（robots.txt準拠、レート制限）
  Step 2: メニュー/料金ページの発見（リンクテキスト解析）
  Step 3: 施術名・価格の構造化抽出（ルールベース正規表現）

使い方:
  uv run python -m src.collectors.website_scraper --dry-run --limit 3
  uv run python -m src.collectors.website_scraper --google-first --limit 336
  uv run python -m src.collectors.website_scraper
  uv run python -m src.collectors.website_scraper --stats
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import warnings

import httpx
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

# lxmlでXMLをHTML解析する際の警告を抑制（クリニックサイトのXHTML応答対策）
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# ============================================================
# 定数
# ============================================================

# データベース・キャッシュパス
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.normpath(os.path.join(BASE_DIR, "..", ".."))
DB_PATH = os.path.join(PROJECT_DIR, "data", "aura.db")
CACHE_DIR = os.path.join(PROJECT_DIR, "data", "scrape_cache")

# HTTPクライアント設定
USER_AGENT = "AuraBot/1.0 (research; contact@aura-health.jp)"
REQUEST_TIMEOUT = 15  # 秒
RATE_LIMIT_SECONDS = 3  # リクエスト間隔（秒）
MAX_MENU_PAGES = 32  # 深堀り上限ページ数

# メニュー/料金ページ検出キーワード
MENU_KEYWORDS = [
    "料金", "メニュー", "施術一覧", "price", "menu",
    "治療内容", "料金表", "施術料金", "診療内容",
    "施術内容", "プラン", "費用", "price list",
    "美容メニュー", "施術案内", "治療メニュー", "コース",
]

# 医師情報ページ検出キーワード（Phase C用）
DOCTOR_KEYWORDS = [
    "ドクター", "医師紹介", "スタッフ", "doctor",
    "医師", "院長紹介", "スタッフ紹介", "dr",
    "担当医", "医師一覧", "院長", "プロフィール",
]

# ============================================================
# 施術名ファジーマッチング用キーワードマップ
# ============================================================

PROCEDURE_KEYWORDS: dict[str, list[str]] = {
    # --- eye カテゴリ ---
    "二重埋没法": ["埋没", "二重埋没", "埋没法", "二重術"],
    "二重切開法": ["切開", "二重切開", "切開法", "全切開", "部分切開"],
    "目頭切開": ["目頭切開", "目頭"],
    "目尻切開・たれ目形成": ["目尻切開", "たれ目", "目尻", "グラマラスライン", "下眼瞼下制"],
    "眼瞼下垂手術": ["眼瞼下垂", "がんけんかすい", "まぶた下垂"],
    "上まぶたの脂肪除去": ["脂肪除去", "上まぶた", "ROOF切除", "まぶた脂肪"],
    "目の下のクマ取り（脱脂）": ["クマ取り", "目の下の脱脂", "脱脂", "経結膜脱脂", "下眼瞼脱脂"],
    "目の下のクマ取り（脱脂＋脂肪注入）": [
        "脱脂脂肪注入", "脱脂＋脂肪注入", "脱脂+脂肪注入",
        "脂肪注入", "目の下脂肪注入",
    ],
    # --- nose カテゴリ ---
    "ヒアルロン酸注入（隆鼻）": ["ヒアルロン酸隆鼻", "隆鼻ヒアルロン酸", "鼻ヒアルロン酸"],
    "プロテーゼ隆鼻": ["プロテーゼ", "隆鼻術", "シリコンプロテーゼ", "I型プロテーゼ", "L型プロテーゼ"],
    "鼻尖縮小": ["鼻尖縮小", "鼻尖形成", "だんご鼻", "鼻尖"],
    "鼻翼縮小（小鼻縮小）": ["鼻翼縮小", "小鼻縮小", "小鼻", "鼻翼"],
    "鼻中隔延長": ["鼻中隔延長", "鼻中隔", "鼻延長"],
    "鼻骨骨切り": ["鼻骨骨切り", "骨切り", "鼻骨", "ワシ鼻修正", "ハンプ"],
    # --- skin カテゴリ ---
    "ピコレーザー（シミ・肝斑）": [
        "ピコレーザー", "ピコ", "シミ取り", "シミレーザー",
        "肝斑", "ピコスポット", "ピコトーニング",
    ],
    "フォトフェイシャル（IPL光治療）": [
        "フォトフェイシャル", "IPL", "光治療", "フォト",
        "フォトRF", "ライムライト", "M22",
    ],
    "レーザートーニング（シミ・くすみ）": [
        "レーザートーニング", "トーニング", "くすみ",
        "メドライト", "スペクトラ",
    ],
    "ケミカルピーリング（ニキビ跡・毛穴）": [
        "ケミカルピーリング", "ピーリング", "サリチル酸", "グリコール酸",
        "マッサージピール", "コラーゲンピール",
    ],
    "ダーマペン（毛穴・ニキビ跡）": [
        "ダーマペン", "ダーマペン4", "マイクロニードル",
        "ヴェルベットスキン", "ベルベットスキン",
    ],
    "ボトックス注射（しわ・表情じわ）": [
        "ボトックス", "ボツリヌストキシン", "アラガン",
        "しわ取り", "表情じわ", "眉間ボトックス", "額ボトックス",
    ],
    "ヒアルロン酸注入（しわ・ほうれい線）": [
        "ヒアルロン酸", "ほうれい線", "しわ注入",
        "ジュビダーム", "レスチレン", "ボリューマ",
    ],
    "糸リフト（たるみ・引き締め）": [
        "糸リフト", "スレッドリフト", "ミントリフト",
        "テスリフト", "アプトス", "フェイスリフト",
    ],
    # --- contour カテゴリ ---
    "エラボトックス（小顔）": [
        "エラボトックス", "小顔ボトックス", "エラ",
        "小顔注射", "咬筋ボトックス",
    ],
    "脂肪溶解注射（二重あご・フェイスライン）": [
        "脂肪溶解注射", "脂肪溶解", "BNLS", "カベリン",
        "二重あご", "メソセラピー",
    ],
    "ヒアルロン酸注入（あご形成）": [
        "あご形成", "顎形成", "あごヒアルロン酸",
        "Eライン", "あご先",
    ],
    "バッカルファット除去（頬の膨らみ）": [
        "バッカルファット", "バッカル", "頬脂肪",
    ],
    "糸リフト（フェイスライン引き上げ）": [
        "フェイスライン", "たるみリフト", "リフトアップ",
        "引き上げ",
    ],
    "脂肪吸引（顎下・頬）": [
        "脂肪吸引", "顎下脂肪吸引", "頬脂肪吸引",
        "ベイザー", "ライポマティック",
    ],
}

# 価格抽出用の正規表現パターン
PRICE_PATTERNS = [
    # 「49,800円」「1,000,000円」形式
    re.compile(r"(\d{1,3}(?:,\d{3})+)\s*円"),
    # 「49800円」形式（カンマなし）
    re.compile(r"(\d{4,8})\s*円"),
    # 「￥49,800」形式
    re.compile(r"[¥￥]\s*(\d{1,3}(?:,\d{3})+)"),
    # 「￥49800」形式
    re.compile(r"[¥￥]\s*(\d{4,8})"),
    # 「5万円」「10万円」「5.5万円」形式
    re.compile(r"(\d+(?:\.\d+)?)\s*万\s*円"),
    # 「5万8千円」「10万5000円」形式
    re.compile(r"(\d+)\s*万\s*(\d+(?:千|,?\d{3,4}))\s*円?"),
]

# 価格として不自然な値の除外範囲（円）
MIN_VALID_PRICE = 1000
MAX_VALID_PRICE = 50_000_000


# ============================================================
# ユーティリティ関数
# ============================================================


def parse_price_yen(text: str) -> int | None:
    """
    テキストから価格（円単位の整数）を抽出する。

    「49,800円」→49800、「5万円」→50000、「￥10,000」→10000 等を解析。
    解析できない場合はNoneを返す。

    Args:
        text: 価格を含むテキスト

    Returns:
        円単位の整数値、または None
    """
    text = text.strip()

    # 「5万8千円」パターン
    match = re.search(r"(\d+)\s*万\s*(\d+)\s*千", text)
    if match:
        return int(match.group(1)) * 10000 + int(match.group(2)) * 1000

    # 「5万5000円」パターン
    match = re.search(r"(\d+)\s*万\s*(\d{1,4})\s*円?", text)
    if match:
        man = int(match.group(1))
        remainder = int(match.group(2))
        return man * 10000 + remainder

    # 「5万円」「5.5万円」パターン
    match = re.search(r"(\d+(?:\.\d+)?)\s*万\s*円?", text)
    if match:
        return int(float(match.group(1)) * 10000)

    # カンマ区切り「49,800円」「￥49,800」パターン
    match = re.search(r"(\d{1,3}(?:,\d{3})+)", text)
    if match:
        return int(match.group(1).replace(",", ""))

    # カンマなし「49800円」「￥49800」パターン
    match = re.search(r"(\d{4,8})", text)
    if match:
        return int(match.group(1))

    return None


def is_valid_price(price: int) -> bool:
    """価格が妥当な範囲内か判定する"""
    return MIN_VALID_PRICE <= price <= MAX_VALID_PRICE


def normalize_url(base_url: str, href: str) -> str | None:
    """
    相対URLを絶対URLに変換し、正規化する。

    フラグメント(#)、javascript:、tel:、mailto: 等は除外する。

    Args:
        base_url: ベースURL
        href: リンク先（相対または絶対URL）

    Returns:
        正規化された絶対URL、または除外対象の場合 None
    """
    if not href:
        return None

    href = href.strip()

    # 除外パターン
    skip_prefixes = ("javascript:", "tel:", "mailto:", "#", "data:")
    if any(href.lower().startswith(p) for p in skip_prefixes):
        return None

    try:
        absolute = urljoin(base_url, href)
        # フラグメントを除去
        parsed = urlparse(absolute)
        clean = parsed._replace(fragment="").geturl()
        return clean
    except Exception:
        return None


def is_same_domain(url1: str, url2: str) -> bool:
    """2つのURLが同一ドメインか判定する"""
    try:
        domain1 = urlparse(url1).netloc.lower().lstrip("www.")
        domain2 = urlparse(url2).netloc.lower().lstrip("www.")
        return domain1 == domain2
    except Exception:
        return False


# ============================================================
# Step 1: HTML取得
# ============================================================


class WebFetcher:
    """
    HTTP取得クラス — robots.txt準拠、レート制限付き

    公式サイトのHTMLを取得する。robots.txtを確認し、
    クロールが許可されたURLのみ取得する。
    """

    def __init__(self):
        """初期化: httpxクライアントを生成"""
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
            max_redirects=5,
        )
        self._robots_cache: dict[str, RobotFileParser | None] = {}
        self._last_request_time: float = 0

    def close(self):
        """HTTPクライアントを閉じる"""
        self._client.close()

    def _rate_limit(self):
        """レート制限: 前回リクエストから一定時間経過するまで待機"""
        elapsed = time.time() - self._last_request_time
        if elapsed < RATE_LIMIT_SECONDS:
            time.sleep(RATE_LIMIT_SECONDS - elapsed)
        self._last_request_time = time.time()

    def _get_robots_parser(self, url: str) -> RobotFileParser | None:
        """
        robots.txtを取得・解析してキャッシュする。

        Args:
            url: 対象URL

        Returns:
            解析済みRobotFileParser、または取得失敗時 None
        """
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

        if robots_url in self._robots_cache:
            return self._robots_cache[robots_url]

        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            response = self._client.get(robots_url, timeout=5)
            if response.status_code == 200:
                parser.parse(response.text.splitlines())
            else:
                # robots.txtが無い場合は全許可と見なす
                parser = None
        except Exception:
            # 取得失敗時も全許可と見なす
            parser = None

        self._robots_cache[robots_url] = parser
        return parser

    def can_fetch(self, url: str) -> bool:
        """
        robots.txtでクロールが許可されているか確認する。

        Args:
            url: 確認対象URL

        Returns:
            クロール許可の場合True
        """
        parser = self._get_robots_parser(url)
        if parser is None:
            return True  # robots.txtがなければ許可
        return parser.can_fetch(USER_AGENT, url)

    def fetch(self, url: str) -> str | None:
        """
        URLからHTMLを取得する。

        robots.txt確認→レート制限→HTTP GET の順で実行。
        失敗時はNoneを返す。

        Args:
            url: 取得対象URL

        Returns:
            HTMLテキスト、または失敗時 None
        """
        if not self.can_fetch(url):
            return None

        self._rate_limit()

        try:
            response = self._client.get(url)
            response.raise_for_status()

            # HTMLコンテンツのみ受け付ける
            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type and "application/xhtml" not in content_type:
                return None

            return response.text
        except httpx.TimeoutException:
            return None
        except httpx.HTTPStatusError:
            return None
        except httpx.RequestError:
            return None
        except Exception:
            return None


# ============================================================
# Step 2: メニューページ発見
# ============================================================


class MenuPageFinder:
    """
    メニュー/料金ページおよび医師情報ページを検出するクラス

    HTMLのリンクテキストをキーワードマッチして、
    料金/施術メニューページと医師情報ページのURLを収集する。
    """

    @staticmethod
    def find_links_by_keywords(
        html: str,
        base_url: str,
        keywords: list[str],
    ) -> list[str]:
        """
        HTMLから指定キーワードにマッチするリンクURLを抽出する。

        リンクテキスト・title属性・href自体をキーワードと照合する。
        同一ドメイン内のリンクのみを返す。

        Args:
            html: HTML文字列
            base_url: ベースURL（相対パス解決用）
            keywords: 検索キーワードリスト

        Returns:
            マッチしたURLのリスト（重複除去済み）
        """
        soup = BeautifulSoup(html, "lxml")
        found_urls: list[str] = []
        seen: set[str] = set()

        for tag in soup.find_all("a", href=True):
            href = tag.get("href", "")
            link_text = tag.get_text(strip=True)
            title = tag.get("title", "") or ""

            # キーワードマッチ対象: リンクテキスト、title属性、href
            search_targets = (link_text + " " + title + " " + href).lower()

            matched = any(kw.lower() in search_targets for kw in keywords)
            if not matched:
                continue

            absolute_url = normalize_url(base_url, href)
            if absolute_url is None:
                continue

            if not is_same_domain(base_url, absolute_url):
                continue

            if absolute_url in seen:
                continue

            seen.add(absolute_url)
            found_urls.append(absolute_url)

            if len(found_urls) >= MAX_MENU_PAGES:
                break

        return found_urls

    @staticmethod
    def find_menu_pages(html: str, base_url: str) -> list[str]:
        """メニュー/料金ページのURLを検出する"""
        return MenuPageFinder.find_links_by_keywords(html, base_url, MENU_KEYWORDS)

    @staticmethod
    def find_doctor_pages(html: str, base_url: str) -> list[str]:
        """医師情報ページのURLを検出する"""
        return MenuPageFinder.find_links_by_keywords(html, base_url, DOCTOR_KEYWORDS)


# ============================================================
# Step 3: 施術・価格の構造化抽出
# ============================================================


class ProcedureExtractor:
    """
    ルールベースの施術名・価格抽出クラス

    HTMLテキストから正規表現とファジーマッチングで
    施術名・価格情報を構造化して抽出する。LLM不使用。
    """

    def __init__(self, procedure_keywords: dict[str, list[str]]):
        """
        初期化

        Args:
            procedure_keywords: 施術名 → キーワードリストのマッピング
        """
        self.procedure_keywords = procedure_keywords

    def extract_from_html(self, html: str) -> list[dict]:
        """
        HTML文字列から施術名・価格情報を抽出する。

        テキストを行ごとに走査し、施術名キーワードと価格パターンを
        同一行または近接行で検出して紐付ける。

        Args:
            html: HTML文字列

        Returns:
            抽出結果のリスト。各要素は:
            {
                "procedure_name": "二重埋没法",
                "price_display": "49,800円～",
                "price_yen": 49800,
                "notes": "両目/追加コメント"
            }
        """
        soup = BeautifulSoup(html, "lxml")

        # script, style, noscript タグを除去
        for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
            tag.decompose()

        text = soup.get_text(separator="\n")
        lines = [line.strip() for line in text.split("\n") if line.strip()]

        results: list[dict] = []
        found_procedures: set[str] = set()

        # 各行を走査し、施術名と価格を検出
        for i, line in enumerate(lines):
            # この行に含まれる施術名を検出
            matched_procedures = self._find_procedures_in_text(line)

            for proc_name in matched_procedures:
                if proc_name in found_procedures:
                    continue

                # 同一行から価格を検出
                price_info = self._extract_price_from_text(line)

                # 同一行に価格がなければ、近接行（前後5行）を走査
                if price_info is None:
                    for offset in range(1, 6):
                        # 後方探索
                        if i + offset < len(lines):
                            price_info = self._extract_price_from_text(lines[i + offset])
                            if price_info:
                                break
                        # 前方探索
                        if i - offset >= 0:
                            price_info = self._extract_price_from_text(lines[i - offset])
                            if price_info:
                                break

                result = {
                    "procedure_name": proc_name,
                    "price_display": price_info["display"] if price_info else None,
                    "price_yen": price_info["yen"] if price_info else None,
                    "notes": self._extract_notes(line),
                }
                results.append(result)
                found_procedures.add(proc_name)

        return results

    def _find_procedures_in_text(self, text: str) -> list[str]:
        """
        テキスト行から施術名をファジーマッチングで検出する。

        Args:
            text: 検索対象テキスト行

        Returns:
            検出された施術名（DB上の正式名称）のリスト
        """
        matched = []
        for proc_name, keywords in self.procedure_keywords.items():
            for kw in keywords:
                if kw in text:
                    matched.append(proc_name)
                    break
        return matched

    def _extract_price_from_text(self, text: str) -> dict | None:
        """
        テキスト行から最初の有効な価格を抽出する。

        Args:
            text: 検索対象テキスト行

        Returns:
            {"display": "49,800円", "yen": 49800} 形式、または None
        """
        # 「5万8千円」パターン（特殊パターンを先に処理）
        match = re.search(r"(\d+)\s*万\s*(\d+)\s*千\s*円?", text)
        if match:
            yen = int(match.group(1)) * 10000 + int(match.group(2)) * 1000
            if is_valid_price(yen):
                return {"display": match.group(0), "yen": yen}

        # 「5万5000円」パターン
        match = re.search(r"(\d+)\s*万\s*(\d{1,4})\s*円", text)
        if match:
            yen = int(match.group(1)) * 10000 + int(match.group(2))
            if is_valid_price(yen):
                return {"display": match.group(0), "yen": yen}

        # 「5万円」「5.5万円」パターン
        match = re.search(r"(\d+(?:\.\d+)?)\s*万\s*円", text)
        if match:
            yen = int(float(match.group(1)) * 10000)
            if is_valid_price(yen):
                return {"display": match.group(0), "yen": yen}

        # カンマ区切り「49,800円」パターン
        match = re.search(r"(\d{1,3}(?:,\d{3})+)\s*円", text)
        if match:
            yen = int(match.group(1).replace(",", ""))
            if is_valid_price(yen):
                return {"display": match.group(0), "yen": yen}

        # 「￥49,800」パターン
        match = re.search(r"[¥￥]\s*(\d{1,3}(?:,\d{3})+)", text)
        if match:
            yen = int(match.group(1).replace(",", ""))
            if is_valid_price(yen):
                return {"display": match.group(0), "yen": yen}

        # カンマなし「49800円」パターン
        match = re.search(r"(\d{4,8})\s*円", text)
        if match:
            yen = int(match.group(1))
            if is_valid_price(yen):
                return {"display": match.group(0), "yen": yen}

        # 「￥49800」パターン
        match = re.search(r"[¥￥]\s*(\d{4,8})", text)
        if match:
            yen = int(match.group(1))
            if is_valid_price(yen):
                return {"display": match.group(0), "yen": yen}

        return None

    def _extract_notes(self, text: str) -> str | None:
        """
        テキスト行から補足情報（片目/両目、税込/税別等）を抽出する。

        Args:
            text: 検索対象テキスト行

        Returns:
            補足テキスト、該当なしの場合 None
        """
        notes_keywords = [
            "税込", "税別", "税抜", "片目", "両目", "片側", "両側",
            "1回", "初回", "2回目以降", "セット", "モニター",
            "キャンペーン", "通常", "特別価格",
        ]
        found = [kw for kw in notes_keywords if kw in text]
        return "、".join(found) if found else None


# ============================================================
# キャッシュ管理
# ============================================================


class ScrapeCache:
    """
    スクレイピング結果のキャッシュマネージャ

    HTMLと抽出結果を data/scrape_cache/{clinic_id}/ に保存する。
    """

    def __init__(self, cache_dir: str = CACHE_DIR):
        """初期化: キャッシュディレクトリを設定"""
        self.cache_dir = cache_dir

    def _clinic_dir(self, clinic_id: str) -> str:
        """クリニック固有のキャッシュディレクトリパスを返す"""
        return os.path.join(self.cache_dir, clinic_id)

    def has_result(self, clinic_id: str) -> bool:
        """このクリニックのスクレイピング結果が既にキャッシュされているか確認"""
        result_path = os.path.join(self._clinic_dir(clinic_id), "result.json")
        return os.path.exists(result_path)

    def save_html(self, clinic_id: str, filename: str, html: str):
        """
        HTMLをキャッシュに保存する。

        Args:
            clinic_id: クリニックID
            filename: ファイル名（index.html, menu.html, doctor.html）
            html: HTML文字列
        """
        clinic_dir = self._clinic_dir(clinic_id)
        os.makedirs(clinic_dir, exist_ok=True)
        filepath = os.path.join(clinic_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)

    def save_result(self, clinic_id: str, result: dict):
        """
        抽出結果をJSONでキャッシュに保存する。

        Args:
            clinic_id: クリニックID
            result: 抽出結果辞書
        """
        clinic_dir = self._clinic_dir(clinic_id)
        os.makedirs(clinic_dir, exist_ok=True)
        filepath = os.path.join(clinic_dir, "result.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    def load_result(self, clinic_id: str) -> dict | None:
        """
        キャッシュからresult.jsonを読み込む。

        Args:
            clinic_id: クリニックID

        Returns:
            結果辞書、またはキャッシュが無い場合 None
        """
        filepath = os.path.join(self._clinic_dir(clinic_id), "result.json")
        if not os.path.exists(filepath):
            return None
        with open(filepath, encoding="utf-8") as f:
            return json.load(f)


# ============================================================
# DB操作
# ============================================================


class DatabaseManager:
    """
    同期版SQLiteデータベースマネージャ

    クリニック・施術データの取得と、clinic_proceduresの更新を担当する。
    """

    def __init__(self, db_path: str = DB_PATH):
        """初期化: DB接続を確立"""
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row

    def close(self):
        """DB接続を閉じる"""
        self.conn.close()

    def get_clinics_with_website(
        self, google_first: bool = False, limit: int | None = None
    ) -> list[dict]:
        """
        websiteカラムにURLがあるクリニック一覧を取得する。

        Args:
            google_first: TrueならGoogle Place IDが紐付いているクリニックを優先
            limit: 取得件数の上限

        Returns:
            クリニック辞書のリスト
        """
        order_clause = ""
        if google_first:
            # google_place_id が NOT NULL のものを先に返す
            order_clause = "ORDER BY (CASE WHEN google_place_id IS NOT NULL THEN 0 ELSE 1 END), name"
        else:
            order_clause = "ORDER BY name"

        limit_clause = f"LIMIT {limit}" if limit else ""

        query = f"""
            SELECT id, name, branch_name, website, google_place_id
            FROM clinics
            WHERE website IS NOT NULL AND website != ''
            {order_clause}
            {limit_clause}
        """
        cursor = self.conn.execute(query)
        return [dict(row) for row in cursor.fetchall()]

    def get_procedures(self) -> list[dict]:
        """
        施術マスタの全レコードを取得する。

        Returns:
            施術辞書のリスト（id, name, category）
        """
        cursor = self.conn.execute(
            "SELECT id, name, category FROM procedures ORDER BY category, name"
        )
        return [dict(row) for row in cursor.fetchall()]

    def build_procedure_name_to_id(self) -> dict[str, str]:
        """
        施術名 → 施術IDのマッピングを構築する。

        PROCEDURE_KEYWORDSのキー（DB上の施術名）とDBの施術名を
        突き合わせてマッピングを返す。

        Returns:
            施術名 → 施術ID の辞書
        """
        procedures = self.get_procedures()
        name_to_id: dict[str, str] = {}
        for proc in procedures:
            name_to_id[proc["name"]] = proc["id"]
        return name_to_id

    def upsert_clinic_procedure(
        self,
        clinic_id: str,
        procedure_id: str,
        price_advertised: int | None,
        price_display: str | None,
        source: str = "website_scrape",
    ):
        """
        clinic_proceduresテーブルにUPSERT（INSERT or UPDATE）する。

        既存レコードがあれば source/price を更新し、
        なければ新規挿入する。

        Args:
            clinic_id: クリニックID
            procedure_id: 施術ID
            price_advertised: 広告価格（円）
            price_display: 表示用価格文字列
            source: データソース名
        """
        now = datetime.now(timezone.utc).isoformat()

        # 既存レコードを確認
        cursor = self.conn.execute(
            "SELECT id, source FROM clinic_procedures WHERE clinic_id = ? AND procedure_id = ?",
            (clinic_id, procedure_id),
        )
        existing = cursor.fetchone()

        if existing:
            # 既存レコードを更新（department_inference → website_scrape にアップグレード）
            self.conn.execute(
                """
                UPDATE clinic_procedures
                SET source = ?, price_advertised = ?, price_display = ?, fetched_at = ?
                WHERE clinic_id = ? AND procedure_id = ?
                """,
                (source, price_advertised, price_display, now, clinic_id, procedure_id),
            )
        else:
            # 新規挿入
            self.conn.execute(
                """
                INSERT INTO clinic_procedures
                (clinic_id, procedure_id, price_advertised, price_display, source, fetched_at, is_active)
                VALUES (?, ?, ?, ?, ?, ?, 1)
                """,
                (clinic_id, procedure_id, price_advertised, price_display, source, now),
            )

    def commit(self):
        """トランザクションをコミットする"""
        self.conn.commit()

    def get_stats(self) -> dict:
        """
        clinic_proceduresの統計情報を取得する。

        Returns:
            統計情報の辞書
        """
        stats = {}

        # ソース別件数
        cursor = self.conn.execute(
            "SELECT source, COUNT(*) FROM clinic_procedures GROUP BY source ORDER BY source"
        )
        stats["by_source"] = {row[0]: row[1] for row in cursor.fetchall()}

        # 価格情報あり件数
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM clinic_procedures WHERE price_advertised IS NOT NULL"
        )
        stats["with_price"] = cursor.fetchone()[0]

        # 総件数
        cursor = self.conn.execute("SELECT COUNT(*) FROM clinic_procedures")
        stats["total"] = cursor.fetchone()[0]

        # website_scrapeの施術別件数
        cursor = self.conn.execute("""
            SELECT p.name, COUNT(*) as cnt
            FROM clinic_procedures cp
            JOIN procedures p ON cp.procedure_id = p.id
            WHERE cp.source = 'website_scrape'
            GROUP BY p.name
            ORDER BY cnt DESC
        """)
        stats["procedure_counts"] = {row[0]: row[1] for row in cursor.fetchall()}

        # スクレイピング済みクリニック数
        cursor = self.conn.execute(
            "SELECT COUNT(DISTINCT clinic_id) FROM clinic_procedures WHERE source = 'website_scrape'"
        )
        stats["scraped_clinics"] = cursor.fetchone()[0]

        # websiteありクリニック数
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM clinics WHERE website IS NOT NULL AND website != ''"
        )
        stats["clinics_with_website"] = cursor.fetchone()[0]

        return stats


# ============================================================
# メインパイプライン
# ============================================================


class WebsiteScraper:
    """
    公式サイト解析パイプライン（メインオーケストレーター）

    3段階パイプラインを実行し、クリニック公式サイトから
    施術メニュー・価格情報を抽出してDB更新する。
    """

    def __init__(self, dry_run: bool = False):
        """
        初期化

        Args:
            dry_run: Trueの場合、DB更新を行わない
        """
        self.dry_run = dry_run
        self.fetcher = WebFetcher()
        self.finder = MenuPageFinder()
        self.cache = ScrapeCache()
        self.db = DatabaseManager()

        # 施術名→IDマッピングを構築
        self.procedure_name_to_id = self.db.build_procedure_name_to_id()

        # DBの施術名でPROCEDURE_KEYWORDSを補完
        self._supplement_keywords()

        self.extractor = ProcedureExtractor(PROCEDURE_KEYWORDS)

        # 統計カウンター
        self.stats = {
            "total": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "procedures_found": 0,
            "prices_found": 0,
            "menu_pages_found": 0,
            "doctor_pages_found": 0,
            "db_updated": 0,
            "errors": [],
        }

    def _supplement_keywords(self):
        """
        DBの施術名でPROCEDURE_KEYWORDSを補完する。

        DB上の施術名がPROCEDURE_KEYWORDSに無い場合、
        施術名そのものをキーワードとして追加する。
        """
        for proc_name in self.procedure_name_to_id:
            if proc_name not in PROCEDURE_KEYWORDS:
                # 施術名をそのままキーワードとして登録
                PROCEDURE_KEYWORDS[proc_name] = [proc_name]
            else:
                # 正式名称もキーワードに含まれていなければ追加
                if proc_name not in PROCEDURE_KEYWORDS[proc_name]:
                    PROCEDURE_KEYWORDS[proc_name].append(proc_name)

    def close(self):
        """リソースを解放する"""
        self.fetcher.close()
        self.db.close()

    def process_clinic(self, clinic: dict) -> dict | None:
        """
        1クリニックの公式サイト解析パイプラインを実行する。

        Step 1: トップページHTML取得
        Step 2: メニュー/料金ページ・医師ページの検出
        Step 3: 施術名・価格の構造化抽出
        → DB更新 & キャッシュ保存

        Args:
            clinic: クリニック辞書（id, name, website 等）

        Returns:
            抽出結果辞書、または失敗時 None
        """
        clinic_id = clinic["id"]
        clinic_name = clinic["name"]
        website = clinic["website"]

        self.stats["total"] += 1

        # キャッシュ確認（スクレイピング済みならスキップ）
        if self.cache.has_result(clinic_id):
            self.stats["skipped"] += 1
            return self.cache.load_result(clinic_id)

        # --- Step 1: トップページHTML取得 ---
        index_html = self.fetcher.fetch(website)
        if not index_html:
            self.stats["failed"] += 1
            error_msg = f"HTML取得失敗: {clinic_name} ({website})"
            self.stats["errors"].append(error_msg)
            # 失敗時も空のresult.jsonを保存してスキップ対象にする
            fail_result = {
                "clinic_id": clinic_id,
                "clinic_name": clinic_name,
                "website": website,
                "status": "fetch_failed",
                "procedures": [],
                "menu_pages": [],
                "doctor_pages": [],
                "scraped_at": datetime.now(timezone.utc).isoformat(),
            }
            self.cache.save_result(clinic_id, fail_result)
            return None

        # トップページをキャッシュ
        self.cache.save_html(clinic_id, "index.html", index_html)

        # --- Step 2: メニュー/料金ページ発見 ---
        menu_urls = self.finder.find_menu_pages(index_html, website)
        doctor_urls = self.finder.find_doctor_pages(index_html, website)

        self.stats["menu_pages_found"] += len(menu_urls)
        self.stats["doctor_pages_found"] += len(doctor_urls)

        # メニューページの取得（最大5ページまで深堀り）
        menu_htmls: list[str] = []
        for menu_url in menu_urls[:5]:
            menu_html = self.fetcher.fetch(menu_url)
            if menu_html:
                menu_htmls.append(menu_html)

        # メニューページHTMLをキャッシュ（結合して保存）
        if menu_htmls:
            combined_menu = "\n<!-- PAGE_BREAK -->\n".join(menu_htmls)
            self.cache.save_html(clinic_id, "menu.html", combined_menu)

        # 医師ページの取得（1ページのみ）
        if doctor_urls:
            doctor_html = self.fetcher.fetch(doctor_urls[0])
            if doctor_html:
                self.cache.save_html(clinic_id, "doctor.html", doctor_html)

        # --- Step 3: 施術・価格の構造化抽出 ---
        all_procedures: list[dict] = []
        seen_procedures: set[str] = set()

        # トップページから抽出
        top_results = self.extractor.extract_from_html(index_html)
        for r in top_results:
            if r["procedure_name"] not in seen_procedures:
                all_procedures.append(r)
                seen_procedures.add(r["procedure_name"])

        # メニューページから抽出
        for menu_html in menu_htmls:
            menu_results = self.extractor.extract_from_html(menu_html)
            for r in menu_results:
                if r["procedure_name"] not in seen_procedures:
                    all_procedures.append(r)
                    seen_procedures.add(r["procedure_name"])

        # 統計更新
        self.stats["procedures_found"] += len(all_procedures)
        self.stats["prices_found"] += sum(
            1 for p in all_procedures if p.get("price_yen")
        )

        # --- DB更新 ---
        if not self.dry_run and all_procedures:
            for proc_data in all_procedures:
                proc_name = proc_data["procedure_name"]
                proc_id = self.procedure_name_to_id.get(proc_name)
                if proc_id:
                    self.db.upsert_clinic_procedure(
                        clinic_id=clinic_id,
                        procedure_id=proc_id,
                        price_advertised=proc_data.get("price_yen"),
                        price_display=proc_data.get("price_display"),
                    )
                    self.stats["db_updated"] += 1
            self.db.commit()

        # 結果をキャッシュに保存
        result = {
            "clinic_id": clinic_id,
            "clinic_name": clinic_name,
            "website": website,
            "status": "success",
            "procedures": all_procedures,
            "menu_pages": menu_urls[:5],
            "doctor_pages": doctor_urls[:3],
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }
        self.cache.save_result(clinic_id, result)

        self.stats["success"] += 1
        return result

    def run(self, google_first: bool = False, limit: int | None = None):
        """
        バッチ処理: 全対象クリニックのスクレイピングを実行する。

        Args:
            google_first: TrueならGoogle紐付きクリニックを優先
            limit: 処理件数の上限
        """
        clinics = self.db.get_clinics_with_website(
            google_first=google_first, limit=limit
        )

        total = len(clinics)
        mode = "DRY-RUN（DB更新なし）" if self.dry_run else "実行モード"
        priority = "Google紐付き優先" if google_first else "名前順"

        print(f"🌐 公式サイト解析エンジン")
        print(f"   モード: {mode}")
        print(f"   対象: {total}件 ({priority})")
        print(f"   DB: {self.db.db_path}")
        print(f"   キャッシュ: {self.cache.cache_dir}")
        print()

        for i, clinic in enumerate(clinics):
            clinic_name = clinic["name"]
            branch = clinic.get("branch_name", "")
            display_name = f"{clinic_name}" + (f" {branch}" if branch else "")

            try:
                result = self.process_clinic(clinic)

                if result and result.get("status") == "success":
                    proc_count = len(result.get("procedures", []))
                    price_count = sum(
                        1 for p in result.get("procedures", []) if p.get("price_yen")
                    )
                    print(
                        f"  ✅ [{i+1}/{total}] {display_name} "
                        f"— 施術: {proc_count}件, 価格: {price_count}件"
                    )
                elif result and result.get("status") == "fetch_failed":
                    print(f"  ❌ [{i+1}/{total}] {display_name} — 取得失敗")
                else:
                    # スキップ（キャッシュ済み）の場合は10件毎に表示
                    pass

            except Exception as e:
                self.stats["failed"] += 1
                self.stats["errors"].append(f"{display_name}: {e}")
                print(f"  ⚠️  [{i+1}/{total}] {display_name} — エラー: {e}")

            # 10件毎に進捗ログ
            if (i + 1) % 10 == 0:
                print(
                    f"\n  📊 進捗 [{i+1}/{total}]: "
                    f"成功={self.stats['success']}, "
                    f"失敗={self.stats['failed']}, "
                    f"スキップ={self.stats['skipped']}, "
                    f"施術検出={self.stats['procedures_found']}件\n"
                )

        # 最終サマリー
        self._print_summary()

    def _print_summary(self):
        """処理結果のサマリーを表示する"""
        print()
        print("=" * 60)
        print("📊 スクレイピング結果サマリー")
        print("=" * 60)
        print(f"  処理対象:     {self.stats['total']}件")
        print(f"  成功:         {self.stats['success']}件")
        print(f"  失敗:         {self.stats['failed']}件")
        print(f"  スキップ:     {self.stats['skipped']}件（キャッシュ済み）")
        print(f"  施術検出:     {self.stats['procedures_found']}件")
        print(f"  価格検出:     {self.stats['prices_found']}件")
        print(f"  メニューページ: {self.stats['menu_pages_found']}件")
        print(f"  医師ページ:   {self.stats['doctor_pages_found']}件")
        if not self.dry_run:
            print(f"  DB更新:       {self.stats['db_updated']}件")
        print()

        if self.stats["errors"]:
            print("⚠️  エラー詳細:")
            for err in self.stats["errors"][:10]:
                print(f"    - {err}")
            if len(self.stats["errors"]) > 10:
                print(f"    ... 他 {len(self.stats['errors']) - 10}件")
        print()


# ============================================================
# 統計表示
# ============================================================


def show_stats():
    """clinic_proceduresテーブルの統計情報を表示する"""
    db = DatabaseManager()
    stats = db.get_stats()
    db.close()

    print("📊 clinic_procedures 統計")
    print("=" * 60)
    print(f"  総レコード数:          {stats['total']}件")
    print(f"  価格情報あり:          {stats['with_price']}件")
    print(f"  スクレイピング済みクリニック: {stats['scraped_clinics']}件")
    print(f"  website保有クリニック:  {stats['clinics_with_website']}件")
    print()

    print("  ソース別内訳:")
    for source, count in stats["by_source"].items():
        print(f"    {source}: {count}件")
    print()

    if stats["procedure_counts"]:
        print("  施術別スクレイピング件数（website_scrape）:")
        for proc_name, count in list(stats["procedure_counts"].items())[:15]:
            print(f"    {proc_name}: {count}件")
        remaining = len(stats["procedure_counts"]) - 15
        if remaining > 0:
            print(f"    ... 他 {remaining}施術")
    print()


# ============================================================
# CLI エントリーポイント
# ============================================================


def main():
    """CLIエントリーポイント"""
    parser = argparse.ArgumentParser(
        description="AURA MVP — 公式サイト解析エンジン",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # テスト（3件のみ、DB更新なし）
  uv run python -m src.collectors.website_scraper --dry-run --limit 3

  # Google紐付き336件を優先実行
  uv run python -m src.collectors.website_scraper --google-first --limit 336

  # 全件実行
  uv run python -m src.collectors.website_scraper

  # 統計のみ表示
  uv run python -m src.collectors.website_scraper --stats
        """,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="DB更新を行わず、スクレイピング結果を表示のみ行う",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="処理するクリニック件数の上限",
    )
    parser.add_argument(
        "--google-first",
        action="store_true",
        help="Google Place IDが紐付いているクリニックを優先して処理する",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="現在のclinic_procedures統計情報を表示して終了する",
    )
    args = parser.parse_args()

    if args.stats:
        show_stats()
        return

    scraper = WebsiteScraper(dry_run=args.dry_run)
    try:
        scraper.run(google_first=args.google_first, limit=args.limit)
    finally:
        scraper.close()


if __name__ == "__main__":
    main()
