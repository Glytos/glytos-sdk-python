import hashlib
import hmac
import time

from glytos import verify_webhook

# A fixed vector produced by the server signer (HMAC-SHA256 over "{ts}.{body}"), so this
# SDK is proven byte-for-byte compatible with how Glytos signs deliveries.
SECRET = "whsec_test_secret"
TS = "1710000000"
BODY = '{"event":"call.completed","id":"evt_123"}'
SIG = "356d865446082d49c6bfa57299c45900ab0d6681363426341acbe7c8f07ba025"


def header(ts: str, sig: str) -> str:
    return f"t={ts},v1={sig}"


def test_accepts_a_known_signature() -> None:
    # Tolerance 0 so the fixed historical timestamp is not rejected as too old.
    assert verify_webhook(BODY, header(TS, SIG), SECRET, tolerance_seconds=0)


def test_rejects_a_tampered_body() -> None:
    assert not verify_webhook(BODY + "x", header(TS, SIG), SECRET, tolerance_seconds=0)


def test_rejects_a_wrong_secret() -> None:
    assert not verify_webhook(BODY, header(TS, SIG), "wrong-secret", tolerance_seconds=0)


def test_rejects_a_malformed_header() -> None:
    assert not verify_webhook(BODY, "garbage", SECRET, tolerance_seconds=0)
    assert not verify_webhook(BODY, f"t={TS}", SECRET, tolerance_seconds=0)


def test_rejects_an_expired_delivery() -> None:
    # With the default tolerance the 2024 timestamp is far outside the window.
    assert not verify_webhook(BODY, header(TS, SIG), SECRET)


def test_accepts_a_fresh_delivery() -> None:
    ts = str(int(time.time()))
    body = '{"hello":"world"}'
    secret = "whsec_live"
    sig = hmac.new(secret.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
    assert verify_webhook(body, header(ts, sig), secret)
