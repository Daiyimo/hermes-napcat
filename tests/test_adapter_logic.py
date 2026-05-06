"""
Unit tests for pure-logic methods in NapCatAdapter.

These tests cover the six methods that contain non-trivial logic with no
(or minimal) I/O: _dedup_check, _is_user_authorized, _maybe_wrap_reply,
_should_reply, _send_segments (circuit-breaker branch), and
check_napcat_requirements.

Importantly, no WebSocket or real HTTP connections are made.

Module-level setup
------------------
conftest.py purposely stubs ``napcat.adapter`` because the adapter imports
several ``gateway.*`` symbols that don't exist in the test environment.
This module enhances those stubs just enough for ``NapCatAdapter`` to be
constructable, then loads the *real* adapter.py via importlib.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from unittest.mock import MagicMock, patch

import pytest

# =============================================================================
# Step 1: Enhance the gateway stubs that conftest.py already installed
# =============================================================================

_gpb = sys.modules["gateway.platforms.base"]
_gc = sys.modules["gateway.config"]


class _BasePlatformAdapter:
    """Permissive stub — accepts any constructor args used by NapCatAdapter."""

    MAX_MESSAGE_LENGTH = 4500

    def __init__(self, config=None, platform=None, **kwargs):
        self._config = config
        self._platform = platform

    def _set_fatal_error(self, code: str, msg: str, retryable: bool = False) -> None:
        pass  # no-op in unit tests


class _SendResult:
    """Minimal stub matching the keyword-arg constructor used in adapter.py."""

    def __init__(
        self,
        success: bool,
        error: str | None = None,
        message_id: str | None = None,
        retryable: bool = False,
    ):
        self.success = success
        self.error = error
        self.message_id = message_id
        self.retryable = retryable


class _Platform:
    """Stub with the platform-name constants that adapter.py references."""

    NAPCAT = "napcat"
    QQBOT = "qqbot"
    SIGNAL = "signal"
    WECOM = "wecom"
    FEISHU = "feishu"
    DINGTALK = "dingtalk"


_gpb.BasePlatformAdapter = _BasePlatformAdapter
_gpb.SendResult = _SendResult
_gc.Platform = _Platform

# =============================================================================
# Step 2: Load the *real* adapter.py (replacing conftest's stub)
# =============================================================================

_root = pathlib.Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location("napcat.adapter", _root / "adapter.py")
_adapter_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_adapter_mod.__package__ = "napcat"
sys.modules["napcat.adapter"] = _adapter_mod
_spec.loader.exec_module(_adapter_mod)  # type: ignore[union-attr]

NapCatAdapter = _adapter_mod.NapCatAdapter
check_napcat_requirements = _adapter_mod.check_napcat_requirements


# =============================================================================
# Factory helper
# =============================================================================


def _make_adapter(**env_overrides) -> NapCatAdapter:
    """Return a NapCatAdapter built from a minimal stub config.

    Pass environment-variable overrides as keyword arguments, e.g.
    ``_make_adapter(NAPCAT_REPLY_MODE="all")``.
    """
    config = MagicMock()
    config.extra = {}
    config.token = ""

    env = {
        "NAPCAT_HTTP_URL": "http://127.0.0.1:3000",
        "NAPCAT_WS_URL": "ws://127.0.0.1:3001",
        # Clear allowlist vars so tests get predictable defaults
        "NAPCAT_ALLOWED_USERS": "",
        "NAPCAT_GROUP_ALLOWED_USERS": "",
        "NAPCAT_ALLOW_ALL_USERS": "",
        **env_overrides,
    }
    with patch.dict("os.environ", env, clear=False):
        adapter = NapCatAdapter(config)
        # _load_authorization is lazy; trigger it now while env is still patched
        adapter._load_authorization()
        return adapter


# =============================================================================
# check_napcat_requirements
# =============================================================================


class TestCheckNapcatRequirements:
    def test_returns_true_when_both_urls_set(self, monkeypatch):
        monkeypatch.setenv("NAPCAT_HTTP_URL", "http://127.0.0.1:3000")
        monkeypatch.setenv("NAPCAT_WS_URL", "ws://127.0.0.1:3001")
        with (
            patch.object(_adapter_mod, "WEBSOCKETS_AVAILABLE", True),
            patch.object(_adapter_mod, "HTTPX_AVAILABLE", True),
        ):
            assert check_napcat_requirements() is True

    def test_returns_false_when_http_url_missing(self, monkeypatch):
        monkeypatch.delenv("NAPCAT_HTTP_URL", raising=False)
        monkeypatch.setenv("NAPCAT_WS_URL", "ws://127.0.0.1:3001")
        with (
            patch.object(_adapter_mod, "WEBSOCKETS_AVAILABLE", True),
            patch.object(_adapter_mod, "HTTPX_AVAILABLE", True),
        ):
            assert check_napcat_requirements() is False

    def test_returns_false_when_ws_url_missing(self, monkeypatch):
        monkeypatch.setenv("NAPCAT_HTTP_URL", "http://127.0.0.1:3000")
        monkeypatch.delenv("NAPCAT_WS_URL", raising=False)
        with (
            patch.object(_adapter_mod, "WEBSOCKETS_AVAILABLE", True),
            patch.object(_adapter_mod, "HTTPX_AVAILABLE", True),
        ):
            assert check_napcat_requirements() is False

    def test_returns_false_when_websockets_unavailable(self, monkeypatch):
        monkeypatch.setenv("NAPCAT_HTTP_URL", "http://127.0.0.1:3000")
        monkeypatch.setenv("NAPCAT_WS_URL", "ws://127.0.0.1:3001")
        with (
            patch.object(_adapter_mod, "WEBSOCKETS_AVAILABLE", False),
            patch.object(_adapter_mod, "HTTPX_AVAILABLE", True),
        ):
            assert check_napcat_requirements() is False

    def test_returns_false_when_httpx_unavailable(self, monkeypatch):
        monkeypatch.setenv("NAPCAT_HTTP_URL", "http://127.0.0.1:3000")
        monkeypatch.setenv("NAPCAT_WS_URL", "ws://127.0.0.1:3001")
        with (
            patch.object(_adapter_mod, "WEBSOCKETS_AVAILABLE", True),
            patch.object(_adapter_mod, "HTTPX_AVAILABLE", False),
        ):
            assert check_napcat_requirements() is False


# =============================================================================
# _dedup_check
# =============================================================================


class TestDedupCheck:
    def test_first_occurrence_returns_true(self):
        assert _make_adapter()._dedup_check("msg-001") is True

    def test_second_occurrence_returns_false(self):
        adapter = _make_adapter()
        adapter._dedup_check("msg-001")
        assert adapter._dedup_check("msg-001") is False

    def test_second_occurrence_increments_metric(self):
        adapter = _make_adapter()
        adapter._dedup_check("msg-002")
        adapter._dedup_check("msg-002")
        assert adapter._obs.metrics.dedup_skipped == 1

    def test_empty_id_always_passes(self):
        adapter = _make_adapter()
        assert adapter._dedup_check("") is True
        assert adapter._dedup_check("") is True  # no dedup on empty ID

    def test_different_ids_both_pass(self):
        adapter = _make_adapter()
        assert adapter._dedup_check("aaa") is True
        assert adapter._dedup_check("bbb") is True

    def test_capacity_eviction_keeps_size_bounded(self):
        from napcat.constants import DEDUP_MAX_SIZE

        adapter = _make_adapter()
        for i in range(DEDUP_MAX_SIZE + 10):
            adapter._dedup_check(str(i))
        assert len(adapter._seen_messages) <= DEDUP_MAX_SIZE

    def test_oldest_entry_evicted_first(self):
        from napcat.constants import DEDUP_MAX_SIZE

        adapter = _make_adapter()
        for i in range(DEDUP_MAX_SIZE):
            adapter._dedup_check(str(i))
        # One more — "0" (oldest) must be evicted
        adapter._dedup_check("overflow")
        assert "0" not in adapter._seen_messages
        assert "overflow" in adapter._seen_messages


# =============================================================================
# _is_user_authorized
# =============================================================================


class TestIsUserAuthorized:
    def test_no_allowlist_allows_everyone(self):
        adapter = _make_adapter()
        assert adapter._is_user_authorized("99999") is True

    def test_allow_all_users_flag_bypasses_lists(self):
        adapter = _make_adapter(
            NAPCAT_ALLOW_ALL_USERS="true",
            NAPCAT_ALLOWED_USERS="111,222",
        )
        assert adapter._is_user_authorized("99999") is True

    def test_global_allowlist_permits_listed_user(self):
        adapter = _make_adapter(NAPCAT_ALLOWED_USERS="111,222,333")
        assert adapter._is_user_authorized("222") is True

    def test_global_allowlist_blocks_unlisted_user(self):
        adapter = _make_adapter(NAPCAT_ALLOWED_USERS="111,222,333")
        assert adapter._is_user_authorized("999") is False

    def test_group_allowlist_takes_precedence_in_groups(self):
        # 555 is NOT in global list but IS in group list
        adapter = _make_adapter(
            NAPCAT_ALLOWED_USERS="111",
            NAPCAT_GROUP_ALLOWED_USERS="555,666",
        )
        assert adapter._is_user_authorized("555", is_group=True) is True

    def test_group_allowlist_blocks_non_member_in_groups(self):
        adapter = _make_adapter(
            NAPCAT_ALLOWED_USERS="111",
            NAPCAT_GROUP_ALLOWED_USERS="555,666",
        )
        # 111 is in global list but NOT in group list → blocked in groups
        assert adapter._is_user_authorized("111", is_group=True) is False

    def test_private_chat_uses_global_allowlist_not_group_list(self):
        adapter = _make_adapter(
            NAPCAT_ALLOWED_USERS="111",
            NAPCAT_GROUP_ALLOWED_USERS="555",
        )
        assert adapter._is_user_authorized("111", is_group=False) is True
        assert adapter._is_user_authorized("555", is_group=False) is False

    def test_authorization_cache_loaded_only_once(self, monkeypatch):
        adapter = _make_adapter(NAPCAT_ALLOWED_USERS="111")
        adapter._is_user_authorized("111")
        # Changing env after first call must not affect the cached result
        monkeypatch.setenv("NAPCAT_ALLOWED_USERS", "999")
        assert adapter._is_user_authorized("111") is True  # still from cache


# =============================================================================
# _should_reply / _maybe_wrap_reply
# =============================================================================


class TestShouldReply:
    def test_off_mode_returns_false(self):
        assert _make_adapter(NAPCAT_REPLY_MODE="off")._should_reply() is False

    def test_first_mode_returns_true(self):
        assert _make_adapter(NAPCAT_REPLY_MODE="first")._should_reply() is True

    def test_all_mode_returns_true(self):
        assert _make_adapter(NAPCAT_REPLY_MODE="all")._should_reply() is True

    def test_invalid_mode_defaults_to_off(self):
        assert _make_adapter(NAPCAT_REPLY_MODE="bogus")._should_reply() is False


class TestMaybeWrapReply:
    _TEXT_SEG = [{"type": "text", "data": {"text": "hi"}}]

    def test_off_mode_returns_segments_unchanged(self):
        adapter = _make_adapter(NAPCAT_REPLY_MODE="off")
        result = adapter._maybe_wrap_reply(self._TEXT_SEG, reply_to="123")
        assert result is self._TEXT_SEG

    def test_first_mode_prepends_reply_segment(self):
        adapter = _make_adapter(NAPCAT_REPLY_MODE="first")
        result = adapter._maybe_wrap_reply(self._TEXT_SEG, reply_to="123")
        assert result[0]["type"] == "reply"
        assert result[0]["data"]["id"] == "123"

    def test_all_mode_prepends_reply_segment(self):
        adapter = _make_adapter(NAPCAT_REPLY_MODE="all")
        result = adapter._maybe_wrap_reply(self._TEXT_SEG, reply_to="456")
        assert result[0]["type"] == "reply"

    def test_none_reply_to_returns_unchanged(self):
        adapter = _make_adapter(NAPCAT_REPLY_MODE="all")
        result = adapter._maybe_wrap_reply(self._TEXT_SEG, reply_to=None)
        assert result is self._TEXT_SEG

    def test_empty_reply_to_returns_unchanged(self):
        adapter = _make_adapter(NAPCAT_REPLY_MODE="all")
        result = adapter._maybe_wrap_reply(self._TEXT_SEG, reply_to="")
        assert result is self._TEXT_SEG


# =============================================================================
# _send_segments — circuit-breaker fast-fail and no-connection guard only
# (the happy path requires a real httpx client; covered by integration tests)
# =============================================================================


class TestSendSegmentsCircuitBreaker:
    @pytest.mark.asyncio
    async def test_fast_fails_when_circuit_is_open(self):
        adapter = _make_adapter()
        adapter._http_client = MagicMock()  # pass the "not connected" guard
        from napcat.observability import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure()  # → OPEN
        adapter._obs.circuit = cb

        result = await adapter._send_segments("123456", [{"type": "text", "data": {"text": "x"}}])

        assert result.success is False
        assert result.retryable is True
        assert "circuit" in result.error.lower()

    @pytest.mark.asyncio
    async def test_fast_fail_records_send_fail_metric(self):
        adapter = _make_adapter()
        adapter._http_client = MagicMock()
        from napcat.observability import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure()
        adapter._obs.circuit = cb

        await adapter._send_segments("123", [])
        assert adapter._obs.metrics.send_failure_rate_in_window() == 1.0

    @pytest.mark.asyncio
    async def test_returns_not_connected_when_no_http_client(self):
        adapter = _make_adapter()
        adapter._http_client = None
        result = await adapter._send_segments("123", [])
        assert result.success is False
        assert "not connected" in result.error.lower()
