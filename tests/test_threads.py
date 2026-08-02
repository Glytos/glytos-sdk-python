"""Threads, streaming, per-turn instructions and uploads.

Mirrors the node SDK's chat tests so the two surfaces cannot drift apart.
"""

import asyncio
import json

import httpx
import pytest

from glytos import AsyncGlytos, Glytos, GlytosError


def make_client(handler):  # type: ignore[no-untyped-def]
    return Glytos(
        api_key="gly_test", http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def make_async_client(handler):  # type: ignore[no-untyped-def]
    return AsyncGlytos(
        api_key="gly_test", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


def sse(*blocks) -> str:  # type: ignore[no-untyped-def]
    """An SSE body, framed exactly as the server writes it."""
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in blocks)


def test_thread_create_opens_a_session_and_carries_the_agent_id() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(
            200,
            json={
                "session_uuid": "ses_1",
                "status": "in_progress",
                "messages": [{"role": "assistant", "content": "Hi"}],
            },
        )

    thread = make_client(handler).threads.create(agent="wf_1", variables={"name": "Ada"})

    assert captured["request"].url.path.endswith("/workflows/wf_1/sessions")
    assert json.loads(captured["request"].content) == {"variables": {"name": "Ada"}}
    # The agent id rides on the thread so no later call has to repeat it.
    assert (thread.id, thread.agent, thread.status) == ("ses_1", "wf_1", "in_progress")
    assert len(thread.messages) == 1


def test_turn_sends_per_turn_instructions() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={"status": "in_progress", "messages": []})

    client = make_client(handler)
    thread = {"id": "ses_1", "agent": "wf_1"}
    client.threads.messages.create(thread, "hello", instructions="answer in French")

    assert captured["request"].url.path.endswith("/workflows/wf_1/sessions/ses_1/messages")
    assert json.loads(captured["request"].content) == {
        "content": "hello",
        "additional_instructions": "answer in French",
    }


def test_a_run_with_no_message_still_sends_empty_content() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={})

    make_client(handler).threads.runs.create(
        {"id": "ses_1", "agent": "wf_1"}, instructions="summarise so far"
    )
    assert json.loads(captured["request"].content) == {
        "content": "",
        "additional_instructions": "summarise so far",
    }


def test_messages_list_returns_the_transcript() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "session_uuid": "ses_1",
                "status": "completed",
                "transcript": [
                    {"role": "user", "content": "a"},
                    {"role": "assistant", "content": "b"},
                ],
            },
        )

    messages = make_client(handler).threads.messages.list({"id": "ses_1", "agent": "wf_1"})
    assert [m["role"] for m in messages] == ["user", "assistant"]


def test_a_thread_reference_missing_an_id_is_refused() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover - never called
        return httpx.Response(200, json={})

    with pytest.raises(ValueError, match="needs both"):
        make_client(handler).threads.messages.create({"agent": "wf_1"}, "hi")


def test_stream_yields_tokens_then_the_finished_run() -> None:
    body = sse(
        ("token", {"delta": "He"}),
        ("token", {"delta": "llo"}),
        ("done", {"session_uuid": "ses_1", "status": "completed", "messages": []}),
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    events = list(make_client(handler).threads.runs.stream({"id": "ses_1", "agent": "wf_1"}, "hi"))
    assert "".join(e.delta for e in events if e.type == "token") == "Hello"
    assert events[-1].type == "done"
    assert events[-1].run["status"] == "completed"


def test_stream_surfaces_an_error_event() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=sse(("error", {"message": "model refused"})),
            headers={"content-type": "text/event-stream"},
        )

    events = list(make_client(handler).chat.stream(token="t", content="hi"))
    assert [(e.type, e.message) for e in events] == [("error", "model refused")]


def test_stream_handles_a_missing_trailing_blank_line() -> None:
    # The last block has no trailing blank line; it must still be emitted.
    body = 'event: token\ndata: {"delta":"x"}\n\nevent: done\ndata: {"status":"completed"}'

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    events = list(make_client(handler).threads.runs.stream({"id": "s", "agent": "w"}))
    assert [e.type for e in events] == ["token", "done"]


def test_stream_raises_on_a_rejected_request() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            402, json={"error": {"code": "insufficient_credit", "message": "no credit"}}
        )

    with pytest.raises(GlytosError) as excinfo:
        list(make_client(handler).threads.runs.stream({"id": "s", "agent": "w"}))
    assert excinfo.value.status == 402
    assert excinfo.value.code == "insufficient_credit"


def test_folders_and_imports() -> None:
    seen: list[tuple[str, str, bytes]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.content))
        return httpx.Response(200, json={})

    client = make_client(handler)
    client.folders.create("Sales")
    client.folders.delete("fld_1")
    client.imports.assistant({"name": "Support"})

    assert seen[0][0] == "POST" and seen[0][1].endswith("/agent-folders")
    assert json.loads(seen[0][2]) == {"name": "Sales"}
    assert seen[1][0] == "DELETE" and seen[1][1].endswith("/agent-folders/fld_1")
    assert json.loads(seen[2][2]) == {"assistant": {"name": "Support"}}


def test_agent_export_and_folder_filing() -> None:
    seen: list[tuple[str, str, bytes]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.content))
        return httpx.Response(200, json={})

    client = make_client(handler)
    client.agents.export("wf_1")
    client.agents.move_to_folder("wf_1", "fld_1")
    client.agents.remove_from_folder("wf_1")

    assert seen[0][0] == "GET" and seen[0][1].endswith("/workflows/wf_1/export")
    assert seen[1][0] == "PATCH"
    assert json.loads(seen[1][2]) == {"folder_uuid": "fld_1"}
    # Sent as null is what unfiles an agent; not sent would leave it where it is.
    assert json.loads(seen[2][2]) == {"folder_uuid": None}


def test_uploads_are_multipart_not_json() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={"file_uuid": "f_1"})

    make_client(handler).chat.upload_file(
        token="tok", session_uuid="ses_1", file="hello", filename="notes.txt"
    )
    content_type = captured["request"].headers["content-type"]
    assert content_type.startswith("multipart/form-data")
    # The boundary has to come from httpx; setting it by hand yields an unparseable body.
    assert "boundary=" in content_type
    assert b"notes.txt" in captured["request"].content


def test_agents_is_the_same_object_as_workflows() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(200, json={})

    client = make_client(handler)
    assert client.agents is client.workflows


def test_async_thread_and_stream() -> None:
    body = sse(("token", {"delta": "hi"}), ("done", {"status": "completed"}))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/sessions"):
            return httpx.Response(200, json={"session_uuid": "ses_1", "status": "in_progress"})
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    async def run() -> None:
        client = make_async_client(handler)
        thread = await client.threads.create(agent="wf_1")
        assert (thread.id, thread.agent) == ("ses_1", "wf_1")
        events = [event async for event in client.threads.runs.stream(thread, "hi")]
        assert [e.type for e in events] == ["token", "done"]
        await client.aclose()

    asyncio.run(run())
