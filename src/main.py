"""
AURA MVP — FastAPIメインアプリケーション

美容医療の患者に、初めての味方を。
"""

import logging
import time
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
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

# レート制限設定
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="美容医療の患者に、初めての味方を。クリニックDB + AIアドバイザーのMVP API",
    lifespan=lifespan,
    docs_url=docs_url,
    redoc_url=redoc_url,
)

# レート制限をアプリに紐付け
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# グローバル例外ハンドラー
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """未処理例外をキャッチし、構造化されたエラーレスポンスを返す"""
    logger.error(
        f"未処理例外: {type(exc).__name__}: {exc}\n"
        f"パス: {request.method} {request.url.path}\n"
        f"{traceback.format_exc()}"
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": "サーバー内部エラーが発生しました。しばらく後にお試しください。",
            "path": str(request.url.path),
        },
    )


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    """404エラーの構造化レスポンス"""
    return JSONResponse(
        status_code=404,
        content={
            "error": "not_found",
            "message": "指定されたリソースが見つかりません。",
            "path": str(request.url.path),
        },
    )


@app.exception_handler(422)
async def validation_error_handler(request: Request, exc):
    """バリデーションエラーの構造化レスポンス"""
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "message": "リクエストの入力値が不正です。",
            "path": str(request.url.path),
        },
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


# リクエストログミドルウェア
class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """APIリクエストのログを記録する"""
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        duration_ms = (time.time() - start) * 1000
        # 静的ファイルはログしない
        if not request.url.path.startswith("/static"):
            logger.info(
                f"{request.method} {request.url.path} → {response.status_code} ({duration_ms:.0f}ms)"
            )
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
app.add_middleware(RequestLoggingMiddleware)

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
@limiter.exempt
async def health(request: Request):
    """APIヘルスチェック（レート制限対象外）"""
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
from src.api.favorites import router as favorites_router

app.include_router(clinics_router, prefix="/api/clinics", tags=["clinics"])
app.include_router(procedures_router, prefix="/api/procedures", tags=["procedures"])
app.include_router(analysis_router, prefix="/api/analysis", tags=["analysis"])
app.include_router(advisor_router, prefix="/api/advisor", tags=["advisor"])
app.include_router(db_admin_router, prefix="/api/db", tags=["db-admin"])
app.include_router(favorites_router, prefix="/api", tags=["favorites"])


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
