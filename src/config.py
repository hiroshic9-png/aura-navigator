"""
AURA MVP バックエンド設定モジュール

環境変数からの設定読み込みを管理する。
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """アプリケーション設定"""

    # アプリケーション
    app_name: str = "AURA MVP API"
    app_version: str = "0.1.0"
    debug: bool = False

    # データベース
    database_url: str = "sqlite+aiosqlite:///./data/aura.db"

    # Google Maps Places API
    google_maps_api_key: str = ""
    google_maps_max_results: int = 20  # 1リクエストあたりの最大結果数

    # LLM設定
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    default_llm: str = "claude"  # "claude" or "gemini"

    # 対象地域
    target_prefecture: str = "東京都"

    model_config = {"env_file": ".env", "env_prefix": "AURA_"}


settings = Settings()
