"""
NapCat platform adapter.

Connects to a NapCat instance via Forward WebSocket (receive events) and
HTTP POST (send API calls) using the OneBot 11 protocol.

Configuration via environment variables:
    NAPCAT_HTTP_URL       — NapCat HTTP API URL (e.g. http://127.0.0.1:3000)
    NAPCAT_WS_URL         — NapCat WebSocket URL (e.g. ws://127.0.0.1:3001)
    NAPCAT_TOKEN          — Optional Bearer token for authentication
    NAPCAT_ADMIN_USERS    — Comma-separated QQ numbers allowed to use admin commands
    NAPCAT_REQUIRE_MENTION — Set to "true" to require @mention in group chats (default: true)
    NAPCAT_ENABLE_REACTIONS — Set to "false" to disable emoji reactions (default: true)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    import websockets
    import websockets.client

    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    websockets = None  # type: ignore[assignment]

try:
    import httpx

    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    httpx = None  # type: ignore[assignment]

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import (
    BasePlatformAdapter,
    MessageEvent,
    MessageType,
    SendResult,
    cache_image_from_url,
    cache_audio_from_url,
    cache_document_from_bytes,
)

from .constants import (
    API_TIMEOUT,
    API_DELETE_MSG,
    API_GET_FORWARD_MSG,
    API_GET_GROUP_INFO,
    API_GET_LOGIN_INFO,
    API_GET_STRANGER_INFO,
    API_SEND_MSG,
    API_SET_MSG_EMOJI_LIKE,
    DEDUP_MAX_SIZE,
    DEDUP_WINDOW_SECONDS,
    HEARTBEAT_INTERVAL,
    MAX_MESSAGE_LENGTH,
    MEDIA_DOWNLOAD_TIMEOUT,
    META_EVENT_HEARTBEAT,
    META_EVENT_LIFECYCLE,
    MSG_TYPE_GROUP,
    MSG_TYPE_PRIVATE,
    POST_TYPE_MESSAGE,
    POST_TYPE_MESSAGE_SENT,
    POST_TYPE_META_EVENT,
    POST_TYPE_NOTICE,
    POST_TYPE_REQUEST,
    RECONNECT_BACKOFF_BASE,
    RECONNECT_JITTER,
    RECONNECT_MAX_ATTEMPTS,
    RECONNECT_MAX_BACKOFF,
    RESP_RETCODE_OK,
    SEG_TEXT,
    WS_CLOSE_TIMEOUT,
    WS_CONNECT_TIMEOUT,
    WS_PING_INTERVAL,
    WS_PING_TIMEOUT,
)
from .event_parser import (
    check_at_bot,
    extract_forward_ids,
    extract_forward_text,
    extract_reply_id,
    parse_message_segments,
)
from .message_builder import (
    _local_file_uri,
    build_document_message,
    build_image_message,
    build_mixed_message,
    build_reply_message,
    build_text_message,
    build_video_message,
    build_voice_message,
)
from .utils import OneBotAPIError, api_call
from .group_commands import AdminCmdContext, handle_group_command, is_admin

logger = logging.getLogger(__name__)


def check_napcat_requirements() -> bool:
    """Check whether NapCat runtime dependencies are satisfied."""
    if not WEBSOCKETS_AVAILABLE:
        return False
    if not HTTPX_AVAILABLE:
        return False
    # At least the HTTP URL must be configured
    http_url = os.getenv("NAPCAT_HTTP_URL", "")
    ws_url = os.getenv("NAPCAT_WS_URL", "")
    return bool(http_url and ws_url)


class NapCatAdapter(BasePlatformAdapter):
    """NapCat adapter using OneBot 11 Forward-WS (events) + HTTP API (actions)."""

    SUPPORTS_MESSAGE_EDITING = False
    MAX_MESSAGE_LENGTH = MAX_MESSAGE_LENGTH

    @property
    def _log_tag(self) -> str:
        self_id = getattr(self, "_self_id", None)
        if self_id:
            return f"NapCat:{self_id}"
        return "NapCat"

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def __init__(self, config: PlatformConfig):
        super().__init__(config, Platform.NAPCAT)

        extra = config.extra or {}
        self._http_url: str = str(
            extra.get("http_url") or os.getenv("NAPCAT_HTTP_URL", "")
        ).strip().rstrip("/")
        self._ws_url: str = str(
            extra.get("ws_url") or os.getenv("NAPCAT_WS_URL", "")
        ).strip().rstrip("/")
        self._token: str = str(
            config.token or extra.get("token") or os.getenv("NAPCAT_TOKEN", "")
        ).strip()

        # Bot's own QQ number — populated during connect via /get_login_info
        self._self_id: Optional[str] = None
        self._self_name: Optional[str] = None

        # Connection state
        self._ws: Any = None  # websockets connection
        self._http_client: Any = None  # httpx.AsyncClient
        self._listen_task: Optional[asyncio.Task] = None

        # Message deduplication
        self._seen_messages: Dict[str, float] = {}

        # Chat type tracking: chat_id → "private" | "group"
        self._chat_type_map: Dict[str, str] = {}

        # Feature flags
        # require_mention: whether group messages require @bot to trigger (default True)
        _require_mention_env = os.getenv("NAPCAT_REQUIRE_MENTION", "true").strip().lower()
        self._require_mention: bool = _require_mention_env not in ("false", "0", "no")
        # enable_reactions: auto emoji reaction on incoming messages (default True)
        _reactions_env = os.getenv("NAPCAT_ENABLE_REACTIONS", "true").strip().lower()
        self._enable_reactions: bool = _reactions_env not in ("false", "0", "no")

    @property
    def name(self) -> str:
        return "NapCat"

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Connect to NapCat WS server and prepare HTTP client."""
        if not WEBSOCKETS_AVAILABLE:
            msg = "NapCat startup failed: websockets not installed"
            self._set_fatal_error("napcat_missing_dep", msg, retryable=True)
            logger.warning("[%s] %s. Run: pip install websockets", self._log_tag, msg)
            return False

        if not HTTPX_AVAILABLE:
            msg = "NapCat startup failed: httpx not installed"
            self._set_fatal_error("napcat_missing_dep", msg, retryable=True)
            logger.warning("[%s] %s. Run: pip install httpx", self._log_tag, msg)
            return False

        if not self._http_url:
            msg = "NapCat startup failed: NAPCAT_HTTP_URL is required"
            self._set_fatal_error("napcat_missing_config", msg, retryable=True)
            logger.warning("[%s] %s", self._log_tag, msg)
            return False

        if not self._ws_url:
            msg = "NapCat startup failed: NAPCAT_WS_URL is required"
            self._set_fatal_error("napcat_missing_config", msg, retryable=True)
            logger.warning("[%s] %s", self._log_tag, msg)
            return False

        # Prevent duplicate connections
        if not self._acquire_platform_lock("napcat-url", self._http_url, "NapCat HTTP URL"):
            return False

        try:
            # 1. Create HTTP client
            self._http_client = httpx.AsyncClient(
                timeout=API_TIMEOUT,
                follow_redirects=True,
            )

            # 2. Get bot info via HTTP API
            try:
                login_info = await api_call(
                    self._http_client,
                    self._http_url,
                    API_GET_LOGIN_INFO,
                    token=self._token,
                )
                self._self_id = str(login_info.get("user_id", ""))
                self._self_name = login_info.get("nickname", "")
                logger.info(
                    "[%s] Bot login info: QQ=%s name=%s",
                    self._log_tag,
                    self._self_id,
                    self._self_name,
                )
            except Exception as exc:
                logger.warning(
                    "[%s] Could not fetch login info: %s (will proceed anyway)",
                    self._log_tag,
                    exc,
                )

            # 3. Start WS listener task (handles reconnection internally)
            self._listen_task = asyncio.create_task(
                self._ws_listen_loop(), name=f"napcat-ws-{self._self_id or 'unknown'}"
            )

            self._mark_connected()
            logger.info(
                "[%s] Connected — HTTP=%s WS=%s",
                self._log_tag,
                self._http_url,
                self._ws_url,
            )
            return True

        except Exception as exc:
            msg = f"NapCat startup failed: {exc}"
            self._set_fatal_error("napcat_connect_error", msg, retryable=True)
            logger.error("[%s] %s", self._log_tag, msg, exc_info=True)
            # Clean up partial state
            if self._http_client:
                await self._http_client.aclose()
                self._http_client = None
            return False

    async def disconnect(self) -> None:
        """Close all connections and stop listeners."""
        self._running = False
        self._mark_disconnected()

        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        if self._http_client:
            try:
                await self._http_client.aclose()
            except Exception:
                pass
            self._http_client = None

        logger.info("[%s] Disconnected", self._log_tag)

    # ------------------------------------------------------------------
    # WebSocket event loop with reconnection
    # ------------------------------------------------------------------

    async def _ws_listen_loop(self) -> None:
        """Connect to NapCat WS server and listen for events.

        Reconnects automatically with exponential backoff + jitter on
        failures.
        """
        attempt = 0

        while self._running:
            try:
                extra_headers = {}
                if self._token:
                    extra_headers["Authorization"] = f"Bearer {self._token}"

                self._ws = await websockets.client.connect(
                    self._ws_url,
                    open_timeout=WS_CONNECT_TIMEOUT,
                    ping_interval=WS_PING_INTERVAL,
                    ping_timeout=WS_PING_TIMEOUT,
                    close_timeout=WS_CLOSE_TIMEOUT,
                    additional_headers=extra_headers,
                )

                attempt = 0  # reset backoff on successful connect
                logger.info("[%s] WebSocket connected to %s", self._log_tag, self._ws_url)

                async for raw_msg in self._ws:
                    if not self._running:
                        break
                    try:
                        data = json.loads(raw_msg)
                        await self._dispatch_event(data)
                    except json.JSONDecodeError:
                        logger.warning("[%s] Non-JSON WS message: %.200s", self._log_tag, raw_msg)
                    except Exception as exc:
                        logger.error(
                            "[%s] Error dispatching event: %s",
                            self._log_tag,
                            exc,
                            exc_info=True,
                        )

            except asyncio.CancelledError:
                logger.debug("[%s] WS listen task cancelled", self._log_tag)
                return
            except Exception as exc:
                if not self._running:
                    return
                attempt += 1
                if attempt > RECONNECT_MAX_ATTEMPTS:
                    msg = f"Exceeded max reconnect attempts ({RECONNECT_MAX_ATTEMPTS})"
                    self._set_fatal_error("napcat_reconnect_exhausted", msg, retryable=True)
                    logger.error("[%s] %s — giving up", self._log_tag, msg)
                    return

                backoff = min(
                    RECONNECT_BACKOFF_BASE * (2 ** (attempt - 1)),
                    RECONNECT_MAX_BACKOFF,
                )
                jitter = backoff * RECONNECT_JITTER * (2 * random.random() - 1)
                wait = max(0.5, backoff + jitter)

                logger.warning(
                    "[%s] WS disconnected (%s), reconnecting in %.1fs (attempt %d/%d)",
                    self._log_tag,
                    exc,
                    wait,
                    attempt,
                    RECONNECT_MAX_ATTEMPTS,
                )
                await asyncio.sleep(wait)
            finally:
                self._ws = None

    # ------------------------------------------------------------------
    # Event dispatch
    # ------------------------------------------------------------------

    async def _dispatch_event(self, data: Dict[str, Any]) -> None:
        """Route an incoming OneBot 11 event to the appropriate handler."""
        post_type = data.get("post_type", "")

        if post_type == POST_TYPE_MESSAGE:
            await self._handle_message_event(data)
        elif post_type == POST_TYPE_MESSAGE_SENT:
            # Self-sent messages — ignore by default
            logger.debug("[%s] Ignoring self-sent message", self._log_tag)
        elif post_type == POST_TYPE_META_EVENT:
            self._handle_meta_event(data)
        elif post_type == POST_TYPE_NOTICE:
            logger.debug("[%s] Notice event: %s", self._log_tag, data.get("notice_type", ""))
        elif post_type == POST_TYPE_REQUEST:
            logger.debug("[%s] Request event: %s", self._log_tag, data.get("request_type", ""))
        else:
            logger.debug("[%s] Unknown post_type: %s", self._log_tag, post_type)

    def _handle_meta_event(self, data: Dict[str, Any]) -> None:
        """Handle meta_event (heartbeat, lifecycle)."""
        meta_type = data.get("meta_event_type", "")
        if meta_type == META_EVENT_HEARTBEAT:
            logger.debug("[%s] Heartbeat received", self._log_tag)
        elif meta_type == META_EVENT_LIFECYCLE:
            sub_type = data.get("sub_type", "")
            logger.info("[%s] Lifecycle event: %s", self._log_tag, sub_type)
            # Update self_id if provided in lifecycle connect
            if "self_id" in data:
                self._self_id = str(data["self_id"])
        else:
            logger.debug("[%s] Meta event: %s", self._log_tag, meta_type)

    # ------------------------------------------------------------------
    # Incoming message handling
    # ------------------------------------------------------------------

    async def _handle_message_event(self, data: Dict[str, Any]) -> None:
        """Process an incoming message event from OneBot 11."""
        message_id = str(data.get("message_id", ""))
        user_id = str(data.get("user_id", ""))
        message_type = data.get("message_type", "")

        # Filter own messages
        if self._self_id and user_id == self._self_id:
            logger.debug("[%s] Ignoring self message %s", self._log_tag, message_id)
            return

        # Deduplication
        if not self._dedup_check(message_id):
            return

        # Extract sender info
        sender = data.get("sender") or {}
        user_name = sender.get("card") or sender.get("nickname") or user_id

        # Determine chat identity
        if message_type == MSG_TYPE_GROUP:
            group_id = str(data.get("group_id", ""))
            chat_id = group_id
            chat_type = "group"
        else:
            chat_id = user_id
            chat_type = "dm"

        # Track chat type for sends
        self._chat_type_map[chat_id] = message_type

        # Parse message segments
        segments = data.get("message", [])
        if isinstance(segments, str):
            # CQ-code string fallback (shouldn't happen with array format)
            text = segments
            media_list = []
            forward_ids: List[str] = []
        else:
            forward_ids = extract_forward_ids(segments)
            text = ""  # populated below after forward expansion
            media_list = []

        # ------------------------------------------------------------------
        # AT-trigger check (group only)
        # ------------------------------------------------------------------
        is_group = (message_type == MSG_TYPE_GROUP)
        if is_group and self._require_mention:
            if not isinstance(segments, list) or not check_at_bot(segments, self._self_id or ""):
                logger.debug(
                    "[%s] Group message %s not @bot — skipping",
                    self._log_tag,
                    message_id,
                )
                return

        # ------------------------------------------------------------------
        # Expand forward (合并转发) messages via get_forward_msg API
        # ------------------------------------------------------------------
        forward_texts: Dict[str, str] = {}
        if forward_ids and self._http_client:
            for fid in forward_ids:
                try:
                    fwd_data = await api_call(
                        self._http_client,
                        self._http_url,
                        API_GET_FORWARD_MSG,
                        # NapCat 4.18.1 accepts both "id" and "message_id"
                        data={"id": fid, "message_id": fid},
                        token=self._token,
                    )
                    forward_texts[fid] = extract_forward_text(fwd_data)
                    logger.debug(
                        "[%s] Expanded forward %s: %d chars",
                        self._log_tag,
                        fid,
                        len(forward_texts[fid]),
                    )
                except Exception as exc:
                    logger.warning(
                        "[%s] Failed to expand forward msg %s: %s",
                        self._log_tag,
                        fid,
                        exc,
                    )
                    forward_texts[fid] = "[转发消息: 获取失败]"

        # ------------------------------------------------------------------
        # Parse segments (now with forward texts)
        # ------------------------------------------------------------------
        if isinstance(segments, list):
            text, media_list = parse_message_segments(segments, forward_texts=forward_texts)

        # Extract reply context
        reply_to_id = extract_reply_id(segments if isinstance(segments, list) else [])

        # ------------------------------------------------------------------
        # Admin command handling (must happen before handle_message)
        # ------------------------------------------------------------------
        user_is_admin = is_admin(user_id)
        if user_is_admin and isinstance(text, str) and text.strip().startswith("/"):
            parts = text.strip().split()
            cmd = parts[0].lower() if parts else ""

            # In groups, admin commands require @bot (already checked above)
            # In private chat, allow without @mention
            async def _reply_admin(msg: str) -> None:
                await self._send_segments(
                    chat_id,
                    [{"type": "text", "data": {"text": msg}}],
                )

            ctx = AdminCmdContext(
                http_client=self._http_client,
                http_url=self._http_url,
                token=self._token,
                is_group=is_group,
                group_id=chat_id if is_group else None,
                user_id=user_id,
                text=text,
                segments=segments if isinstance(segments, list) else [],
                event_time=data.get("time"),
                self_name=self._self_name,
            )
            handled = await handle_group_command(cmd, parts, ctx, _reply_admin)
            if handled:
                return

        # ------------------------------------------------------------------
        # Emoji reaction (贴表情回应)
        # ------------------------------------------------------------------
        if self._enable_reactions and message_id and self._http_client:
            asyncio.create_task(self._send_emoji_reaction(message_id, text))

        # ------------------------------------------------------------------
        # Download and cache media
        # ------------------------------------------------------------------
        media_urls: List[str] = []
        media_types: List[str] = []

        for media in media_list:
            try:
                url = media["url"]
                m_type = media["type"]
                ext = media.get("ext", "")
                is_local = media.get("is_local", False)

                if m_type == "image":
                    if is_local:
                        cached = await self._cache_local_file(url, ext=ext or ".jpg")
                    else:
                        cached = await cache_image_from_url(url, ext=ext or ".jpg")
                    if cached:
                        media_urls.append(cached)
                        media_types.append("image")
                elif m_type == "audio":
                    if is_local:
                        cached = await self._cache_local_file(url, ext=ext or ".ogg")
                    else:
                        cached = await cache_audio_from_url(url, ext=ext or ".ogg")
                    if cached:
                        media_urls.append(cached)
                        media_types.append("audio")
                elif m_type in ("video", "document"):
                    if is_local:
                        cached = await self._cache_local_file(url, ext=ext)
                    else:
                        cached = await self._download_to_cache(url, ext=ext)
                    if cached:
                        media_urls.append(cached)
                        media_types.append(m_type)
            except Exception as exc:
                logger.warning("[%s] Failed to cache media: %s", self._log_tag, exc)

        # Determine message type
        if media_urls:
            if any(t == "image" for t in media_types):
                msg_type = MessageType.PHOTO
            elif any(t == "audio" for t in media_types):
                msg_type = MessageType.AUDIO
            elif any(t == "video" for t in media_types):
                msg_type = MessageType.VIDEO
            else:
                msg_type = MessageType.DOCUMENT
        elif text:
            msg_type = MessageType.TEXT
        elif media_list:
            # All media downloads failed but the message had media —
            # fall back to text-only with a placeholder so the message
            # isn't silently dropped.
            msg_type = MessageType.TEXT
            failed_types = ", ".join(sorted({m["type"] for m in media_list}))
            text = text or f"[媒体消息: {failed_types} 下载失败]"
            logger.warning(
                "[%s] All media downloads failed for msg %s (types: %s) — falling back to text",
                self._log_tag, message_id, failed_types,
            )
        else:
            logger.debug("[%s] Empty message %s — skipping", self._log_tag, message_id)
            return

        # Build source
        source = self.build_source(
            chat_id=chat_id,
            chat_type=chat_type,
            user_id=user_id,
            user_name=user_name,
            message_id=message_id,
        )

        # Build event
        event = MessageEvent(
            text=text,
            message_type=msg_type,
            source=source,
            raw_message=data,
            message_id=message_id,
            media_urls=media_urls,
            media_types=media_types,
            reply_to_message_id=reply_to_id,
        )

        logger.info(
            "[%s] Message from %s in %s:%s — %s%.50s",
            self._log_tag,
            user_name,
            chat_type,
            chat_id,
            f"[{msg_type.value}] " if msg_type != MessageType.TEXT else "",
            text,
        )

        await self.handle_message(event)

    # ------------------------------------------------------------------
    # Emoji reaction helper
    # ------------------------------------------------------------------

    # Mapping: regex keyword → NapCat emoji ID
    _REACTION_RULES: List[tuple] = [
        (r"查找|查询|搜索|检查|检测|查看|打开|获取|看看|找|搜", "124"),
        (r"好的|收到|确认|明白|了解|知道了|没问题|[Oo][Kk]", "76"),
        (r"谢谢|感谢|谢了|多谢|感激", "297"),
        (r"加油|继续|努力|坚持|棒|厉害|牛|强", "315"),
        (r"哈哈|开心|高兴|快乐|好玩|有趣|笑|嘻嘻", "99"),
        (r"难过|悲伤|伤心|哭|呜|唉|可怜|失落", "5"),
        (r"生气|愤怒|气死|烦死|滚|讨厌|恼火", "326"),
        (r"[?？]|为什么|怎么|啥|什么|不懂|不明白|疑问", "32"),
        (r"哇|惊|震惊|不会吧|真的吗|卧槽|天啊|没想到", "180"),
        (r"喜欢|爱你|心动|可爱|萌", "66"),
        (r"你好|早上好|晚安|嗨|[Hh]i|[Hh]ello|[Hh]ey", "14"),
        (r"帮|请|麻烦|劳烦|能不能|可以吗|求", "118"),
        (r"吃|饿|饭|食物|喝|美食", "53"),
        (r"睡|困|累|休息|倦", "8"),
    ]
    _DEFAULT_REACTION = "307"  # 喵喵

    async def _send_emoji_reaction(self, message_id: str, text: str) -> None:
        """Send an auto emoji reaction based on message content keywords.

        Runs as a fire-and-forget background task — failures are silently
        logged and never surface to the caller.
        """
        import re as _re
        try:
            emoji_id = self._DEFAULT_REACTION
            for pattern, eid in self._REACTION_RULES:
                if _re.search(pattern, text):
                    emoji_id = eid
                    break

            await api_call(
                self._http_client,
                self._http_url,
                API_SET_MSG_EMOJI_LIKE,
                data={
                    "message_id": int(message_id),
                    "emoji_id": emoji_id,
                    "set": True,
                },
                token=self._token,
            )
            logger.debug(
                "[%s] Emoji reaction %s sent for msg %s",
                self._log_tag,
                emoji_id,
                message_id,
            )
        except Exception as exc:
            logger.debug("[%s] Emoji reaction failed: %s", self._log_tag, exc)

    def _dedup_check(self, message_id: str) -> bool:
        """Return True if *message_id* has not been seen recently."""
        if not message_id:
            return True  # no ID — can't dedup
        now = time.monotonic()

        # Evict stale entries
        if len(self._seen_messages) > DEDUP_MAX_SIZE:
            cutoff = now - DEDUP_WINDOW_SECONDS
            self._seen_messages = {
                k: v for k, v in self._seen_messages.items() if v > cutoff
            }

        if message_id in self._seen_messages:
            logger.debug("[%s] Duplicate message %s — skipping", self._log_tag, message_id)
            return False

        self._seen_messages[message_id] = now
        return True

    async def _cache_local_file(self, path: str, ext: str = "") -> Optional[str]:
        """Copy a local file into the Hermes cache directory.

        Used when NapCat has already downloaded the media to a local path
        (``data.file`` or ``data.path`` is an absolute filesystem path).
        Returns the cached file path, or the original *path* if it already
        lives inside the cache dir.  Returns ``None`` on failure.
        """
        import shutil
        import uuid
        from pathlib import Path

        try:
            src = Path(path)
            if not src.exists():
                logger.warning("[%s] Local media file not found: %s", self._log_tag, path)
                return None

            if not ext:
                ext = src.suffix or ".bin"

            cache_dir = Path(os.environ.get("HERMES_CACHE_DIR", "/tmp/hermes_cache")) / "downloads"
            cache_dir.mkdir(parents=True, exist_ok=True)

            # If already in cache dir, use as-is
            try:
                src.relative_to(cache_dir)
                return str(src)
            except ValueError:
                pass

            filename = f"napcat_{uuid.uuid4().hex[:12]}{ext}"
            dest = cache_dir / filename
            shutil.copy2(src, dest)
            return str(dest)
        except Exception as exc:
            logger.warning("[%s] Failed to cache local file %s: %s", self._log_tag, path, exc)
            return None

    async def _download_to_cache(self, url: str, ext: str = "") -> Optional[str]:
        """Download a file from *url* to the cache directory.

        Returns the cached file path, or ``None`` on failure.
        """
        import uuid
        from pathlib import Path

        try:
            if not self._http_client:
                return None
            resp = await self._http_client.get(url, timeout=MEDIA_DOWNLOAD_TIMEOUT)
            resp.raise_for_status()
            data = resp.content

            if not ext:
                ct = resp.headers.get("content-type", "")
                if "video" in ct:
                    ext = ".mp4"
                elif "audio" in ct:
                    ext = ".ogg"
                else:
                    ext = ".bin"

            cache_dir = Path(os.environ.get("HERMES_CACHE_DIR", "/tmp/hermes_cache")) / "downloads"
            cache_dir.mkdir(parents=True, exist_ok=True)
            filename = f"napcat_{uuid.uuid4().hex[:12]}{ext}"
            filepath = cache_dir / filename
            filepath.write_bytes(data)
            return str(filepath)
        except Exception as exc:
            logger.warning("[%s] Download failed for %s: %s", self._log_tag, url, exc)
            return None

    # ------------------------------------------------------------------
    # Sending messages
    # ------------------------------------------------------------------

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        """Send a text message to a QQ chat."""
        if not self._http_client:
            return SendResult(success=False, error="Not connected")

        segments = build_text_message(content)
        if reply_to:
            segments = build_reply_message(reply_to, segments)

        return await self._send_segments(chat_id, segments, metadata)

    async def send_image(
        self,
        chat_id: str,
        image_url: str,
        caption: Optional[str] = None,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        """Send an image with optional caption."""
        if not self._http_client:
            return SendResult(success=False, error="Not connected")

        segments = build_image_message(image_url, caption)
        if reply_to:
            segments = build_reply_message(reply_to, segments)

        return await self._send_segments(chat_id, segments, metadata)

    async def send_image_file(
        self,
        chat_id: str,
        image_path: str,
        caption: Optional[str] = None,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        """Send a local image file."""
        file_uri = _local_file_uri(image_path)
        return await self.send_image(chat_id, file_uri, caption, reply_to, metadata)

    async def send_voice(
        self,
        chat_id: str,
        audio_path: str,
        caption: Optional[str] = None,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        """Send a voice / audio message."""
        if not self._http_client:
            return SendResult(success=False, error="Not connected")

        file_uri = _local_file_uri(audio_path)
        segments = build_voice_message(file_uri)
        if reply_to:
            segments = build_reply_message(reply_to, segments)

        return await self._send_segments(chat_id, segments, metadata)

    async def send_video(
        self,
        chat_id: str,
        video_path: str,
        caption: Optional[str] = None,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        """Send a video message."""
        if not self._http_client:
            return SendResult(success=False, error="Not connected")

        file_uri = _local_file_uri(video_path)
        segments = build_video_message(file_uri, caption)
        if reply_to:
            segments = build_reply_message(reply_to, segments)

        return await self._send_segments(chat_id, segments, metadata)

    async def send_document(
        self,
        chat_id: str,
        file_path: str,
        caption: Optional[str] = None,
        file_name: Optional[str] = None,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        """Send a file / document."""
        if not self._http_client:
            return SendResult(success=False, error="Not connected")

        file_uri = _local_file_uri(file_path)
        name = file_name or os.path.basename(file_path)
        segments = build_document_message(file_uri, name, caption)
        if reply_to:
            segments = build_reply_message(reply_to, segments)

        return await self._send_segments(chat_id, segments, metadata)

    async def send_typing(self, chat_id: str, metadata=None) -> None:
        """No standard typing indicator in OneBot 11 — no-op."""
        pass

    async def delete_message(self, chat_id: str, message_id: str) -> bool:
        """Delete a previously sent message."""
        if not self._http_client:
            return False
        try:
            await api_call(
                self._http_client,
                self._http_url,
                API_DELETE_MSG,
                data={"message_id": int(message_id)},
                token=self._token,
            )
            return True
        except Exception as exc:
            logger.warning("[%s] delete_message failed: %s", self._log_tag, exc)
            return False

    # ------------------------------------------------------------------
    # Internal send helper
    # ------------------------------------------------------------------

    async def _send_segments(
        self,
        chat_id: str,
        segments: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SendResult:
        """Send a segment array to the given chat via the HTTP API."""
        if not self._http_client:
            return SendResult(success=False, error="Not connected")

        # Determine message type from tracked chat type
        msg_type = self._chat_type_map.get(chat_id, MSG_TYPE_PRIVATE)

        payload: Dict[str, Any] = {
            "message": segments,
        }

        if msg_type == MSG_TYPE_GROUP:
            payload["message_type"] = MSG_TYPE_GROUP
            payload["group_id"] = int(chat_id)
        else:
            payload["message_type"] = MSG_TYPE_PRIVATE
            payload["user_id"] = int(chat_id)

        try:
            resp = await api_call(
                self._http_client,
                self._http_url,
                API_SEND_MSG,
                data=payload,
                token=self._token,
            )
            mid = resp.get("message_id")
            return SendResult(
                success=True,
                message_id=str(mid) if mid is not None else None,
            )
        except OneBotAPIError as exc:
            logger.error("[%s] Send failed: %s", self._log_tag, exc)
            return SendResult(success=False, error=str(exc))
        except Exception as exc:
            logger.error("[%s] Send failed: %s", self._log_tag, exc, exc_info=True)
            return SendResult(success=False, error=str(exc), retryable=True)

    # ------------------------------------------------------------------
    # Chat info
    # ------------------------------------------------------------------

    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        """Get information about a chat (group or user)."""
        if not self._http_client:
            return {"name": chat_id, "type": "unknown", "chat_id": chat_id}

        # Try group first
        try:
            data = await api_call(
                self._http_client,
                self._http_url,
                API_GET_GROUP_INFO,
                data={"group_id": int(chat_id)},
                token=self._token,
            )
            return {
                "name": data.get("group_name", chat_id),
                "type": "group",
                "chat_id": chat_id,
                "member_count": data.get("member_count"),
            }
        except Exception:
            pass

        # Fall back to user info
        try:
            data = await api_call(
                self._http_client,
                self._http_url,
                API_GET_STRANGER_INFO,
                data={"user_id": int(chat_id)},
                token=self._token,
            )
            return {
                "name": data.get("nickname", chat_id),
                "type": "dm",
                "chat_id": chat_id,
            }
        except Exception:
            pass

        return {"name": chat_id, "type": "unknown", "chat_id": chat_id}
