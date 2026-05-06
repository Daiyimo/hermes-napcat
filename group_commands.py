"""
NapCat group administration command handler.

Implements a small set of slash commands that administrators can use from
within QQ group chats or private chats with the bot:

    /mute  @user [minutes]   Silence a member (default 30 min; 0 = unsilence)
    /ban   @user [minutes]   Alias for /mute
    /kick  @user             Remove a member from the group
    /status                  Show adapter runtime statistics
    /ping                    Measure round-trip message latency
    /help                    Display the command list

Access is restricted to QQ numbers listed in the ``NAPCAT_ADMIN_USERS``
environment variable (comma-separated).  Non-administrators receive no
response and their messages continue through normal processing.

The module is intentionally side-effect-free at import time so it can be
loaded and tested without a live NapCat connection.
"""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, List, Optional

from .constants import (
    API_SET_GROUP_BAN,
    API_SET_GROUP_KICK,
    MSG_TYPE_GROUP,
    MUTE_MAX_MINUTES,
)
from .utils import OneBotAPIError, api_call

if TYPE_CHECKING:
    from .observability import Observability

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Admin QQ list
# ---------------------------------------------------------------------------


def _load_admin_list() -> List[str]:
    """Read admin QQ numbers from ``NAPCAT_ADMIN_USERS`` environment variable.

    Returns:
        A list of stripped QQ number strings.  Empty list when the variable
        is unset or blank.
    """
    raw = os.getenv("NAPCAT_ADMIN_USERS", "").strip()
    if not raw:
        return []
    return [qq.strip() for qq in raw.split(",") if qq.strip()]


_admin_list_cache: List[str] | None = None


def _get_admin_list() -> List[str]:
    """Return the cached admin list, loading it from the environment on first call.

    The list is cached in the module-level ``_admin_list_cache`` variable so
    the environment variable is only parsed once per process lifetime.  Use
    this function instead of calling :func:`_load_admin_list` directly.
    """
    global _admin_list_cache
    if _admin_list_cache is None:
        _admin_list_cache = _load_admin_list()
    return _admin_list_cache


def is_admin(user_id: str) -> bool:
    """Return ``True`` if *user_id* appears in the admin list.

    Args:
        user_id: The QQ number to check (string, e.g. ``"123456789"``).

    Returns:
        ``True`` when the user is an administrator; ``False`` otherwise
        (including when ``NAPCAT_ADMIN_USERS`` is empty).
    """
    return user_id in _get_admin_list()


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


class AdminCmdContext:
    """Runtime context passed to each command handler."""

    def __init__(
        self,
        http_client: Any,
        http_url: str,
        token: str,
        is_group: bool,
        group_id: str | None,
        user_id: str | None,
        text: str,
        segments: List[Dict[str, Any]],
        event_time: float | None = None,
        self_name: str | None = None,
        obs: Any | None = None,  # Observability instance
    ) -> None:
        self.http_client = http_client
        self.http_url = http_url
        self.token = token
        self.is_group = is_group
        self.group_id = group_id
        self.user_id = user_id
        self.text = text
        self.segments = segments
        self.event_time = event_time  # seconds (from OneBot event.time)
        self.self_name = self_name or "Bot"
        self.obs = obs  # Observability | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_at_target(segments: List[Dict[str, Any]], text: str) -> str | None:
    """Return the first @-mentioned QQ number (excluding @all) from *segments*.

    Checks the structured segment array first; falls back to a CQ-code regex
    scan of *text* for clients that send legacy string-format messages.

    Args:
        segments: OneBot 11 message segment array.
        text: Raw message text (CQ-code fallback).

    Returns:
        The QQ number as a string, or ``None`` if no valid mention was found.
    """
    for seg in segments:
        if seg.get("type") == "at":
            qq = str(seg.get("data", {}).get("qq", ""))
            if qq and qq != "all" and qq.isdigit():
                return qq
    # CQ-code fallback (should not normally happen with array format)
    import re

    m = re.search(r"\[CQ:at,qq=(\d+)\]", text)
    return m.group(1) if m else None


def _format_uptime(seconds: float) -> str:
    """Format a duration in seconds as a human-readable Chinese uptime string.

    Examples::

        _format_uptime(45)      → "45秒"
        _format_uptime(125)     → "2分 5秒"
        _format_uptime(3661)    → "1小时 1分 1秒"
        _format_uptime(90061)   → "1天 1小时 1分"

    Args:
        seconds: Non-negative duration in seconds.

    Returns:
        Localised uptime string in Chinese (天/小时/分/秒).
    """
    s = int(seconds)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if d:
        return f"{d}天 {h}小时 {m}分"
    if h:
        return f"{h}小时 {m}分 {s}秒"
    if m:
        return f"{m}分 {s}秒"
    return f"{s}秒"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

_START_TIME = time.monotonic()


async def handle_group_command(
    cmd: str,
    parts: List[str],
    ctx: AdminCmdContext,
    send_fn: Callable[[str], Awaitable[None]],
) -> bool:
    """Dispatch an admin command.

    Args:
        cmd:     The command string, e.g. ``"/mute"``.
        parts:   The full message text split on whitespace.
        ctx:     Runtime context (HTTP client, group/user IDs, etc.).
        send_fn: ``async (text: str) -> None`` — used to send reply messages.

    Returns:
        ``True`` if the command was recognised and handled; ``False`` to
        continue normal message processing.
    """

    # ── /ping ────────────────────────────────────────────────
    if cmd == "/ping":
        now = time.time()
        latency_ms = int((now - ctx.event_time) * 1000) if ctx.event_time else -1
        latency_str = f"{latency_ms}ms" if latency_ms >= 0 else "未知"
        await send_fn(f"🏓 Pong! 延迟: {latency_str}")
        return True

    # ── /status ──────────────────────────────────────────────
    if cmd == "/status":
        try:
            import resource

            mem_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        except Exception:
            mem_mb = -1
        uptime = _format_uptime(time.monotonic() - _START_TIME)
        mem_str = f"{mem_mb:.1f} MB" if mem_mb >= 0 else "未知"

        obs = ctx.obs
        m = obs.metrics if obs else None

        if m:
            # WS + circuit state
            ws_icon = "✅" if m.ws_connected else "❌"
            cb_state = m.circuit_state
            cb_icon = {"CLOSED": "🟢", "HALF_OPEN": "🟡", "OPEN": "🔴"}.get(cb_state, "❓")

            # counters
            recv = m.messages_received
            sent = m.messages_sent
            failed = m.messages_failed
            errs = m.errors
            dedup = m.dedup_skipped
            reconn = m.reconnects
            cb_cnt = m.circuit_opens

            # latency percentiles
            p50r = m.p50_recv_ms()
            p95r = m.p95_recv_ms()
            p50s = m.p50_send_ms()
            p95s = m.p95_send_ms()
            recv_lat = f"p50={p50r:.0f}ms  p95={p95r:.0f}ms" if p50r is not None else "—"
            send_lat = f"p50={p50s:.0f}ms  p95={p95s:.0f}ms" if p50s is not None else "—"

            # last message ago
            last_at = m.last_message_at
            last_str = (_format_uptime(time.monotonic() - last_at) + "前") if last_at else "—"

            # recent alerts
            alerts = obs.alerts.recent_alerts[-3:]  # last 3
            if alerts:
                alert_lines = "\n".join(
                    f"  [{a.fired_at_str()}] {'⚠️' if a.level == 'WARNING' else '🚨'} {a.name}: {a.message}"
                    for a in reversed(alerts)
                )
            else:
                alert_lines = "  无"

            status_msg = (
                f"[NapCat Adapter] {ctx.self_name}\n"
                f"WS: {ws_icon} {'已连接' if m.ws_connected else '断开'}  |  熔断器: {cb_icon} {cb_state}\n"
                f"运行时长: {uptime}  |  最后消息: {last_str}\n"
                f"内存: {mem_str}\n"
                f"\n──── 消息统计 ────\n"
                f"收到: {recv}  已发: {sent}  失败: {failed}  去重: {dedup}\n"
                f"错误: {errs}  重连: {reconn}  熔断触发: {cb_cnt}\n"
                f"\n──── 延迟（最近{m._recv_latency_ms.maxlen}条）────\n"
                f"接收处理: {recv_lat}\n"
                f"发送耗时: {send_lat}\n"
                f"\n──── 最近告警 ────\n"
                f"{alert_lines}"
            )
        else:
            # Fallback: obs not injected (should not normally happen)
            status_msg = (
                f"[NapCat Adapter] {ctx.self_name}\n"
                f"状态: 已连接\n"
                f"内存: {mem_str}\n"
                f"运行时间: {uptime}"
            )

        await send_fn(status_msg)
        return True

    # ── /help ────────────────────────────────────────────────
    if cmd == "/help":
        help_msg = (
            "[NapCat Adapter] 管理命令\n"
            "/status              - 查看运行状态\n"
            "/ping                - 测量消息延迟\n"
            "/mute @用户 [分钟]    - 禁言（0分钟=解除，默认30分钟）\n"
            "/kick @用户          - 踢出群组\n"
            "/help                - 显示本帮助"
        )
        await send_fn(help_msg)
        return True

    # ── 以下命令只在群聊中有效 ───────────────────────────────
    if not ctx.is_group or not ctx.group_id:
        return False

    # ── /mute /ban ───────────────────────────────────────────
    if cmd in ("/mute", "/ban"):
        target_id = _extract_at_target(ctx.segments, ctx.text)
        if not target_id:
            # Allow numeric QQ as first positional arg as fallback
            target_id = parts[1] if len(parts) > 1 and parts[1].isdigit() else None

        if not target_id:
            await send_fn("用法：/mute @用户 [分钟数]（默认 30 分钟，0 = 解除禁言）")
            return True

        raw_min = (
            parts[2]
            if len(parts) > 2
            else (parts[1] if len(parts) > 1 and not parts[1].isdigit() else None)
        )
        # If no positional match from above, look for a trailing integer
        if raw_min is None:
            for p in reversed(parts[1:]):
                if p.isdigit():
                    raw_min = p
                    break

        try:
            minutes = int(raw_min) if raw_min else 30
        except (ValueError, TypeError):
            minutes = 30
        minutes = max(0, min(minutes, MUTE_MAX_MINUTES))  # 0 ~ 30 days
        duration = minutes * 60

        try:
            await api_call(
                ctx.http_client,
                ctx.http_url,
                API_SET_GROUP_BAN,
                data={
                    "group_id": int(ctx.group_id),
                    "user_id": int(target_id),
                    "duration": duration,
                },
                token=ctx.token,
            )
            if minutes == 0:
                await send_fn(f"✅ 已解除 {target_id} 的禁言。")
            else:
                await send_fn(f"✅ 已禁言 {target_id} {minutes} 分钟。")
        except OneBotAPIError as exc:
            logger.warning("[NapCat] /mute failed: %s", exc)
            await send_fn(f"❌ 禁言失败: {exc.wording or exc.message}")
        except Exception as exc:
            logger.error("[NapCat] /mute unexpected error: %s", exc, exc_info=True)
            await send_fn("❌ 禁言失败（未知错误）")
        return True

    # ── /kick ────────────────────────────────────────────────
    if cmd == "/kick":
        target_id = _extract_at_target(ctx.segments, ctx.text)
        if not target_id:
            target_id = parts[1] if len(parts) > 1 and parts[1].isdigit() else None

        if not target_id:
            await send_fn("用法：/kick @用户")
            return True

        try:
            await api_call(
                ctx.http_client,
                ctx.http_url,
                API_SET_GROUP_KICK,
                data={
                    "group_id": int(ctx.group_id),
                    "user_id": int(target_id),
                    "reject_add_request": False,
                },
                token=ctx.token,
            )
            await send_fn(f"✅ 已踢出 {target_id}。")
        except OneBotAPIError as exc:
            logger.warning("[NapCat] /kick failed: %s", exc)
            await send_fn(f"❌ 踢出失败: {exc.wording or exc.message}")
        except Exception as exc:
            logger.error("[NapCat] /kick unexpected error: %s", exc, exc_info=True)
            await send_fn("❌ 踢出失败（未知错误）")
        return True

    return False
