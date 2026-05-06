"""
Tests for napcat/observability.py

Covers: CircuitBreaker state machine, Metrics percentiles and sliding windows,
AlertEngine rule evaluation and cooldowns, Observability.tick() integration.
"""

from __future__ import annotations

import time

import pytest

# conftest.py already registers napcat.* package aliases
from napcat.observability import (
    AlertEngine,
    AlertEvent,
    CircuitBreaker,
    Metrics,
    Observability,
    _SlidingWindow,
)

# =============================================================================
# _SlidingWindow
# =============================================================================


class TestSlidingWindow:
    def test_empty_returns_zero(self):
        w = _SlidingWindow(window_seconds=60)
        assert w.total() == 0

    def test_single_add(self):
        w = _SlidingWindow(window_seconds=60)
        w.add(3)
        assert w.total() == 3

    def test_multiple_adds(self):
        w = _SlidingWindow(window_seconds=60)
        w.add(2)
        w.add(5)
        assert w.total() == 7

    def test_expired_entries_pruned(self):
        w = _SlidingWindow(window_seconds=0.05)  # 50 ms window
        w.add(10)
        time.sleep(0.12)  # 120 ms — well past the 50 ms window
        assert w.total() == 0  # expired

    def test_partial_expiry(self):
        w = _SlidingWindow(window_seconds=0.1)
        w.add(4)
        time.sleep(0.06)
        w.add(3)
        # first add should still be within window at this point on fast machines
        # just check that adding after partial time works
        total = w.total()
        assert total >= 3


# =============================================================================
# Metrics
# =============================================================================


class TestMetrics:
    def test_initial_counters_are_zero(self):
        m = Metrics()
        assert m.messages_received == 0
        assert m.messages_sent == 0
        assert m.errors == 0
        assert m.dedup_skipped == 0
        assert m.reconnects == 0

    def test_uptime_increases(self):
        m = Metrics()
        t0 = m.uptime_seconds()
        time.sleep(0.02)
        assert m.uptime_seconds() >= t0

    def test_record_recv_latency_stored(self):
        m = Metrics()
        m.record_recv_latency(100.0)
        m.record_recv_latency(200.0)
        assert m.p50_recv_ms() is not None
        assert 100.0 <= m.p50_recv_ms() <= 200.0

    def test_p50_p95_ordering(self):
        m = Metrics()
        for v in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
            m.record_recv_latency(float(v))
        p50 = m.p50_recv_ms()
        p95 = m.p95_recv_ms()
        assert p50 is not None and p95 is not None
        assert p50 <= p95

    def test_p50_none_when_no_samples(self):
        m = Metrics()
        assert m.p50_recv_ms() is None
        assert m.p95_send_ms() is None

    def test_record_send_latency(self):
        m = Metrics()
        m.record_send_latency(55.0)
        assert m.p50_send_ms() == 55.0

    def test_record_error_increments_counter_and_window(self):
        m = Metrics()
        m.record_error()
        m.record_error()
        assert m.errors == 2
        assert m.errors_in_window() == 2

    def test_record_reconnect(self):
        m = Metrics()
        m.record_reconnect()
        assert m.reconnects == 1
        assert m.reconnects_in_window() == 1

    def test_send_failure_rate_all_ok(self):
        m = Metrics()
        m.record_send_ok()
        m.record_send_ok()
        assert m.send_failure_rate_in_window() == 0.0

    def test_send_failure_rate_all_fail(self):
        m = Metrics()
        m.record_send_fail()
        m.record_send_fail()
        assert m.send_failure_rate_in_window() == 1.0

    def test_send_failure_rate_mixed(self):
        m = Metrics()
        m.record_send_ok()
        m.record_send_fail()
        rate = m.send_failure_rate_in_window()
        assert abs(rate - 0.5) < 0.01

    def test_send_failure_rate_empty_is_zero(self):
        m = Metrics()
        assert m.send_failure_rate_in_window() == 0.0

    def test_record_heartbeat(self):
        m = Metrics()
        assert m.seconds_since_heartbeat() is None
        m.record_heartbeat()
        secs = m.seconds_since_heartbeat()
        assert secs is not None
        assert 0.0 <= secs < 1.0

    def test_ring_buffer_max_size(self):
        """Latency buffer should not exceed maxlen."""
        m = Metrics()
        for i in range(100):
            m.record_recv_latency(float(i))
        # maxlen is METRICS_LATENCY_BUFFER (default 50)
        assert len(m._recv_latency_ms) <= 50


# =============================================================================
# CircuitBreaker
# =============================================================================


class TestCircuitBreakerClosed:
    def test_initial_state_is_closed(self):
        cb = CircuitBreaker()
        assert cb.state == "CLOSED"

    def test_allows_requests_when_closed(self):
        cb = CircuitBreaker()
        assert cb.allow_request() is True

    def test_single_failure_stays_closed(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        assert cb.state == "CLOSED"

    def test_reaches_threshold_opens(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "OPEN"

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()  # resets counter
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "CLOSED"  # only 2 failures after reset


class TestCircuitBreakerOpen:
    def test_open_rejects_requests(self):
        cb = CircuitBreaker(failure_threshold=1, open_timeout_s=60)
        cb.record_failure()
        assert cb.state == "OPEN"
        assert cb.allow_request() is False

    def test_transitions_to_half_open_after_timeout(self, monkeypatch):
        cb = CircuitBreaker(failure_threshold=1, open_timeout_s=0.0)
        cb.record_failure()
        assert cb.state == "OPEN"
        # open_timeout is 0 → immediately transitions on next allow_request
        result = cb.allow_request()
        assert cb.state == "HALF_OPEN"
        assert result is True  # first probe allowed


class TestCircuitBreakerHalfOpen:
    def _make_half_open_cb(self, success_threshold=2):
        cb = CircuitBreaker(
            failure_threshold=1,
            open_timeout_s=0.0,
            success_threshold=success_threshold,
            half_open_probe=1,
        )
        cb.record_failure()  # → OPEN
        cb.allow_request()  # → HALF_OPEN (probe)
        assert cb.state == "HALF_OPEN"
        return cb

    def test_success_in_half_open_leads_to_closed(self):
        cb = self._make_half_open_cb(success_threshold=1)
        cb.record_success()
        assert cb.state == "CLOSED"

    def test_multiple_successes_needed(self):
        cb = self._make_half_open_cb(success_threshold=2)
        cb.record_success()
        assert cb.state == "HALF_OPEN"  # still waiting
        cb.record_success()
        assert cb.state == "CLOSED"

    def test_failure_in_half_open_reopens(self):
        cb = self._make_half_open_cb()
        cb.record_failure()
        assert cb.state == "OPEN"

    def test_probe_limit_in_half_open(self):
        cb = CircuitBreaker(
            failure_threshold=1,
            open_timeout_s=0.0,
            half_open_probe=1,
        )
        cb.record_failure()
        first = cb.allow_request()  # → HALF_OPEN, probe 1 allowed
        second = cb.allow_request()  # no more probes
        assert first is True
        assert second is False


# =============================================================================
# AlertEngine
# =============================================================================


class TestAlertEngine:
    def _make_metrics(self) -> Metrics:
        return Metrics()

    def test_no_alerts_when_metrics_are_fine(self):
        engine = AlertEngine()
        m = self._make_metrics()
        engine.check(m)
        assert engine.recent_alerts == []

    def test_error_spike_fires(self):
        engine = AlertEngine()
        m = self._make_metrics()
        # Inject enough errors to exceed threshold (default 10)
        for _ in range(11):
            m.record_error()
        engine.check(m)
        names = [a.name for a in engine.recent_alerts]
        assert "error_spike" in names

    def test_error_spike_respects_cooldown(self):
        engine = AlertEngine()
        m = self._make_metrics()
        for _ in range(11):
            m.record_error()
        engine.check(m)
        count_before = len(engine.recent_alerts)
        engine.check(m)  # second check within cooldown
        count_after = len(engine.recent_alerts)
        assert count_after == count_before  # no duplicate

    def test_circuit_open_fires(self):
        engine = AlertEngine()
        m = self._make_metrics()
        m.circuit_state = "OPEN"
        engine.check(m)
        names = [a.name for a in engine.recent_alerts]
        assert "circuit_open" in names

    def test_circuit_open_not_fire_when_closed(self):
        engine = AlertEngine()
        m = self._make_metrics()
        m.circuit_state = "CLOSED"
        engine.check(m)
        names = [a.name for a in engine.recent_alerts]
        assert "circuit_open" not in names

    def test_reconnect_burst_fires(self):
        engine = AlertEngine()
        m = self._make_metrics()
        for _ in range(6):  # default threshold is 5
            m.record_reconnect()
        engine.check(m)
        names = [a.name for a in engine.recent_alerts]
        assert "ws_reconnect_burst" in names

    def test_send_failure_rate_fires(self):
        engine = AlertEngine()
        m = self._make_metrics()
        # 100% failure
        for _ in range(5):
            m.record_send_fail()
        engine.check(m)
        names = [a.name for a in engine.recent_alerts]
        assert "send_failure_rate" in names

    def test_send_failure_rate_low_doesnt_fire(self):
        engine = AlertEngine()
        m = self._make_metrics()
        m.record_send_ok()
        m.record_send_ok()
        engine.check(m)
        names = [a.name for a in engine.recent_alerts]
        assert "send_failure_rate" not in names

    def test_no_heartbeat_fires_after_threshold(self):
        engine = AlertEngine()
        m = self._make_metrics()
        # Simulate last heartbeat way in the past
        m.last_heartbeat_at = time.monotonic() - 200.0  # 200s ago > 90s threshold
        engine.check(m)
        names = [a.name for a in engine.recent_alerts]
        assert "no_heartbeat" in names

    def test_no_heartbeat_not_fire_before_threshold(self):
        engine = AlertEngine()
        m = self._make_metrics()
        m.record_heartbeat()  # just now
        engine.check(m)
        names = [a.name for a in engine.recent_alerts]
        assert "no_heartbeat" not in names

    def test_no_heartbeat_not_fire_when_never_seen(self):
        """If no heartbeat was ever received, the rule should not fire."""
        engine = AlertEngine()
        m = self._make_metrics()
        # last_heartbeat_at == 0.0 → seconds_since_heartbeat returns None
        engine.check(m)
        names = [a.name for a in engine.recent_alerts]
        assert "no_heartbeat" not in names

    def test_max_history_respected(self):
        engine = AlertEngine(max_history=3)
        m = self._make_metrics()
        m.circuit_state = "OPEN"
        # Force-fire more alerts than max_history by clearing cooldown
        for _ in range(5):
            engine._last_fired.clear()
            engine.check(m)
        assert len(engine.recent_alerts) <= 3


# =============================================================================
# Observability
# =============================================================================


class TestObservability:
    def test_tick_syncs_circuit_state(self):
        obs = Observability()
        # Force circuit to OPEN
        for _ in range(obs.circuit._failure_threshold):
            obs.circuit.record_failure()
        assert obs.circuit.state == "OPEN"
        obs.tick()
        assert obs.metrics.circuit_state == "OPEN"

    def test_tick_runs_alert_checks(self):
        obs = Observability()
        # Inject error spike
        for _ in range(11):
            obs.metrics.record_error()
        obs.tick()
        names = [a.name for a in obs.alerts.recent_alerts]
        assert "error_spike" in names

    def test_tick_with_clean_metrics_no_alerts(self):
        obs = Observability()
        obs.tick()
        assert obs.alerts.recent_alerts == []
