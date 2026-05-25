"""
AURA MVP — FastAPIメインアプリケーション

美容医療の患者に、初めての味方を。
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from src.config import settings
from src.db.database import init_db

# ログ設定
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("aura")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """アプリケーションの起動・終了処理"""
    logger.info(f"AURA MVP v{settings.app_version} を起動中...")
    await init_db()
    logger.info("DB初期化完了")
    yield
    logger.info("AURA MVP シャットダウン")


# 本番環境ではSwagger UIを非表示
docs_url = "/docs" if settings.debug else None
redoc_url = "/redoc" if settings.debug else None

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="美容医療の患者に、初めての味方を。クリニックDB + AIアドバイザーのMVP API",
    lifespan=lifespan,
    docs_url=docs_url,
    redoc_url=redoc_url,
)


# セキュリティヘッダーミドルウェア
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """レスポンスにセキュリティヘッダーを追加"""
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response


app.add_middleware(SecurityHeadersMiddleware)

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:8400",
        "http://127.0.0.1:8400",
        "https://aura-navi.vercel.app",
        "https://*.onrender.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    """APIヘルスチェック"""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "running",
    }


@app.get("/stats")
async def stats():
    """DB統計情報"""
    from sqlalchemy import func, select

    from src.db.database import AsyncSessionLocal, ClinicTable, ProcedureTable, ReviewTable

    async with AsyncSessionLocal() as session:
        clinic_count = await session.scalar(select(func.count(ClinicTable.id)))
        procedure_count = await session.scalar(select(func.count(ProcedureTable.id)))
        review_count = await session.scalar(select(func.count(ReviewTable.id)))

    return {
        "clinics": clinic_count or 0,
        "procedures": procedure_count or 0,
        "reviews": review_count or 0,
    }


# APIルーター
from src.api.clinics import router as clinics_router
from src.api.procedures import router as procedures_router
from src.api.analysis import router as analysis_router
from src.api.advisor import router as advisor_router
from src.api.db_admin import router as db_admin_router

app.include_router(clinics_router, prefix="/api/clinics", tags=["clinics"])
app.include_router(procedures_router, prefix="/api/procedures", tags=["procedures"])
app.include_router(analysis_router, prefix="/api/analysis", tags=["analysis"])
app.include_router(advisor_router, prefix="/api/advisor", tags=["advisor"])
app.include_router(db_admin_router, prefix="/api/db", tags=["db-admin"])


# 静的ファイル配信（フロントエンド）
STATIC_DIR = Path(__file__).parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ルートパスでフロントエンドを返す（/api/* より後に配置）
@app.get("/")
async def serve_root():
    """ルートパスでフロントエンドのindex.htmlを返却"""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path), media_type="text/html")
    return {"name": settings.app_name, "version": settings.app_version}
