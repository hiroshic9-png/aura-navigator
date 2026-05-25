"""
専門医名簿突合スクリプト（C-2）

C-1で取得した医師のboard_certificationsデータを正規化・分析し、
専門医資格の信頼性を評価する。

現在の実装:
- クリニック公式サイトから取得した資格情報を「自己申告（self_declared）」として扱う
- 資格名の表記揺れを正規化
- 同一医師の資格重複を除去
- 信頼性スコアを付与（将来の学会名簿突合に備えた設計）

将来対応（TODO）:
- 日本形成外科学会（JSPRS）の専門医名簿との突合
- 日本美容外科学会（JSAPS）の専門医名簿との突合
- マッチング結果でsourceを 'specialist_registry' に更新

使い方:
  uv run python -m src.collectors.specialist_matcher --dry-run
  uv run python -m src.collectors.specialist_matcher --execute
"""

import argparse
import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# ============================================================
# 定数・設定
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "aura.db"

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
# 資格名正規化マップ
# ============================================================

# 資格名の表記揺れを正規名称にマッピング
CERTIFICATION_NORMALIZATION: dict[str, str] = {
    # 形成外科
    "形成外科専門医": "日本形成外科学会専門医",
    "日本形成外科学会認定専門医": "日本形成外科学会専門医",
    "日本形成外科学会 専門医": "日本形成外科学会専門医",
    # 美容外科
    "美容外科専門医": "日本美容外科学会専門医",
    "日本美容外科学会認定専門医": "日本美容外科学会専門医",
    "JSAPS専門医": "日本美容外科学会（JSAPS）専門医",
    "日本美容外科学会(JSAPS)専門医": "日本美容外科学会（JSAPS）専門医",
    "JSAS専門医": "日本美容外科学会（JSAS）専門医",
    "日本美容外科学会(JSAS)専門医": "日本美容外科学会（JSAS）専門医",
    # 皮膚科
    "皮膚科専門医": "日本皮膚科学会専門医",
    "日本皮膚科学会認定専門医": "日本皮膚科学会専門医",
    # 外科
    "外科専門医": "日本外科学会専門医",
    "日本外科学会認定専門医": "日本外科学会専門医",
    # 麻酔科
    "麻酔科専門医": "日本麻酔科学会専門医",
    "日本麻酔科学会認定専門医": "日本麻酔科学会専門医",
    # 眼科
    "眼科専門医": "日本眼科学会専門医",
    # 耳鼻咽喉科
    "耳鼻咽喉科専門医": "日本耳鼻咽喉科学会専門医",
    # 整形外科
    "整形外科専門医": "日本整形外科学会専門医",
    # その他
    "抗加齢医学会専門医": "日本抗加齢医学会専門医",
    "レーザー医学会専門医": "日本レーザー医学会専門医",
}

# 学会とそのWebサイト（将来の名簿突合用）
SPECIALIST_REGISTRIES: dict[str, dict] = {
    "日本形成外科学会": {
        "url": "https://jsprs.or.jp/member/",
        "certification_name": "日本形成外科学会専門医",
        "status": "not_implemented",
        "note": "JavaScriptレンダリングが必要。会員検索フォームあり。",
    },
    "日本美容外科学会（JSAPS）": {
        "url": "https://www.jsaps.com/",
        "certification_name": "日本美容外科学会（JSAPS）専門医",
        "status": "not_implemented",
        "note": "専門医一覧は動的ページ。地域別検索が可能。",
    },
    "日本皮膚科学会": {
        "url": "https://www.dermatol.or.jp/",
        "certification_name": "日本皮膚科学会専門医",
        "status": "not_implemented",
        "note": "専門医検索ページあり。アクセス制限の可能性。",
    },
}

# 信頼性の高い専門医資格（特に美容医療で重視されるもの）
HIGH_VALUE_CERTIFICATIONS: set[str] = {
    "日本形成外科学会専門医",
    "日本美容外科学会（JSAPS）専門医",
    "日本皮膚科学会専門医",
    "日本外科学会専門医",
    "日本麻酔科学会専門医",
}


# ============================================================
# データクラス
# ============================================================


@dataclass
class DoctorCertificationRecord:
    """医師の資格レコード"""

    doctor_id: str
    clinic_id: str
    doctor_name: str
    clinic_name: str
    prefecture: str
    original_certifications: list[str]
    normalized_certifications: list[str] = field(default_factory=list)
    verification_source: str = "self_declared"
    confidence_score: float = 0.5
    issues: list[str] = field(default_factory=list)


@dataclass
class MatchResult:
    """突合結果サマリー"""

    total_doctors: int = 0
    doctors_with_certs: int = 0
    doctors_without_certs: int = 0
    total_certifications: int = 0
    unique_certifications: int = 0
    certification_counts: dict[str, int] = field(default_factory=dict)
    high_value_cert_doctors: int = 0
    normalization_applied: int = 0
    duplicates_removed: int = 0
    records: list[DoctorCertificationRecord] = field(default_factory=list)


# ============================================================
# 資格正規化
# ============================================================


def normalize_certification(cert: str) -> str:
    """
    資格名の表記揺れを正規名称に変換する。

    Args:
        cert: 元の資格名

    Returns:
        正規化された資格名
    """
    # 前後の空白・全角スペースを除去
    cert = cert.strip().replace("\u3000", " ").strip()

    # 正規化マップでの変換
    if cert in CERTIFICATION_NORMALIZATION:
        return CERTIFICATION_NORMALIZATION[cert]

    # 括弧の正規化（半角→全角）
    cert = cert.replace("(", "（").replace(")", "）")

    # 「認定」「取得」等の冗長な語を除去
    cert = re.sub(r"(資格)?取得$", "", cert)
    cert = re.sub(r"^(所属|所持|保有)\s*[:：]\s*", "", cert)

    return cert


def normalize_certifications(certs: list[str]) -> list[str]:
    """
    資格リスト全体を正規化し、重複を除去する。

    Args:
        certs: 元の資格リスト

    Returns:
        正規化・重複除去済みの資格リスト
    """
    normalized: list[str] = []
    seen: set[str] = set()

    for cert in certs:
        norm = normalize_certification(cert)
        if norm and norm not in seen:
            seen.add(norm)
            normalized.append(norm)

    return normalized


# ============================================================
# 信頼性評価
# ============================================================


def calculate_confidence(
    certifications: list[str],
    clinic_name: str,
    has_profile_url: bool,
) -> float:
    """
    資格情報の信頼性スコアを算出する。

    スコアリング基準:
    - ベーススコア: 0.3（自己申告の最低信頼度）
    - 具体的な学会名を含む: +0.2
    - 公式プロフィールURLあり: +0.1
    - 大手チェーン: +0.1（公式サイトの情報管理が比較的信頼性が高い）
    - 複数の整合性ある資格: +0.1
    - 高価値資格あり: +0.1

    Args:
        certifications: 正規化済み資格リスト
        clinic_name: クリニック名
        has_profile_url: プロフィールURLの有無

    Returns:
        0.0〜1.0の信頼度スコア
    """
    if not certifications:
        return 0.0

    score = 0.3  # ベーススコア

    # 具体的な学会名を含むか
    has_specific_society = any(
        "学会" in cert or "JSAPS" in cert or "JSAS" in cert
        for cert in certifications
    )
    if has_specific_society:
        score += 0.2

    # プロフィールURLあり
    if has_profile_url:
        score += 0.1

    # 大手チェーンかどうか
    major_chains = ["湘南美容", "品川美容", "TCB", "聖心美容", "共立美容", "城本"]
    is_major_chain = any(chain in clinic_name for chain in major_chains)
    if is_major_chain:
        score += 0.1

    # 高価値資格
    has_high_value = any(
        cert in HIGH_VALUE_CERTIFICATIONS for cert in certifications
    )
    if has_high_value:
        score += 0.1

    # 複数の整合性ある資格（例: 形成外科+美容外科は自然な組み合わせ）
    if len(certifications) >= 2:
        score += 0.1

    return min(score, 1.0)


# ============================================================
# 学会名簿突合（将来実装用スタブ）
# ============================================================


def match_against_registry(
    doctor_name: str,
    certification: str,
    prefecture: str,
) -> dict | None:
    """
    学会専門医名簿との突合を行う。

    TODO: 各学会の専門医名簿データベースまたはAPIとの連携を実装
    - JSPRS: https://jsprs.or.jp/member/ （会員検索）
    - JSAPS: https://www.jsaps.com/ （専門医一覧）

    現在の実装:
    - 学会サイトへのアクセスは未実装
    - JavaScriptレンダリングが必要なため、PlaywrightまたはSeleniumの導入が必要
    - 代替案: 学会が公開するPDF名簿の手動取り込み

    Args:
        doctor_name: 医師名（漢字フルネーム）
        certification: 突合対象の資格名
        prefecture: クリニック所在地の都道府県

    Returns:
        マッチ結果の辞書、未実装のためNone
    """
    # TODO: 学会名簿との実際の突合を実装
    # 実装時の方針:
    #   1. 医師名（漢字フルネーム）での完全一致検索
    #   2. 都道府県での確認（所属施設の所在地が一致するか）
    #   3. マッチ成功時: source='specialist_registry', confidence=0.9
    #   4. マッチ不一致時: issue追加、confidence据え置き
    return None


# ============================================================
# メイン突合処理
# ============================================================


def run_matching(
    conn: sqlite3.Connection,
    dry_run: bool = True,
) -> MatchResult:
    """
    全医師の資格情報を正規化・分析し、突合結果を返す。

    Args:
        conn: DB接続
        dry_run: Trueの場合はDB更新しない

    Returns:
        突合結果サマリー
    """
    result = MatchResult()

    # 全医師+クリニック情報を取得
    cursor = conn.execute(
        """
        SELECT d.id, d.clinic_id, d.name, d.board_certifications,
               d.profile_url, d.source,
               c.name as clinic_name, c.prefecture
        FROM doctors d
        JOIN clinics c ON d.clinic_id = c.id
        ORDER BY c.name, d.name
        """
    )
    rows = cursor.fetchall()
    result.total_doctors = len(rows)

    for row in rows:
        doctor_id = row[0]
        clinic_id = row[1]
        doctor_name = row[2]
        certs_json = row[3]
        profile_url = row[4]
        source = row[5]
        clinic_name = row[6]
        prefecture = row[7]

        # 既存の資格データをパース
        try:
            original_certs = json.loads(certs_json) if certs_json else []
        except (json.JSONDecodeError, TypeError):
            original_certs = []

        record = DoctorCertificationRecord(
            doctor_id=doctor_id,
            clinic_id=clinic_id,
            doctor_name=doctor_name,
            clinic_name=clinic_name,
            prefecture=prefecture,
            original_certifications=original_certs,
        )

        if not original_certs:
            result.doctors_without_certs += 1
            record.confidence_score = 0.0
            record.issues.append("資格情報なし")
            result.records.append(record)
            continue

        result.doctors_with_certs += 1

        # 正規化
        normalized = normalize_certifications(original_certs)
        record.normalized_certifications = normalized

        if normalized != original_certs:
            result.normalization_applied += 1

        # 重複除去数カウント
        removed_count = len(original_certs) - len(normalized)
        if removed_count > 0:
            result.duplicates_removed += removed_count

        # 資格カウント集計
        result.total_certifications += len(normalized)
        for cert in normalized:
            result.certification_counts[cert] = (
                result.certification_counts.get(cert, 0) + 1
            )

        # 高価値資格チェック
        has_high_value = any(
            cert in HIGH_VALUE_CERTIFICATIONS for cert in normalized
        )
        if has_high_value:
            result.high_value_cert_doctors += 1

        # 信頼性スコア算出
        record.confidence_score = calculate_confidence(
            normalized, clinic_name, bool(profile_url)
        )

        # 学会名簿突合（現在はスタブ）
        for cert in normalized:
            match_result = match_against_registry(doctor_name, cert, prefecture)
            if match_result:
                record.verification_source = "specialist_registry"
                record.confidence_score = max(record.confidence_score, 0.9)

        # 品質チェック
        _validate_certifications(record)

        result.records.append(record)

    result.unique_certifications = len(result.certification_counts)

    # DB更新（dry-runでなければ）
    if not dry_run:
        _update_database(conn, result)

    return result


def _validate_certifications(record: DoctorCertificationRecord) -> None:
    """
    資格情報の妥当性をチェックし、問題があればissuesに追加する。

    チェック項目:
    - 美容外科専門医のJSAPS/JSAS区別
    - 異常に多い資格数（信頼性低下の兆候）
    - 不自然な資格の組み合わせ
    """
    certs = record.normalized_certifications

    # JSAPS/JSAS未区別の「日本美容外科学会専門医」
    if "日本美容外科学会専門医" in certs:
        record.issues.append(
            "美容外科学会はJSAPSとJSASの2学会が存在。"
            "どちらの専門医か区別できません。"
        )

    # 資格数が異常に多い（7個以上は怪しい）
    if len(certs) > 7:
        record.issues.append(
            f"資格数が{len(certs)}個と多く、誤抽出の可能性があります。"
        )

    # 形成外科と美容外科の組み合わせは一般的
    # 形成外科のみで美容クリニック勤務は問題ない

    # 麻酔科専門医が美容外科を名乗るのは稀（ただし副業はありうる）


def _update_database(
    conn: sqlite3.Connection,
    result: MatchResult,
) -> None:
    """
    正規化された資格情報でDBを更新する。

    Args:
        conn: DB接続
        result: 突合結果
    """
    now = datetime.now(timezone.utc).isoformat()
    updated_count = 0

    for record in result.records:
        if not record.normalized_certifications:
            continue

        # 正規化後の資格で更新（元データと異なる場合のみ）
        if record.normalized_certifications != record.original_certifications:
            conn.execute(
                """
                UPDATE doctors
                SET board_certifications = ?,
                    source = CASE
                        WHEN ? = 'specialist_registry' THEN 'specialist_registry'
                        ELSE source
                    END,
                    fetched_at = ?
                WHERE id = ?
                """,
                (
                    json.dumps(record.normalized_certifications, ensure_ascii=False),
                    record.verification_source,
                    now,
                    record.doctor_id,
                ),
            )
            updated_count += 1
            logger.info(
                "更新: %s（%s） %s → %s",
                record.doctor_name,
                record.clinic_name,
                record.original_certifications,
                record.normalized_certifications,
            )

    conn.commit()
    logger.info("DB更新完了: %d件", updated_count)


# ============================================================
# CLI
# ============================================================


def main() -> None:
    """CLIエントリーポイント"""
    parser = argparse.ArgumentParser(
        description="専門医名簿突合スクリプト（C-2）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="DB更新を行わない（デフォルト: False）",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="DB更新を実行する",
    )
    args = parser.parse_args()

    dry_run = not args.execute or args.dry_run

    mode_label = "🔍 dry-runモード" if dry_run else "🚀 実行モード"
    print(f"{'=' * 60}")
    print("  AURA C-2: 専門医名簿突合スクリプト")
    print(f"  モード: {mode_label}")
    print(f"  DB: {DB_PATH}")
    print(f"{'=' * 60}")
    print()

    # 学会名簿突合の状況を表示
    print("📋 学会名簿アクセス状況:")
    for society_name, info in SPECIALIST_REGISTRIES.items():
        status_emoji = "✅" if info["status"] == "implemented" else "⏳"
        print(f"  {status_emoji} {society_name}: {info['status']}")
        print(f"     URL: {info['url']}")
        print(f"     備考: {info['note']}")
    print()
    print(
        "ℹ️  現在は公式サイトからの自己申告データを正規化・分析します。"
    )
    print(
        "   学会名簿との直接突合は将来のフェーズで実装予定です。"
    )
    print()

    if not DB_PATH.exists():
        logger.error("データベースが見つかりません: %s", DB_PATH)
        return

    conn = sqlite3.connect(str(DB_PATH))

    try:
        result = run_matching(conn, dry_run=dry_run)

        # サマリー表示
        print(f"{'=' * 60}")
        print("  突合結果サマリー")
        print(f"{'=' * 60}")
        print(f"  総医師数: {result.total_doctors}")
        print(f"  資格情報あり: {result.doctors_with_certs}")
        print(f"  資格情報なし: {result.doctors_without_certs}")
        print(f"  高価値資格保有: {result.high_value_cert_doctors}")
        print()
        print(f"  総資格数: {result.total_certifications}")
        print(f"  ユニーク資格種類: {result.unique_certifications}")
        print(f"  正規化適用: {result.normalization_applied}名")
        print(f"  重複除去: {result.duplicates_removed}件")
        print()

        if result.certification_counts:
            print("  資格別分布:")
            for cert, count in sorted(
                result.certification_counts.items(), key=lambda x: -x[1]
            ):
                is_high_value = "⭐" if cert in HIGH_VALUE_CERTIFICATIONS else "  "
                print(f"    {is_high_value} {cert}: {count}名")
            print()

        # 問題のあるレコードを表示
        issues_records = [r for r in result.records if r.issues]
        if issues_records:
            print(f"  ⚠ 確認が必要な医師: {len(issues_records)}名")
            for record in issues_records[:10]:
                print(f"    - {record.doctor_name}（{record.clinic_name}）")
                for issue in record.issues:
                    print(f"      → {issue}")
            if len(issues_records) > 10:
                print(f"    ... 他{len(issues_records) - 10}名")
            print()

        # 信頼性スコアの分布
        if result.records:
            scores = [r.confidence_score for r in result.records if r.confidence_score > 0]
            if scores:
                avg_score = sum(scores) / len(scores)
                print(f"  信頼性スコア平均: {avg_score:.2f}")
                print(f"  信頼性スコア分布:")
                brackets = [
                    ("0.0-0.3 (低)", 0.0, 0.3),
                    ("0.3-0.5 (中低)", 0.3, 0.5),
                    ("0.5-0.7 (中)", 0.5, 0.7),
                    ("0.7-0.9 (高)", 0.7, 0.9),
                    ("0.9-1.0 (最高)", 0.9, 1.01),
                ]
                for label, low, high in brackets:
                    bracket_count = sum(1 for s in scores if low <= s < high)
                    bar = "█" * bracket_count
                    print(f"    {label}: {bracket_count}名 {bar}")
                print()

        if dry_run:
            print("ℹ️  dry-runモードのため、DBの更新は行いませんでした。")
            print("   実行するには: --execute オプションを付けてください。")
        print()

    finally:
        conn.close()

    print("✅ 完了")


if __name__ == "__main__":
    main()
