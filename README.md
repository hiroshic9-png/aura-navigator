# AURA MVP — 美容医療の患者に、初めての味方を

## 概要

美容医療クリニックのデータベースとAIアドバイザーを統合したMVPバックエンド。

**主な機能:**
- 🏥 1,358施設のクリニックデータベース（厚労省認可施設）
- 👨‍⚕️ 1,583名の医師情報（名寄せ済み、専門医資格539名）
- 💊 28施術 × 3,765件のクリニック別施術データ（description 100%充填）
- 💬 5,233件のGoogle口コミ（感情分析済み: 😊64% / 😐26% / 😞10%）
- 🔍 6軸品質スコアリング + パーソナライズド推薦
- 📊 AURA透明性スコア（9軸100pt）
- 🤖 Claude APIベースのAIアドバイザー（ストリーミング対応）
- ⚡ SSEストリーミングチャット（リアルタイムレスポンス）

## ローカル開発

```bash
# 依存関係インストール
uv sync

# サーバー起動
uv run python start.py

# または直接起動
uv run python -m uvicorn src.main:app --host 127.0.0.1 --port 8400

# ブラウザで表示
open http://127.0.0.1:8400
```

## Renderデプロイ

### 1. GitHubリポジトリ作成

```bash
# GitHubでリポジトリ作成後
git remote add origin git@github.com:YOUR_USER/aura-mvp.git
git push -u origin main
```

### 2. Render設定

1. [Render Dashboard](https://dashboard.render.com/) にログイン
2. 「New +」→「Blueprint」→ GitHubリポジトリを選択
3. `render.yaml` が自動検出される
4. 環境変数を設定:
   - `AURA_ANTHROPIC_API_KEY`: Claude APIキー
   - `AURA_GOOGLE_MAPS_API_KEY`: Google Maps APIキー

### 3. デプロイ確認

デプロイ完了後、以下のURLでヘルスチェック:
```
https://aura-mvp.onrender.com/api/health
```

## API エンドポイント

| メソッド | パス | 説明 |
|---------|------|------|
| GET | `/` | フロントエンド |
| GET | `/api/health` | ヘルスチェック |
| GET | `/stats` | DB統計（動的） |
| GET | `/api/clinics/` | クリニック一覧（検索・フィルタ） |
| GET | `/api/clinics/{id}` | クリニック詳細 |
| GET | `/api/clinics/stats` | クリニック統計 |
| GET | `/api/procedures/` | 施術一覧（カテゴリ・悩み・侵襲度フィルタ） |
| GET | `/api/procedures/{id}` | 施術詳細 |
| GET | `/api/procedures/stats` | 施術統計 |
| GET | `/api/procedures/compare` | 施術比較 |
| GET | `/api/analysis/price-gaps` | 価格乖離分析 |
| POST | `/api/advisor/chat` | AIアドバイザー（同期） |
| POST | `/api/advisor/chat/stream` | AIアドバイザー（SSEストリーミング） |
| GET | `/api/advisor/concerns` | 対応可能な悩み一覧 |
| GET | `/api/advisor/status` | アドバイザーステータス |

## 技術スタック

- **Backend**: FastAPI + SQLAlchemy + aiosqlite
- **Frontend**: Vanilla HTML/CSS/JS（エディトリアルデザイン）
- **DB**: SQLite（12MB、8テーブル）
- **AI**: Anthropic Claude API（ストリーミング対応）
- **Deploy**: Docker + Render（永続ディスク）

## ライセンス

Private — All rights reserved.
