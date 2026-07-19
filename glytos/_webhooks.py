"""Webhook signature verification.

Matches the server scheme: HMAC-SHA256 over ``"{timestamp}.{body}"``, delivered in
the ``X-Glytos-Signature: t=<ts>,v1=<hex>`` header.
"""

from __future__ import annotations

import hashlib
import hmac
import time


def verify_webhook(
    payload: str | bytes,
    signature_header: str,
    secret: str,
    tolerance_seconds: int = 300,
) -> bool:
    """Return True only if ``signature_header`` is a valid signature for ``payload``.

    Pass the RAW request body (``str`` or ``bytes``), the ``X-Glytos-Signature``
    header value, and your endpoint secret. Constant-time and replay-safe.
    """
    body = payload.encode("utf-8") if isinstance(payload, str) else payload

    parts: dict[str, str] = {}
    for piece in signature_header.split(","):
        key, sep, value = piece.partition("=")
        if sep:
            parts[key.strip()] = value.strip()

    timestamp = parts.get("t")
    provided = parts.get("v1")
    if not timestamp or not provided:
        return False

    expected = hmac.new(
        secret.encode("utf-8"), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, provided):
        return False

    if tolerance_seconds > 0:
        try:
            ts = int(timestamp)
        except ValueError:
            return False
        if abs(time.time() - ts) > tolerance_seconds:
            return False
    return True
