#!/usr/bin/env python3
"""
医師プロフィール写真URL収集スクリプト

各クリニック公式サイトから医師のプロフィール写真URLを取得し、
aura-mvp の doctors.photo_url に投入する。

対応ソース:
- SBC（湘南美容クリニック）: 公式APIからスラッグ取得 → 写真URL構築
- TCB（東京中央美容外科）: ドクター一覧ページから写真URLを抽出
- 品川美容外科: ドクター一覧ページから写真URLを抽出
- その他: プロフィールページのOGP画像またはmeta imageを取得

使い方:
    uv run python scripts/collect_doctor_photos.py --dry-run
    uv run python scripts/collect_doctor_photos.py --source sbc
    uv run python scripts/collect_doctor_photos.py --all
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path

# ========================================================================
# 定数
# ========================================================================

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "aura.db"
REQUEST_DELAY = 1.5  # リクエスト間隔（秒）
REQUEST_TIMEOUT = 8  # リクエストタイムアウト（秒）
MAX_RETRIES = 2

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

# SBCドクターの写真URLテンプレート
SBC_BASE_URL = "https://www.s-b-c.net"
SBC_PHOTO_TEMPLATE = "{base}/assets/doctor/introduction/{slug}/images/main.jpg"

# TCBドクター一覧ページ
TCB_DOCTOR_LIST_URL = "https://aoki-tsuyoshi.com/doctor"

# 品川ドクター一覧ページ
SHINAGAWA_DOCTOR_LIST_URL = "https://www.shinagawa.com/doctor/"


# ========================================================================
# HTTP ユーティリティ
# ========================================================================

def fetch(url: str, timeout: int = REQUEST_TIMEOUT) -> str | None:
    """URLのコンテンツを取得する（リトライ付き）"""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": random.choice(USER_AGENTS),
                    "Accept": "text/html,application/json,*/*;q=0.8",
                    "Accept-Language": "ja,en-US;q=0.9",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = REQUEST_DELAY * attempt * 3
                print(f"    [429] レート制限。{wait:.0f}秒待機...")
                time.sleep(wait)
            elif e.code in (403, 404, 503):
                return None
            else:
                print(f"    [HTTP {e.code}] {url}")
        except Exception as e:
            print(f"    [エラー] {e}")
            if attempt < MAX_RETRIES:
                time.sleep(REQUEST_DELAY * attempt)
    return None


def check_image_exists(url: str) -> bool:
    """画像URLが有効かHEADリクエストで確認する"""
    try:
        req = urllib.request.Request(
            url,
            method="HEAD",
            headers={"User-Agent": random.choice(USER_AGENTS)},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            content_type = resp.headers.get("Content-Type", "")
            return resp.status == 200 and "image" in content_type
    except Exception:
        return False


def rate_limit():
    """リクエスト間隔を制御する"""
    delay = REQUEST_DELAY * (0.8 + random.random() * 0.4)
    time.sleep(delay)


# ========================================================================
# SBC 写真URL収集
# ========================================================================

def collect_sbc_photos(conn: sqlite3.Connection, dry_run: bool = False) -> int:
    """SBCドクターの写真URLを一括APIから収集する

    手順:
    1. SBC一括API(/api/?name=doctor)で全607名を取得
    2. Links.profileからスラッグを抽出
    3. スラッグから写真URLを構築（/assets/doctor/introduction/{slug}/images/main.jpg）
    4. 名前マッチングでaura-mvp doctorsテーブルに紐付け
    5. HEADリクエストで写真の存在を確認してからDB更新
    """
    print("=" * 60)
    print("SBC（湘南美容クリニック）— ドクター写真URL収集")
    print("=" * 60)

    cursor = conn.cursor()

    # SBC関連の医師を特定（chain_name経由）
    cursor.execute("""
        SELECT d.id, d.name, d.clinic_id, d.photo_url
        FROM doctors d
        JOIN clinics c ON d.clinic_id = c.id
        WHERE c.chain_name = '湘南美容クリニック'
        AND (d.photo_url IS NULL OR d.photo_url = '')
    """)
    sbc_doctors = cursor.fetchall()
    print(f"  写真未設定のSBC医師: {len(sbc_doctors)}名")

    if not sbc_doctors:
        print("  → 全員設定済み。スキップ。")
        return 0

    # SBC一括APIで全ドクター情報を取得
    print("  SBC API一括取得中...")
    rate_limit()
    api_url = f"{SBC_BASE_URL}/api/?name=doctor"
    json_text = fetch(api_url, timeout=30)
    if not json_text:
        print("  ❌ SBC一括API取得失敗")
        return 0

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        print("  ❌ JSON解析失敗")
        return 0

    api_doctors = data.get("doctor", [])
    print(f"  SBC API: {len(api_doctors)}名取得")

    # 名前→DB IDのマッピング構築
    doctor_name_map: dict[str, str] = {}  # 正規化名→DB ID
    for db_id, db_name, _, _ in sbc_doctors:
        name_normalized = db_name.replace(" ", "").replace("　", "")
        doctor_name_map[name_normalized] = db_id

    updated = 0
    for dc in api_doctors:
        name = dc.get("Name", "").replace(" 医師", "").strip()
        links = dc.get("Links", {}) or {}
        profile_path = links.get("profile", "")

        if not profile_path:
            continue

        # スラッグを抽出（SBC自身のプロフィールページのみ対象）
        slug_match = re.search(r"/doctor/introduction/([^/]+)/?", profile_path)
        if not slug_match:
            continue

        slug = slug_match.group(1)
        photo_url = SBC_PHOTO_TEMPLATE.format(base=SBC_BASE_URL, slug=slug)

        # 名前マッチングでdoctorsテーブルのIDを特定
        name_normalized = name.replace(" ", "").replace("　", "")
        matched_id = doctor_name_map.get(name_normalized)

        if not matched_id:
            continue  # DB上に対応する医師なし（正常ケース）

        # HEADリクエストで写真の存在を確認
        rate_limit()
        if not check_image_exists(photo_url):
            print(f"  ⚠ {name} — 写真URL無効（404）")
            continue

        if dry_run:
            print(f"  ✅ [DRY-RUN] {name} → {photo_url}")
        else:
            cursor.execute(
                "UPDATE doctors SET photo_url = ? WHERE id = ?",
                (photo_url, matched_id),
            )
            print(f"  ✅ {name} → {photo_url}")

        updated += 1
        # 更新済みをマップから除去（重複処理防止）
        del doctor_name_map[name_normalized]

    if not dry_run:
        conn.commit()

    print(f"\n  SBC: {updated}名の写真URLを{'検出' if dry_run else '更新'}")
    return updated


# ========================================================================
# TCB 写真URL収集
# ========================================================================

def collect_tcb_photos(conn: sqlite3.Connection, dry_run: bool = False) -> int:
    """TCBドクターの写真URLをドクター一覧ページから収集する"""
    print("\n" + "=" * 60)
    print("TCB（東京中央美容外科）— ドクター写真URL収集")
    print("=" * 60)

    cursor = conn.cursor()

    cursor.execute("""
        SELECT d.id, d.name, d.photo_url
        FROM doctors d
        JOIN clinics c ON d.clinic_id = c.id
        WHERE c.chain_name = 'TCB東京中央美容外科'
        AND (d.photo_url IS NULL OR d.photo_url = '')
    """)
    tcb_doctors = cursor.fetchall()
    print(f"  写真未設定のTCB医師: {len(tcb_doctors)}名")

    if not tcb_doctors:
        print("  → 全員設定済み。スキップ。")
        return 0

    # TCBドクター一覧ページからHTML取得
    rate_limit()
    html = fetch(TCB_DOCTOR_LIST_URL)
    if not html:
        print("  ❌ TCBドクター一覧ページ取得失敗")
        return 0

    # ドクター写真URLと名前を抽出
    # TCBのドクターページは通常 <img src="..."> と名前が近くに配置される
    # パターン: doctor画像 → 名前テキスト
    doctor_photos: dict[str, str] = {}  # 名前（正規化）→ 写真URL

    # TCBの一般的なドクターカード構造を解析
    # <img src="...dr_xxx.jpg" ... alt="名前 医師"> パターン
    img_patterns = re.findall(
        r'<img[^>]+src=["\']([^"\']+)["\'][^>]*alt=["\']([^"\']*)["\']',
        html,
    )
    # 逆パターンも
    img_patterns += [
        (url, alt) for alt, url in re.findall(
            r'<img[^>]+alt=["\']([^"\']*)["\'][^>]*src=["\']([^"\']+)["\']',
            html,
        )
    ]

    for img_url, alt_text in img_patterns:
        name = alt_text.strip()
        if not name or len(name) > 20:
            continue
        # 「医師」「先生」サフィックスを除去
        name_clean = re.sub(r'\s*(医師|先生|ドクター|Dr\.)\s*$', '', name).strip()
        if not name_clean:
            continue
        # スペース除去後に漢字2-6文字であることを確認
        name_normalized = name_clean.replace(" ", "").replace("　", "")
        if re.match(r'^[\u4e00-\u9fff]{2,6}$', name_normalized):
            if img_url.startswith("/"):
                img_url = f"https://aoki-tsuyoshi.com{img_url}"
            if name_normalized not in doctor_photos:
                doctor_photos[name_normalized] = img_url

    print(f"  TCB一覧ページから抽出: {len(doctor_photos)}名分の写真URL")

    # DB更新
    updated = 0
    for doctor_id, doctor_name, _ in tcb_doctors:
        name_normalized = doctor_name.replace(" ", "").replace("　", "")
        photo_url = doctor_photos.get(name_normalized)
        if photo_url:
            if dry_run:
                print(f"  ✅ [DRY-RUN] {doctor_name} → {photo_url}")
            else:
                cursor.execute(
                    "UPDATE doctors SET photo_url = ? WHERE id = ?",
                    (photo_url, doctor_id),
                )
            updated += 1

    if not dry_run:
        conn.commit()

    print(f"  TCB: {updated}名の写真URLを{'検出' if dry_run else '更新'}")
    return updated


# ========================================================================
# 品川美容外科 写真URL収集
# ========================================================================

def collect_shinagawa_photos(conn: sqlite3.Connection, dry_run: bool = False) -> int:
    """品川美容外科ドクターの写真URLを一覧ページから収集する"""
    print("\n" + "=" * 60)
    print("品川美容外科 — ドクター写真URL収集")
    print("=" * 60)

    cursor = conn.cursor()

    cursor.execute("""
        SELECT d.id, d.name, d.photo_url
        FROM doctors d
        JOIN clinics c ON d.clinic_id = c.id
        WHERE c.chain_name = '品川美容外科'
        AND (d.photo_url IS NULL OR d.photo_url = '')
    """)
    shinagawa_doctors = cursor.fetchall()
    print(f"  写真未設定の品川美容外科医師: {len(shinagawa_doctors)}名")

    if not shinagawa_doctors:
        print("  → 全員設定済み。スキップ。")
        return 0

    # 品川ドクター一覧ページからHTML取得
    rate_limit()
    html = fetch(SHINAGAWA_DOCTOR_LIST_URL)
    if not html:
        print("  ❌ 品川ドクター一覧ページ取得失敗")
        return 0

    # 品川の写真URL+名前パターンを抽出
    doctor_photos: dict[str, str] = {}

    # <img ... src="写真URL" ... alt="名前" ...>
    img_patterns = re.findall(
        r'<img[^>]+src=["\']([^"\']+)["\'][^>]*alt=["\']([^"\']*)["\']',
        html,
    )
    for img_url, alt_text in img_patterns:
        name = alt_text.strip()
        if not name or len(name) > 20:
            continue
        name_clean = re.sub(r'(医師|先生|ドクター|院長|Dr\.)$', '', name).strip()
        if re.match(r'^[\u4e00-\u9fff]{2,6}$', name_clean.replace(" ", "").replace("　", "")):
            name_normalized = name_clean.replace(" ", "").replace("　", "")
            if img_url.startswith("/"):
                img_url = f"https://www.shinagawa.com{img_url}"
            doctor_photos[name_normalized] = img_url

    # 逆パターン
    img_patterns_rev = re.findall(
        r'<img[^>]+alt=["\']([^"\']*)["\'][^>]*src=["\']([^"\']+)["\']',
        html,
    )
    for alt_text, img_url in img_patterns_rev:
        name = alt_text.strip()
        if not name or len(name) > 20:
            continue
        name_clean = re.sub(r'(医師|先生|ドクター|院長|Dr\.)$', '', name).strip()
        if re.match(r'^[\u4e00-\u9fff]{2,6}$', name_clean.replace(" ", "").replace("　", "")):
            name_normalized = name_clean.replace(" ", "").replace("　", "")
            if name_normalized not in doctor_photos:
                if img_url.startswith("/"):
                    img_url = f"https://www.shinagawa.com{img_url}"
                doctor_photos[name_normalized] = img_url

    print(f"  品川一覧ページから抽出: {len(doctor_photos)}名分の写真URL")

    # DB更新
    updated = 0
    for doctor_id, doctor_name, _ in shinagawa_doctors:
        name_normalized = doctor_name.replace(" ", "").replace("　", "")
        photo_url = doctor_photos.get(name_normalized)
        if photo_url:
            if dry_run:
                print(f"  ✅ [DRY-RUN] {doctor_name} → {photo_url}")
            else:
                cursor.execute(
                    "UPDATE doctors SET photo_url = ? WHERE id = ?",
                    (photo_url, doctor_id),
                )
            updated += 1

    if not dry_run:
        conn.commit()

    print(f"  品川美容外科: {updated}名の写真URLを{'検出' if dry_run else '更新'}")
    return updated


# ========================================================================
# 汎用: プロフィールページから写真URL取得
# ========================================================================

def collect_generic_photos(conn: sqlite3.Connection, dry_run: bool = False, limit: int = 100) -> int:
    """プロフィールURLからOGP画像またはメイン画像を取得する（大手チェーン以外）"""
    print("\n" + "=" * 60)
    print("汎用 — プロフィールページからの写真URL収集")
    print("=" * 60)

    cursor = conn.cursor()

    # 大手チェーン以外で写真未設定の医師
    cursor.execute("""
        SELECT d.id, d.name, d.profile_url
        FROM doctors d
        JOIN clinics c ON d.clinic_id = c.id
        WHERE (d.photo_url IS NULL OR d.photo_url = '')
        AND d.profile_url IS NOT NULL AND d.profile_url != ''
        AND (c.chain_name IS NULL OR c.chain_name NOT IN (
            '湘南美容クリニック', 'TCB東京中央美容外科', '品川美容外科'
        ))
        LIMIT ?
    """, (limit,))
    doctors = cursor.fetchall()
    print(f"  対象医師: {len(doctors)}名（上限{limit}名）")

    if not doctors:
        print("  → 対象なし。スキップ。")
        return 0

    updated = 0
    for i, (doc_id, name, profile_url) in enumerate(doctors):
        print(f"\n  [{i+1}/{len(doctors)}] {name}: {profile_url}...", end=" ")
        rate_limit()

        html = fetch(profile_url)
        if not html:
            print("❌ 取得失敗")
            continue

        # OGP画像を優先取得
        photo_url = None

        # 1. og:image
        og_match = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html)
        if not og_match:
            og_match = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html)
        if og_match:
            candidate = og_match.group(1)
            # OGP画像がサイトロゴなどでないか簡易チェック
            if "logo" not in candidate.lower() and "ogp" not in candidate.lower():
                photo_url = candidate

        # 2. 名前がaltに含まれるimg要素
        if not photo_url:
            name_escaped = re.escape(name.replace(" ", "").replace("　", ""))
            name_patterns = [name, name.replace(" ", ""), name.replace("　", "")]
            for np in name_patterns:
                pattern = rf'<img[^>]+alt=["\'][^"\']*{re.escape(np)}[^"\']*["\'][^>]+src=["\']([^"\']+)["\']'
                m = re.search(pattern, html)
                if m:
                    photo_url = m.group(1)
                    break
                # 逆順
                pattern = rf'<img[^>]+src=["\']([^"\']+)["\'][^>]+alt=["\'][^"\']*{re.escape(np)}[^"\']*["\']'
                m = re.search(pattern, html)
                if m:
                    photo_url = m.group(1)
                    break

        if not photo_url:
            print("⚠ 写真URL取得失敗")
            continue

        # 相対URLを絶対URLに変換
        if photo_url.startswith("//"):
            photo_url = f"https:{photo_url}"
        elif photo_url.startswith("/"):
            from urllib.parse import urlparse
            parsed = urlparse(profile_url)
            photo_url = f"{parsed.scheme}://{parsed.netloc}{photo_url}"

        if dry_run:
            print(f"✅ [DRY-RUN] → {photo_url}")
        else:
            cursor.execute(
                "UPDATE doctors SET photo_url = ? WHERE id = ?",
                (photo_url, doc_id),
            )
            print(f"✅ → {photo_url}")

        updated += 1

    if not dry_run:
        conn.commit()

    print(f"\n  汎用: {updated}名の写真URLを{'検出' if dry_run else '更新'}")
    return updated


# ========================================================================
# メイン
# ========================================================================

def main():
    parser = argparse.ArgumentParser(description="医師プロフィール写真URL収集")
    parser.add_argument("--dry-run", action="store_true", help="DBに書き込まず結果のみ表示")
    parser.add_argument("--source", choices=["sbc", "tcb", "shinagawa", "generic"], help="特定ソースのみ実行")
    parser.add_argument("--all", action="store_true", help="全ソースを実行")
    parser.add_argument("--limit", type=int, default=100, help="汎用収集の上限（デフォルト100）")
    args = parser.parse_args()

    if not args.source and not args.all:
        parser.print_help()
        print("\n例:")
        print("  uv run python scripts/collect_doctor_photos.py --dry-run --source sbc")
        print("  uv run python scripts/collect_doctor_photos.py --all")
        return

    conn = sqlite3.connect(str(DB_PATH))
    total_updated = 0

    try:
        if args.source == "sbc" or args.all:
            total_updated += collect_sbc_photos(conn, dry_run=args.dry_run)

        if args.source == "tcb" or args.all:
            total_updated += collect_tcb_photos(conn, dry_run=args.dry_run)

        if args.source == "shinagawa" or args.all:
            total_updated += collect_shinagawa_photos(conn, dry_run=args.dry_run)

        if args.source == "generic" or args.all:
            total_updated += collect_generic_photos(conn, dry_run=args.dry_run, limit=args.limit)
    finally:
        conn.close()

    print("\n" + "=" * 60)
    print(f"完了: 合計 {total_updated}名の写真URLを{'検出' if args.dry_run else '更新'}")
    print("=" * 60)

    # 現状の統計
    conn2 = sqlite3.connect(str(DB_PATH))
    cursor2 = conn2.cursor()
    cursor2.execute("SELECT COUNT(*) FROM doctors")
    total = cursor2.fetchone()[0]
    cursor2.execute("SELECT COUNT(*) FROM doctors WHERE photo_url IS NOT NULL AND photo_url != ''")
    with_photo = cursor2.fetchone()[0]
    conn2.close()

    print(f"\n📊 写真URL設定状況: {with_photo}/{total} ({with_photo/total*100:.1f}%)")


if __name__ == "__main__":
    main()
