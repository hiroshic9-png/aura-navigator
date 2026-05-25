# AURA MVP — 美容医療の患者に、初めての味方を

## 概要

美容医療クリニックのデータベースとAIアドバイザーを統合したMVPバックエンド。

**主な機能:**
- 🏥 1,358施設のクリニックデータベース（厚労省認可施設）
- 👨‍⚕️ 4,913名の医師情報（専門医資格688名）
- 💊 28施術 × 3,765件のクリニック別施術データ
- 💬 1,652件のGoogle口コミ（感情分析済み）
- 🔍 6軸品質スコアリング + パーソナライズド推薦
- 📊 AURA透明性スコア（9軸100pt）
- 🤖 Claude APIベースのAIアドバイザー

## ローカル開発

```bash
# 依存関係インストール
uv sync

# サーバー起動
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
| GET | `/api/clinics/` | クリニック一覧 |
| GET | `/api/clinics/{id}` | クリニック詳細 |
| GET | `/api/procedures/` | 施術一覧 |
| POST | `/api/advisor/chat` | AIアドバイザー |
| GET | `/stats` | DB統計 |

## 技術スタック

- **Backend**: FastAPI + SQLAlchemy + aiosqlite
- **Frontend**: Vanilla HTML/CSS/JS（エディトリアルデザイン）
- **DB**: SQLite（12MB、8テーブル）
- **AI**: Anthropic Claude API
- **Deploy**: Docker + Render（永続ディスク）

## ライセンス

Private — All rights reserved.
