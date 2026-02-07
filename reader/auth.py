"""Reader session auth: signed cookie (HMAC) with expiry."""

from __future__ import annotations

import base64
import hmac
import hashlib
import json
import time
from typing import Optional

SESSION_COOKIE_NAME = "reader_session"
SESSION_MAX_AGE_SECONDS = 7 * 24 * 3600  # 7 days


def _b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64_decode(s: str) -> bytes:
    pad = 4 - (len(s) % 4)
    if pad != 4:
        s += "=" * pad
    return base64.urlsafe_b64decode(s)


def create_session_cookie_value(username: str, password: str) -> str:
    """Build signed cookie value: base64(payload).base64(hmac)."""
    expiry = int(time.time()) + SESSION_MAX_AGE_SECONDS
    payload = {"u": username, "e": expiry}
    payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
    payload_b64 = _b64_encode(payload_bytes)
    key = password.encode("utf-8")
    sig = hmac.new(key, payload_bytes, hashlib.sha256).digest()
    sig_b64 = _b64_encode(sig)
    return f"{payload_b64}.{sig_b64}"


def verify_session_cookie(cookie_value: Optional[str], password: str) -> Optional[str]:
    """
    Verify signed cookie; return username if valid and not expired, else None.
    """
    if not cookie_value or not password:
        return None
    parts = cookie_value.split(".")
    if len(parts) != 2:
        return None
    try:
        payload_bytes = _b64_decode(parts[0])
        payload = json.loads(payload_bytes.decode("utf-8"))
        expiry = payload.get("e")
        username = payload.get("u")
        if expiry is None or username is None:
            return None
        if int(time.time()) > expiry:
            return None
        key = password.encode("utf-8")
        expected_sig = hmac.new(key, payload_bytes, hashlib.sha256).digest()
        expected_b64 = _b64_encode(expected_sig)
        if not hmac.compare_digest(expected_b64, parts[1]):
            return None
        return username
    except (ValueError, KeyError, json.JSONDecodeError):
        return None
