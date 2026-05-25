"""
AURA MVP — データバリデーション & DB操作ヘルパー

DB書き込み前のデータ整合性チェックと、
監査ログ付きのCRUD操作を提供する。
"""

import json
from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import AuditLog, ClinicTable, DataVersion, ProcedureTable


# ==========================================
# バリデーション
# ==========================================

class ValidationError(Exception):
    """データバリデーションエラー"""
    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


def validate_clinic(data: dict) -> list[str]:
    """
    クリニックデータの整合性チェック

    Returns:
        警告メッセージのリスト（空なら問題なし）
    """
    warnings = []

    # 必須フィールド
    if not data.get("name"):
        raise ValidationError("name", "クリニック名は必須です")
    if not data.get("address"):
        raise ValidationError("address", "住所は必須です")

    # 名前の正規化チェック
    name = data["name"]
    if len(name) > 200:
        raise ValidationError("name", f"名前が長すぎます（{len(name)}文字、上限200文字）")

    # 緯度経度の範囲チェック（東京都周辺）
    lat = data.get("lat")
    lng = data.get("lng")
    if lat is not None:
        if not (34.0 <= lat <= 36.5):
            warnings.append(f"緯度が東京都の範囲外です: {lat}")
    if lng is not None:
        if not (138.5 <= lng <= 141.0):
            warnings.append(f"経度が東京都の範囲外です: {lng}")

    # 厚労省コードの形式チェック
    mhlw = data.get("mhlw_code")
    if mhlw and not mhlw.strip():
        warnings.append("mhlw_codeが空文字列です")

    # 診療科データのJSON検証
    depts = data.get("medical_departments")
    if depts and isinstance(depts, str):
        try:
            parsed = json.loads(depts)
            if not isinstance(parsed, list):
                warnings.append("medical_departmentsがリスト形式ではありません")
        except json.JSONDecodeError:
            raise ValidationError("medical_departments", "不正なJSON形式です")

    # 信頼度の範囲チェック
    conf = data.get("confidence")
    if conf is not None:
        if not (0.0 <= conf <= 1.0):
            raise ValidationError("confidence", f"信頼度は0.0〜1.0の範囲: {conf}")

    return warnings


def validate_procedure(data: dict) -> list[str]:
    """
    施術データの整合性チェック

    Returns:
        警告メッセージのリスト
    """
    warnings = []

    if not data.get("name"):
        raise ValidationError("name", "施術名は必須です")
    if not data.get("category"):
        raise ValidationError("category", "カテゴリは必須です")

    valid_categories = {"eye", "nose", "skin", "contour", "body", "other"}
    if data["category"] not in valid_categories:
        warnings.append(f"未知のカテゴリ: {data['category']}（有効: {valid_categories}）")

    valid_inv = {"low", "medium", "high"}
    inv = data.get("invasiveness", "")
    if inv and inv not in valid_inv:
        warnings.append(f"未知の侵襲度: {inv}（有効: {valid_inv}）")

    # JSON列の検証
    json_fields = [
        "matches_concern", "advertised_price", "real_price",
        "hidden_costs", "risks", "suitable_for", "not_suitable_for",
        "counseling_questions", "recovery_phases",
    ]
    for field in json_fields:
        val = data.get(field)
        if val and isinstance(val, str):
            try:
                json.loads(val)
            except json.JSONDecodeError:
                raise ValidationError(field, f"不正なJSON形式です")

    return warnings


# ==========================================
# 監査ログ記録
# ==========================================

async def log_audit(
    db: AsyncSession,
    table_name: str,
    record_id: str,
    action: str,
    changed_fields: dict | None = None,
    changed_by: str = "system",
    source: str | None = None,
):
    """監査ログを記録"""
    entry = AuditLog(
        table_name=table_name,
        record_id=record_id,
        action=action,
        changed_fields=json.dumps(changed_fields, ensure_ascii=False) if changed_fields else None,
        changed_by=changed_by,
        source=source,
        timestamp=datetime.now(),
    )
    db.add(entry)


# ==========================================
# データバージョン管理
# ==========================================

async def record_data_version(
    db: AsyncSession,
    source: str,
    version_key: str,
    record_count: int,
    status: str = "completed",
    metadata: dict | None = None,
    error_message: str | None = None,
):
    """データ取得バージョンを記録"""
    ver = DataVersion(
        source=source,
        version_key=version_key,
        record_count=record_count,
        status=status,
        started_at=datetime.now(),
        completed_at=datetime.now() if status == "completed" else None,
        error_message=error_message,
        metadata_json=json.dumps(metadata, ensure_ascii=False) if metadata else None,
    )
    db.add(ver)
    await db.flush()
    return ver


async def get_latest_version(db: AsyncSession, source: str) -> DataVersion | None:
    """指定ソースの最新データバージョンを取得"""
    result = await db.execute(
        select(DataVersion)
        .where(DataVersion.source == source, DataVersion.status == "completed")
        .order_by(DataVersion.completed_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


# ==========================================
# データ整合性チェック
# ==========================================

async def check_db_integrity(db: AsyncSession) -> dict:
    """
    DB全体の整合性を検査

    Returns:
        検査結果レポート
    """
    report = {
        "checked_at": datetime.now().isoformat(),
        "tables": {},
        "issues": [],
    }

    # テーブル別件数
    for model, name in [
        (ClinicTable, "clinics"),
        (ProcedureTable, "procedures"),
    ]:
        count = await db.scalar(select(func.count(model.id)))
        report["tables"][name] = {"count": count or 0}

    # クリニック: 必須フィールドのNULLチェック
    null_name = await db.scalar(
        select(func.count(ClinicTable.id)).where(ClinicTable.name.is_(None))
    )
    if null_name:
        report["issues"].append(f"クリニック: 名前がNULLのレコード {null_name}件")

    null_addr = await db.scalar(
        select(func.count(ClinicTable.id)).where(ClinicTable.address.is_(None))
    )
    if null_addr:
        report["issues"].append(f"クリニック: 住所がNULLのレコード {null_addr}件")

    # 施術: JSON列の破損チェック
    proc_result = await db.execute(select(ProcedureTable))
    procs = proc_result.scalars().all()
    broken_json_count = 0
    for proc in procs:
        for field in ["advertised_price", "real_price", "risks", "counseling_questions"]:
            val = getattr(proc, field)
            if val:
                try:
                    json.loads(val)
                except json.JSONDecodeError:
                    broken_json_count += 1
                    report["issues"].append(
                        f"施術 '{proc.name}': {field} のJSONが破損"
                    )
    report["tables"]["procedures"]["broken_json"] = broken_json_count

    # 施術: 必須フィールド充填率チェック
    required_fields = {
        "advertised_price": "広告価格",
        "real_price": "実際の相場",
        "risks": "リスク情報",
        "counseling_questions": "カウンセリング質問",
        "downtime_real": "実際のDT",
    }
    fill_rates = {}
    total_procs = len(procs)
    for field, label in required_fields.items():
        filled = sum(1 for p in procs if getattr(p, field) and getattr(p, field) not in ("", "[]", "{}"))
        rate = (filled / total_procs * 100) if total_procs > 0 else 0
        fill_rates[label] = f"{filled}/{total_procs} ({rate:.0f}%)"
        if rate < 100:
            report["issues"].append(f"施術: {label}の充填率 {rate:.0f}%（{total_procs - filled}件不足）")
    report["tables"]["procedures"]["fill_rates"] = fill_rates

    # 施術: エビデンスレベル分布
    evidence_dist = {}
    for proc in procs:
        level = getattr(proc, "evidence_level", "unverified") or "unverified"
        evidence_dist[level] = evidence_dist.get(level, 0) + 1
    report["tables"]["procedures"]["evidence_levels"] = evidence_dist

    # 施術: publish_status分布
    status_dist = {}
    for proc in procs:
        status = getattr(proc, "publish_status", "draft") or "draft"
        status_dist[status] = status_dist.get(status, 0) + 1
    report["tables"]["procedures"]["publish_status"] = status_dist

    unverified = evidence_dist.get("unverified", 0)
    if unverified > 0:
        report["issues"].append(f"施術: {unverified}件がエビデンス未検証")

    # クリニック: 重複チェック（同名・同住所）
    dup_result = await db.execute(
        select(ClinicTable.name, ClinicTable.address, func.count(ClinicTable.id).label("cnt"))
        .group_by(ClinicTable.name, ClinicTable.address)
        .having(func.count(ClinicTable.id) > 1)
    )
    dups = dup_result.all()
    if dups:
        report["issues"].append(
            f"クリニック: 名前+住所の重複 {len(dups)}組"
        )
        report["duplicates"] = [{"name": d[0], "address": d[1][:40], "count": d[2]} for d in dups[:10]]

    # データ鮮度チェック
    oldest_clinic = await db.scalar(
        select(func.min(ClinicTable.fetched_at))
    )
    if oldest_clinic:
        age_days = (datetime.now() - oldest_clinic).days
        report["data_freshness"] = {
            "oldest_record_days": age_days,
            "oldest_fetched_at": oldest_clinic.isoformat() if oldest_clinic else None,
        }
        if age_days > 180:
            report["issues"].append(
                f"データ鮮度: 最古のレコードが{age_days}日前の取得"
            )

    # データバージョン情報
    ver_result = await db.execute(
        select(DataVersion).where(DataVersion.status == "completed")
    )
    versions = ver_result.scalars().all()
    report["data_versions"] = [
        {
            "source": v.source,
            "version": v.version_key,
            "records": v.record_count,
            "date": v.completed_at.isoformat() if v.completed_at else None,
        }
        for v in versions
    ]

    report["issue_count"] = len(report["issues"])
    report["status"] = "healthy" if not report["issues"] else "issues_found"

    return report


# ==========================================
# バックアップ・エクスポート
# ==========================================

async def export_table_json(db: AsyncSession, table: str) -> list[dict]:
    """指定テーブルのデータをJSON形式でエクスポート"""
    model_map = {
        "clinics": ClinicTable,
        "procedures": ProcedureTable,
    }
    model = model_map.get(table)
    if not model:
        raise ValueError(f"未知のテーブル: {table}")

    result = await db.execute(select(model))
    rows = result.scalars().all()

    exported = []
    for row in rows:
        row_dict = {}
        for col in row.__table__.columns:
            val = getattr(row, col.name)
            if isinstance(val, datetime):
                val = val.isoformat()
            row_dict[col.name] = val
        exported.append(row_dict)

    return exported
