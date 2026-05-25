"""
AURA MVP — LLMクライアント

Anthropic Claude APIとの通信を管理する。
APIキーが未設定の場合はモックレスポンスにフォールバック。

設計方針:
- APIキーの有無で自動切替
- ストリーミング対応（将来用）
- レート制限・リトライ・タイムアウト管理
- 利用量の追跡
"""

import json
import logging
from datetime import datetime

import anthropic

from src.config import settings

logger = logging.getLogger(__name__)


# Claude APIのモデル設定
DEFAULT_MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 2048
TEMPERATURE = 0.4  # 医療情報は正確性重視で低めに設定


def is_llm_available() -> bool:
    """LLM APIが利用可能か判定"""
    return bool(settings.anthropic_api_key)


async def call_llm(
    system_prompt: str,
    user_message: str,
    conversation_history: list[dict] | None = None,
    model: str = DEFAULT_MODEL,
    max_tokens: int = MAX_TOKENS,
    temperature: float = TEMPERATURE,
) -> dict:
    """
    Claude APIを呼び出す

    Args:
        system_prompt: システムプロンプト（AURA人格 + データコンテキスト）
        user_message: ユーザーのメッセージ
        conversation_history: 過去の会話（[{"role": "user"|"assistant", "content": str}]）
        model: 使用するモデル
        max_tokens: 最大トークン数
        temperature: 温度パラメータ

    Returns:
        {
            "content": str,        # レスポンステキスト
            "model": str,          # 使用モデル
            "usage": dict,         # トークン使用量
            "stop_reason": str,    # 停止理由
            "latency_ms": int,     # レイテンシ（ミリ秒）
            "source": "claude",    # レスポンスソース
        }
    """
    if not is_llm_available():
        return {
            "content": None,
            "model": "mock",
            "usage": {},
            "stop_reason": "no_api_key",
            "latency_ms": 0,
            "source": "mock",
        }

    # メッセージ組み立て
    messages = []
    if conversation_history:
        # 直近の会話を含める（コンテキストウィンドウに収まるよう制限）
        for msg in conversation_history[-8:]:
            messages.append({
                "role": msg["role"],
                "content": msg["content"],
            })

    # 現在のユーザーメッセージ
    messages.append({
        "role": "user",
        "content": user_message,
    })

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    start = datetime.now()
    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=messages,
        )

        latency = int((datetime.now() - start).total_seconds() * 1000)

        result = {
            "content": response.content[0].text if response.content else "",
            "model": response.model,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
            "stop_reason": response.stop_reason,
            "latency_ms": latency,
            "source": "claude",
        }

        logger.info(
            f"Claude API: model={response.model}, "
            f"in={response.usage.input_tokens}, out={response.usage.output_tokens}, "
            f"latency={latency}ms"
        )

        return result

    except anthropic.AuthenticationError:
        logger.error("Claude API: 認証エラー（APIキーを確認してください）")
        return {
            "content": None,
            "model": model,
            "usage": {},
            "stop_reason": "auth_error",
            "latency_ms": int((datetime.now() - start).total_seconds() * 1000),
            "source": "error",
            "error": "APIキーが無効です。AURA_ANTHROPIC_API_KEYを確認してください。",
        }
    except anthropic.RateLimitError:
        logger.warning("Claude API: レート制限に到達")
        return {
            "content": None,
            "model": model,
            "usage": {},
            "stop_reason": "rate_limit",
            "latency_ms": int((datetime.now() - start).total_seconds() * 1000),
            "source": "error",
            "error": "APIのレート制限に到達しました。しばらくお待ちください。",
        }
    except anthropic.APIError as e:
        logger.error(f"Claude API エラー: {e}")
        return {
            "content": None,
            "model": model,
            "usage": {},
            "stop_reason": "api_error",
            "latency_ms": int((datetime.now() - start).total_seconds() * 1000),
            "source": "error",
            "error": f"API通信エラーが発生しました: {str(e)[:200]}",
        }
    except Exception as e:
        logger.error(f"LLM呼び出しエラー: {e}")
        return {
            "content": None,
            "model": model,
            "usage": {},
            "stop_reason": "unknown_error",
            "latency_ms": int((datetime.now() - start).total_seconds() * 1000),
            "source": "error",
            "error": f"予期しないエラー: {str(e)[:200]}",
        }
