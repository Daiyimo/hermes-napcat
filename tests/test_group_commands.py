"""
Tests for napcat/group_commands.py
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import napcat.group_commands as _gc
import pytest
from napcat.group_commands import (
    AdminCmdContext,
    _extract_at_target,
    _format_uptime,
    _get_admin_list,
    _load_admin_list,
    handle_group_command,
    is_admin,
)
from napcat.observability import Observability
from napcat.utils import OneBotAPIError

# ---------------------------------------------------------------------------
# Reset the admin cache between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_admin_cache():
    _gc._admin_list_cache = None
    yield
    _gc._admin_list_cache = None


# ---------------------------------------------------------------------------
# _format_uptime
# ---------------------------------------------------------------------------


class TestFormatUptime:
    def test_seconds_only(self):
        assert _format_uptime(45) == "45秒"

    def test_minutes_and_seconds(self):
        result = _format_uptime(125)
        assert "分" in result and "秒" in result

    def test_hours(self):
        result = _format_uptime(3661)
        assert "小时" in result and "分" in result

    def test_days(self):
        result = _format_uptime(86400 + 3600)
        assert "天" in result and "小时" in result

    def test_zero(self):
        assert _format_uptime(0) == "0秒"


# ---------------------------------------------------------------------------
# is_admin / caching
# ---------------------------------------------------------------------------


class TestIsAdmin:
    def test_true_for_listed_admin(self, monkeypatch):
        monkeypatch.setenv("NAPCAT_ADMIN_USERS", "111,222,333")
        assert is_admin("222") is True

    def test_false_for_unlisted(self, monkeypatch):
        monkeypatch.setenv("NAPCAT_ADMIN_USERS", "111,222")
        assert is_admin("999") is False

    def test_false_when_empty_env(self, monkeypatch):
        monkeypatch.setenv("NAPCAT_ADMIN_USERS", "")
        assert is_admin("123") is False

    def test_result_is_cached(self, monkeypatch):
        monkeypatch.setenv("NAPCAT_ADMIN_USERS", "42")
        assert is_admin("42") is True
        # Mutate env — cache should still return old result
        monkeypatch.setenv("NAPCAT_ADMIN_USERS", "")
        assert is_admin("42") is True


# ---------------------------------------------------------------------------
# _extract_at_target
# ---------------------------------------------------------------------------


class TestExtractAtTarget:
    def test_from_at_segment(self):
        segs = [{"type": "at", "data": {"qq": "12345"}}]
        assert _extract_at_target(segs, "") == "12345"

    def test_skips_at_all(self):
        segs = [{"type": "at", "data": {"qq": "all"}}]
        assert _extract_at_target(segs, "") is None

    def test_cq_code_fallback(self):
        assert _extract_at_target([], "[CQ:at,qq=99999]") == "99999"

    def test_none_when_nothing(self):
        assert _extract_at_target([], "no mentions") is None


# ---------------------------------------------------------------------------
# Context factory helper
# ---------------------------------------------------------------------------


def _ctx(is_group=False, group_id=None, segs=None, event_time=None, obs=None):
    return AdminCmdContext(
        http_client=AsyncMock(),
        http_url="http://localhost:3000",
        token="",
        is_group=is_group,
        group_id=group_id,
        user_id="123",
        text="",
        segments=segs or [],
        event_time=event_time,
        self_name="TestBot",
        obs=obs,
    )


# ---------------------------------------------------------------------------
# /ping
# ---------------------------------------------------------------------------


class TestPing:
    @pytest.mark.asyncio
    async def test_returns_true(self):
        send = AsyncMock()
        assert await handle_group_command("/ping", ["/ping"], _ctx(), send) is True
        send.assert_called_once()

    @pytest.mark.asyncio
    async def test_contains_pong(self):
        send = AsyncMock()
        await handle_group_command("/ping", ["/ping"], _ctx(), send)
        assert "Pong" in send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_shows_latency_when_event_time_set(self):
        import time

        send = AsyncMock()
        await handle_group_command("/ping", ["/ping"], _ctx(event_time=time.time() - 0.05), send)
        assert "ms" in send.call_args[0][0]


# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------


class TestHelp:
    @pytest.mark.asyncio
    async def test_returns_true(self):
        send = AsyncMock()
        assert await handle_group_command("/help", ["/help"], _ctx(), send) is True

    @pytest.mark.asyncio
    async def test_lists_commands(self):
        send = AsyncMock()
        await handle_group_command("/help", ["/help"], _ctx(), send)
        msg = send.call_args[0][0]
        for cmd in ("/mute", "/kick", "/status"):
            assert cmd in msg


# ---------------------------------------------------------------------------
# /status
# ---------------------------------------------------------------------------


class TestStatus:
    @pytest.mark.asyncio
    async def test_returns_true(self):
        send = AsyncMock()
        obs = Observability()
        assert await handle_group_command("/status", ["/status"], _ctx(obs=obs), send) is True

    @pytest.mark.asyncio
    async def test_displays_stat_counters(self):
        obs = Observability()
        obs.metrics.messages_received = 42
        obs.metrics.messages_sent = 7
        obs.metrics.errors = 2
        obs.metrics.dedup_skipped = 3
        send = AsyncMock()
        await handle_group_command("/status", ["/status"], _ctx(obs=obs), send)
        msg = send.call_args[0][0]
        assert "42" in msg and "7" in msg

    @pytest.mark.asyncio
    async def test_shows_latency_percentiles(self):
        obs = Observability()
        for v in [100.0, 200.0]:
            obs.metrics.record_recv_latency(v)
        send = AsyncMock()
        await handle_group_command("/status", ["/status"], _ctx(obs=obs), send)
        msg = send.call_args[0][0]
        # p50 should be around 100ms (sorted: [100, 200], idx=0 for p50)
        assert "ms" in msg


# ---------------------------------------------------------------------------
# /mute
# ---------------------------------------------------------------------------


class TestMute:
    @pytest.mark.asyncio
    async def test_not_handled_in_private(self):
        send = AsyncMock()
        assert await handle_group_command("/mute", ["/mute"], _ctx(is_group=False), send) is False

    @pytest.mark.asyncio
    async def test_no_target_sends_usage(self):
        send = AsyncMock()
        ctx = _ctx(is_group=True, group_id="777")
        result = await handle_group_command("/mute", ["/mute"], ctx, send)
        assert result is True
        assert "用法" in send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        monkeypatch.setattr(_gc, "api_call", AsyncMock(return_value={}))
        segs = [{"type": "at", "data": {"qq": "55555"}}]
        send = AsyncMock()
        result = await handle_group_command(
            "/mute", ["/mute"], _ctx(is_group=True, group_id="777", segs=segs), send
        )
        assert result is True
        assert "✅" in send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_api_error_sends_failure(self, monkeypatch):
        monkeypatch.setattr(
            _gc,
            "api_call",
            AsyncMock(side_effect=OneBotAPIError("/set_group_ban", 100, "denied", "no perms")),
        )
        segs = [{"type": "at", "data": {"qq": "55555"}}]
        send = AsyncMock()
        await handle_group_command(
            "/mute", ["/mute"], _ctx(is_group=True, group_id="777", segs=segs), send
        )
        assert "❌" in send.call_args[0][0]


# ---------------------------------------------------------------------------
# /kick
# ---------------------------------------------------------------------------


class TestKick:
    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        monkeypatch.setattr(_gc, "api_call", AsyncMock(return_value={}))
        segs = [{"type": "at", "data": {"qq": "66666"}}]
        send = AsyncMock()
        result = await handle_group_command(
            "/kick", ["/kick"], _ctx(is_group=True, group_id="888", segs=segs), send
        )
        assert result is True
        assert "✅" in send.call_args[0][0]

    @pytest.mark.asyncio
    async def test_api_error(self, monkeypatch):
        monkeypatch.setattr(
            _gc,
            "api_call",
            AsyncMock(side_effect=OneBotAPIError("/set_group_kick", 200, "err", "wording")),
        )
        segs = [{"type": "at", "data": {"qq": "66666"}}]
        send = AsyncMock()
        await handle_group_command(
            "/kick", ["/kick"], _ctx(is_group=True, group_id="888", segs=segs), send
        )
        assert "❌" in send.call_args[0][0]


# ---------------------------------------------------------------------------
# Unknown command
# ---------------------------------------------------------------------------


class TestUnknownCommand:
    @pytest.mark.asyncio
    async def test_returns_false_and_no_send(self):
        send = AsyncMock()
        result = await handle_group_command("/nope", ["/nope"], _ctx(), send)
        assert result is False
        send.assert_not_called()
