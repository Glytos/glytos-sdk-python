"""Campaigns and the do-not-call list, across the sync and async clients."""

import asyncio
import json
from datetime import datetime, timezone

import httpx

from glytos import AsyncGlytos, Glytos


def make_client(handler):  # type: ignore[no-untyped-def]
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return Glytos(api_key="gly_test", http_client=http)


def capturing(status=200, body=None):  # type: ignore[no-untyped-def]
    """A handler that records the request and answers with a fixed body."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(status, json=body if body is not None else {})

    return captured, handler


def test_contacts_are_sent_as_plain_numbers() -> None:
    # The API takes a list of strings. Sending objects is rejected with a 422,
    # so the shape of this field is worth a test of its own.
    captured, handler = capturing(201, {"uuid": "camp_1"})
    client = make_client(handler)

    client.campaigns.create(
        name="Q3",
        workflow_uuid="wf_1",
        from_number="+15551230000",
        contacts=["+15551230001", "0532 123 45 67"],
    )

    body = json.loads(captured["request"].content)
    assert body["contacts"] == ["+15551230001", "0532 123 45 67"]


def test_create_omits_everything_the_caller_left_alone() -> None:
    captured, handler = capturing(201, {"uuid": "camp_1"})
    client = make_client(handler)

    client.campaigns.create(name="Q3", workflow_uuid="wf_1", from_number="+15551230000")

    body = json.loads(captured["request"].content)
    assert body == {"name": "Q3", "workflow_uuid": "wf_1", "from_number": "+15551230000"}


def test_create_carries_the_schedule_and_the_calling_window() -> None:
    captured, handler = capturing(201, {"uuid": "camp_1"})
    client = make_client(handler)

    client.campaigns.create(
        name="Q3",
        workflow_uuid="wf_1",
        from_number="+15551230000",
        contacts_csv="phone,name\n+15551230001,Ada\n",
        scheduled_at=datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc),
        call_window_start="09:00",
        call_window_end="20:00",
        timezone="Europe/Istanbul",
        suppression_policy="ignore",
        override_caller_requests=True,
    )

    body = json.loads(captured["request"].content)
    # A datetime is serialized for the caller: passing one and getting a 422 back
    # is a poor trade for the one line it saves.
    assert body["scheduled_at"] == "2026-03-01T09:00:00+00:00"
    assert body["call_window_start"] == "09:00"
    assert body["timezone"] == "Europe/Istanbul"
    assert body["suppression_policy"] == "ignore"
    assert body["override_caller_requests"] is True


def test_scheduled_at_accepts_a_string_unchanged() -> None:
    captured, handler = capturing(201, {"uuid": "camp_1"})
    client = make_client(handler)

    client.campaigns.create(
        name="Q3",
        workflow_uuid="wf_1",
        from_number="+15551230000",
        scheduled_at="2026-03-01T09:00:00Z",
    )

    assert json.loads(captured["request"].content)["scheduled_at"] == "2026-03-01T09:00:00Z"


def test_stop_and_delete_address_the_campaign() -> None:
    captured, handler = capturing(200, {"uuid": "camp_1", "status": "stopped"})
    client = make_client(handler)

    client.campaigns.stop("camp_1")
    assert captured["request"].method == "POST"
    assert captured["request"].url.path.endswith("/telephony/campaigns/camp_1/stop")

    client.campaigns.delete("camp_1")
    assert captured["request"].method == "DELETE"
    assert captured["request"].url.path.endswith("/telephony/campaigns/camp_1")


def test_add_contacts_posts_csv_text_and_no_source_url() -> None:
    captured, handler = capturing(200, {"added": 2, "skipped": 1, "phone_column": "telefon"})
    client = make_client(handler)

    result = client.campaigns.add_contacts("camp_1", "telefon;isim\n+905321234567;Ada\n")

    body = json.loads(captured["request"].content)
    assert captured["request"].url.path.endswith("/telephony/campaigns/camp_1/contacts/sync")
    assert "source_url" not in body
    assert body["contacts_csv"].startswith("telefon;isim")
    # The column actually read is what separates a file parsed from the wrong
    # column from one that could not be parsed at all.
    assert result["phone_column"] == "telefon"


def test_preview_suppression_reports_caller_requests() -> None:
    captured, handler = capturing(
        200,
        {
            "contacts": 100,
            "suppressed_total": 12,
            "caller_requested": 4,
            "reached_if_strict": 88,
            "reached_if_transactional": 92,
            "reached_if_ignore": 96,
            "reached_if_override": 100,
        },
    )
    client = make_client(handler)

    preview = client.campaigns.preview_suppression(contacts=["+15551230001"])

    assert captured["request"].url.path.endswith("/telephony/campaigns/suppression-preview")
    assert preview["caller_requested"] == 4
    assert preview["reached_if_strict"] == 88


def test_dnc_list_passes_search_and_paging() -> None:
    captured, handler = capturing(200, {"items": [], "total": 0})
    client = make_client(handler)

    client.dnc.list(search="0555", limit=50, offset=100)

    params = captured["request"].url.params
    assert captured["request"].url.path.endswith("/dnc")
    assert params.get("search") == "0555"
    assert params.get("limit") == "50"
    assert params.get("offset") == "100"


def test_dnc_list_omits_unset_filters() -> None:
    captured, handler = capturing(200, {"items": [], "total": 0})
    client = make_client(handler)

    client.dnc.list()

    assert str(captured["request"].url.params) == ""


def test_dnc_scope_and_removal_carry_the_phone_number() -> None:
    captured, handler = capturing(200, {"uuid": "d1", "scope": "marketing"})
    client = make_client(handler)

    client.dnc.set_scope("+15551230001", "marketing")
    assert captured["request"].method == "PATCH"
    # A phone number is a path parameter, so "+" is escaped rather than read as
    # a space by anything in the way.
    assert captured["request"].url.raw_path.endswith(b"/dnc/%2B15551230001")
    assert json.loads(captured["request"].content) == {"scope": "marketing"}

    client.dnc.remove("+15551230001")
    assert captured["request"].method == "DELETE"
    assert captured["request"].url.raw_path.endswith(b"/dnc/%2B15551230001")


def test_dnc_omits_an_unstated_reason_rather_than_sending_null() -> None:
    # The reason is a plain string server-side, not a nullable one, so a null
    # is a 422 rather than "no reason given".
    captured, handler = capturing(201, {"uuid": "d1"})
    client = make_client(handler)

    client.dnc.add("+15551230001")
    assert json.loads(captured["request"].content) == {"phone": "+15551230001"}

    client.dnc.import_(["+15551230001"])
    assert json.loads(captured["request"].content) == {"phones": ["+15551230001"]}


def test_dnc_import_reports_what_it_did() -> None:
    captured, handler = capturing(200, {"added": 8, "duplicates": 1, "rejected": 2})
    client = make_client(handler)

    result = client.dnc.import_(["+15551230001", "not a number"], reason="CRM export")

    assert captured["request"].url.path.endswith("/dnc/import")
    assert json.loads(captured["request"].content)["reason"] == "CRM export"
    assert result["added"] == 8


def test_async_campaign_and_dnc_reach_the_same_endpoints() -> None:
    # The async client duplicates the sync resource classes, so the two can drift
    # apart silently. This is the check that they have not.
    captured, handler = capturing(200, {"uuid": "camp_1"})

    async def run() -> None:
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        async with AsyncGlytos(api_key="gly_async", http_client=http) as client:
            await client.campaigns.create(
                name="Q3",
                workflow_uuid="wf_1",
                from_number="+15551230000",
                contacts=["+15551230001"],
                suppression_policy="transactional",
            )
            body = json.loads(captured["request"].content)
            assert body["contacts"] == ["+15551230001"]
            assert body["suppression_policy"] == "transactional"

            await client.campaigns.stop("camp_1")
            assert captured["request"].url.path.endswith("/telephony/campaigns/camp_1/stop")

            await client.campaigns.add_contacts("camp_1", "phone\n+15551230002\n")
            assert "contacts_csv" in json.loads(captured["request"].content)

            await client.campaigns.preview_suppression(contacts=["+15551230001"])
            assert captured["request"].url.path.endswith("/telephony/campaigns/suppression-preview")

            await client.dnc.add("+15551230001", reason="asked on a call")
            assert captured["request"].url.path.endswith("/dnc")
            assert json.loads(captured["request"].content)["phone"] == "+15551230001"

            await client.dnc.set_scope("+15551230001", "marketing")
            assert captured["request"].url.raw_path.endswith(b"/dnc/%2B15551230001")

            await client.dnc.remove("+15551230001")
            assert captured["request"].method == "DELETE"

    asyncio.run(run())


def test_update_sends_only_what_it_was_given() -> None:
    captured, handler = capturing()
    make_client(handler).campaigns.update("camp-1", name="Renamed")

    request = captured["request"]
    assert request.method == "PATCH"
    assert request.url.path.endswith("/telephony/campaigns/camp-1")
    assert json.loads(request.content) == {"name": "Renamed"}


def test_unschedule_sends_the_null_that_absence_cannot_express() -> None:
    # `update` drops anything left unset, so clearing a schedule needs its own
    # method: omitting the field and setting it to nothing are different
    # instructions and only one of them survives a dict comprehension.
    captured, handler = capturing()
    make_client(handler).campaigns.unschedule("camp-1")

    assert json.loads(captured["request"].content) == {"scheduled_at": None}


def test_duplicate_posts_to_the_campaign_it_copies() -> None:
    captured, handler = capturing()
    make_client(handler).campaigns.duplicate("camp-1", "Second run")

    request = captured["request"]
    assert request.method == "POST"
    assert request.url.path.endswith("/telephony/campaigns/camp-1/duplicate")
    assert json.loads(request.content) == {"name": "Second run"}


def test_export_returns_csv_text_rather_than_failing_to_parse_it() -> None:
    csv = "phone,outcome,dialed_at,error,session_uuid\n+905551112233,answered,,,run-1\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=csv)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    assert Glytos(api_key="gly_test", http_client=http).campaigns.export("camp-1") == csv


def test_the_async_client_carries_the_same_campaign_methods() -> None:
    # The two clients are kept at deliberate parity, and a method added to one
    # and not the other is the failure mode this file exists to catch.
    captured, handler = capturing()
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AsyncGlytos(api_key="gly_test", http_client=http)

    asyncio.run(client.campaigns.update("camp-1", name="Renamed"))
    assert json.loads(captured["request"].content) == {"name": "Renamed"}

    asyncio.run(client.campaigns.unschedule("camp-1"))
    assert json.loads(captured["request"].content) == {"scheduled_at": None}

    asyncio.run(client.campaigns.duplicate("camp-1"))
    assert captured["request"].url.path.endswith("/telephony/campaigns/camp-1/duplicate")

    asyncio.run(client.campaigns.export("camp-1"))
    assert captured["request"].url.path.endswith("/telephony/campaigns/camp-1/export")
