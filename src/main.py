"""
AURA MVP — FastAPIメインアプリケーション

美容医療の患者に、初めての味方を。
"""

import asyncio
import logging
import sys
import time
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware

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

    # セッションクリーンアップのバックグラウンドタスク
    cleanup_task = asyncio.create_task(_periodic_session_cleanup())

    yield

    # シャットダウン時にクリーンアップタスクを停止
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    logger.info("AURA MVP シャットダウン")


async def _periodic_session_cleanup():
    """古いセッションを1時間ごとにクリーンアップ"""
    from src.advisor.engine import cleanup_old_sessions
    while True:
        await asyncio.sleep(3600)  # 1時間ごと
        try:
            cleanup_old_sessions(max_age_hours=24)
            logger.info("セッションクリーンアップ完了")
        except Exception as e:
            logger.warning(f"セッションクリーンアップエラー: {e}")


# 本番環境ではSwagger UIを非表示
docs_url = "/docs" if settings.debug else None
redoc_url = "/redoc" if settings.debug else None

# レート制限設定（共有インスタンスを使用）
from src.rate_limit import limiter

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
    """レスポンスにセキュリティヘッダーとキャッシュ制御を追加"""
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        # 静的アセットのキャッシュ制御
        path = request.url.path
        if path.startswith("/static/css/") or path.startswith("/static/js/"):
            # CSS/JS: 1時間キャッシュ + 再検証
            response.headers["Cache-Control"] = "public, max-age=3600, must-revalidate"
        elif path.startswith("/static/icons/"):
            # アイコン: 1週間キャッシュ
            response.headers["Cache-Control"] = "public, max-age=604800, immutable"
        elif path.startswith("/static/"):
            # その他の静的ファイル: 10分
            response.headers["Cache-Control"] = "public, max-age=600"
        elif path.startswith("/api/"):
            # API: キャッシュなし
            response.headers["Cache-Control"] = "no-store"

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


# GZip圧縮（500バイト以上のレスポンスを圧縮）
app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(AdminApiProtectionMiddleware)
app.add_middleware(RequestLoggingMiddleware)

# 入力サニタイズ（XSS/SQLインジェクション対策）
from src.middleware.sanitize import InputSanitizationMiddleware
app.add_middleware(InputSanitizationMiddleware)

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:8400",
        "http://127.0.0.1:8400",
        "https://aura-navi.vercel.app",
        "https://aura-mvp.onrender.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
@limiter.exempt
async def health(request: Request):
    """APIヘルスチェック（レート制限対象外）

    DB接続、LLM設定、データ統計を確認。
    """
    health_status = {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "healthy",
        "checks": {},
    }

    # DB接続チェック
    try:
        from src.db.database import AsyncSessionLocal
        from sqlalchemy import text as sa_text

        async with AsyncSessionLocal() as session:
            result = await session.execute(sa_text("SELECT COUNT(*) FROM clinics"))
            clinic_count = result.scalar()
            health_status["checks"]["database"] = {
                "status": "ok",
                "clinics": clinic_count,
            }
    except Exception as e:
        health_status["checks"]["database"] = {"status": "error", "message": str(e)}
        health_status["status"] = "degraded"

    # LLM設定チェック
    llm_configured = bool(settings.anthropic_api_key)
    health_status["checks"]["llm"] = {
        "status": "ok" if llm_configured else "not_configured",
        "provider": settings.default_llm,
    }

    health_status["environment"] = {
        "python": sys.version.split()[0],
        "debug": settings.debug,
    }

    return health_status


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
from src.api.doctors import router as doctors_router
from src.api.procedures import router as procedures_router
from src.api.timeline import router as timeline_router
from src.api.analysis import router as analysis_router
from src.api.advisor import router as advisor_router
from src.api.db_admin import router as db_admin_router
from src.api.favorites import router as favorites_router
from src.api.nearby import router as nearby_router
from src.api.notifications import router as notifications_router
from src.api.case_photos import router as case_photos_router

app.include_router(nearby_router, prefix="/api/clinics", tags=["clinics"])
app.include_router(clinics_router, prefix="/api/clinics", tags=["clinics"])
app.include_router(doctors_router, prefix="/api/doctors", tags=["doctors"])
app.include_router(timeline_router, prefix="/api/procedures", tags=["procedures"])
app.include_router(procedures_router, prefix="/api/procedures", tags=["procedures"])
app.include_router(analysis_router, prefix="/api/analysis", tags=["analysis"])
app.include_router(advisor_router, prefix="/api/advisor", tags=["advisor"])
app.include_router(db_admin_router, prefix="/api/db", tags=["db-admin"])
app.include_router(favorites_router, prefix="/api", tags=["favorites"])
app.include_router(notifications_router, prefix="/api", tags=["notifications"])
app.include_router(case_photos_router, prefix="/api/case-photos", tags=["case-photos"])


# 静的ファイル配信（フロントエンド）
STATIC_DIR = Path(__file__).parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# SPAルーティング対応 — フロントエンドのルートを全てindex.htmlにフォールバック
SPA_ROUTES = ["/", "/procedures", "/clinics", "/doctors", "/advisor"]


@app.get("/sw.js")
async def serve_service_worker():
    """ルートパスでService Workerを配信（スコープ確保）"""
    sw_path = STATIC_DIR / "sw.js"
    if sw_path.exists():
        return FileResponse(
            str(sw_path),
            media_type="application/javascript",
            headers={"Service-Worker-Allowed": "/"}
        )
    return JSONResponse(status_code=404, content={"error": "sw.js not found"})


@app.get("/")
async def serve_root():
    """ルートパスでフロントエンドのindex.htmlを返却"""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path), media_type="text/html")
    return {"name": settings.app_name, "version": settings.app_version}


@app.get("/procedures")
@app.get("/clinics")
@app.get("/doctors")
@app.get("/advisor")
@app.get("/favorites")
async def serve_spa_route():
    """SPA用ルート — ブラウザの戻る/進むボタンに対応

    /procedures, /clinics, /advisor へのGETリクエストでも
    index.htmlを返し、フロントエンドのJSがルーティングを処理する。
    """
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path), media_type="text/html")
    return {"name": settings.app_name, "version": settings.app_version}


@app.get("/clinics/{clinic_id}")
@app.get("/procedures/{procedure_id}")
@app.get("/doctors/{doctor_id}")
async def serve_spa_detail_route(
    clinic_id: str = None,
    procedure_id: str = None,
    doctor_id: str = None,
):
    """SPA詳細ページ用ルート — 個別リソースのDeep Linkingに対応

    /clinics/{id}, /procedures/{id}, /doctors/{id} へのGETリクエストでも
    index.htmlを返し、フロントエンドのJSがルーティングを処理する。
    """
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path), media_type="text/html")
    return {"name": settings.app_name, "version": settings.app_version}
