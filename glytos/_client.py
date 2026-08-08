"""Glytos API client and resource namespaces."""

from __future__ import annotations

import json as _json
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Union
from urllib.parse import quote

import httpx

from ._webhooks import verify_webhook

DEFAULT_BASE_URL = "https://api.glytos.com/api/v1"

JSON = Any


@dataclass
class Thread:
    """A conversation with an agent.

    Created against one agent and carrying its id, so no later call has to repeat
    it. Pass the object itself wherever a thread is expected.
    """

    id: str
    agent: str
    status: str = ""
    #: Anything the agent opened with; empty for a silent opening.
    messages: list[JSON] = field(default_factory=list)
    #: Everything else the API returned, untouched.
    extra: dict[str, Any] = field(default_factory=dict)


#: A thread, or the two ids spelled out as a mapping. Spelled with ``Union`` rather
#: than ``X | Y`` because this is a runtime expression and the package supports 3.9.
ThreadRef = Union[Thread, Mapping[str, str]]

#: Events in an SSE stream are separated by a blank line.
_SSE_SEP = "\n\n"


@dataclass
class StreamEvent:
    """One Server-Sent Event from a streamed turn.

    ``type`` is ``"token"`` (``delta`` carries the piece), ``"done"`` (``run`` carries
    the finished turn, the same payload the non-streamed call returns) or ``"error"``.
    """

    type: str
    delta: str = ""
    run: JSON = None
    message: str = ""


def _thread_ids(thread: ThreadRef) -> tuple[str, str]:
    """The agent and thread ids behind a reference, whichever form was passed."""
    if isinstance(thread, Thread):
        agent, thread_id = thread.agent, thread.id
    else:
        agent, thread_id = str(thread.get("agent", "")), str(thread.get("id", ""))
    if not agent or not thread_id:
        raise ValueError("Glytos: a thread reference needs both 'id' and 'agent'")
    return agent, thread_id


def _turn_body(
    content: str = "",
    images: Sequence[str] | None = None,
    instructions: str | None = None,
) -> dict[str, Any]:
    """The turn body shared by the plain and the streamed endpoint."""
    body: dict[str, Any] = {"content": content}
    if images is not None:
        body["images"] = list(images)
    if instructions is not None:
        body["additional_instructions"] = instructions
    return body


def _as_thread(agent: str, started: JSON) -> Thread:
    payload = dict(started or {})
    return Thread(
        id=str(payload.pop("session_uuid", "")),
        agent=agent,
        status=str(payload.pop("status", "")),
        messages=list(payload.pop("messages", []) or []),
        extra=payload,
    )


def _parse_sse(block: str) -> StreamEvent | None:
    """Turn one raw SSE block ("event: x\\ndata: {...}") into a typed event."""
    name = ""
    data_lines: list[str] = []
    for line in block.split("\n"):
        if line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())
    if not name or not data_lines:
        return None
    try:
        data = _json.loads("\n".join(data_lines))
    except ValueError:
        data = {}
    if name == "token":
        return StreamEvent("token", delta=str(data.get("delta", "")))
    if name == "error":
        return StreamEvent("error", message=str(data.get("message", "stream failed")))
    if name == "done":
        return StreamEvent("done", run=data)
    return None


def _sse_blocks(chunks: Iterator[str]) -> Iterator[StreamEvent]:
    """Split a byte/text stream into events, keeping any trailing partial buffered."""
    buffer = ""
    for chunk in chunks:
        buffer += chunk
        while "\n\n" in buffer:
            block, buffer = buffer.split("\n\n", 1)
            event = _parse_sse(block)
            if event is not None:
                yield event
    last = _parse_sse(buffer)
    if last is not None:
        yield last


class GlytosError(Exception):
    """Raised on any non-2xx API response. Carries the API error ``code``."""

    def __init__(self, status: int, code: str, message: str, request_id: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.request_id = request_id


def _prepare_params(params: dict[str, Any] | None) -> dict[str, Any] | None:
    """Drop ``None`` query parameters so callers can pass optionals freely."""
    clean = {k: v for k, v in (params or {}).items() if v is not None}
    return clean or None


def _handle_response(response: httpx.Response) -> JSON:
    """Decode a fully-read response, or raise :class:`GlytosError` on failure."""
    request_id = response.headers.get("x-request-id")
    if response.is_success:
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text
    code, message = "error", response.reason_phrase or "Request failed"
    try:
        error = response.json().get("error") or {}
        code = error.get("code", code)
        message = error.get("message", message)
    except ValueError:
        pass
    raise GlytosError(response.status_code, code, message, request_id)


class Glytos:
    """Glytos API client.

    ``api_key`` is your organization API key (starts with ``gly_``). Use it as a
    context manager, or call ``close()`` when done.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        environment: str | None = None,
        timeout: float = 30.0,
        http_client: httpx.Client | None = None,
    ):
        if not api_key:
            raise ValueError("Glytos: an api_key is required")
        self._base_url = base_url.rstrip("/")
        self._http = http_client or httpx.Client(timeout=timeout)
        self._headers = {"X-API-Key": api_key, "Accept": "application/json"}
        # The environment to act in: "dev"/"staging"/"prod" or an environment uuid.
        # Defaults to the organization's default environment (Development). Agents are
        # still created in Development regardless; this scopes reads and calls.
        if environment:
            self._headers["X-Environment-Id"] = environment

        self.workflows = Workflows(self)
        #: The same resource as :attr:`workflows`, under the word the product uses.
        self.agents = self.workflows
        self.threads = Threads(self)
        self.folders = Folders(self)
        self.imports = Imports(self)
        self.calls = Calls(self)
        self.phone_numbers = PhoneNumbers(self)
        self.sessions = Sessions(self)
        self.webhooks = Webhooks(self)
        self.campaigns = Campaigns(self)
        self.dnc = Dnc(self)
        self.chat = Chat(self)
        self.tools = Tools(self)
        self.knowledge_base = KnowledgeBase(self)
        self.vector_stores = VectorStores(self)
        self.analytics = Analytics(self)

    def request(
        self,
        method: str,
        path: str,
        *,
        json: JSON | None = None,
        params: dict[str, Any] | None = None,
    ) -> JSON:
        """Low-level request against any endpoint (path relative to the API base)."""
        response = self._http.request(
            method,
            self._base_url + path,
            headers=self._headers,
            json=json,
            params=_prepare_params(params),
        )
        return _handle_response(response)

    def request_form(
        self, method: str, path: str, *, data: dict[str, Any], files: dict[str, Any]
    ) -> JSON:
        """Upload a file. Separate from :meth:`request` because the body is multipart,
        so httpx has to set the Content-Type with its own boundary."""
        response = self._http.request(
            method, self._base_url + path, headers=self._headers, data=data, files=files
        )
        return _handle_response(response)

    def stream(self, method: str, path: str, *, json: JSON | None = None) -> Iterator[StreamEvent]:
        """Stream a Server-Sent Events endpoint, yielding one parsed event at a time.

        The reply arrives as it is written rather than after the last token, which
        is the whole difference on a long answer. The terminal ``done`` event carries
        the same payload the non-streamed call returns.
        """
        headers = {**self._headers, "Accept": "text/event-stream"}
        with self._http.stream(
            method, self._base_url + path, headers=headers, json=json
        ) as response:
            if not response.is_success:
                response.read()
                _handle_response(response)
            yield from _sse_blocks(response.iter_text())

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Glytos:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


class _Resource:
    def __init__(self, client: Glytos):
        self._client = client


class Workflows(_Resource):
    """Agents: prompt agents and visual workflows."""

    def list(self, *, archived: bool | None = None, environment: str | None = None) -> JSON:
        return self._client.request(
            "GET", "/workflows", params={"archived": archived, "environment": environment}
        )

    def retrieve(self, workflow_uuid: str) -> JSON:
        return self._client.request("GET", f"/workflows/{quote(workflow_uuid, safe='')}")

    def create(
        self, *, name: str, mode: str = "prompt", config: dict[str, Any] | None = None
    ) -> JSON:
        body: dict[str, Any] = {"name": name, "mode": mode}
        if config is not None:
            body["config"] = config
        return self._client.request("POST", "/workflows", json=body)

    def rename(self, workflow_uuid: str, name: str) -> JSON:
        return self._client.request(
            "PATCH", f"/workflows/{quote(workflow_uuid, safe='')}", json={"name": name}
        )

    def export(self, workflow_uuid: str) -> JSON:
        """Export an agent as portable, secret-free JSON.

        It imports back through ``imports.create("glytos", ...)``, on this account
        or another."""
        return self._client.request("GET", f"/workflows/{quote(workflow_uuid, safe='')}/export")

    def move_to_folder(self, workflow_uuid: str, folder_uuid: str) -> JSON:
        """File an agent into a folder. Both must be in the same environment."""
        return self._client.request(
            "PATCH",
            f"/workflows/{quote(workflow_uuid, safe='')}",
            json={"folder_uuid": folder_uuid},
        )

    def remove_from_folder(self, workflow_uuid: str) -> JSON:
        """Take an agent out of its folder, leaving it ungrouped."""
        # Sent as null is what unfiles it; not sent at all would leave it where it is.
        return self._client.request(
            "PATCH", f"/workflows/{quote(workflow_uuid, safe='')}", json={"folder_uuid": None}
        )

    def duplicate(self, workflow_uuid: str) -> JSON:
        return self._client.request("POST", f"/workflows/{quote(workflow_uuid, safe='')}/duplicate")

    def archive(self, workflow_uuid: str) -> JSON:
        return self._client.request("POST", f"/workflows/{quote(workflow_uuid, safe='')}/archive")

    def unarchive(self, workflow_uuid: str) -> JSON:
        return self._client.request("POST", f"/workflows/{quote(workflow_uuid, safe='')}/unarchive")

    def promote(self, workflow_uuid: str, target_environment_id: str) -> JSON:
        return self._client.request(
            "POST",
            f"/workflows/{quote(workflow_uuid, safe='')}/promote",
            json={"target_environment_id": target_environment_id},
        )

    def versions(self, workflow_uuid: str) -> JSON:
        return self._client.request("GET", f"/workflows/{quote(workflow_uuid, safe='')}/versions")

    def update_definition(self, workflow_uuid: str, graph: dict[str, Any]) -> JSON:
        return self._client.request(
            "PUT", f"/workflows/{quote(workflow_uuid, safe='')}/definition", json={"graph": graph}
        )

    def update_config(self, workflow_uuid: str, config: dict[str, Any]) -> JSON:
        return self._client.request(
            "PUT", f"/workflows/{quote(workflow_uuid, safe='')}/config", json={"config": config}
        )

    def publish(self, workflow_uuid: str) -> JSON:
        return self._client.request("POST", f"/workflows/{quote(workflow_uuid, safe='')}/publish")

    def delete(self, workflow_uuid: str) -> JSON:
        return self._client.request("DELETE", f"/workflows/{quote(workflow_uuid, safe='')}")

    def templates(self) -> JSON:
        return self._client.request("GET", "/workflows/templates")

    def start_session(
        self,
        workflow_uuid: str,
        *,
        variables: dict[str, Any] | None = None,
        version: int | str | None = None,
    ) -> JSON:
        body: dict[str, Any] = {}
        if variables is not None:
            body["variables"] = variables
        if version is not None:
            body["version"] = version
        return self._client.request(
            "POST", f"/workflows/{quote(workflow_uuid, safe='')}/sessions", json=body
        )

    def send_message(
        self,
        workflow_uuid: str,
        session_uuid: str,
        content: str = "",
        *,
        images: Sequence[str] | None = None,
        instructions: str | None = None,
    ) -> JSON:
        """One turn. ``instructions`` is extra context for THIS turn only, applied
        below the agent's own and never saved to it."""
        return self._client.request(
            "POST",
            f"/workflows/{quote(workflow_uuid, safe='')}"
            f"/sessions/{quote(session_uuid, safe='')}/messages",
            json=_turn_body(content, images, instructions),
        )

    def stream_message(
        self,
        workflow_uuid: str,
        session_uuid: str,
        content: str = "",
        *,
        images: Sequence[str] | None = None,
        instructions: str | None = None,
    ) -> Iterator[StreamEvent]:
        """The same turn, delivered as it is written."""
        return self._client.stream(
            "POST",
            f"/workflows/{quote(workflow_uuid, safe='')}"
            f"/sessions/{quote(session_uuid, safe='')}/messages/stream",
            json=_turn_body(content, images, instructions),
        )

    def run_text(self, workflow_uuid: str, messages: Sequence[dict[str, Any]]) -> JSON:
        return self._client.request(
            "POST",
            f"/workflows/{quote(workflow_uuid, safe='')}/runs/text",
            json={"messages": messages},
        )

    def session(self, workflow_uuid: str, session_uuid: str) -> JSON:
        return self._client.request(
            "GET",
            f"/workflows/{quote(workflow_uuid, safe='')}/sessions/{quote(session_uuid, safe='')}",
        )

    def session_events(self, workflow_uuid: str, session_uuid: str) -> JSON:
        return self._client.request(
            "GET",
            f"/workflows/{quote(workflow_uuid, safe='')}"
            f"/sessions/{quote(session_uuid, safe='')}/events",
        )


class Threads(_Resource):
    """Conversations with a text agent, in the vocabulary the rest of the industry
    uses: a thread holds the conversation, a run is one turn on it.

    The same session API :attr:`Glytos.agents` exposes, shaped so code written
    against a thread/run model reads the same here.
    """

    def __init__(self, client: Glytos):
        super().__init__(client)
        self.messages = ThreadMessages(client)
        self.runs = ThreadRuns(client)

    def create(
        self,
        *,
        agent: str,
        variables: dict[str, Any] | None = None,
        version: int | str | None = None,
    ) -> Thread:
        """Open a conversation with an agent."""
        body: dict[str, Any] = {}
        if variables is not None:
            body["variables"] = variables
        if version is not None:
            body["version"] = version
        started = self._client.request(
            "POST", f"/workflows/{quote(agent, safe='')}/sessions", json=body
        )
        return _as_thread(agent, started)

    def retrieve(self, thread: ThreadRef) -> JSON:
        """The conversation so far, with its variables and cost."""
        agent, thread_id = _thread_ids(thread)
        return self._client.request(
            "GET",
            f"/workflows/{quote(agent, safe='')}/sessions/{quote(thread_id, safe='')}",
        )


class ThreadMessages(_Resource):
    def create(
        self,
        thread: ThreadRef,
        content: str = "",
        *,
        images: Sequence[str] | None = None,
        instructions: str | None = None,
    ) -> JSON:
        """Add a user message and run the agent on it. Returns that turn's reply."""
        agent, thread_id = _thread_ids(thread)
        return self._client.request(
            "POST",
            f"/workflows/{quote(agent, safe='')}/sessions/{quote(thread_id, safe='')}/messages",
            json=_turn_body(content, images, instructions),
        )

    def list(self, thread: ThreadRef) -> JSON:
        """Every message in the conversation, oldest first."""
        agent, thread_id = _thread_ids(thread)
        detail = self._client.request(
            "GET",
            f"/workflows/{quote(agent, safe='')}/sessions/{quote(thread_id, safe='')}",
        )
        return (detail or {}).get("transcript", [])


class ThreadRuns(_Resource):
    def create(
        self,
        thread: ThreadRef,
        content: str = "",
        *,
        images: Sequence[str] | None = None,
        instructions: str | None = None,
    ) -> JSON:
        """Run one turn and wait for it. A turn completes before it returns, so there
        is no run to poll: the reply is already in the result."""
        agent, thread_id = _thread_ids(thread)
        return self._client.request(
            "POST",
            f"/workflows/{quote(agent, safe='')}/sessions/{quote(thread_id, safe='')}/messages",
            json=_turn_body(content, images, instructions),
        )

    def stream(
        self,
        thread: ThreadRef,
        content: str = "",
        *,
        images: Sequence[str] | None = None,
        instructions: str | None = None,
    ) -> Iterator[StreamEvent]:
        """The same turn, delivered as it is written."""
        agent, thread_id = _thread_ids(thread)
        return self._client.stream(
            "POST",
            f"/workflows/{quote(agent, safe='')}"
            f"/sessions/{quote(thread_id, safe='')}/messages/stream",
            json=_turn_body(content, images, instructions),
        )


class Folders(_Resource):
    """Folders that group agents inside an environment."""

    def list(self) -> JSON:
        return self._client.request("GET", "/agent-folders")

    def create(self, name: str) -> JSON:
        return self._client.request("POST", "/agent-folders", json={"name": name})

    def rename(self, folder_uuid: str, name: str) -> JSON:
        return self._client.request(
            "PATCH", f"/agent-folders/{quote(folder_uuid, safe='')}", json={"name": name}
        )

    def delete(self, folder_uuid: str) -> JSON:
        """Delete a folder. The agents filed in it are deleted with it."""
        return self._client.request("DELETE", f"/agent-folders/{quote(folder_uuid, safe='')}")


class Imports(_Resource):
    """Bring an agent over from another platform."""

    def sources(self) -> JSON:
        return self._client.request("GET", "/imports/sources")

    def create(self, source: str, payload: dict[str, Any]) -> JSON:
        return self._client.request(
            "POST", f"/imports/{quote(source, safe='')}", json={"payload": payload}
        )

    def assistant(self, assistant: dict[str, Any]) -> JSON:
        """Bring over an assistant definition, tools and all."""
        return self._client.request(
            "POST", "/imports/openai-assistant", json={"assistant": assistant}
        )


def _items(resp: JSON) -> JSON:
    """Return the items of a paginated ``{items, ...}`` list envelope.

    Most list endpoints return a bare array; the paginated ones wrap results in
    an ``{items, total, limit, offset}`` object. This unwraps the latter so every
    list method yields a plain list.
    """
    if isinstance(resp, dict) and "items" in resp:
        return resp["items"]
    return resp


class Calls(_Resource):
    def create(self, **body: Any) -> JSON:
        return self._client.request("POST", "/calls", json=body)

    def list(self, **params: Any) -> JSON:
        return _items(self._client.request("GET", "/calls", params=params))

    def retrieve(self, call_uuid: str) -> JSON:
        return self._client.request("GET", f"/calls/{quote(call_uuid, safe='')}")

    def web_token(
        self, *, workflow_uuid: str | None = None, agent: dict[str, Any] | None = None
    ) -> JSON:
        """Mint a short-lived, workflow-scoped token for an in-browser web call."""
        body: dict[str, Any] = {}
        if workflow_uuid is not None:
            body["workflow_uuid"] = workflow_uuid
        if agent is not None:
            body["agent"] = agent
        return self._client.request("POST", "/calls/web-token", json=body)

    def control(self, call_uuid: str, **body: Any) -> JSON:
        return self._client.request(
            "POST", f"/calls/{quote(call_uuid, safe='')}/control", json=body
        )


class PhoneNumbers(_Resource):
    def search(self, **params: Any) -> JSON:
        return self._client.request("GET", "/telephony/numbers/search", params=params)

    def list(self) -> JSON:
        return self._client.request("GET", "/telephony/numbers")

    def providers(self) -> JSON:
        return self._client.request("GET", "/telephony/providers")

    def provision(self, *, e164: str, **body: Any) -> JSON:
        return self._client.request("POST", "/telephony/numbers", json={"e164": e164, **body})

    def import_number(
        self,
        *,
        e164: str,
        provider: str | None = None,
        provider_sid: str | None = None,
        credentials: dict[str, Any] | None = None,
        workflow_uuid: str | None = None,
    ) -> JSON:
        body: dict[str, Any] = {"e164": e164}
        if provider is not None:
            body["provider"] = provider
        if provider_sid is not None:
            body["provider_sid"] = provider_sid
        if credentials is not None:
            body["credentials"] = credentials
        if workflow_uuid is not None:
            body["workflow_uuid"] = workflow_uuid
        return self._client.request("POST", "/telephony/numbers/import", json=body)

    def instant(self, *, country: str | None = None, provider: str | None = None) -> JSON:
        return self._client.request(
            "POST",
            "/telephony/numbers/instant",
            params={"country": country, "provider": provider},
        )

    def assign(self, number_uuid: str, **body: Any) -> JSON:
        return self._client.request(
            "POST", f"/telephony/numbers/{quote(number_uuid, safe='')}/assign", json=body
        )

    def release(self, number_uuid: str) -> JSON:
        return self._client.request("DELETE", f"/telephony/numbers/{quote(number_uuid, safe='')}")


def _campaign_body(
    name: str,
    workflow_uuid: str,
    from_number: str,
    contacts: Sequence[str] | None,
    contacts_csv: str | None,
    scheduled_at: str | datetime | None,
    call_window_start: str | None,
    call_window_end: str | None,
    timezone: str | None,
    suppression_policy: str | None,
    override_caller_requests: bool | None,
) -> dict[str, Any]:
    """Build a campaign payload, omitting everything the caller left alone."""
    body: dict[str, Any] = {
        "name": name,
        "workflow_uuid": workflow_uuid,
        "from_number": from_number,
    }
    if contacts is not None:
        body["contacts"] = list(contacts)
    if contacts_csv is not None:
        body["contacts_csv"] = contacts_csv
    if scheduled_at is not None:
        body["scheduled_at"] = (
            scheduled_at.isoformat() if isinstance(scheduled_at, datetime) else scheduled_at
        )
    if call_window_start is not None:
        body["call_window_start"] = call_window_start
    if call_window_end is not None:
        body["call_window_end"] = call_window_end
    if timezone is not None:
        body["timezone"] = timezone
    if suppression_policy is not None:
        body["suppression_policy"] = suppression_policy
    if override_caller_requests is not None:
        body["override_caller_requests"] = override_caller_requests
    return body


class Campaigns(_Resource):
    """Outbound calling campaigns over a phone number."""

    def list(self) -> JSON:
        return self._client.request("GET", "/telephony/campaigns")

    def create(
        self,
        *,
        name: str,
        workflow_uuid: str,
        from_number: str,
        contacts: Sequence[str] | None = None,
        contacts_csv: str | None = None,
        scheduled_at: str | datetime | None = None,
        call_window_start: str | None = None,
        call_window_end: str | None = None,
        timezone: str | None = None,
        suppression_policy: str | None = None,
        override_caller_requests: bool | None = None,
    ) -> JSON:
        """Create an outbound calling campaign.

        ``from_number`` must be a number your organization has connected, or the
        campaign is refused. ``contacts`` takes numbers in any spelling; they are
        converted to international form and deduplicated. ``contacts_csv`` takes
        the contents of a CSV file instead, and every column beside the phone
        number travels with that contact's call as a variable, so ``{{name}}`` in
        the agent's prompt means the person being called.

        Left unscheduled, a campaign is a draft until :meth:`start`. Set
        ``call_window_start`` and ``call_window_end`` together to bound dialing
        to a range of hours, read in ``timezone`` (an IANA name).
        """
        body = _campaign_body(
            name,
            workflow_uuid,
            from_number,
            contacts,
            contacts_csv,
            scheduled_at,
            call_window_start,
            call_window_end,
            timezone,
            suppression_policy,
            override_caller_requests,
        )
        return self._client.request("POST", "/telephony/campaigns", json=body)

    def retrieve(self, campaign_uuid: str) -> JSON:
        """A campaign with its contacts and their outcomes."""
        return self._client.request("GET", f"/telephony/campaigns/{quote(campaign_uuid, safe='')}")

    def start(self, campaign_uuid: str) -> JSON:
        """Begin dialing, from the contacts that have not been called yet."""
        return self._client.request(
            "POST", f"/telephony/campaigns/{quote(campaign_uuid, safe='')}/start"
        )

    def stop(self, campaign_uuid: str) -> JSON:
        """End dialing at the next contact.

        Calls already handed to the carrier run to their end; undialed contacts
        stay ready, so :meth:`start` resumes.
        """
        return self._client.request(
            "POST", f"/telephony/campaigns/{quote(campaign_uuid, safe='')}/stop"
        )

    def delete(self, campaign_uuid: str) -> JSON:
        """Remove a campaign and its contact list, stopping it first if running."""
        return self._client.request(
            "DELETE", f"/telephony/campaigns/{quote(campaign_uuid, safe='')}"
        )

    def add_contacts(self, campaign_uuid: str, contacts_csv: str) -> JSON:
        """Append contacts from the contents of a CSV file."""
        return self._client.request(
            "POST",
            f"/telephony/campaigns/{quote(campaign_uuid, safe='')}/contacts/sync",
            json={"contacts_csv": contacts_csv},
        )

    def sync_contacts(self, campaign_uuid: str, source_url: str) -> JSON:
        """Append contacts from a CSV your own system serves over HTTP."""
        return self._client.request(
            "POST",
            f"/telephony/campaigns/{quote(campaign_uuid, safe='')}/contacts/sync",
            json={"source_url": source_url},
        )

    def preview_suppression(
        self,
        *,
        contacts: Sequence[str] | None = None,
        contacts_csv: str | None = None,
    ) -> JSON:
        """How many of a contact list each suppression policy would reach.

        Includes how many of those people asked, on a call, not to be contacted
        again. Measure before choosing anything other than the default.
        """
        body: dict[str, Any] = {}
        if contacts is not None:
            body["contacts"] = list(contacts)
        if contacts_csv is not None:
            body["contacts_csv"] = contacts_csv
        return self._client.request("POST", "/telephony/campaigns/suppression-preview", json=body)


class Dnc(_Resource):
    """The numbers your organization must not call.

    Every outbound call is checked against this list, whether it comes from a
    campaign or from :meth:`Calls.create`. Agents add to it themselves when a
    caller asks not to be contacted again.
    """

    def list(
        self,
        *,
        search: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> JSON:
        """Suppressed numbers, newest first.

        ``search`` is normalized before matching, so a number typed the way it
        appears on a contact list finds the entry stored in international form.
        """
        params: dict[str, Any] = {}
        if search is not None:
            params["search"] = search
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        return self._client.request("GET", "/dnc", params=params)

    def add(self, phone: str, *, reason: str | None = None) -> JSON:
        """Suppress a number.

        Any spelling is accepted and stored in international form. Adding one
        already on the list returns the existing entry rather than failing.
        """
        return self._client.request("POST", "/dnc", json={"phone": phone, "reason": reason})

    def import_(self, phones: Sequence[str], *, reason: str | None = None) -> JSON:
        """Suppress many numbers at once, e.g. a list exported from your CRM."""
        return self._client.request(
            "POST", "/dnc/import", json={"phones": list(phones), "reason": reason}
        )

    def set_scope(self, phone: str, scope: str) -> JSON:
        """Change how far a suppression reaches.

        ``all`` covers every call; ``marketing`` still allows a transactional
        call about the person's own order.
        """
        return self._client.request("PATCH", f"/dnc/{quote(phone, safe='')}", json={"scope": scope})

    def remove(self, phone: str) -> JSON:
        """Take a number off the list, so it can be called again."""
        return self._client.request("DELETE", f"/dnc/{quote(phone, safe='')}")


class Sessions(_Resource):
    def list(self, **params: Any) -> JSON:
        return self._client.request("GET", "/sessions", params=params)


class Webhooks(_Resource):
    def list(self) -> JSON:
        return self._client.request("GET", "/webhooks/endpoints")

    def create(self, *, url: str, events: Sequence[str], **body: Any) -> JSON:
        return self._client.request(
            "POST", "/webhooks/endpoints", json={"url": url, "events": events, **body}
        )

    def update(
        self,
        endpoint_id: int | str,
        *,
        url: str | None = None,
        events: Sequence[str] | None = None,
        is_active: bool | None = None,
        timeout_seconds: int | None = None,
        headers: dict[str, str] | None = None,
        auth_header: str | None = None,
    ) -> JSON:
        body: dict[str, Any] = {}
        if url is not None:
            body["url"] = url
        if events is not None:
            body["events"] = events
        if is_active is not None:
            body["is_active"] = is_active
        if timeout_seconds is not None:
            body["timeout_seconds"] = timeout_seconds
        if headers is not None:
            body["headers"] = headers
        if auth_header is not None:
            body["auth_header"] = auth_header
        return self._client.request(
            "PATCH", f"/webhooks/endpoints/{quote(str(endpoint_id), safe='')}", json=body
        )

    def delete(self, endpoint_id: int | str) -> JSON:
        return self._client.request(
            "DELETE", f"/webhooks/endpoints/{quote(str(endpoint_id), safe='')}"
        )

    def events(self) -> JSON:
        return self._client.request("GET", "/webhooks/events")

    def deliveries(
        self,
        *,
        event_type: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> JSON:
        return _items(
            self._client.request(
                "GET",
                "/webhooks/deliveries",
                params={
                    "event_type": event_type,
                    "status": status,
                    "limit": limit,
                    "offset": offset,
                },
            )
        )

    def redeliver(self, delivery_id: int | str) -> JSON:
        return self._client.request(
            "POST", f"/webhooks/deliveries/{quote(str(delivery_id), safe='')}/redeliver"
        )

    @staticmethod
    def verify(
        payload: str | bytes,
        signature_header: str,
        secret: str,
        tolerance_seconds: int = 300,
    ) -> bool:
        """Verify a webhook delivery signature (see :func:`glytos.verify_webhook`)."""
        return verify_webhook(payload, signature_header, secret, tolerance_seconds)


class Chat(_Resource):
    """Embeddable text chat: mint a widget token, then exchange messages with it."""

    def token(self, workflow_uuid: str) -> JSON:
        return self._client.request("POST", "/chat/token", json={"workflow_uuid": workflow_uuid})

    def messages(
        self,
        *,
        token: str,
        content: str,
        session_uuid: str | None = None,
        images: Sequence[str] | None = None,
    ) -> JSON:
        """Send a chat turn. Authed by the body ``token`` from :meth:`token`."""
        body: dict[str, Any] = {"token": token, "content": content}
        if session_uuid is not None:
            body["session_uuid"] = session_uuid
        if images is not None:
            body["images"] = images
        return self._client.request("POST", "/chat/messages", json=body)

    def stream(
        self,
        *,
        token: str,
        content: str,
        session_uuid: str | None = None,
        images: Sequence[str] | None = None,
    ) -> Iterator[StreamEvent]:
        """The same turn, delivered as it is written."""
        body: dict[str, Any] = {"token": token, "content": content}
        if session_uuid is not None:
            body["session_uuid"] = session_uuid
        if images is not None:
            body["images"] = images
        return self._client.stream("POST", "/chat/stream", json=body)

    def upload_file(
        self,
        *,
        token: str,
        session_uuid: str,
        file: bytes | str,
        filename: str = "file",
    ) -> JSON:
        """Attach a file to one conversation. Its text is put in front of the agent
        for that conversation only - it does not join the knowledge base."""
        payload = file.encode() if isinstance(file, str) else file
        return self._client.request_form(
            "POST",
            "/chat/files",
            data={"token": token, "session_uuid": session_uuid},
            files={"file": (filename, payload)},
        )


class Tools(_Resource):
    """Reusable tools an agent can call (``kind`` = http / static / mcp)."""

    def list(self) -> JSON:
        return self._client.request("GET", "/tools")

    def create(
        self,
        *,
        name: str,
        kind: str,
        description: str | None = None,
        config: dict[str, Any] | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> JSON:
        body: dict[str, Any] = {"name": name, "kind": kind}
        if description is not None:
            body["description"] = description
        if config is not None:
            body["config"] = config
        if parameters is not None:
            body["parameters"] = parameters
        return self._client.request("POST", "/tools", json=body)

    def update(
        self,
        tool_uuid: str,
        *,
        name: str | None = None,
        description: str | None = None,
        kind: str | None = None,
        config: dict[str, Any] | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> JSON:
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        if kind is not None:
            body["kind"] = kind
        if config is not None:
            body["config"] = config
        if parameters is not None:
            body["parameters"] = parameters
        return self._client.request("PATCH", f"/tools/{quote(tool_uuid, safe='')}", json=body)

    def delete(self, tool_uuid: str) -> JSON:
        return self._client.request("DELETE", f"/tools/{quote(tool_uuid, safe='')}")


class KnowledgeBase(_Resource):
    """Knowledge-base documents and hybrid retrieval search."""

    def list_documents(self) -> JSON:
        return self._client.request("GET", "/knowledge-base/documents")

    def create_document(
        self,
        *,
        name: str,
        content: str,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ) -> JSON:
        body: dict[str, Any] = {"name": name, "content": content}
        if chunk_size is not None:
            body["chunk_size"] = chunk_size
        if chunk_overlap is not None:
            body["chunk_overlap"] = chunk_overlap
        return self._client.request("POST", "/knowledge-base/documents", json=body)

    def upload_document(self, file: bytes | str, filename: str = "document") -> JSON:
        """Upload a document file (txt, md, pdf) instead of pasting its text."""
        payload = file.encode() if isinstance(file, str) else file
        return self._client.request_form(
            "POST", "/knowledge-base/documents/upload", data={}, files={"file": (filename, payload)}
        )

    def search(
        self,
        *,
        query: str,
        top_k: int | None = None,
        document_ids: Sequence[int] | None = None,
        min_score: float | None = None,
    ) -> JSON:
        body: dict[str, Any] = {"query": query}
        if top_k is not None:
            body["top_k"] = top_k
        if document_ids is not None:
            body["document_ids"] = document_ids
        if min_score is not None:
            body["min_score"] = min_score
        return self._client.request("POST", "/knowledge-base/search", json=body)


class VectorStores(_Resource):
    """Vector stores over knowledge-base documents."""

    def list(self) -> JSON:
        return self._client.request("GET", "/vector-stores")

    def create(self, *, name: str) -> JSON:
        return self._client.request("POST", "/vector-stores", json={"name": name})

    def retrieve(self, vector_store_uuid: str) -> JSON:
        return self._client.request("GET", f"/vector-stores/{quote(vector_store_uuid, safe='')}")

    def delete(self, vector_store_uuid: str) -> JSON:
        return self._client.request("DELETE", f"/vector-stores/{quote(vector_store_uuid, safe='')}")

    def upload_document(
        self, vector_store_uuid: str, file: bytes | str, filename: str = "document"
    ) -> JSON:
        """Add a document file to a vector store, so an agent can search it."""
        payload = file.encode() if isinstance(file, str) else file
        return self._client.request_form(
            "POST",
            f"/vector-stores/{quote(vector_store_uuid, safe='')}/documents/upload",
            data={},
            files={"file": (filename, payload)},
        )


class Analytics(_Resource):
    """Usage and activity analytics."""

    def overview(self, *, days: int | None = None) -> JSON:
        return self._client.request("GET", "/analytics/overview", params={"days": days})


class AsyncGlytos:
    """Asynchronous Glytos API client (the async twin of :class:`Glytos`).

    ``api_key`` is your organization API key (starts with ``gly_``). Use it as an
    async context manager, or call ``aclose()`` when done.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        environment: str | None = None,
        timeout: float = 30.0,
        http_client: httpx.AsyncClient | None = None,
    ):
        if not api_key:
            raise ValueError("Glytos: an api_key is required")
        self._base_url = base_url.rstrip("/")
        self._http = http_client or httpx.AsyncClient(timeout=timeout)
        self._headers = {"X-API-Key": api_key, "Accept": "application/json"}
        if environment:
            self._headers["X-Environment-Id"] = environment

        self.workflows = AsyncWorkflows(self)
        #: The same resource as :attr:`workflows`, under the word the product uses.
        self.agents = self.workflows
        self.threads = AsyncThreads(self)
        self.folders = AsyncFolders(self)
        self.imports = AsyncImports(self)
        self.calls = AsyncCalls(self)
        self.phone_numbers = AsyncPhoneNumbers(self)
        self.sessions = AsyncSessions(self)
        self.webhooks = AsyncWebhooks(self)
        self.campaigns = AsyncCampaigns(self)
        self.dnc = AsyncDnc(self)
        self.chat = AsyncChat(self)
        self.tools = AsyncTools(self)
        self.knowledge_base = AsyncKnowledgeBase(self)
        self.vector_stores = AsyncVectorStores(self)
        self.analytics = AsyncAnalytics(self)

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: JSON | None = None,
        params: dict[str, Any] | None = None,
    ) -> JSON:
        """Low-level request against any endpoint (path relative to the API base)."""
        response = await self._http.request(
            method,
            self._base_url + path,
            headers=self._headers,
            json=json,
            params=_prepare_params(params),
        )
        return _handle_response(response)

    async def request_form(
        self, method: str, path: str, *, data: dict[str, Any], files: dict[str, Any]
    ) -> JSON:
        """Upload a file. Separate from :meth:`request` because the body is multipart,
        so httpx has to set the Content-Type with its own boundary."""
        response = await self._http.request(
            method, self._base_url + path, headers=self._headers, data=data, files=files
        )
        return _handle_response(response)

    async def stream(
        self, method: str, path: str, *, json: JSON | None = None
    ) -> AsyncIterator[StreamEvent]:
        """Stream a Server-Sent Events endpoint, yielding one parsed event at a time.

        The terminal ``done`` event carries the same payload the non-streamed call
        returns, so a caller can render the deltas and still end up with the
        authoritative result.
        """
        headers = {**self._headers, "Accept": "text/event-stream"}
        async with self._http.stream(
            method, self._base_url + path, headers=headers, json=json
        ) as response:
            if not response.is_success:
                await response.aread()
                _handle_response(response)
            buffer = ""
            async for chunk in response.aiter_text():
                buffer += chunk
                while _SSE_SEP in buffer:
                    block, buffer = buffer.split(_SSE_SEP, 1)
                    event = _parse_sse(block)
                    if event is not None:
                        yield event
            last = _parse_sse(buffer)
            if last is not None:
                yield last

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> AsyncGlytos:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()


class _AsyncResource:
    def __init__(self, client: AsyncGlytos):
        self._client = client


class AsyncWorkflows(_AsyncResource):
    """Agents: prompt agents and visual workflows."""

    async def list(self, *, archived: bool | None = None, environment: str | None = None) -> JSON:
        return await self._client.request(
            "GET", "/workflows", params={"archived": archived, "environment": environment}
        )

    async def retrieve(self, workflow_uuid: str) -> JSON:
        return await self._client.request("GET", f"/workflows/{quote(workflow_uuid, safe='')}")

    async def create(
        self, *, name: str, mode: str = "prompt", config: dict[str, Any] | None = None
    ) -> JSON:
        body: dict[str, Any] = {"name": name, "mode": mode}
        if config is not None:
            body["config"] = config
        return await self._client.request("POST", "/workflows", json=body)

    async def rename(self, workflow_uuid: str, name: str) -> JSON:
        return await self._client.request(
            "PATCH", f"/workflows/{quote(workflow_uuid, safe='')}", json={"name": name}
        )

    async def export(self, workflow_uuid: str) -> JSON:
        """Export an agent as portable, secret-free JSON.

        It imports back through ``imports.create("glytos", ...)``, on this account
        or another."""
        return await self._client.request(
            "GET", f"/workflows/{quote(workflow_uuid, safe='')}/export"
        )

    async def move_to_folder(self, workflow_uuid: str, folder_uuid: str) -> JSON:
        """File an agent into a folder. Both must be in the same environment."""
        return await self._client.request(
            "PATCH",
            f"/workflows/{quote(workflow_uuid, safe='')}",
            json={"folder_uuid": folder_uuid},
        )

    async def remove_from_folder(self, workflow_uuid: str) -> JSON:
        """Take an agent out of its folder, leaving it ungrouped."""
        # Sent as null is what unfiles it; not sent at all would leave it where it is.
        return await self._client.request(
            "PATCH", f"/workflows/{quote(workflow_uuid, safe='')}", json={"folder_uuid": None}
        )

    async def duplicate(self, workflow_uuid: str) -> JSON:
        return await self._client.request(
            "POST", f"/workflows/{quote(workflow_uuid, safe='')}/duplicate"
        )

    async def archive(self, workflow_uuid: str) -> JSON:
        return await self._client.request(
            "POST", f"/workflows/{quote(workflow_uuid, safe='')}/archive"
        )

    async def unarchive(self, workflow_uuid: str) -> JSON:
        return await self._client.request(
            "POST", f"/workflows/{quote(workflow_uuid, safe='')}/unarchive"
        )

    async def promote(self, workflow_uuid: str, target_environment_id: str) -> JSON:
        return await self._client.request(
            "POST",
            f"/workflows/{quote(workflow_uuid, safe='')}/promote",
            json={"target_environment_id": target_environment_id},
        )

    async def versions(self, workflow_uuid: str) -> JSON:
        return await self._client.request(
            "GET", f"/workflows/{quote(workflow_uuid, safe='')}/versions"
        )

    async def update_definition(self, workflow_uuid: str, graph: dict[str, Any]) -> JSON:
        return await self._client.request(
            "PUT", f"/workflows/{quote(workflow_uuid, safe='')}/definition", json={"graph": graph}
        )

    async def update_config(self, workflow_uuid: str, config: dict[str, Any]) -> JSON:
        return await self._client.request(
            "PUT", f"/workflows/{quote(workflow_uuid, safe='')}/config", json={"config": config}
        )

    async def publish(self, workflow_uuid: str) -> JSON:
        return await self._client.request(
            "POST", f"/workflows/{quote(workflow_uuid, safe='')}/publish"
        )

    async def delete(self, workflow_uuid: str) -> JSON:
        return await self._client.request("DELETE", f"/workflows/{quote(workflow_uuid, safe='')}")

    async def templates(self) -> JSON:
        return await self._client.request("GET", "/workflows/templates")

    async def start_session(
        self,
        workflow_uuid: str,
        *,
        variables: dict[str, Any] | None = None,
        version: int | str | None = None,
    ) -> JSON:
        body: dict[str, Any] = {}
        if variables is not None:
            body["variables"] = variables
        if version is not None:
            body["version"] = version
        return await self._client.request(
            "POST", f"/workflows/{quote(workflow_uuid, safe='')}/sessions", json=body
        )

    async def send_message(
        self,
        workflow_uuid: str,
        session_uuid: str,
        content: str = "",
        *,
        images: Sequence[str] | None = None,
        instructions: str | None = None,
    ) -> JSON:
        """One turn. ``instructions`` is extra context for THIS turn only, applied
        below the agent own instructions and never saved to it."""
        return await self._client.request(
            "POST",
            f"/workflows/{quote(workflow_uuid, safe='')}"
            f"/sessions/{quote(session_uuid, safe='')}/messages",
            json=_turn_body(content, images, instructions),
        )

    def stream_message(
        self,
        workflow_uuid: str,
        session_uuid: str,
        content: str = "",
        *,
        images: Sequence[str] | None = None,
        instructions: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """The same turn, delivered as it is written."""
        return self._client.stream(
            "POST",
            f"/workflows/{quote(workflow_uuid, safe='')}"
            f"/sessions/{quote(session_uuid, safe='')}/messages/stream",
            json=_turn_body(content, images, instructions),
        )

    async def run_text(self, workflow_uuid: str, messages: Sequence[dict[str, Any]]) -> JSON:
        return await self._client.request(
            "POST",
            f"/workflows/{quote(workflow_uuid, safe='')}/runs/text",
            json={"messages": messages},
        )

    async def session(self, workflow_uuid: str, session_uuid: str) -> JSON:
        return await self._client.request(
            "GET",
            f"/workflows/{quote(workflow_uuid, safe='')}/sessions/{quote(session_uuid, safe='')}",
        )

    async def session_events(self, workflow_uuid: str, session_uuid: str) -> JSON:
        return await self._client.request(
            "GET",
            f"/workflows/{quote(workflow_uuid, safe='')}"
            f"/sessions/{quote(session_uuid, safe='')}/events",
        )


class AsyncCalls(_AsyncResource):
    async def create(self, **body: Any) -> JSON:
        return await self._client.request("POST", "/calls", json=body)

    async def list(self, **params: Any) -> JSON:
        return _items(await self._client.request("GET", "/calls", params=params))

    async def retrieve(self, call_uuid: str) -> JSON:
        return await self._client.request("GET", f"/calls/{quote(call_uuid, safe='')}")

    async def web_token(
        self, *, workflow_uuid: str | None = None, agent: dict[str, Any] | None = None
    ) -> JSON:
        """Mint a short-lived, workflow-scoped token for an in-browser web call."""
        body: dict[str, Any] = {}
        if workflow_uuid is not None:
            body["workflow_uuid"] = workflow_uuid
        if agent is not None:
            body["agent"] = agent
        return await self._client.request("POST", "/calls/web-token", json=body)

    async def control(self, call_uuid: str, **body: Any) -> JSON:
        return await self._client.request(
            "POST", f"/calls/{quote(call_uuid, safe='')}/control", json=body
        )


class AsyncPhoneNumbers(_AsyncResource):
    async def search(self, **params: Any) -> JSON:
        return await self._client.request("GET", "/telephony/numbers/search", params=params)

    async def list(self) -> JSON:
        return await self._client.request("GET", "/telephony/numbers")

    async def providers(self) -> JSON:
        return await self._client.request("GET", "/telephony/providers")

    async def provision(self, *, e164: str, **body: Any) -> JSON:
        return await self._client.request("POST", "/telephony/numbers", json={"e164": e164, **body})

    async def import_number(
        self,
        *,
        e164: str,
        provider: str | None = None,
        provider_sid: str | None = None,
        credentials: dict[str, Any] | None = None,
        workflow_uuid: str | None = None,
    ) -> JSON:
        body: dict[str, Any] = {"e164": e164}
        if provider is not None:
            body["provider"] = provider
        if provider_sid is not None:
            body["provider_sid"] = provider_sid
        if credentials is not None:
            body["credentials"] = credentials
        if workflow_uuid is not None:
            body["workflow_uuid"] = workflow_uuid
        return await self._client.request("POST", "/telephony/numbers/import", json=body)

    async def instant(self, *, country: str | None = None, provider: str | None = None) -> JSON:
        return await self._client.request(
            "POST",
            "/telephony/numbers/instant",
            params={"country": country, "provider": provider},
        )

    async def assign(self, number_uuid: str, **body: Any) -> JSON:
        return await self._client.request(
            "POST", f"/telephony/numbers/{quote(number_uuid, safe='')}/assign", json=body
        )

    async def release(self, number_uuid: str) -> JSON:
        return await self._client.request(
            "DELETE", f"/telephony/numbers/{quote(number_uuid, safe='')}"
        )


class AsyncCampaigns(_AsyncResource):
    """Outbound calling campaigns over a phone number."""

    async def list(self) -> JSON:
        return await self._client.request("GET", "/telephony/campaigns")

    async def create(
        self,
        *,
        name: str,
        workflow_uuid: str,
        from_number: str,
        contacts: Sequence[str] | None = None,
        contacts_csv: str | None = None,
        scheduled_at: str | datetime | None = None,
        call_window_start: str | None = None,
        call_window_end: str | None = None,
        timezone: str | None = None,
        suppression_policy: str | None = None,
        override_caller_requests: bool | None = None,
    ) -> JSON:
        """Create an outbound calling campaign.

        ``from_number`` must be a number your organization has connected, or the
        campaign is refused. ``contacts`` takes numbers in any spelling; they are
        converted to international form and deduplicated. ``contacts_csv`` takes
        the contents of a CSV file instead, and every column beside the phone
        number travels with that contact's call as a variable, so ``{{name}}`` in
        the agent's prompt means the person being called.

        Left unscheduled, a campaign is a draft until :meth:`start`. Set
        ``call_window_start`` and ``call_window_end`` together to bound dialing
        to a range of hours, read in ``timezone`` (an IANA name).
        """
        body = _campaign_body(
            name,
            workflow_uuid,
            from_number,
            contacts,
            contacts_csv,
            scheduled_at,
            call_window_start,
            call_window_end,
            timezone,
            suppression_policy,
            override_caller_requests,
        )
        return await self._client.request("POST", "/telephony/campaigns", json=body)

    async def retrieve(self, campaign_uuid: str) -> JSON:
        """A campaign with its contacts and their outcomes."""
        return await self._client.request(
            "GET", f"/telephony/campaigns/{quote(campaign_uuid, safe='')}"
        )

    async def start(self, campaign_uuid: str) -> JSON:
        """Begin dialing, from the contacts that have not been called yet."""
        return await self._client.request(
            "POST", f"/telephony/campaigns/{quote(campaign_uuid, safe='')}/start"
        )

    async def stop(self, campaign_uuid: str) -> JSON:
        """End dialing at the next contact.

        Calls already handed to the carrier run to their end; undialed contacts
        stay ready, so :meth:`start` resumes.
        """
        return await self._client.request(
            "POST", f"/telephony/campaigns/{quote(campaign_uuid, safe='')}/stop"
        )

    async def delete(self, campaign_uuid: str) -> JSON:
        """Remove a campaign and its contact list, stopping it first if running."""
        return await self._client.request(
            "DELETE", f"/telephony/campaigns/{quote(campaign_uuid, safe='')}"
        )

    async def add_contacts(self, campaign_uuid: str, contacts_csv: str) -> JSON:
        """Append contacts from the contents of a CSV file."""
        return await self._client.request(
            "POST",
            f"/telephony/campaigns/{quote(campaign_uuid, safe='')}/contacts/sync",
            json={"contacts_csv": contacts_csv},
        )

    async def sync_contacts(self, campaign_uuid: str, source_url: str) -> JSON:
        """Append contacts from a CSV your own system serves over HTTP."""
        return await self._client.request(
            "POST",
            f"/telephony/campaigns/{quote(campaign_uuid, safe='')}/contacts/sync",
            json={"source_url": source_url},
        )

    async def preview_suppression(
        self,
        *,
        contacts: Sequence[str] | None = None,
        contacts_csv: str | None = None,
    ) -> JSON:
        """How many of a contact list each suppression policy would reach.

        Includes how many of those people asked, on a call, not to be contacted
        again. Measure before choosing anything other than the default.
        """
        body: dict[str, Any] = {}
        if contacts is not None:
            body["contacts"] = list(contacts)
        if contacts_csv is not None:
            body["contacts_csv"] = contacts_csv
        return await self._client.request(
            "POST", "/telephony/campaigns/suppression-preview", json=body
        )


class AsyncDnc(_AsyncResource):
    """The numbers your organization must not call.

    Every outbound call is checked against this list, whether it comes from a
    campaign or from :meth:`AsyncCalls.create`. Agents add to it themselves when
    a caller asks not to be contacted again.
    """

    async def list(
        self,
        *,
        search: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> JSON:
        """Suppressed numbers, newest first.

        ``search`` is normalized before matching, so a number typed the way it
        appears on a contact list finds the entry stored in international form.
        """
        params: dict[str, Any] = {}
        if search is not None:
            params["search"] = search
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        return await self._client.request("GET", "/dnc", params=params)

    async def add(self, phone: str, *, reason: str | None = None) -> JSON:
        """Suppress a number.

        Any spelling is accepted and stored in international form. Adding one
        already on the list returns the existing entry rather than failing.
        """
        return await self._client.request("POST", "/dnc", json={"phone": phone, "reason": reason})

    async def import_(self, phones: Sequence[str], *, reason: str | None = None) -> JSON:
        """Suppress many numbers at once, e.g. a list exported from your CRM."""
        return await self._client.request(
            "POST", "/dnc/import", json={"phones": list(phones), "reason": reason}
        )

    async def set_scope(self, phone: str, scope: str) -> JSON:
        """Change how far a suppression reaches.

        ``all`` covers every call; ``marketing`` still allows a transactional
        call about the person's own order.
        """
        return await self._client.request(
            "PATCH", f"/dnc/{quote(phone, safe='')}", json={"scope": scope}
        )

    async def remove(self, phone: str) -> JSON:
        """Take a number off the list, so it can be called again."""
        return await self._client.request("DELETE", f"/dnc/{quote(phone, safe='')}")


class AsyncSessions(_AsyncResource):
    async def list(self, **params: Any) -> JSON:
        return await self._client.request("GET", "/sessions", params=params)


class AsyncWebhooks(_AsyncResource):
    async def list(self) -> JSON:
        return await self._client.request("GET", "/webhooks/endpoints")

    async def create(self, *, url: str, events: Sequence[str], **body: Any) -> JSON:
        return await self._client.request(
            "POST", "/webhooks/endpoints", json={"url": url, "events": events, **body}
        )

    async def update(
        self,
        endpoint_id: int | str,
        *,
        url: str | None = None,
        events: Sequence[str] | None = None,
        is_active: bool | None = None,
        timeout_seconds: int | None = None,
        headers: dict[str, str] | None = None,
        auth_header: str | None = None,
    ) -> JSON:
        body: dict[str, Any] = {}
        if url is not None:
            body["url"] = url
        if events is not None:
            body["events"] = events
        if is_active is not None:
            body["is_active"] = is_active
        if timeout_seconds is not None:
            body["timeout_seconds"] = timeout_seconds
        if headers is not None:
            body["headers"] = headers
        if auth_header is not None:
            body["auth_header"] = auth_header
        return await self._client.request(
            "PATCH", f"/webhooks/endpoints/{quote(str(endpoint_id), safe='')}", json=body
        )

    async def delete(self, endpoint_id: int | str) -> JSON:
        return await self._client.request(
            "DELETE", f"/webhooks/endpoints/{quote(str(endpoint_id), safe='')}"
        )

    async def events(self) -> JSON:
        return await self._client.request("GET", "/webhooks/events")

    async def deliveries(
        self,
        *,
        event_type: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> JSON:
        return _items(
            await self._client.request(
                "GET",
                "/webhooks/deliveries",
                params={
                    "event_type": event_type,
                    "status": status,
                    "limit": limit,
                    "offset": offset,
                },
            )
        )

    async def redeliver(self, delivery_id: int | str) -> JSON:
        return await self._client.request(
            "POST", f"/webhooks/deliveries/{quote(str(delivery_id), safe='')}/redeliver"
        )

    @staticmethod
    def verify(
        payload: str | bytes,
        signature_header: str,
        secret: str,
        tolerance_seconds: int = 300,
    ) -> bool:
        """Verify a webhook delivery signature (see :func:`glytos.verify_webhook`)."""
        return verify_webhook(payload, signature_header, secret, tolerance_seconds)


class AsyncChat(_AsyncResource):
    """Embeddable text chat: mint a widget token, then exchange messages with it."""

    async def token(self, workflow_uuid: str) -> JSON:
        return await self._client.request(
            "POST", "/chat/token", json={"workflow_uuid": workflow_uuid}
        )

    async def messages(
        self,
        *,
        token: str,
        content: str,
        session_uuid: str | None = None,
        images: Sequence[str] | None = None,
    ) -> JSON:
        """Send a chat turn. Authed by the body ``token`` from :meth:`token`."""
        body: dict[str, Any] = {"token": token, "content": content}
        if session_uuid is not None:
            body["session_uuid"] = session_uuid
        if images is not None:
            body["images"] = images
        return await self._client.request("POST", "/chat/messages", json=body)

    def stream(
        self,
        *,
        token: str,
        content: str,
        session_uuid: str | None = None,
        images: Sequence[str] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """The same turn, delivered as it is written."""
        body: dict[str, Any] = {"token": token, "content": content}
        if session_uuid is not None:
            body["session_uuid"] = session_uuid
        if images is not None:
            body["images"] = images
        return self._client.stream("POST", "/chat/stream", json=body)

    async def upload_file(
        self,
        *,
        token: str,
        session_uuid: str,
        file: bytes | str,
        filename: str = "file",
    ) -> JSON:
        """Attach a file to one conversation. Its text is put in front of the agent
        for that conversation only - it does not join the knowledge base."""
        payload = file.encode() if isinstance(file, str) else file
        return await self._client.request_form(
            "POST",
            "/chat/files",
            data={"token": token, "session_uuid": session_uuid},
            files={"file": (filename, payload)},
        )


class AsyncThreads(_AsyncResource):
    """Conversations with a text agent, in the vocabulary the rest of the industry
    uses: a thread holds the conversation, a run is one turn on it."""

    def __init__(self, client: AsyncGlytos):
        super().__init__(client)
        self.messages = AsyncThreadMessages(client)
        self.runs = AsyncThreadRuns(client)

    async def create(
        self,
        *,
        agent: str,
        variables: dict[str, Any] | None = None,
        version: int | str | None = None,
    ) -> Thread:
        """Open a conversation with an agent."""
        body: dict[str, Any] = {}
        if variables is not None:
            body["variables"] = variables
        if version is not None:
            body["version"] = version
        started = await self._client.request(
            "POST", f"/workflows/{quote(agent, safe='')}/sessions", json=body
        )
        return _as_thread(agent, started)

    async def retrieve(self, thread: ThreadRef) -> JSON:
        """The conversation so far, with its variables and cost."""
        agent, thread_id = _thread_ids(thread)
        return await self._client.request(
            "GET",
            f"/workflows/{quote(agent, safe='')}/sessions/{quote(thread_id, safe='')}",
        )


class AsyncThreadMessages(_AsyncResource):
    async def create(
        self,
        thread: ThreadRef,
        content: str = "",
        *,
        images: Sequence[str] | None = None,
        instructions: str | None = None,
    ) -> JSON:
        """Add a user message and run the agent on it. Returns that turn reply."""
        agent, thread_id = _thread_ids(thread)
        return await self._client.request(
            "POST",
            f"/workflows/{quote(agent, safe='')}/sessions/{quote(thread_id, safe='')}/messages",
            json=_turn_body(content, images, instructions),
        )

    async def list(self, thread: ThreadRef) -> JSON:
        """Every message in the conversation, oldest first."""
        agent, thread_id = _thread_ids(thread)
        detail = await self._client.request(
            "GET",
            f"/workflows/{quote(agent, safe='')}/sessions/{quote(thread_id, safe='')}",
        )
        return (detail or {}).get("transcript", [])


class AsyncThreadRuns(_AsyncResource):
    async def create(
        self,
        thread: ThreadRef,
        content: str = "",
        *,
        images: Sequence[str] | None = None,
        instructions: str | None = None,
    ) -> JSON:
        """Run one turn and wait for it. A turn completes before it returns, so there
        is no run to poll: the reply is already in the result."""
        agent, thread_id = _thread_ids(thread)
        return await self._client.request(
            "POST",
            f"/workflows/{quote(agent, safe='')}/sessions/{quote(thread_id, safe='')}/messages",
            json=_turn_body(content, images, instructions),
        )

    def stream(
        self,
        thread: ThreadRef,
        content: str = "",
        *,
        images: Sequence[str] | None = None,
        instructions: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """The same turn, delivered as it is written."""
        agent, thread_id = _thread_ids(thread)
        return self._client.stream(
            "POST",
            f"/workflows/{quote(agent, safe='')}"
            f"/sessions/{quote(thread_id, safe='')}/messages/stream",
            json=_turn_body(content, images, instructions),
        )


class AsyncFolders(_AsyncResource):
    """Folders that group agents inside an environment."""

    async def list(self) -> JSON:
        return await self._client.request("GET", "/agent-folders")

    async def create(self, name: str) -> JSON:
        return await self._client.request("POST", "/agent-folders", json={"name": name})

    async def rename(self, folder_uuid: str, name: str) -> JSON:
        return await self._client.request(
            "PATCH", f"/agent-folders/{quote(folder_uuid, safe='')}", json={"name": name}
        )

    async def delete(self, folder_uuid: str) -> JSON:
        """Delete a folder. The agents filed in it are deleted with it."""
        return await self._client.request("DELETE", f"/agent-folders/{quote(folder_uuid, safe='')}")


class AsyncImports(_AsyncResource):
    """Bring an agent over from another platform."""

    async def sources(self) -> JSON:
        return await self._client.request("GET", "/imports/sources")

    async def create(self, source: str, payload: dict[str, Any]) -> JSON:
        return await self._client.request(
            "POST", f"/imports/{quote(source, safe='')}", json={"payload": payload}
        )

    async def assistant(self, assistant: dict[str, Any]) -> JSON:
        """Bring over an assistant definition, tools and all."""
        return await self._client.request(
            "POST", "/imports/openai-assistant", json={"assistant": assistant}
        )


class AsyncTools(_AsyncResource):
    """Reusable tools an agent can call (``kind`` = http / static / mcp)."""

    async def list(self) -> JSON:
        return await self._client.request("GET", "/tools")

    async def create(
        self,
        *,
        name: str,
        kind: str,
        description: str | None = None,
        config: dict[str, Any] | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> JSON:
        body: dict[str, Any] = {"name": name, "kind": kind}
        if description is not None:
            body["description"] = description
        if config is not None:
            body["config"] = config
        if parameters is not None:
            body["parameters"] = parameters
        return await self._client.request("POST", "/tools", json=body)

    async def update(
        self,
        tool_uuid: str,
        *,
        name: str | None = None,
        description: str | None = None,
        kind: str | None = None,
        config: dict[str, Any] | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> JSON:
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        if kind is not None:
            body["kind"] = kind
        if config is not None:
            body["config"] = config
        if parameters is not None:
            body["parameters"] = parameters
        return await self._client.request("PATCH", f"/tools/{quote(tool_uuid, safe='')}", json=body)

    async def delete(self, tool_uuid: str) -> JSON:
        return await self._client.request("DELETE", f"/tools/{quote(tool_uuid, safe='')}")


class AsyncKnowledgeBase(_AsyncResource):
    """Knowledge-base documents and hybrid retrieval search."""

    async def list_documents(self) -> JSON:
        return await self._client.request("GET", "/knowledge-base/documents")

    async def create_document(
        self,
        *,
        name: str,
        content: str,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ) -> JSON:
        body: dict[str, Any] = {"name": name, "content": content}
        if chunk_size is not None:
            body["chunk_size"] = chunk_size
        if chunk_overlap is not None:
            body["chunk_overlap"] = chunk_overlap
        return await self._client.request("POST", "/knowledge-base/documents", json=body)

    async def upload_document(self, file: bytes | str, filename: str = "document") -> JSON:
        """Upload a document file (txt, md, pdf) instead of pasting its text."""
        payload = file.encode() if isinstance(file, str) else file
        return await self._client.request_form(
            "POST", "/knowledge-base/documents/upload", data={}, files={"file": (filename, payload)}
        )

    async def search(
        self,
        *,
        query: str,
        top_k: int | None = None,
        document_ids: Sequence[int] | None = None,
        min_score: float | None = None,
    ) -> JSON:
        body: dict[str, Any] = {"query": query}
        if top_k is not None:
            body["top_k"] = top_k
        if document_ids is not None:
            body["document_ids"] = document_ids
        if min_score is not None:
            body["min_score"] = min_score
        return await self._client.request("POST", "/knowledge-base/search", json=body)


class AsyncVectorStores(_AsyncResource):
    """Vector stores over knowledge-base documents."""

    async def list(self) -> JSON:
        return await self._client.request("GET", "/vector-stores")

    async def create(self, *, name: str) -> JSON:
        return await self._client.request("POST", "/vector-stores", json={"name": name})

    async def retrieve(self, vector_store_uuid: str) -> JSON:
        return await self._client.request(
            "GET", f"/vector-stores/{quote(vector_store_uuid, safe='')}"
        )

    async def delete(self, vector_store_uuid: str) -> JSON:
        return await self._client.request(
            "DELETE", f"/vector-stores/{quote(vector_store_uuid, safe='')}"
        )

    async def upload_document(
        self, vector_store_uuid: str, file: bytes | str, filename: str = "document"
    ) -> JSON:
        """Add a document file to a vector store, so an agent can search it."""
        payload = file.encode() if isinstance(file, str) else file
        return await self._client.request_form(
            "POST",
            f"/vector-stores/{quote(vector_store_uuid, safe='')}/documents/upload",
            data={},
            files={"file": (filename, payload)},
        )


class AsyncAnalytics(_AsyncResource):
    """Usage and activity analytics."""

    async def overview(self, *, days: int | None = None) -> JSON:
        return await self._client.request("GET", "/analytics/overview", params={"days": days})
