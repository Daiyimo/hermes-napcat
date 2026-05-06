"""
Tests for napcat/utils.py
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from napcat.utils import OneBotAPIError, _summarise_body, api_call, redact_qq_number

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(payload: dict, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    return resp


def _make_client(payload: dict, status_code: int = 200):
    client = AsyncMock()
    client.post = AsyncMock(return_value=_make_response(payload, status_code))
    return client


# ---------------------------------------------------------------------------
# OneBotAPIError
# ---------------------------------------------------------------------------


class TestOneBotAPIError:
    def test_str_uses_wording(self):
        exc = OneBotAPIError("/send_msg", 100, "msg", "human wording")
        assert "human wording" in str(exc)
        assert "/send_msg" in str(exc)
        assert "100" in str(exc)

    def test_str_falls_back_to_message(self):
        exc = OneBotAPIError("/send_msg", 100, "fallback message")
        assert "fallback message" in str(exc)

    def test_attributes(self):
        exc = OneBotAPIError("/ep", 200, "msg", "wrd")
        assert exc.endpoint == "/ep"
        assert exc.retcode == 200
        assert exc.message == "msg"
        assert exc.wording == "wrd"


# ---------------------------------------------------------------------------
# api_call — success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_call_success_returns_data():
    client = _make_client({"status": "ok", "retcode": 0, "data": {"message_id": 42}})
    result = await api_call(client, "http://127.0.0.1:3000", "/send_msg")
    assert result == {"message_id": 42}


@pytest.mark.asyncio
async def test_api_call_no_data_field_returns_empty():
    client = _make_client({"status": "ok", "retcode": 0})
    result = await api_call(client, "http://127.0.0.1:3000", "/ep")
    assert result == {}


# ---------------------------------------------------------------------------
# api_call — failure paths  (validates the error-detection logic)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_call_raises_on_nonzero_retcode():
    """retcode != 0 with status='ok' must raise."""
    client = _make_client({"status": "ok", "retcode": 100, "message": "err"})
    with pytest.raises(OneBotAPIError) as exc_info:
        await api_call(client, "http://127.0.0.1:3000", "/send_msg")
    assert exc_info.value.retcode == 100


@pytest.mark.asyncio
async def test_api_call_raises_on_failed_status():
    """status='failed' with retcode=0 must raise (failed is never acceptable)."""
    client = _make_client({"status": "failed", "retcode": 0, "message": "bad"})
    with pytest.raises(OneBotAPIError) as exc_info:
        await api_call(client, "http://127.0.0.1:3000", "/send_msg")
    assert exc_info.value.endpoint == "/send_msg"


@pytest.mark.asyncio
async def test_api_call_raises_on_both_bad():
    client = _make_client({"status": "failed", "retcode": 50, "wording": "oops"})
    with pytest.raises(OneBotAPIError) as exc_info:
        await api_call(client, "http://127.0.0.1:3000", "/kick")
    assert "oops" in str(exc_info.value)


@pytest.mark.asyncio
async def test_api_call_accepts_async_status():
    """status='async' with retcode=0 must NOT raise — NapCat uses this for
    operations like set_group_ban and set_group_kick that are applied
    asynchronously server-side."""
    client = _make_client({"status": "async", "retcode": 0, "data": {}})
    result = await api_call(client, "http://127.0.0.1:3000", "/set_group_ban")
    assert result == {}  # should succeed silently


@pytest.mark.asyncio
async def test_api_call_passes_bearer_token():
    client = _make_client({"status": "ok", "retcode": 0, "data": {}})
    await api_call(client, "http://host", "/ep", token="mytoken")
    call_kwargs = client.post.call_args.kwargs
    assert call_kwargs["headers"]["Authorization"] == "Bearer mytoken"


# ---------------------------------------------------------------------------
# redact_qq_number
# ---------------------------------------------------------------------------


class TestRedactQQNumber:
    def test_redacts_user_id(self):
        result = redact_qq_number("user_id=123456789")
        assert "123***" in result
        assert "456789" not in result

    def test_redacts_group_id(self):
        result = redact_qq_number("group_id:987654321")
        assert "987***" in result

    def test_no_false_positive_on_short_number(self):
        result = redact_qq_number("count=42")
        assert result == "count=42"

    def test_no_false_positive_plain_text(self):
        result = redact_qq_number("hello world 12345678")
        assert result == "hello world 12345678"

    def test_case_insensitive(self):
        result = redact_qq_number("USER_ID=111222333")
        assert "111***" in result


# ---------------------------------------------------------------------------
# _summarise_body
# ---------------------------------------------------------------------------


class TestSummariseBody:
    def test_short_body_returned_as_is(self):
        body = {"action": "ping"}
        result = _summarise_body(body, max_len=200)
        assert result == json.dumps(body, ensure_ascii=False)

    def test_long_body_truncated(self):
        body = {"key": "x" * 300}
        result = _summarise_body(body, max_len=200)
        assert len(result) == 203
        assert result.endswith("...")

    def test_exact_limit_not_truncated(self):
        body = {"k": "v"}
        raw = json.dumps(body, ensure_ascii=False)
        result = _summarise_body(body, max_len=len(raw))
        assert not result.endswith("...")
