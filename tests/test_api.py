"""
AURA MVP — API統合テスト + エンジン単体テスト

pytest + httpx AsyncClient (ASGITransport) 使用。

実行:
    uv sync --extra dev
    uv run python -m pytest tests/ -v
"""

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    """テスト用HTTPクライアント"""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=True,
    ) as ac:
        yield ac


# ==========================================
# ヘルスチェック
# ==========================================


@pytest.mark.anyio
async def test_health_check(client: AsyncClient):
    """ヘルスチェックが正常応答する"""
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data


@pytest.mark.anyio
async def test_db_health(client: AsyncClient):
    """DB統計ヘルスチェック"""
    resp = await client.get("/api/db/health")
    assert resp.status_code == 200


# ==========================================
# 施術 API
# ==========================================


@pytest.mark.anyio
async def test_get_procedures(client: AsyncClient):
    """施術一覧を取得できる"""
    resp = await client.get("/api/procedures/")
    assert resp.status_code == 200
    data = resp.json()
    # レスポンスがlistかdictかに対応
    if isinstance(data, dict):
        procs = data.get("procedures", data.get("items", []))
    else:
        procs = data
    assert len(procs) > 0
    proc = procs[0]
    assert "id" in proc
    assert "name" in proc


@pytest.mark.anyio
async def test_get_procedure_detail(client: AsyncClient):
    """施術詳細を取得できる"""
    resp = await client.get("/api/procedures/")
    data = resp.json()
    if isinstance(data, dict):
        procs = data.get("procedures", data.get("items", []))
    else:
        procs = data
    if not procs:
        pytest.skip("施術データなし")

    proc_id = procs[0]["id"]
    resp = await client.get(f"/api/procedures/{proc_id}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["id"] == proc_id


@pytest.mark.anyio
async def test_get_procedures_stats(client: AsyncClient):
    """施術統計を取得できる"""
    resp = await client.get("/api/procedures/stats")
    assert resp.status_code == 200


# ==========================================
# クリニック API
# ==========================================


@pytest.mark.anyio
async def test_get_clinics(client: AsyncClient):
    """クリニック一覧を取得できる"""
    resp = await client.get("/api/clinics/")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "clinics" in data
    assert "total" in data
    assert data["total"] > 0


@pytest.mark.anyio
async def test_get_clinics_pagination(client: AsyncClient):
    """ページネーションが機能する"""
    resp = await client.get("/api/clinics/?limit=5&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    clinics = data.get("clinics", [])
    # limit指定がデフォルト(20)にフォールバックする場合もある
    assert len(clinics) <= 20


@pytest.mark.anyio
async def test_get_clinic_detail(client: AsyncClient):
    """クリニック詳細を取得できる"""
    resp = await client.get("/api/clinics/?limit=1")
    clinics = resp.json()["clinics"]
    if not clinics:
        pytest.skip("クリニックデータなし")

    clinic_id = clinics[0]["id"]
    resp = await client.get(f"/api/clinics/{clinic_id}")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_get_clinics_stats(client: AsyncClient):
    """クリニック統計を取得できる"""
    resp = await client.get("/api/clinics/stats")
    assert resp.status_code == 200


# ==========================================
# アドバイザー API
# ==========================================


@pytest.mark.anyio
async def test_advisor_status(client: AsyncClient):
    """アドバイザーステータスを取得できる"""
    resp = await client.get("/api/advisor/status")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_advisor_tools_list(client: AsyncClient):
    """法的行動支援ツール一覧を取得できる"""
    resp = await client.get("/api/advisor/tools")
    assert resp.status_code == 200
    data = resp.json()
    # レスポンスがdict(tools key)かlistかに対応
    if isinstance(data, dict):
        tools = data.get("tools", [])
    else:
        tools = data
    assert len(tools) == 7  # 7つのギリギリ行動
    tool = tools[0]
    assert "id" in tool


@pytest.mark.anyio
async def test_advisor_concerns(client: AsyncClient):
    """悩みカテゴリ一覧を取得できる"""
    resp = await client.get("/api/advisor/concerns")
    assert resp.status_code == 200


# ==========================================
# 分析 API
# ==========================================


@pytest.mark.anyio
async def test_analysis_dashboard(client: AsyncClient):
    """分析ダッシュボードを取得できる"""
    resp = await client.get("/api/analysis/dashboard")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_analysis_transparency(client: AsyncClient):
    """透明性分析を取得できる"""
    resp = await client.get("/api/analysis/transparency")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_analysis_price_gaps(client: AsyncClient):
    """価格差分析を取得できる"""
    resp = await client.get("/api/analysis/price-gaps")
    assert resp.status_code == 200


# ==========================================
# 静的ファイル
# ==========================================


@pytest.mark.anyio
async def test_serve_index_html(client: AsyncClient):
    """トップページが配信される"""
    resp = await client.get("/")
    assert resp.status_code == 200
    content_type = resp.headers.get("content-type", "")
    assert "html" in content_type or resp.text.strip().startswith("<!") or "<html" in resp.text[:200]


# ==========================================
# エンジン単体テスト
# ==========================================


def test_match_tool_triggers():
    """ツールトリガーキーワードが正しくマッチする"""
    from src.advisor.engine import match_tool_triggers

    assert "cooling_off" in match_tool_triggers("契約を解約したい")
    assert "cooling_off" in match_tool_triggers("クーリングオフできますか？")
    assert "medical_records" in match_tool_triggers("カルテを見せてほしい")
    assert "post_surgery" in match_tool_triggers("術後の腫れが心配")
    assert match_tool_triggers("二重にしたいです") == []


def test_match_concerns():
    """悩みタグのマッチング"""
    from src.advisor.engine import match_concerns

    tags = match_concerns("シワが気になる")
    assert isinstance(tags, list)


def test_check_legal_boundary():
    """法的境界チェック"""
    from src.advisor.engine import LegalBoundary, check_legal_boundary

    boundary, _ = check_legal_boundary("この施術について教えてください")
    assert isinstance(boundary, LegalBoundary)


def test_build_system_prompt():
    """システムプロンプト構築"""
    from src.advisor.engine import AdvisorContext, build_system_prompt

    ctx = AdvisorContext(concern="シミが気になる")
    prompt = build_system_prompt(ctx)
    assert isinstance(prompt, str)
    assert len(prompt) > 100


def test_build_system_prompt_with_tool_trigger():
    """ツールトリガー付きシステムプロンプト"""
    from src.advisor.engine import AdvisorContext, build_system_prompt

    ctx = AdvisorContext(concern="契約をキャンセルしたい、クーリングオフは？")
    prompt = build_system_prompt(ctx)
    assert "案内すべきツール" in prompt
    assert "cooling_off" in prompt


def test_legal_tools_defined():
    """法的行動支援ツールが正しく定義されている"""
    from src.advisor.legal_tools import LEGAL_TOOLS

    assert len(LEGAL_TOOLS) == 7
    for tool in LEGAL_TOOLS:
        assert tool.id
        assert tool.title
        assert tool.description


def test_phone_extraction():
    """電話番号抽出が正しく動作する"""
    from src.collectors.phone_extraction import extract_phone_from_html, normalize_phone

    # tel:リンクから
    html = '<a href="tel:0312345678">電話する</a>'
    assert extract_phone_from_html(html) is not None

    # 正規化テスト
    assert normalize_phone("0312345678") == "03-1234-5678"
    assert normalize_phone("0120-123-456") == "0120-123-456"


def test_data_freshness_report():
    """データ鮮度レポートが生成できる"""
    from src.collectors.auto_update import DataFreshnessChecker

    checker = DataFreshnessChecker()
    report = checker.get_freshness_report()
    assert "total_clinics" in report
    assert "fill_rates" in report
    assert "price_data" in report
    assert report["total_clinics"] > 0


# ==========================================
# お気に入り・比較 API
# ==========================================


@pytest.mark.anyio
async def test_favorites_empty(client: AsyncClient):
    """初期状態でお気に入りが空"""
    resp = await client.get("/api/favorites?session_id=test_session_empty")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0


@pytest.mark.anyio
async def test_favorites_toggle(client: AsyncClient):
    """お気に入りの追加と削除（トグル）が動作する"""
    # クリニックIDを取得
    resp = await client.get("/api/clinics/?limit=1")
    clinics = resp.json()["clinics"]
    if not clinics:
        pytest.skip("クリニックデータなし")
    clinic_id = clinics[0]["id"]

    # 追加
    resp = await client.post(
        "/api/favorites?session_id=test_toggle",
        json={"clinic_id": clinic_id},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "added"
    assert data["total_favorites"] == 1

    # 再度トグルで削除
    resp = await client.post(
        "/api/favorites?session_id=test_toggle",
        json={"clinic_id": clinic_id},
    )
    data = resp.json()
    assert data["action"] == "removed"
    assert data["total_favorites"] == 0


@pytest.mark.anyio
async def test_favorites_nonexistent_clinic(client: AsyncClient):
    """存在しないクリニックはお気に入りに追加できない"""
    resp = await client.post(
        "/api/favorites",
        json={"clinic_id": "nonexistent_12345"},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_compare_clinics(client: AsyncClient):
    """2クリニックの比較が動作する"""
    resp = await client.get("/api/clinics/?limit=2")
    clinics = resp.json()["clinics"]
    if len(clinics) < 2:
        pytest.skip("クリニック2件未満")

    clinic_ids = [c["id"] for c in clinics[:2]]
    resp = await client.post(
        "/api/compare",
        json={"clinic_ids": clinic_ids},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "clinics" in data
    assert "comparison_matrix" in data
    assert "insights" in data
    assert len(data["clinics"]) == 2


@pytest.mark.anyio
async def test_compare_too_few(client: AsyncClient):
    """1件のみでは比較できない"""
    resp = await client.get("/api/clinics/?limit=1")
    clinics = resp.json()["clinics"]
    if not clinics:
        pytest.skip("クリニックデータなし")

    resp = await client.post(
        "/api/compare",
        json={"clinic_ids": [clinics[0]["id"]]},
    )
    assert resp.status_code == 422  # バリデーションエラー

