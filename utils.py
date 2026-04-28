"""
NapCat adapter utilities.

HTTP client helper for OneBot 11 API calls and logging helpers.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .constants import (
    API_TIMEOUT,
    RESP_RETCODE_OK,
    RESP_STATUS_OK,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# OneBot 11 HTTP API caller
# ---------------------------------------------------------------------------

class OneBotAPIError(Exception):
    """Raised when a OneBot 11 API call fails."""

    def __init__(self, endpoint: str, retcode: int, message: str, wording: str = ""):
        self.endpoint = endpoint
        self.retcode = retcode
        self.message = message
        self.wording = wording
        detail = wording or message
        super().__init__(f"OneBot API {endpoint} failed (retcode={retcode}): {detail}")


async def api_call(
    http_client,
    base_url: str,
    endpoint: str,
    data: Optional[Dict[str, Any]] = None,
    token: Optional[str] = None,
    timeout: float = API_TIMEOUT,
) -> Dict[str, Any]:
    """Make a POST request to a OneBot 11 HTTP API endpoint.

    Args:
        http_client: An ``httpx.AsyncClient`` instance.
        base_url: NapCat HTTP server URL (e.g. ``http://127.0.0.1:3000``).
        endpoint: API path (e.g. ``/send_msg``).
        data: JSON body to send.  ``None`` sends ``{}``.
        token: Optional Bearer token for ``Authorization`` header.
        timeout: Request timeout in seconds.

    Returns:
        The ``data`` field from the OneBot 11 response envelope, or ``{}``
        if the response has no data field.

    Raises:
        OneBotAPIError: If ``retcode != 0`` in the response.
        httpx.HTTPError: On transport-level failures.
    """
    import httpx as _httpx

    url = f"{base_url.rstrip('/')}{endpoint}"
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    body = data or {}
    logger.debug("OneBot API → %s  body=%s", endpoint, _summarise_body(body))

    resp = await http_client.post(url, json=body, headers=headers, timeout=timeout)
    resp.raise_for_status()
    envelope = resp.json()

    status = envelope.get("status", "")
    retcode = envelope.get("retcode", -1)

    if retcode != RESP_RETCODE_OK and status != RESP_STATUS_OK:
        raise OneBotAPIError(
            endpoint=endpoint,
            retcode=retcode,
            message=envelope.get("message", "unknown error"),
            wording=envelope.get("wording", ""),
        )

    logger.debug("OneBot API ← %s  status=%s retcode=%s", endpoint, status, retcode)
    return envelope.get("data") or {}


async def api_call_raw(
    http_client,
    base_url: str,
    endpoint: str,
    data: Optional[Dict[str, Any]] = None,
    token: Optional[str] = None,
    timeout: float = API_TIMEOUT,
) -> Dict[str, Any]:
    """Like :func:`api_call` but returns the full response envelope.

    Useful when the caller needs to inspect ``status``, ``retcode``, etc.
    """
    import httpx as _httpx

    url = f"{base_url.rstrip('/')}{endpoint}"
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    resp = await http_client.post(url, json=data or {}, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def _summarise_body(body: Dict[str, Any], max_len: int = 200) -> str:
    """Return a short string representation of *body* for debug logs."""
    import json
    raw = json.dumps(body, ensure_ascii=False)
    if len(raw) <= max_len:
        return raw
    return raw[:max_len] + "..."


def redact_qq_number(text: str) -> str:
    """Redact QQ number-like substrings in structured log messages.

    Only applied to known-format log lines (e.g. ``user_id=123456789``).
    Avoids false positives from broad digit patterns.
    """
    import re
    return re.sub(
        r"(user_id|group_id|self_id|qq)\s*[=:]\s*(\d{5,11})",
        lambda m: f"{m.group(1)}={m.group(2)[:3]}***",
        text,
        flags=re.IGNORECASE,
    )
