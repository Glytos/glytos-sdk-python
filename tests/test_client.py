import httpx
import pytest

from glytos import Glytos, GlytosError


def make_client(handler, environment=None):  # type: ignore[no-untyped-def]
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return Glytos(api_key="gly_test", environment=environment, http_client=http)


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
