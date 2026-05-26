"""
AURA MVP — LLMクライアント

Anthropic Claude APIとの通信を管理する。
APIキーが未設定の場合はGeminiフォールバック → モックの順で切替。

設計方針:
- Claude優先、Geminiフォールバック、最終手段としてモック
- ストリーミング対応（将来用）
- レート制限・リトライ・タイムアウト管理
- 利用量の追跡
"""

import logging
from datetime import datetime

import anthropic

from src.config import settings

logger = logging.getLogger(__name__)


# Claude APIのモデル設定
DEFAULT_MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 4096  # 複雑な比較質問でも回答が途切れないよう拡大
TEMPERATURE = 0.4  # 医療情報は正確性重視で低めに設定

# Geminiライブラリの読み込み（未インストール時はフォールバック）
_genai = None
try:
    import google.generativeai as genai
    _genai = genai
except ImportError:
    logger.warning(
        "google-generativeai ライブラリが未インストールです。"
        "Geminiフォールバックは無効になります。"
        "有効にするには: pip install google-generativeai"
    )


def is_llm_available() -> bool:
    """LLM APIが利用可能か判定"""
    return bool(settings.anthropic_api_key)


async def _call_gemini(
    system_prompt: str,
    user_message: str,
    conversation_history: list[dict] | None = None,
    max_tokens: int = MAX_TOKENS,
    temperature: float = TEMPERATURE,
) -> dict:
    """
    Google Gemini APIを呼び出す（Claudeのフォールバック）

    Args:
        system_prompt: システムプロンプト
        user_message: ユーザーのメッセージ
        conversation_history: 過去の会話履歴
        max_tokens: 最大トークン数
        temperature: 温度パラメータ

    Returns:
        call_llm と同じ形式の辞書
    """
    if _genai is None:
        logger.error("google-generativeai が利用できないため、Geminiフォールバックをスキップ")
        return {
            "content": None,
            "model": "mock",
            "usage": {},
            "stop_reason": "gemini_unavailable",
            "latency_ms": 0,
            "source": "mock",
        }

    start = datetime.now()

    try:
        _genai.configure(api_key=settings.gemini_api_key)

        model = _genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            system_instruction=system_prompt,
        )

        # 会話履歴の組み立て
        history = []
        if conversation_history:
            for msg in conversation_history[-12:]:
                role = "user" if msg["role"] == "user" else "model"
                history.append({"role": role, "parts": [msg["content"]]})

        chat = model.start_chat(history=history)
        response = chat.send_message(
            user_message,
            generation_config=_genai.types.GenerationConfig(
                max_output_tokens=max_tokens,
                temperature=temperature,
            ),
        )

        latency = int((datetime.now() - start).total_seconds() * 1000)

        result = {
            "content": response.text,
            "model": "gemini-2.5-flash",
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "stop_reason": "end_turn",
            "latency_ms": latency,
            "source": "gemini",
        }

        logger.info(f"Gemini API: model=gemini-2.5-flash, latency={latency}ms")

        return result

    except Exception as e:
        latency = int((datetime.now() - start).total_seconds() * 1000)
        logger.error(f"Gemini API エラー: {e}")
        return {
            "content": None,
            "model": "gemini-2.5-flash",
            "usage": {},
            "stop_reason": "gemini_error",
            "latency_ms": latency,
            "source": "error",
            "error": f"Gemini API エラー: {str(e)[:200]}",
        }


async def call_llm(
    system_prompt: str,
    user_message: str,
    conversation_history: list[dict] | None = None,
    model: str = DEFAULT_MODEL,
    max_tokens: int = MAX_TOKENS,
    temperature: float = TEMPERATURE,
) -> dict:
    """
    Claude APIを呼び出す（エラー時はGeminiフォールバック）

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
            "source": "claude" | "gemini" | "mock" | "error",
        }
    """
    if not is_llm_available():
        # Claude APIキーなし → Geminiフォールバックを試行
        if settings.gemini_api_key and _genai is not None:
            logger.info("Claude APIキー未設定、Geminiにフォールバック")
            return await _call_gemini(
                system_prompt, user_message, conversation_history,
                max_tokens, temperature,
            )
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
        # 直近12件の会話を含める（マルチターンの文脈理解を改善）
        for msg in conversation_history[-12:]:
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

    except anthropic.AuthenticationError as e:
        logger.error("Claude API: 認証エラー（APIキーを確認してください）")
        # Geminiフォールバック
        if settings.gemini_api_key and _genai is not None:
            logger.warning(f"Claude API認証エラー、Geminiにフォールバック: {e}")
            return await _call_gemini(
                system_prompt, user_message, conversation_history,
                max_tokens, temperature,
            )
        return {
            "content": None,
            "model": model,
            "usage": {},
            "stop_reason": "auth_error",
            "latency_ms": int((datetime.now() - start).total_seconds() * 1000),
            "source": "error",
            "error": "APIキーが無効です。AURA_ANTHROPIC_API_KEYを確認してください。",
        }
    except anthropic.RateLimitError as e:
        logger.warning("Claude API: レート制限に到達")
        # Geminiフォールバック
        if settings.gemini_api_key and _genai is not None:
            logger.warning(f"Claude APIレート制限、Geminiにフォールバック: {e}")
            return await _call_gemini(
                system_prompt, user_message, conversation_history,
                max_tokens, temperature,
            )
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
        # Geminiフォールバック
        if settings.gemini_api_key and _genai is not None:
            logger.warning(f"Claude APIエラー、Geminiにフォールバック: {e}")
            return await _call_gemini(
                system_prompt, user_message, conversation_history,
                max_tokens, temperature,
            )
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
        # 予期しないエラーでもGeminiフォールバックを試行
        if settings.gemini_api_key and _genai is not None:
            logger.warning(f"Claude予期しないエラー、Geminiにフォールバック: {e}")
            return await _call_gemini(
                system_prompt, user_message, conversation_history,
                max_tokens, temperature,
            )
        return {
            "content": None,
            "model": model,
            "usage": {},
            "stop_reason": "unknown_error",
            "latency_ms": int((datetime.now() - start).total_seconds() * 1000),
            "source": "error",
            "error": f"予期しないエラー: {str(e)[:200]}",
        }


# ==========================================
# ストリーミング対応
# ==========================================

import asyncio
from typing import AsyncGenerator


async def _stream_mock(mock_text: str) -> AsyncGenerator[dict, None]:
    """
    モックテキストをストリーミング風に文字分割して yield する。

    Claude API未接続時のフォールバック。一文字ずつではなく
    数文字のチャンクに分割して自然なタイピング感を再現する。

    Yields:
        {"type": "delta", "content": "テキスト断片"}
        または {"type": "done", "model": "mock", "source": "mock"}
    """
    # 5文字ずつのチャンクに分割してyield
    chunk_size = 5
    for i in range(0, len(mock_text), chunk_size):
        chunk = mock_text[i:i + chunk_size]
        yield {"type": "delta", "content": chunk}
        await asyncio.sleep(0.02)  # 自然なタイピング感

    yield {
        "type": "done",
        "model": "mock",
        "source": "mock",
        "usage": {},
    }


async def stream_llm(
    system_prompt: str,
    user_message: str,
    conversation_history: list[dict] | None = None,
    model: str = DEFAULT_MODEL,
    max_tokens: int = MAX_TOKENS,
    temperature: float = TEMPERATURE,
    mock_text: str | None = None,
) -> AsyncGenerator[dict, None]:
    """
    Claude APIをストリーミングで呼び出す async generator。

    各テキストデルタを yield し、完了時にメタデータを返す。
    エラー時はGeminiフォールバック（一括yield）、
    APIキー未設定時はmock_textを文字分割してyield。

    Args:
        system_prompt: システムプロンプト
        user_message: ユーザーメッセージ
        conversation_history: 過去の会話履歴
        model: 使用モデル
        max_tokens: 最大トークン数
        temperature: 温度パラメータ
        mock_text: モック時に使用するテキスト

    Yields:
        {"type": "delta", "content": "テキスト断片"}
        {"type": "done", "model": str, "source": str, "usage": dict}
        {"type": "error", "message": str}
    """

    # --- APIキーなし → Geminiフォールバック or モック ---
    if not is_llm_available():
        # Geminiフォールバックを試行
        if settings.gemini_api_key and _genai is not None:
            logger.info("Claude APIキー未設定、Geminiにフォールバック（ストリーミング）")
            gemini_result = await _call_gemini(
                system_prompt, user_message, conversation_history,
                max_tokens, temperature,
            )
            if gemini_result["source"] != "error" and gemini_result["content"]:
                # Geminiはストリーミング未対応なので一括yield
                yield {"type": "delta", "content": gemini_result["content"]}
                yield {
                    "type": "done",
                    "model": gemini_result["model"],
                    "source": "gemini",
                    "usage": gemini_result.get("usage", {}),
                }
                return

        # モックフォールバック
        if mock_text:
            async for event in _stream_mock(mock_text):
                yield event
        else:
            yield {"type": "done", "model": "mock", "source": "mock", "usage": {}}
        return

    # --- メッセージ組み立て ---
    messages = []
    if conversation_history:
        for msg in conversation_history[-12:]:
            messages.append({
                "role": msg["role"],
                "content": msg["content"],
            })
    messages.append({
        "role": "user",
        "content": user_message,
    })

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    start = datetime.now()

    try:
        # Claude APIストリーミング呼び出し
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                yield {"type": "delta", "content": text}

            # ストリーム完了後にメタデータを取得
            response = stream.get_final_message()
            latency = int((datetime.now() - start).total_seconds() * 1000)

            logger.info(
                f"Claude Streaming: model={response.model}, "
                f"in={response.usage.input_tokens}, out={response.usage.output_tokens}, "
                f"latency={latency}ms"
            )

            yield {
                "type": "done",
                "model": response.model,
                "source": "claude",
                "usage": {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
            }

    except (anthropic.AuthenticationError, anthropic.RateLimitError, anthropic.APIError) as e:
        logger.warning(f"Claude Streaming エラー、フォールバック試行: {e}")
        # Geminiフォールバック（一括yield）
        if settings.gemini_api_key and _genai is not None:
            gemini_result = await _call_gemini(
                system_prompt, user_message, conversation_history,
                max_tokens, temperature,
            )
            if gemini_result["source"] != "error" and gemini_result["content"]:
                yield {"type": "delta", "content": gemini_result["content"]}
                yield {
                    "type": "done",
                    "model": gemini_result["model"],
                    "source": "gemini",
                    "usage": gemini_result.get("usage", {}),
                }
                return

        # フォールバックも失敗 → モック or エラー
        if mock_text:
            async for event in _stream_mock(mock_text):
                yield event
        else:
            yield {"type": "error", "message": f"API通信エラー: {str(e)[:200]}"}

    except Exception as e:
        logger.error(f"LLMストリーミングエラー: {e}")
        # Geminiフォールバック
        if settings.gemini_api_key and _genai is not None:
            gemini_result = await _call_gemini(
                system_prompt, user_message, conversation_history,
                max_tokens, temperature,
            )
            if gemini_result["source"] != "error" and gemini_result["content"]:
                yield {"type": "delta", "content": gemini_result["content"]}
                yield {
                    "type": "done",
                    "model": gemini_result["model"],
                    "source": "gemini",
                    "usage": gemini_result.get("usage", {}),
                }
                return

        if mock_text:
            async for event in _stream_mock(mock_text):
                yield event
        else:
            yield {"type": "error", "message": f"予期しないエラー: {str(e)[:200]}"}
