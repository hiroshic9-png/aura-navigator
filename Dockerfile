FROM python:3.12-slim

# システム依存パッケージ
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# uvインストール
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# 依存関係のインストール（レイヤーキャッシュ活用）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# アプリケーションコード
COPY src/ src/
COPY static/ static/
COPY start.py start.py

# 初期DBデータ（永続ディスクが空の場合にコピーされる）
COPY data/aura.db data/aura.db

# データディレクトリ（永続ディスクのマウントポイント）
RUN mkdir -p /data

# セキュリティ: 非rootユーザーで実行
RUN useradd -m -s /bin/bash aura && \
    chown -R aura:aura /app /data
USER aura

# 環境変数
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# ポート
EXPOSE 8400

# ヘルスチェック（stdlib のみ使用、外部ライブラリ不要）
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8400/api/health')" || exit 1

# 起動コマンド（start.pyが永続ディスクのDB管理を行う）
CMD ["uv", "run", "python", "start.py"]
