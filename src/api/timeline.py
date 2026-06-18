"""
AURA MVP — 施術タイムラインAPI

施術後の回復フェーズ（ダウンタイム）の詳細タイムラインを提供。
recovery_phasesデータがある場合はそれを構造化し、
ない場合はダウンタイム情報からシンプルなタイムラインを自動生成する。
"""

import json
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import ProcedureTable, get_db

router = APIRouter()


@router.get("/{procedure_id}/timeline")
async def get_procedure_timeline(
    procedure_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    施術タイムラインを取得

    施術後の回復フェーズ（腫れ・赤み等）を時系列で返却。
    recovery_phasesデータがある場合はそのまま返し、
    ない場合はdowntime情報からシンプルなタイムラインを自動生成。
    """
    result = await db.execute(
        select(ProcedureTable).where(ProcedureTable.id == procedure_id)
    )
    procedure = result.scalar_one_or_none()

    if not procedure:
        raise HTTPException(status_code=404, detail="施術が見つかりません")

    # recovery_phasesをパース
    phases = _parse_recovery_phases(procedure.recovery_phases)

    # データがない場合はダウンタイム情報から自動生成
    if not phases:
        phases = _generate_simple_timeline(
            procedure.downtime_official,
            procedure.downtime_real,
        )

    # 満足度データから完了月数を取得
    satisfaction = _parse_json(procedure.satisfaction)
    completion_months = (
        satisfaction.get("completion_months")
        if isinstance(satisfaction, dict)
        else None
    )

    # 総回復日数を推定
    total_recovery_days = _estimate_total_recovery_days(
        phases, procedure.downtime_real or procedure.downtime_official
    )

    return {
        "procedure_id": procedure.id,
        "procedure_name": procedure.name,
        "downtime": {
            "official": procedure.downtime_official,
            "real": procedure.downtime_real,
        },
        "phases": phases,
        "total_recovery_days": total_recovery_days,
        "completion_months": completion_months,
    }


def _parse_json(value: str | None) -> list | dict:
    """JSON文字列をパース。失敗時は空リスト/空辞書を返却"""
    if not value:
        return []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []


def _parse_recovery_phases(raw: str | None) -> list[dict]:
    """recovery_phasesカラムのJSONをパースし構造化されたフェーズリストを返却"""
    if not raw:
        return []

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []

    if not isinstance(data, list) or len(data) == 0:
        return []

    phases = []
    for i, phase in enumerate(data):
        if not isinstance(phase, dict):
            continue
        phases.append({
            "phase_number": phase.get("phase_number", i + 1),
            "label": phase.get("label", f"フェーズ{i + 1}"),
            "duration": phase.get("duration", ""),
            "symptoms": phase.get("symptoms", []),
            "do": phase.get("do", []),
            "avoid": phase.get("avoid", []),
        })

    return phases


def _generate_simple_timeline(
    official: str | None,
    real: str | None,
) -> list[dict]:
    """ダウンタイム情報からシンプルな2-3フェーズのタイムラインを自動生成"""
    # ダウンタイム情報すらない場合は空リスト
    if not official and not real:
        return []

    dt_text = real or official or ""

    # 日数を推定（テキストから数値を抽出）
    estimated_days = _extract_days(dt_text)

    phases = [
        {
            "phase_number": 1,
            "label": "施術直後",
            "duration": "当日",
            "symptoms": ["腫れ", "赤み"],
            "do": ["安静にする", "患部を冷却する"],
            "avoid": ["入浴", "飲酒", "激しい運動"],
        },
    ]

    if estimated_days >= 3:
        phases.append({
            "phase_number": 2,
            "label": "回復初期",
            "duration": f"2日〜{min(estimated_days, 7)}日",
            "symptoms": ["腫れの軽減", "内出血（場合あり）"],
            "do": ["処方薬の使用", "紫外線対策"],
            "avoid": ["化粧（患部）", "サウナ", "過度な飲酒"],
        })

    if estimated_days >= 7:
        phases.append({
            "phase_number": 3 if estimated_days >= 3 else 2,
            "label": "回復後期",
            "duration": f"{min(estimated_days, 7) + 1}日〜{estimated_days}日",
            "symptoms": ["ほぼ通常の状態に回復"],
            "do": ["通常生活に段階的に復帰", "経過観察"],
            "avoid": ["患部への強い刺激"],
        })

    return phases


def _extract_days(text: str) -> int:
    """ダウンタイムテキストから日数を推定する"""
    if not text:
        return 3  # デフォルト

    # 「X日」パターン
    match = re.search(r"(\d+)\s*日", text)
    if match:
        return int(match.group(1))

    # 「X週間」パターン
    match = re.search(r"(\d+)\s*週間?", text)
    if match:
        return int(match.group(1)) * 7

    # 「Xヶ月」パターン
    match = re.search(r"(\d+)\s*[ヶか]?月", text)
    if match:
        return int(match.group(1)) * 30

    # 「ほぼなし」「なし」
    if "なし" in text:
        return 1

    return 3  # デフォルト


def _estimate_total_recovery_days(phases: list[dict], downtime_text: str | None) -> int:
    """総回復日数を推定"""
    if downtime_text:
        return _extract_days(downtime_text)

    # フェーズ情報から推定（最後のフェーズのdurationを参照）
    if phases:
        last_phase = phases[-1]
        duration = last_phase.get("duration", "")
        match = re.search(r"(\d+)\s*日", duration)
        if match:
            return int(match.group(1))

    return 3  # デフォルト
