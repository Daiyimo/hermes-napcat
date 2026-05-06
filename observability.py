"""
hermes-napcat observability module.

Provides three lightweight, zero-dependency building blocks:

* :class:`Metrics`        — structured counters, gauges and latency ring-buffers
* :class:`CircuitBreaker` — three-state FSM protecting outbound API calls
* :class:`AlertEngine`    — threshold-based alert rules with per-rule cooldowns
* :class:`Observability`  — top-level container owned by the adapter

All state is in-process memory.  No external services, no open ports.
Inspect via the ``/status`` admin command.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (imported by adapter / group_commands; defaults defined inline
# so this module stays self-contained for tests)
# ---------------------------------------------------------------------------
# Attempt to read from constants module; fall back to sensible defaults.
try:
    from .constants import (
        ALERT_COOLDOWN_S,
        ALERT_CRITICAL_COOLDOWN_S,
        ALERT_ERROR_SPIKE_THRESHOLD,
        ALERT_NO_HEARTBEAT_S,
        ALERT_RECONNECT_BURST_THRESHOLD,
        ALERT_SEND_FAILURE_RATE_THRESHOLD,
        ALERT_WINDOW_S,
        CB_FAILURE_THRESHOLD,
        CB_HALF_OPEN_PROBE,
        CB_OPEN_TIMEOUT_S,
        CB_SUCCESS_THRESHOLD,
        METRICS_LATENCY_BUFFER,
    )
except ImportError:
    CB_FAILURE_THRESHOLD = 5
    CB_OPEN_TIMEOUT_S = 30.0
    CB_SUCCESS_THRESHOLD = 2
    CB_HALF_OPEN_PROBE = 1
    ALERT_ERROR_SPIKE_THRESHOLD = 10
    ALERT_RECONNECT_BURST_THRESHOLD = 5
    ALERT_SEND_FAILURE_RATE_THRESHOLD = 0.5
    ALERT_NO_HEARTBEAT_S = 90.0
    ALERT_COOLDOWN_S = 120.0
    ALERT_CRITICAL_COOLDOWN_S = 60.0
    METRICS_LATENCY_BUFFER = 50
    ALERT_WINDOW_S = 60.0


# ---------------------------------------------------------------------------
# Alert event
# ---------------------------------------------------------------------------


@dataclass
class AlertEvent:
    """A single fired alert record."""

    name: str
    level: str  # "WARNING" or "CRITICAL"
    message: str
    fired_at: float  # time.monotonic() timestamp

    def age_seconds(self) -> float:
        return time.monotonic() - self.fired_at

    def fired_at_str(self) -> str:
        """Wall-clock string derived from monotonic offset."""
        wall = time.time() - (time.monotonic() - self.fired_at)
        import datetime

        return datetime.datetime.fromtimestamp(wall).strftime("%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Sliding-window counter (used for rate-based alerts)
# ---------------------------------------------------------------------------


class _SlidingWindow:
    """Counts events within a rolling time window.

    Stores a deque of (timestamp, count) tuples.  Entries older than
    *window_seconds* are pruned on each :meth:`add` call.
    """

    def __init__(self, window_seconds: float = ALERT_WINDOW_S) -> None:
        self._window = window_seconds
        self._events: Deque[Tuple[float, int]] = deque()
        self._total: int = 0

    def add(self, count: int = 1) -> None:
        now = time.monotonic()
        self._events.append((now, count))
        self._total += count
        self._prune(now)

    def _prune(self, now: float) -> None:
        cutoff = now - self._window
        while self._events and self._events[0][0] < cutoff:
            _, c = self._events.popleft()
            self._total -= c

    def total(self) -> int:
        self._prune(time.monotonic())
        return max(0, self._total)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class Metrics:
    """Structured metrics store for the NapCat adapter.

    All counters are monotonically increasing.  Latency samples are kept in
    fixed-size deques (ring buffers) of :data:`METRICS_LATENCY_BUFFER` entries.
    """

    def __init__(self) -> None:
        # ---- monotonic counters ----
        self.messages_received: int = 0
        self.messages_sent: int = 0
        self.messages_failed: int = 0
        self.errors: int = 0
        self.dedup_skipped: int = 0
        self.reconnects: int = 0
        self.circuit_opens: int = 0

        # ---- gauges ----
        self.ws_connected: bool = False
        self.circuit_state: str = "CLOSED"

        # ---- latency ring buffers ----
        self._recv_latency_ms: Deque[float] = deque(maxlen=METRICS_LATENCY_BUFFER)
        self._send_latency_ms: Deque[float] = deque(maxlen=METRICS_LATENCY_BUFFER)

        # ---- sliding windows (for alert engine) ----
        self._errors_window = _SlidingWindow(ALERT_WINDOW_S)
        self._reconnect_window = _SlidingWindow(ALERT_WINDOW_S)
        self._send_ok_window = _SlidingWindow(ALERT_WINDOW_S)
        self._send_fail_window = _SlidingWindow(ALERT_WINDOW_S)

        # ---- timestamps ----
        self.started_at: float = time.monotonic()
        self.last_message_at: float = 0.0
        self.last_error_at: float = 0.0
        self.last_send_ok_at: float = 0.0
        self.last_heartbeat_at: float = 0.0

    # ------------------------------------------------------------------ #
    # Recording helpers                                                    #
    # ------------------------------------------------------------------ #

    def record_recv_latency(self, ms: float) -> None:
        """Record a single receive-to-process latency sample in milliseconds."""
        self._recv_latency_ms.append(ms)

    def record_send_latency(self, ms: float) -> None:
        """Record a single send-API-call latency sample in milliseconds."""
        self._send_latency_ms.append(ms)

    def record_error(self) -> None:
        """Increment the error counter and update the sliding window."""
        self.errors += 1
        self.last_error_at = time.monotonic()
        self._errors_window.add()

    def record_reconnect(self) -> None:
        """Increment reconnect counter and update the sliding window."""
        self.reconnects += 1
        self._reconnect_window.add()

    def record_send_ok(self) -> None:
        """Record a successful send."""
        self.messages_sent += 1
        self.last_send_ok_at = time.monotonic()
        self._send_ok_window.add()

    def record_send_fail(self) -> None:
        """Record a failed send."""
        self.messages_failed += 1
        self._send_fail_window.add()

    def record_heartbeat(self) -> None:
        """Update the last-heartbeat timestamp."""
        self.last_heartbeat_at = time.monotonic()

    # ------------------------------------------------------------------ #
    # Derived values                                                       #
    # ------------------------------------------------------------------ #

    def uptime_seconds(self) -> float:
        """Seconds since the Metrics object was created."""
        return time.monotonic() - self.started_at

    @staticmethod
    def _percentile(samples: Deque[float], pct: float) -> float | None:
        if not samples:
            return None
        sorted_s = sorted(samples)
        idx = max(0, int(len(sorted_s) * pct / 100) - 1)
        return sorted_s[idx]

    def p50_recv_ms(self) -> float | None:
        """p50 receive-latency in ms, or None if no samples."""
        return self._percentile(self._recv_latency_ms, 50)

    def p95_recv_ms(self) -> float | None:
        """p95 receive-latency in ms, or None if no samples."""
        return self._percentile(self._recv_latency_ms, 95)

    def p50_send_ms(self) -> float | None:
        """p50 send-latency in ms, or None if no samples."""
        return self._percentile(self._send_latency_ms, 50)

    def p95_send_ms(self) -> float | None:
        """p95 send-latency in ms, or None if no samples."""
        return self._percentile(self._send_latency_ms, 95)

    def errors_in_window(self) -> int:
        """Errors recorded within the last :data:`ALERT_WINDOW_S` seconds."""
        return self._errors_window.total()

    def reconnects_in_window(self) -> int:
        """Reconnects within the last :data:`ALERT_WINDOW_S` seconds."""
        return self._reconnect_window.total()

    def send_failure_rate_in_window(self) -> float:
        """Fraction of sends that failed within the last window (0.0 – 1.0)."""
        ok = self._send_ok_window.total()
        fail = self._send_fail_window.total()
        total = ok + fail
        return (fail / total) if total > 0 else 0.0

    def seconds_since_heartbeat(self) -> float | None:
        """Seconds since the last heartbeat, or None if no heartbeat seen yet."""
        if self.last_heartbeat_at == 0.0:
            return None
        return time.monotonic() - self.last_heartbeat_at


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------

_CB_CLOSED = "CLOSED"
_CB_OPEN = "OPEN"
_CB_HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """Three-state circuit breaker protecting outbound HTTP API calls.

    States
    ------
    CLOSED
        Normal operation.  Failures are counted; when *failure_threshold*
        consecutive failures occur the breaker trips to OPEN.

    OPEN
        Fast-fail mode.  All requests are rejected immediately without
        making a network call.  After *open_timeout_s* seconds the breaker
        moves to HALF_OPEN.

    HALF_OPEN
        Recovery probe mode.  Up to *half_open_probe* requests are allowed
        through.  On *success_threshold* consecutive successes the breaker
        returns to CLOSED; a single failure resets back to OPEN.
    """

    def __init__(
        self,
        failure_threshold: int = CB_FAILURE_THRESHOLD,
        open_timeout_s: float = CB_OPEN_TIMEOUT_S,
        success_threshold: int = CB_SUCCESS_THRESHOLD,
        half_open_probe: int = CB_HALF_OPEN_PROBE,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._open_timeout_s = open_timeout_s
        self._success_threshold = success_threshold
        self._half_open_probe = half_open_probe

        self._state: str = _CB_CLOSED
        self._consecutive_failures: int = 0
        self._consecutive_successes: int = 0
        self._probes_sent: int = 0
        self._opened_at: float = 0.0

    @property
    def state(self) -> str:
        """Current state string: ``"CLOSED"``, ``"OPEN"``, or ``"HALF_OPEN"``."""
        return self._state

    def allow_request(self) -> bool:
        """Return ``True`` when the caller may proceed with the request.

        Side-effects
        ------------
        * OPEN → HALF_OPEN transition when the open timeout has elapsed.
        * Increments the HALF_OPEN probe counter.
        """
        if self._state == _CB_CLOSED:
            return True

        if self._state == _CB_OPEN:
            if time.monotonic() - self._opened_at >= self._open_timeout_s:
                self._transition(_CB_HALF_OPEN)
                self._probes_sent = 0
                return self._try_probe()
            return False  # still open

        # HALF_OPEN
        return self._try_probe()

    def _try_probe(self) -> bool:
        if self._probes_sent < self._half_open_probe:
            self._probes_sent += 1
            return True
        return False

    def record_success(self) -> None:
        """Report a successful request outcome."""
        if self._state == _CB_HALF_OPEN:
            self._consecutive_successes += 1
            if self._consecutive_successes >= self._success_threshold:
                self._transition(_CB_CLOSED)
        elif self._state == _CB_CLOSED:
            self._consecutive_failures = 0

    def record_failure(self) -> None:
        """Report a failed request outcome (may trip the breaker)."""
        if self._state == _CB_HALF_OPEN:
            # Any failure in probe mode re-opens the breaker
            self._transition(_CB_OPEN)
            return

        if self._state == _CB_CLOSED:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._failure_threshold:
                self._transition(_CB_OPEN)

    def _transition(self, new_state: str) -> None:
        if new_state == self._state:
            return
        old = self._state
        self._state = new_state
        if new_state == _CB_OPEN:
            self._opened_at = time.monotonic()
            self._consecutive_successes = 0
        elif new_state == _CB_CLOSED:
            self._consecutive_failures = 0
            self._consecutive_successes = 0
        elif new_state == _CB_HALF_OPEN:
            self._consecutive_successes = 0
            self._probes_sent = 0
        logger.info("CircuitBreaker: %s → %s", old, new_state)


# ---------------------------------------------------------------------------
# Alert Engine
# ---------------------------------------------------------------------------


class AlertEngine:
    """Rule-based alert engine with per-rule cooldowns.

    Rules are evaluated by :meth:`check` which is called periodically by the
    adapter's ``_alert_loop``.  Fired alerts are logged at WARNING/CRITICAL
    level **and** stored in a ring buffer for display via the ``/status`` command.
    """

    def __init__(self, max_history: int = 20) -> None:
        self._history: Deque[AlertEvent] = deque(maxlen=max_history)
        # name → last-fired monotonic timestamp
        self._last_fired: Dict[str, float] = {}

    @property
    def recent_alerts(self) -> List[AlertEvent]:
        """Most-recent alerts, newest last."""
        return list(self._history)

    def check(self, metrics: Metrics) -> None:
        """Evaluate all rules against current *metrics*.

        Call this every 30 seconds from the adapter's alert loop.
        """
        self._rule_error_spike(metrics)
        self._rule_circuit_open(metrics)
        self._rule_reconnect_burst(metrics)
        self._rule_send_failure_rate(metrics)
        self._rule_no_heartbeat(metrics)

    # ------------------------------------------------------------------ #
    # Rules                                                                #
    # ------------------------------------------------------------------ #

    def _rule_error_spike(self, m: Metrics) -> None:
        count = m.errors_in_window()
        if count >= ALERT_ERROR_SPIKE_THRESHOLD:
            self._fire(
                "error_spike",
                "WARNING",
                f"{ALERT_WINDOW_S:.0f}s内错误数达到{count}次 (阈值={ALERT_ERROR_SPIKE_THRESHOLD})",
                cooldown=ALERT_COOLDOWN_S,
            )

    def _rule_circuit_open(self, m: Metrics) -> None:
        if m.circuit_state == "OPEN":
            self._fire(
                "circuit_open",
                "CRITICAL",
                "熔断器已打开，发送API调用被快速失败",
                cooldown=ALERT_CRITICAL_COOLDOWN_S,
            )

    def _rule_reconnect_burst(self, m: Metrics) -> None:
        count = m.reconnects_in_window()
        if count >= ALERT_RECONNECT_BURST_THRESHOLD:
            self._fire(
                "ws_reconnect_burst",
                "WARNING",
                f"{ALERT_WINDOW_S:.0f}s内WebSocket重连{count}次 (阈值={ALERT_RECONNECT_BURST_THRESHOLD})",
                cooldown=ALERT_COOLDOWN_S,
            )

    def _rule_send_failure_rate(self, m: Metrics) -> None:
        rate = m.send_failure_rate_in_window()
        if rate >= ALERT_SEND_FAILURE_RATE_THRESHOLD:
            pct = int(rate * 100)
            self._fire(
                "send_failure_rate",
                "WARNING",
                f"{ALERT_WINDOW_S:.0f}s内发送失败率{pct}% (阈值={int(ALERT_SEND_FAILURE_RATE_THRESHOLD * 100)}%)",
                cooldown=ALERT_COOLDOWN_S,
            )

    def _rule_no_heartbeat(self, m: Metrics) -> None:
        secs = m.seconds_since_heartbeat()
        # Only fire if we have seen at least one heartbeat before
        if secs is not None and secs >= ALERT_NO_HEARTBEAT_S:
            self._fire(
                "no_heartbeat",
                "WARNING",
                f"{secs:.0f}s未收到NapCat心跳 (阈值={ALERT_NO_HEARTBEAT_S:.0f}s)",
                cooldown=ALERT_CRITICAL_COOLDOWN_S,
            )

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _fire(self, name: str, level: str, message: str, cooldown: float) -> None:
        now = time.monotonic()
        last = self._last_fired.get(name, 0.0)
        if now - last < cooldown:
            return  # still in cooldown

        self._last_fired[name] = now
        event = AlertEvent(name=name, level=level, message=message, fired_at=now)
        self._history.append(event)

        emoji = "🚨" if level == "CRITICAL" else "⚠️"
        logger.warning("[ALERT][%s] %s %s: %s", level, emoji, name, message)


# ---------------------------------------------------------------------------
# Top-level container
# ---------------------------------------------------------------------------


class Observability:
    """Top-level observability container owned by :class:`NapCatAdapter`.

    Usage in adapter::

        self._obs = Observability()
        # on send success:
        self._obs.metrics.record_send_ok()
        # on send fail:
        self._obs.circuit.record_failure()
        # periodic tick (every 30 s):
        self._obs.tick()
    """

    def __init__(self) -> None:
        self.metrics = Metrics()
        self.circuit = CircuitBreaker()
        self.alerts = AlertEngine()

    def tick(self) -> None:
        """Drive the alert engine and sync circuit state to metrics.

        Call every ``ALERT_TICK_INTERVAL_S`` seconds from the adapter's
        ``_alert_loop`` background task.
        """
        self.metrics.circuit_state = self.circuit.state
        self.alerts.check(self.metrics)
