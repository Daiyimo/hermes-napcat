"""
NapCat 群管理命令处理模块。

支持以下管理员命令（群聊中需要 @ 机器人，私聊可直接使用）：
    /mute   @用户 [分钟数]  - 禁言（默认 30 分钟，0 = 解除禁言）
    /ban    @用户 [分钟数]  - /mute 的别名
    /kick   @用户           - 踢出群组
    /status                 - 查看适配器运行状态
    /ping                   - 测量消息延迟
    /help                   - 显示帮助信息

仅允许 NAPCAT_ADMIN_USERS 环境变量中列出的 QQ 号使用。
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

from .constants import (
    API_SET_GROUP_BAN,
    API_SET_GROUP_KICK,
    MSG_TYPE_GROUP,
)
from .utils import OneBotAPIError, api_call

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Admin QQ list
# ---------------------------------------------------------------------------

def _load_admin_list() -> List[str]:
    """Load admin QQ numbers from NAPCAT_ADMIN_USERS environment variable."""
    raw = os.getenv("NAPCAT_ADMIN_USERS", "").strip()
    if not raw:
        return []
    return [qq.strip() for qq in raw.split(",") if qq.strip()]


def is_admin(user_id: str) -> bool:
    """Return True if *user_id* is in the admin list."""
    return user_id in _load_admin_list()


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
        group_id: Optional[str],
        user_id: Optional[str],
        text: str,
        segments: List[Dict[str, Any]],
        event_time: Optional[float] = None,
        self_name: Optional[str] = None,
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_at_target(segments: List[Dict[str, Any]], text: str) -> Optional[str]:
    """Return the first @mentioned QQ number (excluding @all) from segments."""
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
    """Format a seconds count as a human-readable uptime string."""
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
    send_fn,
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

        raw_min = parts[2] if len(parts) > 2 else (parts[1] if len(parts) > 1 and not parts[1].isdigit() else None)
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
        minutes = max(0, min(minutes, 43200))  # 0 ~ 30 days
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
            logger.warning("[NapCat] /mute failed: %s", exc)
            await send_fn(f"❌ 禁言失败: {exc}")
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
            logger.warning("[NapCat] /kick failed: %s", exc)
            await send_fn(f"❌ 踢出失败: {exc}")
        return True

    return False
