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


# 管理APIアクセス制限ミドルウェア
class AdminApiProtectionMiddleware(BaseHTTPMiddleware):
    """管理API（/api/db/）を本番環境で保護

    debugモード以外では、API_ADMIN_KEYヘッダーによる認証を要求する。
    これにより/api/db/export/等の管理エンドポイントへの不正アクセスを防止。
    """
    async def dispatch(self, request: Request, call_next):
        import os
        from fastapi.responses import JSONResponse

        # 管理APIパスのみ対象
        if request.url.path.startswith("/api/db/"):
            # デバッグモードではスキップ
            if not settings.debug:
                admin_key = os.environ.get("AURA_ADMIN_KEY", "")
                request_key = request.headers.get("X-Admin-Key", "")
                # キーが未設定の場合は全てブロック
                if not admin_key or request_key != admin_key:
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "管理APIへのアクセスが拒否されました"},
                    )
        return await call_next(request)


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(AdminApiProtectionMiddleware)

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
    """DB統計情報（ヒーロー統計で使用）"""
    from sqlalchemy import func, select

    from src.db.database import AsyncSessionLocal, ClinicTable, DoctorTable, ProcedureTable, ReviewTable

    async with AsyncSessionLocal() as session:
        clinic_count = await session.scalar(select(func.count(ClinicTable.id)))
        procedure_count = await session.scalar(select(func.count(ProcedureTable.id)))
        doctor_count = await session.scalar(select(func.count(DoctorTable.id)))
        review_count = await session.scalar(select(func.count(ReviewTable.id)))

    return {
        "clinics": clinic_count or 0,
        "procedures": procedure_count or 0,
        "doctors": doctor_count or 0,
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


# SPAルーティング対応 — フロントエンドのルートを全てindex.htmlにフォールバック
SPA_ROUTES = ["/", "/procedures", "/clinics", "/advisor"]


@app.get("/")
async def serve_root():
    """ルートパスでフロントエンドのindex.htmlを返却"""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path), media_type="text/html")
    return {"name": settings.app_name, "version": settings.app_version}


@app.get("/procedures")
@app.get("/clinics")
@app.get("/advisor")
async def serve_spa_route():
    """SPA用ルート — ブラウザの戻る/進むボタンに対応

    /procedures, /clinics, /advisor へのGETリクエストでも
    index.htmlを返し、フロントエンドのJSがルーティングを処理する。
    """
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path), media_type="text/html")
    return {"name": settings.app_name, "version": settings.app_version}
