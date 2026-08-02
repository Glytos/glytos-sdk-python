import asyncio
import json
import pathlib

import httpx
import pytest
import tomllib

from glytos import AsyncGlytos, Glytos, GlytosError


def make_client(handler, environment=None):  # type: ignore[no-untyped-def]
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return Glytos(api_key="gly_test", environment=environment, http_client=http)


def test_version_matches_the_manifest() -> None:
    # The release bump edits only pyproject.toml, so a hardcoded __version__ would
    # ship the previous release's number forever. It did once.
    import glytos

    root = pathlib.Path(__file__).resolve().parent.parent / "pyproject.toml"
    declared = tomllib.loads(root.read_text(encoding="utf-8"))["project"]["version"]
    assert glytos.__version__ == declared


def test_requires_an_api_key() -> None:
    with pytest.raises(ValueError):
        Glytos(api_key="")


def test_successful_request_decodes_json_and_sends_auth_headers() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=[{"uuid": "wf_1"}], headers={"x-request-id": "req_1"})

    client = make_client(handler, environment="prod")
    agents = client.workflows.list()

    assert agents == [{"uuid": "wf_1"}]
    request = captured["request"]
    assert request.headers["X-API-Key"] == "gly_test"
    assert request.headers["X-Environment-Id"] == "prod"
    assert request.method == "GET"
    assert str(request.url).endswith("/workflows")


def test_drops_null_query_parameters() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=[])

    client = make_client(handler)
    client.calls.list(status="completed", agent=None)

    assert captured["request"].url.query.decode() == "status=completed"


def test_path_parameters_are_percent_encoded() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={})

    client = make_client(handler)
    client.workflows.retrieve("../secret?x=1#y")

    url = captured["request"].url
    # The slash, query and fragment characters are encoded on the wire, so the request
    # can neither traverse to another path nor inject query/fragment components.
    assert url.raw_path == b"/api/v1/workflows/..%2Fsecret%3Fx%3D1%23y"
    assert url.query == b""
    assert url.fragment == ""


def test_error_response_raises_glytos_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"error": {"code": "not_found", "message": "Nope"}},
            headers={"x-request-id": "req_2"},
        )

    client = make_client(handler)
    with pytest.raises(GlytosError) as exc_info:
        client.workflows.retrieve("missing")

    error = exc_info.value
    assert error.status == 404
    assert error.code == "not_found"
    assert error.message == "Nope"
    assert error.request_id == "req_2"


def test_promote_sends_target_environment_id() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler)
    client.workflows.promote("wf_1", "env_prod")

    request = captured["request"]
    assert request.method == "POST"
    assert str(request.url).endswith("/workflows/wf_1/promote")
    assert json.loads(request.content) == {"target_environment_id": "env_prod"}


def test_update_config_uses_put_with_config_body() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={})

    client = make_client(handler)
    client.workflows.update_config("wf_1", {"end_call_message": "Goodbye"})

    request = captured["request"]
    assert request.method == "PUT"
    assert str(request.url).endswith("/workflows/wf_1/config")
    assert json.loads(request.content) == {"config": {"end_call_message": "Goodbye"}}


def test_instant_sends_query_params_not_body() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={})

    client = make_client(handler)
    client.phone_numbers.instant(country="US")

    request = captured["request"]
    assert request.method == "POST"
    assert request.url.path.endswith("/telephony/numbers/instant")
    assert request.url.params.get("country") == "US"
    # No JSON body: the arguments travel as the query string only.
    assert request.content == b""


def test_campaigns_create_posts_body() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(201, json={"uuid": "camp_1"})

    client = make_client(handler)
    client.campaigns.create(name="Q3", workflow_uuid="wf_1", from_number="+15551230000")

    request = captured["request"]
    assert request.method == "POST"
    assert str(request.url).endswith("/telephony/campaigns")
    assert json.loads(request.content) == {
        "name": "Q3",
        "workflow_uuid": "wf_1",
        "from_number": "+15551230000",
    }


def test_tools_update_patch_omits_null_fields() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={})

    client = make_client(handler)
    client.tools.update("tool_1", name="Renamed")

    request = captured["request"]
    assert request.method == "PATCH"
    assert str(request.url).endswith("/tools/tool_1")
    # Only the provided field is sent; kind/description/config/parameters are omitted.
    assert json.loads(request.content) == {"name": "Renamed"}


def test_knowledge_base_search_posts_query() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=[])

    client = make_client(handler)
    client.knowledge_base.search(query="refund policy", top_k=3)

    request = captured["request"]
    assert request.method == "POST"
    assert str(request.url).endswith("/knowledge-base/search")
    assert json.loads(request.content) == {"query": "refund policy", "top_k": 3}


def test_analytics_overview_sends_days_query() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={})

    client = make_client(handler)
    client.analytics.overview(days=30)

    request = captured["request"]
    assert request.method == "GET"
    assert request.url.path.endswith("/analytics/overview")
    assert request.url.params.get("days") == "30"


def test_async_client_sends_api_key_and_decodes_json() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=[{"uuid": "wf_async"}])

    async def run() -> object:
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        async with AsyncGlytos(api_key="gly_async", http_client=http) as client:
            return await client.workflows.list()

    agents = asyncio.run(run())

    assert agents == [{"uuid": "wf_async"}]
    request = captured["request"]
    assert request.headers["X-API-Key"] == "gly_async"
    assert request.method == "GET"
    assert str(request.url).endswith("/workflows")


def test_async_promote_sends_body() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={"ok": True})

    async def run() -> None:
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        async with AsyncGlytos(api_key="gly_async", http_client=http) as client:
            await client.workflows.promote("wf_1", "env_prod")

    asyncio.run(run())

    request = captured["request"]
    assert request.method == "POST"
    assert str(request.url).endswith("/workflows/wf_1/promote")
    assert json.loads(request.content) == {"target_environment_id": "env_prod"}
