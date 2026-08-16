"""The resources added after the first release, across the sync and async clients.

Same MockTransport pattern as test_outbound.py: record the outgoing request and
assert the method, path and body, so a wrong path or a renamed field is caught
without a live API.
"""

import asyncio
import json

import httpx

from glytos import AsyncGlytos, Glytos


def make_client(handler):  # type: ignore[no-untyped-def]
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return Glytos(api_key="gly_test", http_client=http)


def make_async_client(handler):  # type: ignore[no-untyped-def]
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return AsyncGlytos(api_key="gly_test", http_client=http)


def capturing(status=200, body=None):  # type: ignore[no-untyped-def]
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(status, json=body if body is not None else {})

    return captured, handler


def body_of(captured):  # type: ignore[no-untyped-def]
    return json.loads(captured["request"].content)


def test_sip_trunk_create_posts_the_login() -> None:
    captured, handler = capturing(201, {"uuid": "trunk_1"})
    client = make_client(handler)

    client.sip_trunks.create(username="line-1", password="secret", preset="netgsm")

    request = captured["request"]
    assert request.method == "POST"
    assert request.url.path.endswith("/telephony/sip-trunks")
    assert body_of(captured) == {
        "username": "line-1",
        "password": "secret",
        "preset": "netgsm",
    }


def test_sip_trunk_test_reports_reachable_separately_from_ok() -> None:
    # A carrier that refused the credentials is a different problem from one that
    # never answered, and only the first is worth changing the password over.
    captured, handler = capturing(200, {"ok": False, "detail": "no reply", "reachable": False})
    client = make_client(handler)

    result = client.sip_trunks.test("trunk_1")

    assert captured["request"].url.path.endswith("/telephony/sip-trunks/trunk_1/test")
    assert result["reachable"] is False


def test_import_number_can_name_a_sip_trunk() -> None:
    captured, handler = capturing(201, {"uuid": "num_1"})
    client = make_client(handler)

    client.phone_numbers.import_number(e164="+905321234567", sip_trunk_uuid="trunk_1")

    assert body_of(captured) == {"e164": "+905321234567", "sip_trunk_uuid": "trunk_1"}


def test_connection_create_posts_the_credential_payload() -> None:
    captured, handler = capturing(201, {"uuid": "conn_1"})
    client = make_client(handler)

    client.integrations.connections.create(
        integration_key="slack",
        name="Sales channel",
        data={"webhook_url": "https://hooks.example.com/x"},
    )

    assert captured["request"].url.path.endswith("/integrations/connections")
    assert body_of(captured) == {
        "integration_key": "slack",
        "name": "Sales channel",
        "data": {"webhook_url": "https://hooks.example.com/x"},
    }


def test_connection_run_addresses_the_connection_not_the_integration() -> None:
    captured, handler = capturing(200, {"result": {}})
    client = make_client(handler)

    client.integrations.connections.run(
        "conn_1", action="post_message", params={"text": "A lead came in"}
    )

    assert captured["request"].url.path.endswith("/integrations/connections/conn_1/run")
    assert body_of(captured) == {"action": "post_message", "params": {"text": "A lead came in"}}


def test_automation_create_carries_the_trigger_and_template() -> None:
    captured, handler = capturing(201, {"uuid": "auto_1"})
    client = make_client(handler)

    client.automations.create(
        name="Tell sales",
        trigger_event="session.completed",
        connection_uuid="conn_1",
        action="post_message",
        payload_template={"text": "Call from {{from_number}}"},
    )

    sent = body_of(captured)
    assert sent["trigger_event"] == "session.completed"
    assert sent["payload_template"] == {"text": "Call from {{from_number}}"}
    # Conditions were not given, so they are absent rather than an empty object.
    assert "conditions" not in sent


def test_automation_test_sends_an_empty_payload_by_default() -> None:
    captured, handler = capturing(200, {"params": {}, "result": {}})
    client = make_client(handler)

    client.automations.test("auto_1")

    assert captured["request"].url.path.endswith("/automations/auto_1/test")
    assert body_of(captured) == {"payload": {}}


def test_test_suite_run_posts_to_the_suite() -> None:
    captured, handler = capturing(
        200,
        {"suite_uuid": "s1", "passed": False, "total": 3, "passed_count": 2, "results": []},
    )
    client = make_client(handler)

    result = client.test_suites.run("s1")

    assert captured["request"].method == "POST"
    assert captured["request"].url.path.endswith("/test-suites/s1/run")
    assert result["passed_count"] == 2


def test_billing_reads_the_balance_and_filters_the_ledger() -> None:
    captured, handler = capturing(200, {"balance": 12.5, "currency": "USD"})
    client = make_client(handler)

    balance = client.billing.credits()
    assert captured["request"].url.path.endswith("/billing/credits")
    assert balance["balance"] == 12.5

    captured, handler = capturing(200, [])
    client = make_client(handler)
    client.billing.transactions(kind="debit", limit=10)
    assert captured["request"].url.params["kind"] == "debit"
    assert captured["request"].url.params["limit"] == "10"


def test_api_key_create_omits_unstated_limits() -> None:
    # Omitting both is exactly the behaviour keys have always had, so an SDK that
    # sent nulls would change what an unchanged caller gets.
    captured, handler = capturing(201, {"id": 1, "key": "gly_x"})
    client = make_client(handler)

    client.api_keys.create(name="CI")
    assert body_of(captured) == {"name": "CI"}

    captured, handler = capturing(201, {"id": 2, "key": "gly_y"})
    client = make_client(handler)
    client.api_keys.create(name="CI", expires_in_days=90, scopes=["workflow:read"])
    assert body_of(captured) == {
        "name": "CI",
        "expires_in_days": 90,
        "scopes": ["workflow:read"],
    }


def test_discover_mcp_returns_the_tool_list_not_the_envelope() -> None:
    captured, handler = capturing(200, {"tools": [{"name": "search"}, {"name": "fetch"}]})
    client = make_client(handler)

    tools = client.tools.discover_mcp(server_url="https://mcp.example.com")

    assert captured["request"].url.path.endswith("/tools/mcp/discover")
    assert [tool["name"] for tool in tools] == ["search", "fetch"]


def test_knowledge_base_documents_can_be_read_and_deleted() -> None:
    captured, handler = capturing(200, {"id": 7, "name": "Refunds"})
    client = make_client(handler)

    client.knowledge_base.retrieve_document(7)
    assert captured["request"].method == "GET"
    assert captured["request"].url.path.endswith("/knowledge-base/documents/7")

    captured, handler = capturing(204)
    client = make_client(handler)
    client.knowledge_base.delete_document(7)
    assert captured["request"].method == "DELETE"


def test_imports_connect_and_pull_carry_the_other_platform_key() -> None:
    captured, handler = capturing(200, {"agents": []})
    client = make_client(handler)

    client.imports.connect("vapi", api_key="vapi_key")
    assert captured["request"].url.path.endswith("/imports/vapi/connect")
    assert body_of(captured) == {"api_key": "vapi_key"}

    captured, handler = capturing(200, {"imports": []})
    client = make_client(handler)
    client.imports.pull("vapi", api_key="vapi_key", agent_ids=["a1"])
    assert captured["request"].url.path.endswith("/imports/vapi/pull")
    assert body_of(captured) == {"api_key": "vapi_key", "agent_ids": ["a1"]}


def test_async_client_exposes_the_same_new_resources() -> None:
    # The two clients are twins; a resource added to one and forgotten on the
    # other is the failure mode this guards.
    captured, handler = capturing(200, {"balance": 1.0, "currency": "USD"})
    client = make_async_client(handler)

    async def run() -> None:
        await client.billing.credits()
        await client.sip_trunks.list()
        await client.test_suites.list()
        await client.integrations.connections.list()
        await client.automations.list()
        await client.environments.list()
        await client.providers.list()
        await client.api_keys.list()
        await client.organizations.regions()
        await client.aclose()

    asyncio.run(run())
    assert captured["request"].url.path.endswith("/regions")
