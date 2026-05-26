"""
AURA MVP — 入力サニタイズミドルウェア

ユーザー入力のXSS対策とSQLインジェクション検出。

機能:
1. リクエストボディ内のHTML/スクリプトタグをエスケープ
2. 危険なSQLパターンの検出・ログ
3. 入力長の制限
"""

import html
import json
import logging
import re
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# XSSパターン
XSS_PATTERNS = [
    re.compile(r'<script', re.IGNORECASE),
    re.compile(r'javascript:', re.IGNORECASE),
    re.compile(r'on\w+\s*=', re.IGNORECASE),  # onload=, onerror=, etc.
    re.compile(r'<iframe', re.IGNORECASE),
    re.compile(r'<object', re.IGNORECASE),
    re.compile(r'<embed', re.IGNORECASE),
]

# SQLインジェクションパターン（警告ログのみ）
SQL_PATTERNS = [
    re.compile(r"('\s*(OR|AND)\s*'?\s*\d+\s*=\s*\d+)", re.IGNORECASE),
    re.compile(r'(UNION\s+SELECT)', re.IGNORECASE),
    re.compile(r'(DROP\s+TABLE)', re.IGNORECASE),
    re.compile(r'(;\s*DELETE\s+FROM)', re.IGNORECASE),
    re.compile(r'(;\s*UPDATE\s+\w+\s+SET)', re.IGNORECASE),
]

# 入力最大長
MAX_INPUT_LENGTH = 10000  # 10KB（チャットメッセージ）
MAX_FIELD_LENGTH = 5000  # 5KB（一般フィールド）


def sanitize_string(value: str) -> str:
    """文字列からXSSリスクのある内容をエスケープする"""
    # HTMLタグをエスケープ
    sanitized = html.escape(value, quote=True)
    return sanitized


def check_xss(value: str) -> bool:
    """XSSパターンが含まれているか検出する"""
    for pattern in XSS_PATTERNS:
        if pattern.search(value):
            return True
    return False


def check_sql_injection(value: str) -> bool:
    """SQLインジェクションパターンが含まれているか検出する"""
    for pattern in SQL_PATTERNS:
        if pattern.search(value):
            return True
    return False


def sanitize_dict(data: Any, path: str = "") -> Any:
    """辞書/リスト内の全文字列を再帰的にサニタイズする"""
    if isinstance(data, str):
        if len(data) > MAX_FIELD_LENGTH:
            data = data[:MAX_FIELD_LENGTH]
            logger.warning(f"入力切り詰め: {path} ({len(data)}文字 → {MAX_FIELD_LENGTH}文字)")

        if check_xss(data):
            logger.warning(f"XSSパターン検出: path={path}, value={data[:100]!r}")
            data = sanitize_string(data)

        if check_sql_injection(data):
            logger.warning(f"SQLインジェクション疑い: path={path}, value={data[:100]!r}")
            # SQLAlchemy使用のため直接リスクは低いが、ログに記録

        return data

    elif isinstance(data, dict):
        return {k: sanitize_dict(v, f"{path}.{k}") for k, v in data.items()}

    elif isinstance(data, list):
        return [sanitize_dict(item, f"{path}[{i}]") for i, item in enumerate(data)]

    return data


class InputSanitizationMiddleware(BaseHTTPMiddleware):
    """入力サニタイズミドルウェア

    POSTリクエストのJSONボディをサニタイズし、
    XSSやSQLインジェクションのリスクを軽減する。
    """

    async def dispatch(self, request: Request, call_next):
        # POSTリクエストのみ対象
        if request.method in ("POST", "PUT", "PATCH"):
            content_type = request.headers.get("content-type", "")
            if "application/json" in content_type:
                try:
                    body = await request.body()

                    # ボディサイズ制限
                    if len(body) > MAX_INPUT_LENGTH:
                        return JSONResponse(
                            status_code=413,
                            content={
                                "error": "payload_too_large",
                                "message": f"リクエストボディが上限（{MAX_INPUT_LENGTH}バイト）を超えています",
                            },
                        )

                    data = json.loads(body)
                    sanitized = sanitize_dict(data, "body")

                    # サニタイズ後のボディでリクエストを再構築
                    sanitized_body = json.dumps(sanitized, ensure_ascii=False).encode("utf-8")

                    # リクエストのボディを上書き
                    async def receive():
                        return {"type": "http.request", "body": sanitized_body}

                    request._receive = receive

                except json.JSONDecodeError:
                    pass  # JSONでない場合はスキップ
                except Exception as e:
                    logger.error(f"入力サニタイズエラー: {e}")

        return await call_next(request)
