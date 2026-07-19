"""Glytos API client and resource namespaces."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

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

    def request(
        self,
        method: str,
        path: str,
        *,
        json: JSON | None = None,
        params: dict[str, Any] | None = None,
    ) -> JSON:
        """Low-level request against any endpoint (path relative to the API base)."""
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}
        response = self._http.request(
            method,
            self._base_url + path,
            headers=self._headers,
            json=json,
            params=clean_params or None,
        )
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

    def list(self) -> JSON:
        return self._client.request("GET", "/workflows")

    def retrieve(self, workflow_uuid: str) -> JSON:
        return self._client.request("GET", f"/workflows/{workflow_uuid}")

    def create(
        self, *, name: str, mode: str = "prompt", config: dict[str, Any] | None = None
    ) -> JSON:
        body: dict[str, Any] = {"name": name, "mode": mode}
        if config is not None:
            body["config"] = config
        return self._client.request("POST", "/workflows", json=body)

    def publish(self, workflow_uuid: str) -> JSON:
        return self._client.request("POST", f"/workflows/{workflow_uuid}/publish")

    def delete(self, workflow_uuid: str) -> JSON:
        return self._client.request("DELETE", f"/workflows/{workflow_uuid}")

    def templates(self) -> JSON:
        return self._client.request("GET", "/workflows/templates")

    def session(self, workflow_uuid: str, session_uuid: str) -> JSON:
        return self._client.request("GET", f"/workflows/{workflow_uuid}/sessions/{session_uuid}")

    def session_events(self, workflow_uuid: str, session_uuid: str) -> JSON:
        return self._client.request(
            "GET", f"/workflows/{workflow_uuid}/sessions/{session_uuid}/events"
        )


class Calls(_Resource):
    def create(self, **body: Any) -> JSON:
        return self._client.request("POST", "/calls", json=body)

    def list(self, **params: Any) -> JSON:
        return self._client.request("GET", "/calls", params=params)

    def retrieve(self, call_uuid: str) -> JSON:
        return self._client.request("GET", f"/calls/{call_uuid}")

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
        return self._client.request("POST", f"/calls/{call_uuid}/control", json=body)


class PhoneNumbers(_Resource):
    def search(self, **params: Any) -> JSON:
        return self._client.request("GET", "/telephony/numbers/search", params=params)

    def list(self) -> JSON:
        return self._client.request("GET", "/telephony/numbers")

    def provision(self, *, e164: str, **body: Any) -> JSON:
        return self._client.request("POST", "/telephony/numbers", json={"e164": e164, **body})

    def assign(self, number_uuid: str, **body: Any) -> JSON:
        return self._client.request("POST", f"/telephony/numbers/{number_uuid}/assign", json=body)

    def release(self, number_uuid: str) -> JSON:
        return self._client.request("DELETE", f"/telephony/numbers/{number_uuid}")


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

    def delete(self, endpoint_id: int | str) -> JSON:
        return self._client.request("DELETE", f"/webhooks/endpoints/{endpoint_id}")

    def events(self) -> JSON:
        return self._client.request("GET", "/webhooks/events")

    @staticmethod
    def verify(
        payload: str | bytes,
        signature_header: str,
        secret: str,
        tolerance_seconds: int = 300,
    ) -> bool:
        """Verify a webhook delivery signature (see :func:`glytos.verify_webhook`)."""
        return verify_webhook(payload, signature_header, secret, tolerance_seconds)
