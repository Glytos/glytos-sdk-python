"""Glytos API client and resource namespaces."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from urllib.parse import quote

import httpx

from ._webhooks import verify_webhook

DEFAULT_BASE_URL = "https://api.glytos.com/api/v1"

JSON = Any


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
        self.calls = Calls(self)
        self.phone_numbers = PhoneNumbers(self)
        self.sessions = Sessions(self)
        self.webhooks = Webhooks(self)
        self.campaigns = Campaigns(self)
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
        content: str,
        *,
        images: Sequence[str] | None = None,
    ) -> JSON:
        body: dict[str, Any] = {"content": content}
        if images is not None:
            body["images"] = images
        return self._client.request(
            "POST",
            f"/workflows/{quote(workflow_uuid, safe='')}"
            f"/sessions/{quote(session_uuid, safe='')}/messages",
            json=body,
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
        contacts: Sequence[dict[str, Any]] | None = None,
    ) -> JSON:
        body: dict[str, Any] = {
            "name": name,
            "workflow_uuid": workflow_uuid,
            "from_number": from_number,
        }
        if contacts is not None:
            body["contacts"] = contacts
        return self._client.request("POST", "/telephony/campaigns", json=body)

    def retrieve(self, campaign_uuid: str) -> JSON:
        return self._client.request("GET", f"/telephony/campaigns/{quote(campaign_uuid, safe='')}")

    def start(self, campaign_uuid: str) -> JSON:
        return self._client.request(
            "POST", f"/telephony/campaigns/{quote(campaign_uuid, safe='')}/start"
        )

    def sync_contacts(self, campaign_uuid: str, source_url: str) -> JSON:
        return self._client.request(
            "POST",
            f"/telephony/campaigns/{quote(campaign_uuid, safe='')}/contacts/sync",
            json={"source_url": source_url},
        )


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
        self.calls = AsyncCalls(self)
        self.phone_numbers = AsyncPhoneNumbers(self)
        self.sessions = AsyncSessions(self)
        self.webhooks = AsyncWebhooks(self)
        self.campaigns = AsyncCampaigns(self)
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
        content: str,
        *,
        images: Sequence[str] | None = None,
    ) -> JSON:
        body: dict[str, Any] = {"content": content}
        if images is not None:
            body["images"] = images
        return await self._client.request(
            "POST",
            f"/workflows/{quote(workflow_uuid, safe='')}"
            f"/sessions/{quote(session_uuid, safe='')}/messages",
            json=body,
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
        contacts: Sequence[dict[str, Any]] | None = None,
    ) -> JSON:
        body: dict[str, Any] = {
            "name": name,
            "workflow_uuid": workflow_uuid,
            "from_number": from_number,
        }
        if contacts is not None:
            body["contacts"] = contacts
        return await self._client.request("POST", "/telephony/campaigns", json=body)

    async def retrieve(self, campaign_uuid: str) -> JSON:
        return await self._client.request(
            "GET", f"/telephony/campaigns/{quote(campaign_uuid, safe='')}"
        )

    async def start(self, campaign_uuid: str) -> JSON:
        return await self._client.request(
            "POST", f"/telephony/campaigns/{quote(campaign_uuid, safe='')}/start"
        )

    async def sync_contacts(self, campaign_uuid: str, source_url: str) -> JSON:
        return await self._client.request(
            "POST",
            f"/telephony/campaigns/{quote(campaign_uuid, safe='')}/contacts/sync",
            json={"source_url": source_url},
        )


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


class AsyncAnalytics(_AsyncResource):
    """Usage and activity analytics."""

    async def overview(self, *, days: int | None = None) -> JSON:
        return await self._client.request("GET", "/analytics/overview", params={"days": days})
