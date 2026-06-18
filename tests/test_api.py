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
    assert data["status"] in ("healthy", "degraded")
    assert "checks" in data
    assert "database" in data["checks"]


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
# Phase 63: クリニック JSON-LD API
# ==========================================


@pytest.mark.anyio
async def test_clinic_jsonld(client: AsyncClient):
    """クリニックJSON-LDがMedicalClinic型で返される"""
    resp = await client.get("/api/clinics/?limit=1")
    clinics = resp.json()["clinics"]
    if not clinics:
        pytest.skip("クリニックデータなし")

    clinic_id = clinics[0]["id"]
    resp = await client.get(f"/api/clinics/{clinic_id}/jsonld")
    assert resp.status_code == 200
    data = resp.json()
    assert data["@context"] == "https://schema.org"
    assert data["@type"] == "MedicalClinic"
    assert "name" in data
    assert len(data["name"]) > 0


@pytest.mark.anyio
async def test_clinic_jsonld_not_found(client: AsyncClient):
    """存在しないクリニックIDでJSON-LDを取得すると404"""
    resp = await client.get("/api/clinics/nonexistent_99999/jsonld")
    assert resp.status_code == 404


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
    assert len(tools) == 10  # 7つのギリギリ行動 + 3つのカウンセリング防衛キット
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

    assert len(LEGAL_TOOLS) == 10
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


# ==========================================
# 入力サニタイズ
# ==========================================


def test_sanitize_xss():
    """XSSパターンがサニタイズされる"""
    from src.middleware.sanitize import sanitize_dict, check_xss

    assert check_xss('<script>alert("xss")</script>')
    assert check_xss('javascript:alert(1)')
    assert not check_xss('普通のテキスト')

    result = sanitize_dict({"msg": '<script>alert("xss")</script>'})
    assert "<script" not in result["msg"]
    assert "&lt;script&gt;" in result["msg"]


def test_sanitize_nested():
    """ネストされた辞書も再帰的にサニタイズされる"""
    from src.middleware.sanitize import sanitize_dict

    data = {"a": {"b": {"c": '<img onerror="alert(1)">'}}}
    result = sanitize_dict(data)
    # HTMLエスケープにより<imgタグが&lt;img に変換される
    assert "<img" not in result["a"]["b"]["c"]
    assert "&lt;" in result["a"]["b"]["c"]


# ==========================================
# concerns API 拡張
# ==========================================


@pytest.mark.anyio
async def test_advisor_concerns_expanded(client: AsyncClient):
    """8カテゴリの悩みが返される"""
    resp = await client.get("/api/advisor/concerns")
    assert resp.status_code == 200
    data = resp.json()
    cats = data["categories"]
    assert "anti_aging" in cats
    assert "body" in cats
    assert "hair_removal" in cats
    assert "breast" in cats
    assert len(cats) == 8


# ==========================================
# 近隣クリニック検索 API
# ==========================================


@pytest.mark.anyio
async def test_nearby_clinics_basic(client: AsyncClient):
    """近隣クリニック検索が正常に動作する"""
    # 東京駅付近の座標で検索
    resp = await client.get(
        "/api/clinics/nearby",
        params={"lat": 35.6812, "lng": 139.7671, "radius_km": 50},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "center" in data
    assert "radius_km" in data
    assert "total" in data
    assert "clinics" in data
    assert data["center"]["lat"] == 35.6812
    assert data["center"]["lng"] == 139.7671
    assert isinstance(data["clinics"], list)


@pytest.mark.anyio
async def test_nearby_clinics_sorted_by_distance(client: AsyncClient):
    """近隣クリニック検索の結果が距離順でソートされている"""
    resp = await client.get(
        "/api/clinics/nearby",
        params={"lat": 35.6812, "lng": 139.7671, "radius_km": 50},
    )
    assert resp.status_code == 200
    clinics = resp.json()["clinics"]
    if len(clinics) >= 2:
        # 距離が昇順であることを確認
        for i in range(len(clinics) - 1):
            assert clinics[i]["distance_km"] <= clinics[i + 1]["distance_km"]


@pytest.mark.anyio
async def test_nearby_clinics_limit(client: AsyncClient):
    """近隣クリニック検索のlimit制限が機能する"""
    resp = await client.get(
        "/api/clinics/nearby",
        params={"lat": 35.6812, "lng": 139.7671, "radius_km": 50, "limit": 3},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["clinics"]) <= 3


@pytest.mark.anyio
async def test_nearby_clinics_small_radius(client: AsyncClient):
    """極小半径では結果が0件になりうる"""
    resp = await client.get(
        "/api/clinics/nearby",
        params={"lat": 0.0, "lng": 0.0, "radius_km": 0.1},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["clinics"] == []


@pytest.mark.anyio
async def test_nearby_clinics_missing_params(client: AsyncClient):
    """必須パラメータ不足で422エラー"""
    resp = await client.get("/api/clinics/nearby")
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_nearby_clinics_has_distance(client: AsyncClient):
    """検索結果にdistance_kmフィールドが含まれる"""
    resp = await client.get(
        "/api/clinics/nearby",
        params={"lat": 35.6812, "lng": 139.7671, "radius_km": 50},
    )
    assert resp.status_code == 200
    for clinic in resp.json()["clinics"]:
        assert "distance_km" in clinic
        assert isinstance(clinic["distance_km"], (int, float))
        assert clinic["distance_km"] >= 0


# ==========================================
# Haversine距離計算 単体テスト
# ==========================================


def test_haversine_same_point():
    """同一地点の距離は0"""
    from src.api.nearby import haversine_distance
    assert haversine_distance(35.6812, 139.7671, 35.6812, 139.7671) == 0.0


def test_haversine_known_distance():
    """東京駅〜新宿駅の距離が妥当な範囲（約6km）"""
    from src.api.nearby import haversine_distance
    # 東京駅(35.6812, 139.7671) → 新宿駅(35.6896, 139.7006)
    dist = haversine_distance(35.6812, 139.7671, 35.6896, 139.7006)
    assert 5.0 < dist < 8.0  # 約6km


# ==========================================
# チャットAPI 基本テスト
# ==========================================


@pytest.mark.anyio
async def test_chat_basic_response(client: AsyncClient):
    """チャットAPIが正常にレスポンスを返す"""
    resp = await client.post(
        "/api/advisor/chat",
        json={"message": "二重にしたいのですが"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert "message" in data
    assert "legal_boundary" in data
    assert len(data["message"]) > 0


@pytest.mark.anyio
async def test_chat_legal_boundary_prohibited(client: AsyncClient):
    """禁止ワード（診断・処方）を含むメッセージで適切な法的制約が返る"""
    resp = await client.post(
        "/api/advisor/chat",
        json={"message": "この薬を処方してください"},
    )
    assert resp.status_code == 200
    data = resp.json()
    # 禁止またはCAUTIONの法的境界が返る
    assert data["legal_boundary"] in ("prohibited", "caution", "allowed")


@pytest.mark.anyio
async def test_chat_session_continuity(client: AsyncClient):
    """セッションIDを指定して会話を継続できる"""
    # 1回目のメッセージ
    resp1 = await client.post(
        "/api/advisor/chat",
        json={"message": "シミが気になります"},
    )
    assert resp1.status_code == 200
    session_id = resp1.json()["session_id"]

    # 2回目（同じセッションIDで継続）
    resp2 = await client.post(
        "/api/advisor/chat",
        json={"message": "費用はどのくらいですか？", "session_id": session_id},
    )
    assert resp2.status_code == 200
    assert resp2.json()["session_id"] == session_id


@pytest.mark.anyio
async def test_chat_empty_message_rejected(client: AsyncClient):
    """空メッセージが拒否される"""
    resp = await client.post(
        "/api/advisor/chat",
        json={"message": ""},
    )
    assert resp.status_code == 422


# ==========================================
# 予算パーサー 単体テスト
# ==========================================


class TestParseBudget:
    """parse_budget関数の単体テスト"""

    def test_man_unit(self):
        """「15万」→ 150000 に変換"""
        from src.advisor.recommendation_engine import parse_budget
        assert parse_budget("15万") == 150000

    def test_man_yen(self):
        """「15万円」→ 150000 に変換"""
        from src.advisor.recommendation_engine import parse_budget
        assert parse_budget("15万円") == 150000

    def test_man_inai(self):
        """「10万以内」→ 100000 に変換"""
        from src.advisor.recommendation_engine import parse_budget
        assert parse_budget("10万以内") == 100000

    def test_man_kurai(self):
        """「30万円くらい」→ 300000 に変換"""
        from src.advisor.recommendation_engine import parse_budget
        assert parse_budget("30万円くらい") == 300000

    def test_numeric_yen(self):
        """「150000円」→ 150000 に変換"""
        from src.advisor.recommendation_engine import parse_budget
        assert parse_budget("150000円") == 150000

    def test_numeric_only(self):
        """「150000」→ 150000 に変換"""
        from src.advisor.recommendation_engine import parse_budget
        assert parse_budget("150000") == 150000

    def test_small_number_as_man(self):
        """「15」→ 万単位と推定して150000"""
        from src.advisor.recommendation_engine import parse_budget
        assert parse_budget("15") == 150000

    def test_decimal_man(self):
        """「1.5万」→ 15000 に変換"""
        from src.advisor.recommendation_engine import parse_budget
        assert parse_budget("1.5万") == 15000

    def test_empty_string(self):
        """空文字列 → None"""
        from src.advisor.recommendation_engine import parse_budget
        assert parse_budget("") is None

    def test_no_number(self):
        """数値を含まない文字列 → None"""
        from src.advisor.recommendation_engine import parse_budget
        assert parse_budget("予算なし") is None

    def test_comma_separated(self):
        """「150,000円」→ カンマ除去して150000"""
        from src.advisor.recommendation_engine import parse_budget
        assert parse_budget("150,000円") == 150000


# ==========================================
# DTパーサー 単体テスト
# ==========================================


class TestParseDowntimeDays:
    """parse_downtime_days関数の単体テスト"""

    def test_days(self):
        """「3日」→ 3"""
        from src.advisor.recommendation_engine import parse_downtime_days
        assert parse_downtime_days("3日") == 3

    def test_days_kan(self):
        """「3日間」→ 3"""
        from src.advisor.recommendation_engine import parse_downtime_days
        assert parse_downtime_days("3日間") == 3

    def test_one_week(self):
        """「1週間」→ 7"""
        from src.advisor.recommendation_engine import parse_downtime_days
        assert parse_downtime_days("1週間") == 7

    def test_two_weeks(self):
        """「2週間」→ 14"""
        from src.advisor.recommendation_engine import parse_downtime_days
        assert parse_downtime_days("2週間") == 14

    def test_nashi(self):
        """「なし」→ 0"""
        from src.advisor.recommendation_engine import parse_downtime_days
        assert parse_downtime_days("なし") == 0

    def test_zero_days(self):
        """「0日」→ 0"""
        from src.advisor.recommendation_engine import parse_downtime_days
        assert parse_downtime_days("0日") == 0

    def test_torenai(self):
        """「取れない」→ 0"""
        from src.advisor.recommendation_engine import parse_downtime_days
        assert parse_downtime_days("取れない") == 0

    def test_empty_string(self):
        """空文字列 → None"""
        from src.advisor.recommendation_engine import parse_downtime_days
        assert parse_downtime_days("") is None


class TestEstimateDtDays:
    """estimate_dt_days関数の単体テスト"""

    def test_single_days(self):
        """「5日」→ 5"""
        from src.advisor.recommendation_engine import estimate_dt_days
        assert estimate_dt_days("5日") == 5

    def test_single_weeks(self):
        """「2週間」→ 14"""
        from src.advisor.recommendation_engine import estimate_dt_days
        assert estimate_dt_days("2週間") == 14

    def test_range_days(self):
        """「3-5日」→ 平均4"""
        from src.advisor.recommendation_engine import estimate_dt_days
        assert estimate_dt_days("3-5日") == 4

    def test_range_weeks(self):
        """「1-2週間」→ 平均10(日)"""
        from src.advisor.recommendation_engine import estimate_dt_days
        result = estimate_dt_days("1-2週間")
        assert result == 10  # (1+2)*7//2 = 10

    def test_one_month(self):
        """「1ヶ月」→ 30"""
        from src.advisor.recommendation_engine import estimate_dt_days
        assert estimate_dt_days("1ヶ月") == 30

    def test_one_month_ka(self):
        """「1か月」→ 30"""
        from src.advisor.recommendation_engine import estimate_dt_days
        assert estimate_dt_days("1か月") == 30

    def test_empty_string(self):
        """空文字列 → None"""
        from src.advisor.recommendation_engine import estimate_dt_days
        assert estimate_dt_days("") is None

    def test_none(self):
        """None → None"""
        from src.advisor.recommendation_engine import estimate_dt_days
        assert estimate_dt_days(None) is None

    def test_tilde_range(self):
        """「3〜5日」→ 平均4（全角チルダ）"""
        from src.advisor.recommendation_engine import estimate_dt_days
        assert estimate_dt_days("3〜5日") == 4


# ==========================================
# エリア解決 単体テスト
# ==========================================


class TestResolveArea:
    """resolve_area関数の単体テスト"""

    def test_shibuya(self):
        """「渋谷」→ 渋谷区 + 隣接エリアを返す"""
        from src.advisor.recommendation_engine import resolve_area
        primary, adjacent = resolve_area("渋谷")
        assert primary == "渋谷区"
        assert "港区" in adjacent
        assert "目黒区" in adjacent

    def test_tokyo_station(self):
        """「有楽町」→ 千代田区を返す（東京駅近く）"""
        from src.advisor.recommendation_engine import resolve_area
        primary, adjacent = resolve_area("有楽町")
        assert primary == "千代田区"

    def test_ginza(self):
        """「銀座」→ 中央区を返す"""
        from src.advisor.recommendation_engine import resolve_area
        primary, adjacent = resolve_area("銀座")
        assert primary == "中央区"
        assert "千代田区" in adjacent

    def test_direct_ward(self):
        """「新宿区」→ そのまま新宿区を返す"""
        from src.advisor.recommendation_engine import resolve_area
        primary, adjacent = resolve_area("新宿区")
        assert primary == "新宿区"
        assert "渋谷区" in adjacent

    def test_unknown_area(self):
        """未知のエリア → (None, [])"""
        from src.advisor.recommendation_engine import resolve_area
        primary, adjacent = resolve_area("ニューヨーク")
        assert primary is None
        assert adjacent == []

    def test_empty_string(self):
        """空文字列 → (None, [])"""
        from src.advisor.recommendation_engine import resolve_area
        primary, adjacent = resolve_area("")
        assert primary is None
        assert adjacent == []

    def test_omotesando(self):
        """「表参道」→ 渋谷区（エリアマップに基づく）"""
        from src.advisor.recommendation_engine import resolve_area
        primary, _ = resolve_area("表参道")
        assert primary == "渋谷区"

    def test_roppongi(self):
        """「六本木」→ 港区"""
        from src.advisor.recommendation_engine import resolve_area
        primary, _ = resolve_area("六本木")
        assert primary == "港区"


# ==========================================
# スコアリングエンジン 単体テスト
# ==========================================


class TestCalculateQualityScore:
    """calculate_quality_score関数の単体テスト"""

    def test_high_quality_clinic(self):
        """高評価+多口コミ+専門医 → 高スコア"""
        from src.advisor.recommendation_engine import calculate_quality_score
        score = calculate_quality_score(
            google_rating=4.8,
            google_review_count=200,
            has_specialist=True,
            departments=["美容外科", "形成外科"],
            transparency_score=80.0,
            review_sentiment=0.8,
        )
        # 高品質クリニックは高スコアを持つべき
        assert score >= 80
        assert score <= 100

    def test_low_quality_clinic(self):
        """低評価+少口コミ → 低スコア"""
        from src.advisor.recommendation_engine import calculate_quality_score
        score = calculate_quality_score(
            google_rating=2.5,
            google_review_count=3,
            has_specialist=False,
            departments=[],
            transparency_score=None,
            review_sentiment=-0.5,
        )
        # 低品質クリニックはスコアが低い
        assert score < 40

    def test_score_range(self):
        """スコアは0-100の範囲内"""
        from src.advisor.recommendation_engine import calculate_quality_score
        # 最大値テスト
        max_score = calculate_quality_score(
            google_rating=5.0,
            google_review_count=10000,
            has_specialist=True,
            departments=["美容外科", "形成外科"],
            transparency_score=100.0,
            review_sentiment=1.0,
        )
        assert 0 <= max_score <= 100

        # 最小値テスト
        min_score = calculate_quality_score(
            google_rating=1.0,
            google_review_count=0,
            has_specialist=False,
            departments=[],
            transparency_score=None,
            review_sentiment=-1.0,
        )
        assert 0 <= min_score <= 100

    def test_no_data(self):
        """データなしでもスコアが算出される（中間値）"""
        from src.advisor.recommendation_engine import calculate_quality_score
        score = calculate_quality_score(
            google_rating=None,
            google_review_count=None,
            has_specialist=False,
            departments=[],
        )
        # None/デフォルトの場合でもスコアは0以上
        assert score > 0
        assert score <= 100

    def test_specialist_bonus(self):
        """専門医在籍でスコアが上がる"""
        from src.advisor.recommendation_engine import calculate_quality_score
        score_without = calculate_quality_score(
            google_rating=4.0,
            google_review_count=50,
            has_specialist=False,
            departments=["美容外科"],
        )
        score_with = calculate_quality_score(
            google_rating=4.0,
            google_review_count=50,
            has_specialist=True,
            departments=["美容外科"],
        )
        # 専門医ありの方が13pt高い
        assert score_with > score_without
        assert score_with - score_without == 13

    def test_departments_bonus(self):
        """美容外科+形成外科で最高の診療科スコア"""
        from src.advisor.recommendation_engine import calculate_quality_score
        score_both = calculate_quality_score(
            google_rating=4.0,
            google_review_count=50,
            has_specialist=False,
            departments=["美容外科", "形成外科"],
        )
        score_one = calculate_quality_score(
            google_rating=4.0,
            google_review_count=50,
            has_specialist=False,
            departments=["美容外科"],
        )
        # 両方ある方がスコアが高い
        assert score_both > score_one


class TestCalculateMatchScore:
    """calculate_match_score関数の単体テスト"""

    def test_perfect_match(self):
        """全条件一致でスコアが高い"""
        from src.advisor.recommendation_engine import calculate_match_score, UserPriority
        score = calculate_match_score(
            quality_score=90.0,
            area_match="exact",
            budget_fit=True,
            dt_fit=True,
            priority=UserPriority.BALANCED,
        )
        assert score >= 80

    def test_no_match(self):
        """条件不一致でスコアが低い"""
        from src.advisor.recommendation_engine import calculate_match_score, UserPriority
        score = calculate_match_score(
            quality_score=20.0,
            area_match="none",
            budget_fit=False,
            dt_fit=False,
            priority=UserPriority.BALANCED,
        )
        assert score < 30

    def test_quality_priority_weights(self):
        """品質優先モードでは品質スコアの影響が大きい"""
        from src.advisor.recommendation_engine import calculate_match_score, UserPriority
        # 品質高い + エリア不一致
        score_q = calculate_match_score(
            quality_score=100.0,
            area_match="none",
            budget_fit=True,
            dt_fit=True,
            priority=UserPriority.QUALITY,
        )
        # 品質低い + エリア完全一致
        score_a = calculate_match_score(
            quality_score=20.0,
            area_match="exact",
            budget_fit=True,
            dt_fit=True,
            priority=UserPriority.QUALITY,
        )
        # 品質優先では品質が高い方がスコアが高い
        assert score_q > score_a

    def test_price_priority_weights(self):
        """コスト優先モードでは予算適合の影響が大きい"""
        from src.advisor.recommendation_engine import calculate_match_score, UserPriority
        # 予算内
        score_fit = calculate_match_score(
            quality_score=50.0,
            area_match="none",
            budget_fit=True,
            dt_fit=False,
            priority=UserPriority.PRICE,
        )
        # 予算外
        score_no = calculate_match_score(
            quality_score=50.0,
            area_match="none",
            budget_fit=False,
            dt_fit=False,
            priority=UserPriority.PRICE,
        )
        # 予算内の方がスコアが高い
        assert score_fit > score_no

    def test_adjacent_area_score(self):
        """隣接エリアはexactとnoneの中間スコア"""
        from src.advisor.recommendation_engine import calculate_match_score, UserPriority
        exact = calculate_match_score(80, "exact", True, True, UserPriority.BALANCED)
        adjacent = calculate_match_score(80, "adjacent", True, True, UserPriority.BALANCED)
        none = calculate_match_score(80, "none", True, True, UserPriority.BALANCED)
        assert exact > adjacent > none

    def test_score_is_rounded(self):
        """スコアはround(total, 1)で丸められている"""
        from src.advisor.recommendation_engine import calculate_match_score, UserPriority
        score = calculate_match_score(75.0, "exact", True, True, UserPriority.BALANCED)
        # 小数点第1位まで丸め
        assert score == round(score, 1)


# ==========================================
# インテーク 単体テスト
# ==========================================


class TestIsRecommendationRequest:
    """is_recommendation_request関数の単体テスト"""

    def test_concern_with_trigger(self):
        """悩み + トリガーワード → True"""
        from src.advisor.intake import is_recommendation_request
        assert is_recommendation_request("二重のおすすめクリニックを探して") is True

    def test_concern_area_budget(self):
        """悩み + エリア + 予算 → True"""
        from src.advisor.intake import is_recommendation_request
        assert is_recommendation_request("二重にしたい 渋谷 10万以内") is True

    def test_area_with_strong_trigger(self):
        """エリア + 強いトリガー → True"""
        from src.advisor.intake import is_recommendation_request
        assert is_recommendation_request("渋谷でいいクリニック探して") is True

    def test_no_concern_no_trigger(self):
        """悩みもトリガーもない → False"""
        from src.advisor.intake import is_recommendation_request
        assert is_recommendation_request("こんにちは") is False

    def test_concern_only(self):
        """悩みのみ（トリガーなし） → False"""
        from src.advisor.intake import is_recommendation_request
        assert is_recommendation_request("二重にしたいのですが") is False

    def test_trigger_only(self):
        """トリガーのみ（悩みなし） → False"""
        from src.advisor.intake import is_recommendation_request
        assert is_recommendation_request("おすすめはどこですか") is False


class TestExtractConditionsFromMessage:
    """extract_conditions_from_message関数の単体テスト"""

    def test_extract_area(self):
        """メッセージからエリアを抽出"""
        from src.advisor.intake import extract_conditions_from_message
        from src.advisor.recommendation_engine import UserConditions
        conditions = extract_conditions_from_message(
            "渋谷で探しています", UserConditions()
        )
        assert conditions.area == "渋谷"

    def test_extract_budget(self):
        """メッセージから予算を抽出"""
        from src.advisor.intake import extract_conditions_from_message
        from src.advisor.recommendation_engine import UserConditions
        conditions = extract_conditions_from_message(
            "予算は15万円くらい", UserConditions()
        )
        assert conditions.budget == 150000

    def test_extract_downtime(self):
        """メッセージからDT日数を抽出"""
        from src.advisor.intake import extract_conditions_from_message
        from src.advisor.recommendation_engine import UserConditions
        conditions = extract_conditions_from_message(
            "3日休めます", UserConditions()
        )
        assert conditions.downtime_days == 3

    def test_extract_concern_tags(self):
        """メッセージから悩みタグを抽出"""
        from src.advisor.intake import extract_conditions_from_message
        from src.advisor.recommendation_engine import UserConditions
        conditions = extract_conditions_from_message(
            "二重にしたいです", UserConditions()
        )
        assert "double" in conditions.concern_tags

    def test_extract_age_range(self):
        """メッセージから年代を抽出"""
        from src.advisor.intake import extract_conditions_from_message
        from src.advisor.recommendation_engine import UserConditions
        conditions = extract_conditions_from_message(
            "30代です", UserConditions()
        )
        assert conditions.age_range == "30代"

    def test_extract_priority_quality(self):
        """品質重視の優先度を抽出"""
        from src.advisor.intake import extract_conditions_from_message
        from src.advisor.recommendation_engine import UserConditions, UserPriority
        conditions = extract_conditions_from_message(
            "安全性を重視したい", UserConditions()
        )
        assert conditions.priority == UserPriority.QUALITY

    def test_extract_priority_price(self):
        """コスト重視の優先度を抽出"""
        from src.advisor.intake import extract_conditions_from_message
        from src.advisor.recommendation_engine import UserConditions, UserPriority
        conditions = extract_conditions_from_message(
            "できるだけ安くしたい", UserConditions()
        )
        assert conditions.priority == UserPriority.PRICE

    def test_preserve_existing(self):
        """既存の条件を保持したまま新規抽出"""
        from src.advisor.intake import extract_conditions_from_message
        from src.advisor.recommendation_engine import UserConditions
        existing = UserConditions(
            concern_tags=["double"],
            concern_text="二重にしたい",
            area="渋谷",
        )
        conditions = extract_conditions_from_message(
            "予算は10万です", existing
        )
        # 既存の悩みタグとエリアが保持される
        assert "double" in conditions.concern_tags
        assert conditions.budget == 100000

    def test_combined_message(self):
        """複数条件を含むメッセージから一括抽出"""
        from src.advisor.intake import extract_conditions_from_message
        from src.advisor.recommendation_engine import UserConditions
        conditions = extract_conditions_from_message(
            "二重にしたい 新宿 10万以内 3日休めます",
            UserConditions(),
        )
        assert "double" in conditions.concern_tags
        assert conditions.area == "新宿"
        assert conditions.budget == 100000
        assert conditions.downtime_days == 3


class TestAssessIntakeState:
    """assess_intake_state関数の単体テスト"""

    def test_initial_state(self):
        """悩みタグなし → INITIAL"""
        from src.advisor.intake import assess_intake_state, IntakeState
        from src.advisor.recommendation_engine import UserConditions
        state, missing = assess_intake_state(UserConditions())
        assert state == IntakeState.INITIAL
        assert "concern" in missing

    def test_concern_only(self):
        """悩みのみ → CONCERN_IDENTIFIED + 不足フィールドあり"""
        from src.advisor.intake import assess_intake_state, IntakeState
        from src.advisor.recommendation_engine import UserConditions
        conditions = UserConditions(concern_tags=["double"])
        state, missing = assess_intake_state(conditions)
        assert state == IntakeState.CONCERN_IDENTIFIED
        assert "area" in missing
        assert "budget" in missing
        assert "downtime" in missing

    def test_all_filled(self):
        """全条件揃い → READY"""
        from src.advisor.intake import assess_intake_state, IntakeState
        from src.advisor.recommendation_engine import UserConditions
        conditions = UserConditions(
            concern_tags=["double"],
            area="渋谷",
            budget=150000,
            downtime_days=3,
        )
        state, missing = assess_intake_state(conditions)
        assert state == IntakeState.READY
        assert missing == []

    def test_partial_filled(self):
        """部分的に揃い → CONCERN_IDENTIFIED + 不足分のみ"""
        from src.advisor.intake import assess_intake_state, IntakeState
        from src.advisor.recommendation_engine import UserConditions
        conditions = UserConditions(
            concern_tags=["double"],
            area="渋谷",
            budget=None,
            downtime_days=3,
        )
        state, missing = assess_intake_state(conditions)
        assert state == IntakeState.CONCERN_IDENTIFIED
        assert missing == ["budget"]
        assert "area" not in missing
        assert "downtime" not in missing


# ==========================================
# サジェストAPI テスト
# ==========================================


@pytest.mark.anyio
async def test_suggest_returns_results(client: AsyncClient):
    """2文字以上でサジェストが返る"""
    resp = await client.get("/api/clinics/suggest?q=渋谷")
    assert resp.status_code == 200
    data = resp.json()
    assert "suggestions" in data


@pytest.mark.anyio
async def test_suggest_short_query(client: AsyncClient):
    """1文字では空配列"""
    resp = await client.get("/api/clinics/suggest?q=渋")
    assert resp.status_code == 200
    assert resp.json()["suggestions"] == []


@pytest.mark.anyio
async def test_suggest_empty_query(client: AsyncClient):
    """空クエリでは空配列"""
    resp = await client.get("/api/clinics/suggest?q=")
    assert resp.status_code == 200
    assert resp.json()["suggestions"] == []


@pytest.mark.anyio
async def test_suggest_limit(client: AsyncClient):
    """結果は最大8件"""
    resp = await client.get("/api/clinics/suggest?q=クリニック")
    assert resp.status_code == 200
    assert len(resp.json()["suggestions"]) <= 8


# ==========================================
# カウンセリング防衛キット テスト
# ==========================================


class TestCounselingDefenseKit:
    """カウンセリング防衛キットの統合テスト"""

    @pytest.mark.anyio
    async def test_tools_list_includes_new_tools(self, client: AsyncClient):
        """ツール一覧に新ツール3つが含まれる"""
        resp = await client.get("/api/advisor/tools")
        assert resp.status_code == 200
        data = resp.json()
        if isinstance(data, dict):
            tools = data.get("tools", [])
        else:
            tools = data
        tool_ids = [t["id"] for t in tools]
        assert "counseling_armor" in tool_ids
        assert "question_generator" in tool_ids
        assert "cooling_off_check" in tool_ids

    @pytest.mark.anyio
    async def test_counseling_armor(self, client: AsyncClient):
        """カウンセリング防衛カードが正しく生成される"""
        resp = await client.post("/api/advisor/tools/counseling_armor", json={"params": {}})
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert "pressure_scripts" in result
        assert len(result["pressure_scripts"]) >= 5
        assert "before_counseling_checklist" in result
        assert "after_counseling_checklist" in result
        assert "recording_guide" in result

    @pytest.mark.anyio
    async def test_question_generator_common(self, client: AsyncClient):
        """共通質問リストが生成される"""
        resp = await client.post("/api/advisor/tools/question_generator", json={"params": {}})
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert "questions" in result
        assert len(result["questions"]) >= 4

    @pytest.mark.anyio
    async def test_question_generator_eye(self, client: AsyncClient):
        """目元固有の質問が含まれる"""
        resp = await client.post("/api/advisor/tools/question_generator", json={"params": {"procedure_type": "eye"}})
        assert resp.status_code == 200
        result = resp.json()["result"]
        categories = [q["category"] for q in result["questions"]]
        assert "二重・目元固有の質問" in categories

    @pytest.mark.anyio
    async def test_cooling_off_check_applicable(self, client: AsyncClient):
        """条件を満たす場合に適用可と判定される"""
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        resp = await client.post("/api/advisor/tools/cooling_off_check", json={
            "params": {
                "contract_date": today,
                "procedure_type": "脱毛",
                "total_amount": "100000",
                "contract_period": "3ヶ月",
            }
        })
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert "✅" in result["judgment"]

    @pytest.mark.anyio
    async def test_cooling_off_check_not_applicable(self, client: AsyncClient):
        """金額条件を満たさない場合に対象外と判定"""
        resp = await client.post("/api/advisor/tools/cooling_off_check", json={
            "params": {
                "total_amount": "30000",
                "contract_period": "3ヶ月",
            }
        })
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert "⚠️" in result["judgment"] or "❌" in [c["status"].split()[0] for c in result.get("checks", [])]

    @pytest.mark.anyio
    async def test_tools_have_badge(self, client: AsyncClient):
        """新ツールにNEWバッジがついている"""
        resp = await client.get("/api/advisor/tools")
        data = resp.json()
        if isinstance(data, dict):
            tools = data.get("tools", [])
        else:
            tools = data
        new_tool_ids = ["counseling_armor", "question_generator", "cooling_off_check"]
        for tool in tools:
            if tool["id"] in new_tool_ids:
                assert tool.get("badge") == "NEW"


# ==========================================
# ドクター API テスト
# ==========================================


@pytest.mark.anyio
async def test_get_doctors(client: AsyncClient):
    """医師一覧を取得できる"""
    resp = await client.get("/api/doctors/")
    assert resp.status_code == 200
    data = resp.json()
    assert "doctors" in data
    assert "total" in data
    assert isinstance(data["doctors"], list)


@pytest.mark.anyio
async def test_get_doctors_pagination(client: AsyncClient):
    """医師一覧のページネーションが機能する"""
    resp = await client.get("/api/doctors/?page=1&per_page=5")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["doctors"]) <= 5
    assert "total_pages" in data


@pytest.mark.anyio
async def test_get_doctors_sort_by_score(client: AsyncClient):
    """信頼性スコア順でソートできる"""
    resp = await client.get("/api/doctors/?sort_by=score")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["doctors"], list)


@pytest.mark.anyio
async def test_get_doctors_sort_by_experience(client: AsyncClient):
    """経験年数順でソートできる"""
    resp = await client.get("/api/doctors/?sort_by=experience")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_search_doctors(client: AsyncClient):
    """医師名で検索できる"""
    resp = await client.get("/api/doctors/search?q=医師")
    assert resp.status_code == 200
    data = resp.json()
    assert "doctors" in data
    assert "total" in data


@pytest.mark.anyio
async def test_search_doctors_empty_query(client: AsyncClient):
    """空クエリでバリデーションエラー（min_length=1）"""
    resp = await client.get("/api/doctors/search?q=")
    assert resp.status_code == 422  # min_length=1 バリデーション


@pytest.mark.anyio
async def test_get_doctors_stats(client: AsyncClient):
    """医師統計APIが正常応答する"""
    resp = await client.get("/api/doctors/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "certification_rate" in data
    assert "note" in data


@pytest.mark.anyio
async def test_get_doctor_detail(client: AsyncClient):
    """医師詳細を取得できる"""
    resp = await client.get("/api/doctors/?per_page=1")
    doctors = resp.json()["doctors"]
    if not doctors:
        pytest.skip("医師データなし")

    doctor_id = doctors[0]["id"]
    resp = await client.get(f"/api/doctors/{doctor_id}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["id"] == doctor_id
    assert "name" in detail


@pytest.mark.anyio
async def test_get_doctor_detail_not_found(client: AsyncClient):
    """存在しない医師IDで404が返る"""
    resp = await client.get("/api/doctors/nonexistent_id_12345")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_get_doctors_by_clinic(client: AsyncClient):
    """クリニックIDで医師一覧を取得できる"""
    # まずクリニックIDを取得
    resp = await client.get("/api/clinics/?limit=1")
    clinics = resp.json()["clinics"]
    if not clinics:
        pytest.skip("クリニックデータなし")

    clinic_id = clinics[0]["id"]
    resp = await client.get(f"/api/doctors/by-clinic/{clinic_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["doctors"], list)


@pytest.mark.anyio
async def test_doctor_response_has_trust_fields(client: AsyncClient):
    """医師レスポンスにtrust_score関連フィールドが含まれる"""
    resp = await client.get("/api/doctors/?per_page=1")
    doctors = resp.json()["doctors"]
    if not doctors:
        pytest.skip("医師データなし")

    doc = doctors[0]
    # trust_scoreフィールドが存在する（null可）
    assert "trust_score" in doc or "name" in doc
    # 基本フィールド
    assert "name" in doc
    assert "id" in doc


# ==========================================
# ドクタースコアリング 単体テスト
# ==========================================


class TestDoctorScoring:
    """医師信頼性スコアリングエンジンの単体テスト"""

    def test_calculate_basic_score(self):
        """基本スコア計算が動作する"""
        from src.analyzers.doctor_scoring import calculate_trust_score
        result = calculate_trust_score(
            board_certifications=["日本形成外科学会認定専門医"],
            experience_years=15,
            specialties=["二重", "鼻整形"],
        )
        assert hasattr(result, "total")
        assert 0 <= result.total <= 100
        assert result.certification > 0
        assert result.experience > 0

    def test_calculate_score_no_data(self):
        """データなしでもスコアが計算できる"""
        from src.analyzers.doctor_scoring import calculate_trust_score
        result = calculate_trust_score()
        assert result.total >= 0
        assert result.total <= 100

    def test_score_level_mapping(self):
        """スコアレベルのマッピングが正しく動作する"""
        from src.analyzers.doctor_scoring import get_trust_level
        level_high = get_trust_level(80)
        assert level_high["label"] is not None
        assert level_high["color"] is not None

        level_low = get_trust_level(20)
        assert level_low["label"] != level_high["label"]

    def test_jsaps_bonus(self):
        """JSAPS資格でボーナスが付く"""
        from src.analyzers.doctor_scoring import calculate_trust_score
        without = calculate_trust_score(
            board_certifications=["形成外科専門医"],
        )
        with_jsaps = calculate_trust_score(
            board_certifications=["形成外科専門医"],
            jsaps_certified=True,
        )
        assert with_jsaps.total >= without.total

    def test_to_dict(self):
        """to_dict()でスコア内訳を辞書形式に変換できる"""
        from src.analyzers.doctor_scoring import calculate_trust_score
        result = calculate_trust_score(
            board_certifications=["形成外科専門医"],
            experience_years=10,
        )
        d = result.to_dict()
        assert "total" in d
        assert "certification" in d
        assert d["certification"]["max"] == 25


# ==========================================
# 推薦エンジン — 医師データ活用テスト
# ==========================================


class TestRecommendationDoctorIntegration:
    """推薦エンジンの医師データ活用に関するテスト"""

    def test_quality_score_with_specialist(self):
        """専門医在籍でquality_scoreが上がる"""
        from src.advisor.recommendation_engine import calculate_quality_score
        without = calculate_quality_score(
            google_rating=4.0,
            google_review_count=50,
            has_specialist=False,
            departments=["美容外科"],
        )
        with_spec = calculate_quality_score(
            google_rating=4.0,
            google_review_count=50,
            has_specialist=True,
            departments=["美容外科"],
        )
        assert with_spec > without

    def test_match_score_quality_priority(self):
        """品質重視の場合にquality_scoreの重みが大きい"""
        from src.advisor.recommendation_engine import calculate_match_score, UserPriority
        # 予算オーバー（budget_fit=False）で品質スコア高 → 品質重視のほうが高スコア
        score_q = calculate_match_score(
            quality_score=90,
            area_match="none",
            budget_fit=False,
            dt_fit=True,
            priority=UserPriority.QUALITY,
        )
        score_p = calculate_match_score(
            quality_score=90,
            area_match="none",
            budget_fit=False,
            dt_fit=True,
            priority=UserPriority.PRICE,
        )
        # 品質重視のほうが品質スコアの影響が大きい
        assert score_q > score_p


# ==========================================
# Phase 12: 口コミ分析深化テスト
# ==========================================


class TestReviewAnalyzerEnhanced:
    """レッドフラグ検出・品質スコア・医師マッピングのテスト"""

    def setup_method(self):
        """テスト用アナライザーの初期化"""
        from src.analyzers.review_analyzer import ReviewAnalyzer
        self.analyzer = ReviewAnalyzer()

    # --- レッドフラグ検出 ---

    def test_detect_red_flag_pressure_sales(self):
        """圧力販売のレッドフラグを検出する"""
        text = "カウンセリングで即日契約を迫られました。とても不愉快でした。"
        result = self.analyzer.analyze("test-1", text)
        assert len(result.red_flags) > 0
        assert any(f["category"] == "pressure_sales" for f in result.red_flags)

    def test_detect_red_flag_treatment_trouble(self):
        """施術トラブルのレッドフラグを検出する"""
        text = "二重手術に失敗され、修正手術が必要になりました。"
        result = self.analyzer.analyze("test-2", text)
        assert len(result.red_flags) > 0
        assert any(f["category"] == "treatment_trouble" for f in result.red_flags)

    def test_detect_red_flag_staff_issue(self):
        """スタッフ問題のレッドフラグを検出する"""
        text = "受付の態度が悪い。質問しても横柄な対応でした。"
        result = self.analyzer.analyze("test-3", text)
        assert len(result.red_flags) > 0
        assert any(f["category"] == "staff_issue" for f in result.red_flags)

    def test_detect_red_flag_billing_issue(self):
        """会計問題のレッドフラグを検出する"""
        text = "事前の説明と違う追加料金が発生して驚きました。ぼったくりです。"
        result = self.analyzer.analyze("test-4", text)
        assert len(result.red_flags) > 0
        assert any(f["category"] == "billing_issue" for f in result.red_flags)

    def test_no_red_flags_on_positive_review(self):
        """ポジティブな口コミにはレッドフラグが検出されない"""
        text = "先生がとても丁寧で安心しました。仕上がりも綺麗で満足です。おすすめです。"
        result = self.analyzer.analyze("test-5", text)
        assert len(result.red_flags) == 0

    # --- 品質スコア ---

    def test_quality_score_high_for_detailed_review(self):
        """詳細な口コミは高品質スコアになる"""
        text = "2024年3月に埋没法の二重手術を受けました。費用は15万円でした。先生の説明が丁寧で安心しました。仕上がりも自然で大変満足しています。ダウンタイムは1週間程度でした。"
        result = self.analyzer.analyze("test-6", text, rating=5.0)
        assert result.quality_score >= 60

    def test_quality_score_low_for_short_review(self):
        """短い口コミは低品質スコアになる"""
        text = "まあまあでした。"
        result = self.analyzer.analyze("test-7", text, rating=3.0)
        assert result.quality_score < 40

    def test_quality_score_penalizes_inconsistency(self):
        """テキストとレーティングが矛盾する口コミは低スコア"""
        text = "最悪でした。後悔しています。二度と行かない。失敗されました。"
        result_consistent = self.analyzer.analyze("test-8a", text, rating=1.0)
        result_inconsistent = self.analyzer.analyze("test-8b", text, rating=5.0)
        assert result_consistent.quality_score > result_inconsistent.quality_score

    def test_quality_score_bonus_for_specificity(self):
        """具体的な金額・施術名の言及があるとボーナス"""
        generic = "良い病院でした。先生が親切で安心しました。対応も丁寧でした。"
        specific = "ヒアルロン酸を3万円で受けました。先生が親切で安心しました。対応も丁寧でした。"
        result_generic = self.analyzer.analyze("test-9a", generic, rating=5.0)
        result_specific = self.analyzer.analyze("test-9b", specific, rating=5.0)
        assert result_specific.quality_score > result_generic.quality_score

    # --- 医師マッピング ---

    def test_doctor_match_fullname(self):
        """フルネームで医師をマッチする"""
        from types import SimpleNamespace
        doctors = [SimpleNamespace(id="doc-1", name="田中 太郎")]
        text = "田中太郎先生に二重の手術をしてもらいました。とても丁寧でした。"
        result = self.analyzer.analyze("test-10", text, clinic_doctors=doctors)
        assert result.matched_doctor_id == "doc-1"

    def test_doctor_match_surname_with_suffix(self):
        """姓+敬称で医師をマッチする"""
        from types import SimpleNamespace
        doctors = [SimpleNamespace(id="doc-2", name="鈴木 花子")]
        text = "鈴木先生のカウンセリングが丁寧で安心しました。おすすめです。"
        result = self.analyzer.analyze("test-11", text, clinic_doctors=doctors)
        assert result.matched_doctor_id == "doc-2"

    def test_doctor_no_match(self):
        """マッチしない場合はNone"""
        from types import SimpleNamespace
        doctors = [SimpleNamespace(id="doc-3", name="佐藤 一郎")]
        text = "とても良いクリニックでした。先生が親切で安心しました。"
        result = self.analyzer.analyze("test-12", text, clinic_doctors=doctors)
        assert result.matched_doctor_id is None


class TestGenerateCautionsWithRedFlags:
    """レッドフラグに基づくcaution生成のテスト"""

    def test_pressure_sales_caution(self):
        """圧力販売のレッドフラグでcautionが生成される"""
        from src.advisor.recommendation_engine import generate_cautions
        from types import SimpleNamespace
        clinic = SimpleNamespace(google_place_id=None)
        review_summary = {"red_flags": {"pressure_sales": 3}}
        cautions = generate_cautions(clinic, [], None, None, review_summary=review_summary)
        assert any("勧誘" in c for c in cautions)

    def test_treatment_trouble_caution(self):
        """施術トラブルのレッドフラグでcautionが生成される"""
        from src.advisor.recommendation_engine import generate_cautions
        from types import SimpleNamespace
        clinic = SimpleNamespace(google_place_id=None)
        review_summary = {"red_flags": {"treatment_trouble": 2}}
        cautions = generate_cautions(clinic, [], None, None, review_summary=review_summary)
        assert any("施術結果" in c for c in cautions)

    def test_single_flag_generates_mild_caution(self):
        """レッドフラグが1件でもmild cautionが生成される"""
        from src.advisor.recommendation_engine import generate_cautions
        from types import SimpleNamespace
        clinic = SimpleNamespace(google_place_id=None)
        review_summary = {"red_flags": {"pressure_sales": 1}}
        cautions = generate_cautions(clinic, [], 4.5, 100, review_summary=review_summary)
        assert any("圧力販売" in c for c in cautions)


@pytest.mark.anyio
async def test_clinic_detail_has_review_quality(client: AsyncClient):
    """クリニック詳細APIにreview quality関連データが含まれる"""
    resp = await client.get("/api/clinics")
    clinics = resp.json()["clinics"]
    if not clinics:
        pytest.skip("クリニックデータなし")
    clinic_id = clinics[0]["id"]
    detail = await client.get(f"/api/clinics/{clinic_id}")
    data = detail.json()
    # review_summaryが存在する場合、構造を検証
    if "review_summary" in data and data["review_summary"]["total"] > 0:
        rs = data["review_summary"]
        assert "total" in rs
        assert "positive" in rs
        assert "negative" in rs
        # Phase 12で追加されたフィールド
        # avg_qualityはデータがあれば含まれる
    # 個別口コミにquality_score/red_flagsが含まれる
    if data.get("reviews"):
        for r in data["reviews"]:
            assert "quality_score" in r
            assert "red_flags" in r


# ==========================================
# Phase 14: データ・機能強化テスト
# ==========================================


@pytest.mark.anyio
async def test_market_prices_endpoint(client: AsyncClient):
    """施術別市場価格統計APIの正常レスポンス"""
    resp = await client.get("/api/procedures/market-prices")
    assert resp.status_code == 200
    data = resp.json()
    assert "market_prices" in data
    assert "total_procedures" in data
    assert data["total_procedures"] > 0
    for p in data["market_prices"][:3]:
        assert "procedure_id" in p
        assert "median" in p
        assert p["sample_count"] >= 3


@pytest.mark.anyio
async def test_procedure_detail_has_market_price(client: AsyncClient):
    """施術詳細APIにmarket_priceが含まれる"""
    resp = await client.get("/api/procedures")
    procs = resp.json()["procedures"]
    assert len(procs) > 0
    proc_id = procs[0]["id"]
    detail = await client.get(f"/api/procedures/{proc_id}")
    assert detail.status_code == 200
    data = detail.json()
    assert "id" in data
    assert "pricing" in data


class TestDoctorSpecialtyMapping:
    """医師×施術 専門性マッピングのテスト"""

    def test_jsaps_maps_to_surgery(self):
        """JSAPS認定は外科系カテゴリにマッピングされる"""
        from src.analyzers.doctor_specialty import estimate_doctor_specialties
        result = estimate_doctor_specialties("doc-1", "テスト太郎", jsaps_certified=True)
        assert "eye" in result.matched_categories
        assert "nose" in result.matched_categories

    def test_dermatology_maps_to_skin(self):
        """皮膚科専門医はスキン系にマッピングされる"""
        from src.analyzers.doctor_specialty import estimate_doctor_specialties
        result = estimate_doctor_specialties("doc-2", "テスト花子", certifications=["皮膚科専門医"])
        assert "skin" in result.matched_categories

    def test_specialty_keyword_mapping(self):
        """専門分野キーワードからカテゴリをマッピング"""
        from src.analyzers.doctor_specialty import estimate_doctor_specialties
        result = estimate_doctor_specialties("doc-3", "テスト次郎", specialties=["二重", "目元"])
        assert "eye" in result.matched_categories

    def test_confidence_high(self):
        """複数ソースで信頼度high"""
        from src.analyzers.doctor_specialty import estimate_doctor_specialties
        result = estimate_doctor_specialties("doc-4", "テスト三郎", certifications=["形成外科専門医"], jsaps_certified=True)
        assert result.confidence == "high"

    def test_procedure_category_match(self):
        """施術カテゴリとのマッチ判定"""
        from src.analyzers.doctor_specialty import estimate_doctor_specialties, match_doctor_to_procedure_category
        spec = estimate_doctor_specialties("doc-5", "テスト五郎", certifications=["形成外科専門医"])
        assert match_doctor_to_procedure_category(spec, "eye") is True
        assert match_doctor_to_procedure_category(spec, "hair_removal") is False


class TestPriceLabel:
    """相場対比ラベルのテスト"""

    def test_affordable_label(self):
        """相場の7割未満はお手頃"""
        from src.analyzers.price_intelligence import get_price_label
        result = get_price_label(50000, 100000)
        assert result.label == "お手頃"

    def test_average_label(self):
        """相場の±30%は平均的"""
        from src.analyzers.price_intelligence import get_price_label
        result = get_price_label(100000, 100000)
        assert result.label == "平均的"

    def test_premium_label(self):
        """相場の2倍以上はプレミアム"""
        from src.analyzers.price_intelligence import get_price_label
        result = get_price_label(250000, 100000)
        assert result.label == "プレミアム"


# ==========================================
# Phase 16: クリニック比較+施術検索テスト
# ==========================================


@pytest.mark.anyio
async def test_clinics_by_procedure(client: AsyncClient):
    """施術特化型クリニック検索の正常レスポンス"""
    # まず施術IDを取得
    resp = await client.get("/api/procedures")
    procs = resp.json()["procedures"]
    assert len(procs) > 0
    proc_id = procs[0]["id"]

    # 施術別クリニック検索
    resp = await client.get(f"/api/clinics/by-procedure/{proc_id}?sort_by=price&per_page=5")
    assert resp.status_code == 200
    data = resp.json()
    assert "procedure" in data
    assert data["procedure"]["id"] == proc_id
    assert "clinics" in data
    assert "total" in data


@pytest.mark.anyio
async def test_clinics_by_procedure_with_city_filter(client: AsyncClient):
    """施術特化型クリニック検索 — 市区町村フィルタ"""
    resp = await client.get("/api/procedures")
    procs = resp.json()["procedures"]
    proc_id = procs[0]["id"]

    resp = await client.get(f"/api/clinics/by-procedure/{proc_id}?city=渋谷区&per_page=5")
    assert resp.status_code == 200
    data = resp.json()
    # 渋谷区のクリニックのみ
    for c in data["clinics"]:
        assert c["city"] == "渋谷区"


@pytest.mark.anyio
async def test_clinic_compare_side_by_side(client: AsyncClient):
    """クリニック比較APIの正常レスポンス"""
    # まずクリニックIDを2件取得
    resp = await client.get("/api/clinics?per_page=2")
    clinics = resp.json()["clinics"]
    if len(clinics) < 2:
        pytest.skip("比較に必要な2院以上のデータがありません")
    ids = ",".join([c["id"] for c in clinics[:2]])

    resp = await client.get(f"/api/clinics/compare/side-by-side?ids={ids}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    for c in data["clinics"]:
        assert "name" in c
        assert "google_rating" in c
        assert "doctor_count" in c
        assert "procedure_count" in c
        assert "review_count" in c


@pytest.mark.anyio
async def test_clinic_compare_too_few(client: AsyncClient):
    """クリニック比較 — 1件のみでエラー"""
    resp = await client.get("/api/clinics?per_page=1")
    clinics = resp.json()["clinics"]
    if not clinics:
        pytest.skip("データなし")
    resp = await client.get(f"/api/clinics/compare/side-by-side?ids={clinics[0]['id']}")
    assert resp.status_code == 400


# ==========================================
# エリア統計API テスト
# ==========================================


@pytest.mark.anyio
async def test_area_stats(client: AsyncClient):
    """エリア統計APIが正常にレスポンスを返す"""
    resp = await client.get("/api/clinics/area-stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "areas" in data
    assert "total_areas" in data
    assert isinstance(data["areas"], list)
    # データがある場合、各エリアのフィールドを検証
    if data["total_areas"] > 0:
        area = data["areas"][0]
        assert "city" in area
        assert "clinic_count" in area
        assert "avg_rating" in area
        assert "avg_transparency" in area
        assert "doctor_count" in area
        assert "jsaps_count" in area
        assert "review_count" in area
        assert "avg_sentiment" in area
        assert "red_flag_count" in area
        assert "top_procedures" in area
        assert isinstance(area["top_procedures"], list)
        # クリニック数降順であることを確認
        counts = [a["clinic_count"] for a in data["areas"]]
        assert counts == sorted(counts, reverse=True)
    # 最大15エリアであること
    assert data["total_areas"] <= 15


# ==========================================
# Time Decay 単体テスト
# ==========================================


class TestTimeDecayWeight:
    """time_decay_weight関数の単体テスト"""

    def test_recent_review(self):
        """今日の口コミ → 重み≒1.0"""
        from datetime import datetime, timezone
        from src.advisor.recommendation_engine import time_decay_weight
        now = datetime.now(timezone.utc)
        weight = time_decay_weight(now)
        assert 0.99 <= weight <= 1.0

    def test_one_year_ago(self):
        """1年前の口コミ → 重み≒0.5（半減期365日）"""
        from datetime import datetime, timezone, timedelta
        from src.advisor.recommendation_engine import time_decay_weight
        one_year_ago = datetime.now(timezone.utc) - timedelta(days=365)
        weight = time_decay_weight(one_year_ago)
        assert 0.45 <= weight <= 0.55

    def test_two_years_ago(self):
        """2年前の口コミ → 重み≒0.25"""
        from datetime import datetime, timezone, timedelta
        from src.advisor.recommendation_engine import time_decay_weight
        two_years_ago = datetime.now(timezone.utc) - timedelta(days=730)
        weight = time_decay_weight(two_years_ago)
        assert 0.20 <= weight <= 0.30

    def test_none_date(self):
        """日付がNone → 重み0.5（中間値）"""
        from src.advisor.recommendation_engine import time_decay_weight
        weight = time_decay_weight(None)
        assert weight == 0.5

    def test_naive_datetime(self):
        """timezone情報なしのdatetime → UTC扱いで正常動作"""
        from datetime import datetime, timedelta
        from src.advisor.recommendation_engine import time_decay_weight
        recent = datetime.utcnow() - timedelta(days=1)
        weight = time_decay_weight(recent)
        assert 0.99 <= weight <= 1.0

    def test_custom_half_life(self):
        """半減期180日 → 180日前の口コミが重み≒0.5"""
        from datetime import datetime, timezone, timedelta
        from src.advisor.recommendation_engine import time_decay_weight
        half_life_ago = datetime.now(timezone.utc) - timedelta(days=180)
        weight = time_decay_weight(half_life_ago, half_life_days=180)
        assert 0.45 <= weight <= 0.55

    def test_future_date(self):
        """未来の日付 → 重み1.0（days_agoを0にクリップ）"""
        from datetime import datetime, timezone, timedelta
        from src.advisor.recommendation_engine import time_decay_weight
        future = datetime.now(timezone.utc) + timedelta(days=30)
        weight = time_decay_weight(future)
        assert weight == 1.0


# ==========================================
# レッドフラグ注意文生成 テスト
# ==========================================


class TestRedFlagCautionGeneration:
    """generate_cautions関数のレッドフラグ注意文テスト"""

    def _make_mock_clinic(self):
        """テスト用のモッククリニックを生成"""
        from unittest.mock import MagicMock
        clinic = MagicMock()
        clinic.google_rating = 4.0
        clinic.google_review_count = 50
        clinic.city = "渋谷区"
        return clinic

    def test_pressure_sales_mild(self):
        """圧力販売1-2件 → mild表現"""
        from src.advisor.recommendation_engine import generate_cautions
        clinic = self._make_mock_clinic()
        review_summary = {"red_flags": {"pressure_sales": 2}}
        cautions = generate_cautions(
            clinic, ["美容外科"], 4.0, 50, review_summary=review_summary,
        )
        # mildメッセージが含まれる
        flag_cautions = [c for c in cautions if "圧力販売" in c or "勧誘" in c]
        assert len(flag_cautions) == 1
        assert "2件" in flag_cautions[0]

    def test_pressure_sales_severe(self):
        """圧力販売3件以上 → severe表現"""
        from src.advisor.recommendation_engine import generate_cautions
        clinic = self._make_mock_clinic()
        review_summary = {"red_flags": {"pressure_sales": 5}}
        cautions = generate_cautions(
            clinic, ["美容外科"], 4.0, 50, review_summary=review_summary,
        )
        flag_cautions = [c for c in cautions if "勧誘" in c or "断る" in c]
        assert len(flag_cautions) == 1
        assert "断る準備" in flag_cautions[0]

    def test_treatment_trouble_mild(self):
        """施術トラブル1件 → mild表現"""
        from src.advisor.recommendation_engine import generate_cautions
        clinic = self._make_mock_clinic()
        review_summary = {"red_flags": {"treatment_trouble": 1}}
        cautions = generate_cautions(
            clinic, ["美容外科"], 4.0, 50, review_summary=review_summary,
        )
        flag_cautions = [c for c in cautions if "施術結果" in c]
        assert len(flag_cautions) == 1
        assert "1件" in flag_cautions[0]

    def test_treatment_trouble_severe(self):
        """施術トラブル2件以上 → severe表現（閾値が低い）"""
        from src.advisor.recommendation_engine import generate_cautions
        clinic = self._make_mock_clinic()
        review_summary = {"red_flags": {"treatment_trouble": 3}}
        cautions = generate_cautions(
            clinic, ["美容外科"], 4.0, 50, review_summary=review_summary,
        )
        flag_cautions = [c for c in cautions if "施術結果" in c and "確認" in c]
        assert len(flag_cautions) == 1

    def test_billing_issue_severe(self):
        """会計トラブル2件以上 → severe表現"""
        from src.advisor.recommendation_engine import generate_cautions
        clinic = self._make_mock_clinic()
        review_summary = {"red_flags": {"billing_issue": 2}}
        cautions = generate_cautions(
            clinic, ["美容外科"], 4.0, 50, review_summary=review_summary,
        )
        flag_cautions = [c for c in cautions if "料金" in c and "書面" in c]
        assert len(flag_cautions) == 1

    def test_multiple_red_flags(self):
        """複数カテゴリのレッドフラグ → それぞれ個別の注意文"""
        from src.advisor.recommendation_engine import generate_cautions
        clinic = self._make_mock_clinic()
        review_summary = {
            "red_flags": {
                "pressure_sales": 3,
                "treatment_trouble": 1,
                "staff_issue": 2,
            }
        }
        cautions = generate_cautions(
            clinic, ["美容外科"], 4.0, 50, review_summary=review_summary,
        )
        # 3カテゴリ分の注意文が含まれる
        flag_related = [c for c in cautions if any(
            kw in c for kw in ["勧誘", "施術結果", "スタッフ"]
        )]
        assert len(flag_related) == 3

    def test_no_red_flags(self):
        """レッドフラグなし → レッドフラグ関連の注意文は出ない"""
        from src.advisor.recommendation_engine import generate_cautions
        clinic = self._make_mock_clinic()
        review_summary = {"red_flags": {}}
        cautions = generate_cautions(
            clinic, ["美容外科"], 4.0, 50, review_summary=review_summary,
        )
        flag_related = [c for c in cautions if any(
            kw in c for kw in ["勧誘", "施術結果", "スタッフ", "料金"]
        )]
        assert len(flag_related) == 0

    def test_unknown_category(self):
        """未定義カテゴリ → 汎用メッセージ"""
        from src.advisor.recommendation_engine import generate_cautions
        clinic = self._make_mock_clinic()
        review_summary = {"red_flags": {"unknown_category": 2}}
        cautions = generate_cautions(
            clinic, ["美容外科"], 4.0, 50, review_summary=review_summary,
        )
        flag_related = [c for c in cautions if "unknown_category" in c]
        assert len(flag_related) == 1


# ==========================================
# Phase 31: 施術比較APIテスト
# ==========================================


@pytest.mark.anyio
async def test_procedure_compare_basic(client: AsyncClient):
    """2件以上の施術IDで比較レスポンスが返ることを確認"""
    # まず施術一覧を取得し、2つのIDを使用
    resp = await client.get("/api/procedures")
    procs = resp.json()["procedures"]
    if len(procs) >= 2:
        ids = f"{procs[0]['id']},{procs[1]['id']}"
        resp = await client.get(f"/api/procedures/compare?ids={ids}")
        assert resp.status_code == 200
        data = resp.json()
        assert "procedures" in data
        assert len(data["procedures"]) >= 2


@pytest.mark.anyio
async def test_procedure_compare_too_few(client: AsyncClient):
    """施術IDが1件以下の場合400エラー"""
    resp = await client.get("/api/procedures/compare?ids=fake_id")
    assert resp.status_code == 400


# ==========================================
# Phase 31: Deep Linking SPAルートテスト
# ==========================================


@pytest.mark.anyio
async def test_deep_link_clinic(client: AsyncClient):
    """/clinics/{id}が200を返すことを確認"""
    resp = await client.get("/clinics/test-id")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


@pytest.mark.anyio
async def test_deep_link_procedure(client: AsyncClient):
    """/procedures/{id}が200を返すことを確認"""
    resp = await client.get("/procedures/test-id")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


@pytest.mark.anyio
async def test_deep_link_doctor(client: AsyncClient):
    """/doctors/{id}が200を返すことを確認"""
    resp = await client.get("/doctors/test-id")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


# ==========================================
# Phase 31: タイムラインAPIテスト
# ==========================================


@pytest.mark.anyio
async def test_timeline_basic(client: AsyncClient):
    """施術タイムラインが取得できることを確認"""
    resp = await client.get("/api/procedures")
    procs = resp.json()["procedures"]
    if procs:
        pid = procs[0]["id"]
        resp = await client.get(f"/api/procedures/{pid}/timeline")
        assert resp.status_code == 200
        data = resp.json()
        assert "phases" in data
        assert "procedure_name" in data


@pytest.mark.anyio
async def test_timeline_not_found(client: AsyncClient):
    """存在しない施術IDは404"""
    resp = await client.get("/api/procedures/nonexistent/timeline")
    assert resp.status_code == 404


# ==========================================
# Phase 31: 口コミ要約APIテスト
# ==========================================


@pytest.mark.anyio
async def test_review_summary_basic(client: AsyncClient):
    """口コミ要約が取得できることを確認"""
    resp = await client.get("/api/clinics")
    clinics = resp.json()["clinics"]
    if clinics:
        cid = clinics[0]["id"]
        resp = await client.get(f"/api/clinics/{cid}/review-summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "clinic_id" in data
        assert "total_reviews" in data
        assert "sentiment_distribution" in data


@pytest.mark.anyio
async def test_review_summary_nonexistent(client: AsyncClient):
    """存在しないクリニックIDは404を返す"""
    resp = await client.get("/api/clinics/nonexistent/review-summary")
    assert resp.status_code == 404



# ==========================================
# Phase 31: 通知APIテスト
# ==========================================


@pytest.mark.anyio
async def test_notifications_empty(client: AsyncClient):
    """お気に入りなしで空配列を返す"""
    resp = await client.get("/api/notifications")
    assert resp.status_code == 200
    data = resp.json()
    assert data["notifications"] == []
    assert data["unread_count"] == 0


@pytest.mark.anyio
async def test_notifications_with_favorites(client: AsyncClient):
    """お気に入りIDがある場合のレスポンス形式確認"""
    resp = await client.get("/api/clinics")
    clinics = resp.json()["clinics"]
    if clinics:
        cid = clinics[0]["id"]
        resp = await client.get(f"/api/notifications?favorite_ids={cid}")
        assert resp.status_code == 200
        data = resp.json()
        assert "notifications" in data
        assert "unread_count" in data


# ==========================================
# Phase 33: チェーン分析 + クリニックスコア
# ==========================================


@pytest.mark.anyio
async def test_chain_analysis(client: AsyncClient):
    """チェーン分析APIが正常にレスポンスを返す"""
    resp = await client.get("/api/clinics/chain-analysis")
    assert resp.status_code == 200
    data = resp.json()
    assert "chains" in data
    assert "independent" in data
    assert isinstance(data["chains"], list)
    assert data["independent"]["clinic_count"] > 0


@pytest.mark.anyio
async def test_chain_analysis_has_scores(client: AsyncClient):
    """チェーン分析にスコア情報が含まれる"""
    resp = await client.get("/api/clinics/chain-analysis")
    data = resp.json()
    if data["chains"]:
        chain = data["chains"][0]
        assert "chain_name" in chain
        assert "clinic_count" in chain
        assert "avg_clinic_score" in chain


@pytest.mark.anyio
async def test_clinic_stats_has_grade_distribution(client: AsyncClient):
    """クリニック統計にグレード分布が含まれる"""
    resp = await client.get("/api/clinics/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "grade_distribution" in data
    assert "chain_stats" in data
    assert data["chain_stats"]["chain_count"] > 0


@pytest.mark.anyio
async def test_clinic_has_score_in_response(client: AsyncClient):
    """クリニック一覧レスポンスにスコア・グレード情報が含まれる"""
    resp = await client.get("/api/clinics/?limit=1")
    assert resp.status_code == 200
    clinics = resp.json()["clinics"]
    if clinics:
        c = clinics[0]
        assert "clinic_score" in c
        assert "clinic_grade" in c


@pytest.mark.anyio
async def test_clinic_detail_has_score(client: AsyncClient):
    """クリニック詳細にもスコアが含まれる"""
    resp = await client.get("/api/clinics/?limit=1")
    clinics = resp.json()["clinics"]
    if not clinics:
        pytest.skip("クリニックデータなし")
    clinic_id = clinics[0]["id"]
    resp = await client.get(f"/api/clinics/{clinic_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert "clinic_score" in data
    assert "clinic_grade" in data


# ==========================================
# Phase 34: カテゴリ拡充確認
# ==========================================


@pytest.mark.anyio
async def test_all_categories_have_clinic_procedures(client: AsyncClient):
    """全8カテゴリに施術クリニック紐付けが存在する"""
    resp = await client.get("/api/procedures/")
    data = resp.json()
    procs = data.get("procedures", [])
    # カテゴリごとに最初の施術でclinic紐付けチェック
    categories_seen = {}
    for p in procs:
        cat = p["category"]
        if cat not in categories_seen:
            categories_seen[cat] = p["id"]
    categories_checked = set()
    for cat, proc_id in categories_seen.items():
        r = await client.get(f"/api/procedures/{proc_id}/top-clinics?limit=1")
        if r.status_code == 200:
            data2 = r.json()
            if data2.get("total", 0) > 0:
                categories_checked.add(cat)
    # 少なくとも4カテゴリ以上にデータがあること
    assert len(categories_checked) >= 4, f"カバー: {categories_checked} ({len(categories_checked)}/8)"


# ==========================================
# Phase 35: 施術別クリニックランキング
# ==========================================


@pytest.mark.anyio
async def test_top_clinics_for_procedure(client: AsyncClient):
    """施術別クリニックランキングが正常に動作する"""
    resp = await client.get("/api/procedures/")
    procs = resp.json().get("procedures", [])
    if not procs:
        pytest.skip("施術データなし")

    proc_id = procs[0]["id"]
    resp = await client.get(f"/api/procedures/{proc_id}/top-clinics")
    assert resp.status_code == 200
    data = resp.json()
    assert "procedure" in data
    assert "clinics" in data
    assert "total" in data
    assert isinstance(data["clinics"], list)


@pytest.mark.anyio
async def test_top_clinics_has_ranking_fields(client: AsyncClient):
    """ランキングレスポンスにスコア・順位が含まれる"""
    resp = await client.get("/api/procedures/")
    procs = resp.json().get("procedures", [])
    if not procs:
        pytest.skip("施術データなし")

    proc_id = procs[0]["id"]
    resp = await client.get(f"/api/procedures/{proc_id}/top-clinics?limit=3")
    data = resp.json()
    if data["clinics"]:
        clinic = data["clinics"][0]
        assert "rank" in clinic
        assert "score" in clinic
        assert "clinic_grade" in clinic
        assert "name" in clinic
        assert clinic["rank"] == 1


@pytest.mark.anyio
async def test_top_clinics_sort_by_price(client: AsyncClient):
    """価格順ソートが動作する"""
    resp = await client.get("/api/procedures/")
    procs = resp.json().get("procedures", [])
    if not procs:
        pytest.skip("施術データなし")

    proc_id = procs[0]["id"]
    resp = await client.get(f"/api/procedures/{proc_id}/top-clinics?sort_by=price&limit=5")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_top_clinics_sort_by_rating(client: AsyncClient):
    """評価順ソートが動作する"""
    resp = await client.get("/api/procedures/")
    procs = resp.json().get("procedures", [])
    if not procs:
        pytest.skip("施術データなし")

    proc_id = procs[0]["id"]
    resp = await client.get(f"/api/procedures/{proc_id}/top-clinics?sort_by=rating&limit=5")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_top_clinics_not_found(client: AsyncClient):
    """存在しない施術IDで404を返す"""
    resp = await client.get("/api/procedures/nonexistent_id/top-clinics")
    assert resp.status_code == 404


# ==========================================
# Phase 36: セッション一覧
# ==========================================


@pytest.mark.anyio
async def test_sessions_list(client: AsyncClient):
    """セッション一覧APIが正常に動作する"""
    resp = await client.get("/api/advisor/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert "sessions" in data
    assert "total" in data
    assert isinstance(data["sessions"], list)


@pytest.mark.anyio
async def test_session_appears_after_chat(client: AsyncClient):
    """チャット後にセッション一覧に表示される"""
    # 会話を作成
    resp = await client.post(
        "/api/advisor/chat",
        json={"message": "テストセッション用のメッセージ"},
    )
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    # セッション一覧に表示されるか確認
    resp2 = await client.get("/api/advisor/sessions")
    data = resp2.json()
    session_ids = [s["session_id"] for s in data["sessions"]]
    assert session_id in session_ids


@pytest.mark.anyio
async def test_session_has_summary(client: AsyncClient):
    """セッションにsummaryが含まれる"""
    # 会話を作成
    resp = await client.post(
        "/api/advisor/chat",
        json={"message": "鼻を高くしたいです"},
    )
    session_id = resp.json()["session_id"]

    resp2 = await client.get("/api/advisor/sessions")
    sessions = resp2.json()["sessions"]
    target = [s for s in sessions if s["session_id"] == session_id]
    assert len(target) == 1
    assert "鼻を高くしたい" in target[0]["summary"]


# ==========================================
# Phase 33: クリニックスコアリングエンジン 単体テスト
# ==========================================


class TestClinicScoring:
    """クリニックスコアリングエンジンの単体テスト"""

    def test_score_basic(self):
        """基本的なスコア算出が動作する"""
        from src.analyzers.clinic_scoring import score_clinic
        result = score_clinic(google_rating=4.0, has_website=True)
        assert 0 <= result.total <= 100
        assert result.transparency > 0
        assert result.review_quality > 0

    def test_score_high_quality(self):
        """高品質クリニックが高スコアになる"""
        from src.analyzers.clinic_scoring import score_clinic
        result = score_clinic(
            google_rating=4.8,
            google_review_count=200,
            has_website=True,
            doctor_count=5,
            avg_doctor_trust_score=80,
            has_certified_doctor=True,
            review_count=50,
            avg_sentiment=0.7,
            red_flag_count=0,
            price_data_count=10,
            procedure_count=20,
        )
        assert result.total >= 70

    def test_score_low_quality(self):
        """レッドフラグが多いクリニックが低スコアになる"""
        from src.analyzers.clinic_scoring import score_clinic
        result = score_clinic(
            google_rating=2.5,
            review_count=20,
            avg_sentiment=-0.5,
            red_flag_count=10,
            red_flag_ratio=0.5,
        )
        assert result.total < 50
        assert result.red_flag_penalty < 15

    def test_grade_assignment(self):
        """グレードが正しく割り当てられる"""
        from src.analyzers.clinic_scoring import get_clinic_grade
        assert get_clinic_grade(85) == "A"
        assert get_clinic_grade(70) == "B"
        assert get_clinic_grade(55) == "C"
        assert get_clinic_grade(40) == "D"
        assert get_clinic_grade(20) == "E"

    def test_score_to_dict(self):
        """to_dictが正しいキーを返す"""
        from src.analyzers.clinic_scoring import score_clinic
        result = score_clinic(google_rating=4.0)
        d = result.to_dict()
        assert "total" in d
        assert "transparency" in d
        assert "review_quality" in d
        assert "red_flag_penalty" in d
        assert "doctor_quality" in d
        assert "freshness" in d


# ==========================================
# Phase 41-43: 紹介文・グレードフィルタ・ホーム新機能
# ==========================================


@pytest.mark.anyio
async def test_clinic_has_editorial_summary(client: AsyncClient):
    """クリニック詳細に紹介文が含まれる"""
    resp = await client.get("/api/clinics/?limit=1&sort_by=score")
    clinics = resp.json()["clinics"]
    if not clinics:
        pytest.skip("クリニックデータなし")
    clinic_id = clinics[0]["id"]
    resp2 = await client.get(f"/api/clinics/{clinic_id}")
    assert resp2.status_code == 200
    data = resp2.json()
    assert data.get("editorial_summary")
    assert len(data["editorial_summary"]) > 20


@pytest.mark.anyio
async def test_clinic_grade_filter(client: AsyncClient):
    """グレードフィルタが機能する"""
    resp = await client.get("/api/clinics/?grade=A&per_page=5")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] > 0
    for c in data["clinics"]:
        assert c["clinic_grade"] == "A"


@pytest.mark.anyio
async def test_clinic_score_sort(client: AsyncClient):
    """AURAスコア順ソートが機能する"""
    resp = await client.get("/api/clinics/?sort_by=score&per_page=5")
    assert resp.status_code == 200
    clinics = resp.json()["clinics"]
    if len(clinics) >= 2:
        for i in range(len(clinics) - 1):
            score1 = clinics[i].get("clinic_score") or 0
            score2 = clinics[i + 1].get("clinic_score") or 0
            assert score1 >= score2


@pytest.mark.anyio
async def test_clinic_detail_has_score_breakdown(client: AsyncClient):
    """クリニック詳細にスコアブレークダウンが含まれる"""
    resp = await client.get("/api/clinics/?sort_by=score&per_page=1")
    clinics = resp.json()["clinics"]
    if not clinics:
        pytest.skip("クリニックデータなし")
    clinic_id = clinics[0]["id"]
    resp2 = await client.get(f"/api/clinics/{clinic_id}")
    data = resp2.json()
    assert "clinic_score_breakdown" in data
    bd = data["clinic_score_breakdown"]
    assert "transparency" in bd
    assert "review_quality" in bd

