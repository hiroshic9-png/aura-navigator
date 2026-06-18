# AURA — 美容医療、受ける前に知っておきたいこと

> 美容医療の患者に、初めての味方を。

[デモ](https://aura-mvp.onrender.com) | [技術スタック](#技術スタック)

## 概要

AURAは、美容医療の広告ではわからない情報——実際の価格、リスク、ダウンタイム、カウンセリングで聞くべき質問——を提供するモバイルファーストのPWAです。

## 主な機能

- 🏥 **クリニック検索**: 厚生労働省認可1,358施設のデータベース
- 📊 **施術情報**: 広告価格 vs 実勢価格、DT、リスク
- 💬 **AIアドバイザー**: Claude Sonnetベースの相談機能
- 🌙 **ダークモード**: OS連動 + 手動切替
- ♿ **アクセシビリティ**: WCAG AA準拠
- 📱 **PWA**: オフライン対応 + インストール可能

## 技術スタック

| レイヤー | 技術 |
|---------|------|
| Backend | FastAPI + SQLAlchemy + aiosqlite |
| Frontend | Vanilla JS + CSS (3,500+ lines) |
| AI | Anthropic Claude Sonnet 4 + Geminiフォールバック |
| Deploy | Docker + Render |
| Data | SQLite (厚生労働省 1,358施設) |

## クイックスタート

### ローカル開発

```bash
cd backend
uv sync
uv run python -m uvicorn src.main:app --port 8400 --reload
```

http://127.0.0.1:8400 でアクセス

### Docker

```bash
docker compose up -d
```

### テスト

```bash
uv run python -m pytest tests/ -v
```

## 環境変数

| 変数 | 説明 | デフォルト |
|------|------|----------|
| `AURA_ANTHROPIC_API_KEY` | Claude APIキー | なし（モックモード） |
| `AURA_GOOGLE_MAPS_API_KEY` | Google Maps APIキー | なし |
| `AURA_DATABASE_URL` | DB接続文字列 | `sqlite+aiosqlite:///data/aura.db` |
| `AURA_DEBUG` | デバッグモード | `true` |
| `AURA_ADMIN_KEY` | 管理API認証キー | なし |

## APIエンドポイント

| エンドポイント | 説明 |
|--------------|------|
| `GET /api/health` | ヘルスチェック |
| `GET /api/clinics/` | クリニック一覧 |
| `GET /api/clinics/suggest?q=` | 検索サジェスト |
| `GET /api/clinics/nearby` | 近隣検索 |
| `GET /api/procedures/` | 施術一覧 |
| `POST /api/advisor/chat` | AIチャット |
| `GET /api/analysis/price-gaps` | 価格分析 |

## ライセンス

MIT
