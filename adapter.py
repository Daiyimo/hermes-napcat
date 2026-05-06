"""
NapCat platform adapter.

Connects to a NapCat instance via Forward WebSocket (receive events) and
HTTP POST (send API calls) using the OneBot 11 protocol.

Configuration via environment variables:
    NAPCAT_HTTP_URL          - NapCat HTTP API URL (e.g. http://127.0.0.1:3000)
    NAPCAT_WS_URL            - NapCat WebSocket URL (e.g. ws://127.0.0.1:3001 for forward,
                               ws://127.0.0.1:3002 for reverse)
    NAPCAT_WS_MODE           - "forward" (adapter connects to NapCat, default)
                               "reverse" (NapCat connects to adapter, for websocketClients)
    NAPCAT_TOKEN             - Optional Bearer token for authentication
    NAPCAT_ADMIN_USERS       - Comma-separated QQ numbers allowed to use admin commands
    NAPCAT_ALLOWED_USERS     - Comma-separated QQ numbers allowed to interact with the bot
    NAPCAT_GROUP_ALLOWED_USERS - Optional per-group allowed user list (overrides global)
    NAPCAT_ALLOW_ALL_USERS   - Set to "true" to allow any user (default if no allowlist)
    NAPCAT_REQUIRE_MENTION   - Set to "true" to require @mention in group chats (default: true)
    NAPCAT_ENABLE_REACTIONS  - Set to "false" to disable emoji reactions (default: true)
    NAPCAT_REPLY_MODE       - "off" = never quote received message (default), "first", "all"
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, Dict, List, Optional

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
    ProcessingOutcome,
    SendResult,
    _ssrf_redirect_guard,
    cache_audio_from_url,
    cache_image_from_url,
)
from gateway.platforms.helpers import strip_markdown

from .constants import (
    ALERT_TICK_INTERVAL_S,
    API_DELETE_MSG,
    API_GET_FORWARD_MSG,
    API_GET_GROUP_INFO,
    API_GET_LOGIN_INFO,
    API_GET_STRANGER_INFO,
    API_SEND_MSG,
    API_SET_MSG_EMOJI_LIKE,
    API_TIMEOUT,
    CHUNK_SEND_DELAY,
    DEDUP_MAX_SIZE,
    DEDUP_WINDOW_SECONDS,
    EMOJI_FAILURE,
    EMOJI_SUCCESS,
    EMOJI_THINKING,
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
from .group_commands import AdminCmdContext, handle_group_command, is_admin
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
from .observability import Observability
from .utils import OneBotAPIError, api_call

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
    """NapCat adapter — OneBot 11 over WebSocket + HTTP.

    Bridges between the Hermes Agent gateway and a running NapCat instance.
    Supports two WebSocket topologies:

    **Forward mode** (default, ``NAPCAT_WS_MODE=forward``):
        The adapter connects to NapCat's WS Server (``websocketServers``).
        NapCat pushes events; the adapter sends actions via HTTP POST.

    **Reverse mode** (``NAPCAT_WS_MODE=reverse``):
        The adapter runs a WS Server; NapCat connects as a client
        (``websocketClients``).  Useful when NapCat cannot reach the adapter
        host directly (e.g. behind a NAT).

    Configuration is driven entirely by environment variables — see README
    for the full reference.  The adapter is auto-discovered by the gateway
    via ``plugin.yaml`` and registered through ``platform_registry``.

    Attributes:
        SUPPORTS_MESSAGE_EDITING: Always ``False`` (OneBot 11 limitation).
        MAX_MESSAGE_LENGTH: Maximum characters per outgoing message chunk
            (4 500).  Longer content is split automatically.
    """

    SUPPORTS_MESSAGE_EDITING = False
    MAX_MESSAGE_LENGTH = MAX_MESSAGE_LENGTH

    @property
    def _log_tag(self) -> str:
        """Logging prefix that includes the bot's QQ number once known."""
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
        self._http_url: str = (
            str(extra.get("http_url") or os.getenv("NAPCAT_HTTP_URL", "")).strip().rstrip("/")
        )
        self._ws_url: str = (
            str(extra.get("ws_url") or os.getenv("NAPCAT_WS_URL", "")).strip().rstrip("/")
        )
        self._token: str = str(
            config.token or extra.get("token") or os.getenv("NAPCAT_TOKEN", "")
        ).strip()

        # Bot's own QQ number — populated during connect via /get_login_info
        self._self_id: str | None = None
        self._self_name: str | None = None

        # Connection state
        if TYPE_CHECKING:
            import httpx as _httpx
            import websockets.client as _wsclient
            import websockets.server as _wsserver
        self._ws: Any | None = None  # websockets connection (client or server-accepted)
        self._ws_server: Any | None = None  # websockets server (reverse mode only)
        self._http_client: Any | None = None  # httpx.AsyncClient
        self._listen_task: asyncio.Task | None = None

        # Message deduplication — OrderedDict preserves insertion order for O(1) eviction
        self._seen_messages: OrderedDict[str, float] = OrderedDict()

        # Chat type tracking: chat_id → "private" | "group"
        self._chat_type_map: Dict[str, str] = {}

        # Observability: metrics + circuit breaker + alert engine
        self._obs: Observability = Observability()

        # Background alert loop task (started in connect())
        self._alert_task: asyncio.Task | None = None

        # Feature flags
        # require_mention: whether group messages require @bot to trigger (default True)
        _require_mention_env = os.getenv("NAPCAT_REQUIRE_MENTION", "true").strip().lower()
        self._require_mention: bool = _require_mention_env not in ("false", "0", "no")
        # enable_reactions: auto emoji reaction on incoming messages (default True)
        _reactions_env = os.getenv("NAPCAT_ENABLE_REACTIONS", "true").strip().lower()
        self._enable_reactions: bool = _reactions_env not in ("false", "0", "no")
        # reply_to_mode: "off" = never quote received message, "first" = first chunk, "all" = all chunks
        _reply_env = os.getenv("NAPCAT_REPLY_MODE", "off").strip().lower()
        self._reply_to_mode: str = _reply_env if _reply_env in ("off", "first", "all") else "off"

        # WS mode: "forward" = adapter connects to NapCat WS server (websocketServers)
        #          "reverse" = NapCat connects to adapter WS server (websocketClients)
        _ws_mode_env = os.getenv("NAPCAT_WS_MODE", "forward").strip().lower()
        self._ws_mode: str = _ws_mode_env if _ws_mode_env in ("forward", "reverse") else "forward"
        # For reverse mode, parse listen host:port from the WS URL
        self._ws_listen_host: str = "127.0.0.1"
        self._ws_listen_port: int = 3002
        if self._ws_mode == "reverse" and self._ws_url:
            from urllib.parse import urlparse

            parsed = urlparse(self._ws_url)
            self._ws_listen_host = parsed.hostname or "127.0.0.1"
            self._ws_listen_port = parsed.port or 3002

        # Authorized users cache (lazy-loaded)
        self._allowed_users_cache: set | None = None
        self._allowed_group_users_cache: set | None = None
        self._allow_all_users: bool | None = None

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
            # 1. Create HTTP client with SSRF protection
            self._http_client = httpx.AsyncClient(
                timeout=API_TIMEOUT,
                follow_redirects=True,
                event_hooks={"response": [_ssrf_redirect_guard]},
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

            # 3. Start WS (forward or reverse mode)
            if self._ws_mode == "reverse":
                self._listen_task = asyncio.create_task(
                    self._start_ws_server(), name=f"napcat-ws-server-{self._self_id or 'unknown'}"
                )
            else:
                self._listen_task = asyncio.create_task(
                    self._ws_listen_loop(), name=f"napcat-ws-{self._self_id or 'unknown'}"
                )

            # 4. Start periodic alert loop
            self._alert_task = asyncio.create_task(
                self._alert_loop(), name=f"napcat-alerts-{self._self_id or 'unknown'}"
            )

            self._obs.metrics.ws_connected = True
            self._mark_connected()
            logger.info(
                "[%s] Connected — HTTP=%s WS=%s mode=%s",
                self._log_tag,
                self._http_url,
                self._ws_url,
                self._ws_mode,
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

        self._obs.metrics.ws_connected = False

        if self._alert_task:
            self._alert_task.cancel()
            try:
                await self._alert_task
            except asyncio.CancelledError:
                pass
            self._alert_task = None

        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None

        # Reverse mode: close the WS server
        ws_server = getattr(self, "_ws_server", None)
        if ws_server:
            ws_server.close()
            await ws_server.wait_closed()
            self._ws_server = None

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
    # Reverse WebSocket server (NapCat connects to us)
    # ------------------------------------------------------------------

    async def _start_ws_server(self) -> None:
        """Run a WS server that NapCat connects to (reverse WebSocket mode).

        In reverse mode, NapCat is the WS client (configured as a
        ``websocketClients`` entry), and the adapter acts as the WS server.
        NapCat pushes OneBot 11 events through this connection.

        The server accepts one NapCat connection at a time and processes
        events from it.  If NapCat disconnects and reconnects, the new
        connection is accepted seamlessly.
        """

        self._ws_server: Any | None = None

        async def on_connect(ws: Any) -> None:
            """Handle an incoming NapCat connection."""
            if self._ws is not None:
                logger.info(
                    "[%s] New NapCat connection from %s (replacing existing)",
                    self._log_tag,
                    ws.remote_address,
                )
            else:
                logger.info(
                    "[%s] NapCat connected from %s",
                    self._log_tag,
                    ws.remote_address,
                )
            self._ws = ws
            try:
                async for raw_msg in ws:
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
                pass
            except Exception as exc:
                logger.warning("[%s] NapCat connection closed: %s", self._log_tag, exc)
            finally:
                if self._ws is ws:
                    self._ws = None
                logger.info("[%s] NapCat disconnected — waiting for reconnect", self._log_tag)

        try:
            self._ws_server = await websockets.serve(
                on_connect,
                host=self._ws_listen_host,
                port=self._ws_listen_port,
            )
            logger.info(
                "[%s] Reverse WS server listening on %s:%d",
                self._log_tag,
                self._ws_listen_host,
                self._ws_listen_port,
            )
            # Keep the server alive until shutdown
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.debug("[%s] Reverse WS server task cancelled", self._log_tag)
        except Exception as exc:
            if self._running:
                self._set_fatal_error("napcat_ws_server_error", str(exc), retryable=True)
                logger.error(
                    "[%s] Reverse WS server crashed: %s", self._log_tag, exc, exc_info=True
                )
        finally:
            if self._ws_server:
                self._ws_server.close()
                await self._ws_server.wait_closed()
                self._ws_server = None

    # ------------------------------------------------------------------
    # Forward WebSocket client (adapter connects to NapCat)
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
                    extra_headers=extra_headers,
                )

                attempt = 0  # reset backoff on successful connect
                self._obs.metrics.ws_connected = True
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
                self._obs.metrics.ws_connected = False
                self._obs.metrics.record_reconnect()
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
    # Alert loop
    # ------------------------------------------------------------------

    async def _alert_loop(self) -> None:
        """Periodically tick the observability engine to evaluate alert rules.

        Runs every :data:`ALERT_TICK_INTERVAL_S` seconds in the background.
        Cancelled cleanly on :meth:`disconnect`.
        """
        try:
            while self._running:
                await asyncio.sleep(ALERT_TICK_INTERVAL_S)
                if self._running:
                    self._obs.tick()
        except asyncio.CancelledError:
            logger.debug("[%s] Alert loop cancelled", self._log_tag)

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
            self._obs.metrics.record_heartbeat()
        elif meta_type == META_EVENT_LIFECYCLE:
            sub_type = data.get("sub_type", "")
            logger.info("[%s] Lifecycle event: %s", self._log_tag, sub_type)
            # Update self_id if provided in lifecycle connect
            if "self_id" in data:
                self._self_id = str(data["self_id"])
        else:
            logger.debug("[%s] Meta event: %s", self._log_tag, meta_type)

    # ------------------------------------------------------------------
    # User authorization
    # ------------------------------------------------------------------

    def _load_authorization(self) -> None:
        """Lazily load user allowlists from environment variables.

        Called on the first message that requires an authorization check.
        Reads ``NAPCAT_ALLOWED_USERS``, ``NAPCAT_GROUP_ALLOWED_USERS``, and
        ``NAPCAT_ALLOW_ALL_USERS`` and caches the results for the lifetime of
        the adapter.
        """
        if self._allowed_users_cache is not None:
            return
        raw = os.getenv("NAPCAT_ALLOWED_USERS", "").strip()
        self._allowed_users_cache = (
            {u.strip() for u in raw.split(",") if u.strip()} if raw else set()
        )
        raw_group = os.getenv("NAPCAT_GROUP_ALLOWED_USERS", "").strip()
        self._allowed_group_users_cache = (
            {u.strip() for u in raw_group.split(",") if u.strip()} if raw_group else set()
        )
        allow_all = os.getenv("NAPCAT_ALLOW_ALL_USERS", "").strip().lower()
        self._allow_all_users = allow_all in ("true", "1", "yes")

    def _is_user_authorized(self, user_id: str, is_group: bool = False) -> bool:
        """Return True if *user_id* is allowed to interact with the bot."""
        self._load_authorization()
        if self._allow_all_users:
            return True
        # Group-specific allowlist takes precedence in groups
        if is_group and self._allowed_group_users_cache:
            return user_id in self._allowed_group_users_cache
        # Global allowlist
        if self._allowed_users_cache:
            return user_id in self._allowed_users_cache
        # No allowlists configured → allow everyone
        return True

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

        m = self._obs.metrics
        m.messages_received += 1
        m.last_message_at = time.monotonic()

        # Record receive-side latency (event.time is a Unix timestamp in seconds)
        event_time = data.get("time")
        if event_time:
            recv_latency_ms = (time.time() - float(event_time)) * 1000
            m.record_recv_latency(recv_latency_ms)

        try:
            await self._handle_message_event_inner(data, message_id, user_id, message_type)
        except Exception:
            m.record_error()
            logger.error(
                "[%s] Unhandled error processing message %s — skipping",
                self._log_tag,
                message_id,
                exc_info=True,
            )

    async def _handle_message_event_inner(
        self,
        data: Dict[str, Any],
        message_id: str,
        user_id: str,
        message_type: str,
    ) -> None:
        """Core message processing (extracted for error isolation)."""

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

        # Determine whether this is a group chat (reused below)
        is_group = message_type == MSG_TYPE_GROUP

        # User authorization gate (admins always bypass)
        if not is_admin(user_id) and not self._is_user_authorized(user_id, is_group=is_group):
            logger.debug("[%s] User %s not authorized — skipping", self._log_tag, user_id)
            return

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
                obs=self._obs,
            )
            handled = await handle_group_command(cmd, parts, ctx, _reply_admin)
            if handled:
                return

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
                self._log_tag,
                message_id,
                failed_types,
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
    # Processing lifecycle hooks (emoji reaction status indicators)
    # ------------------------------------------------------------------

    async def on_processing_start(self, event: MessageEvent) -> None:
        """React with a "thinking" emoji (face 32) when processing begins."""
        if not self._enable_reactions or not self._http_client or not event.message_id:
            return
        try:
            await api_call(
                self._http_client,
                self._http_url,
                API_SET_MSG_EMOJI_LIKE,
                data={"message_id": int(event.message_id), "emoji_id": EMOJI_THINKING, "set": True},
                token=self._token,
            )
        except Exception as exc:
            logger.debug("[%s] Processing-start reaction failed: %s", self._log_tag, exc)

    async def on_processing_complete(self, event: MessageEvent, outcome: ProcessingOutcome) -> None:
        """Swap the processing emoji for thumbs-up (76) on success or angry (326) on failure."""
        if not self._enable_reactions or not self._http_client or not event.message_id:
            return
        if outcome == ProcessingOutcome.CANCELLED:
            return  # Leave the thinking emoji in place
        try:
            emoji_id = EMOJI_SUCCESS if outcome == ProcessingOutcome.SUCCESS else EMOJI_FAILURE
            await api_call(
                self._http_client,
                self._http_url,
                API_SET_MSG_EMOJI_LIKE,
                data={"message_id": int(event.message_id), "emoji_id": emoji_id, "set": True},
                token=self._token,
            )
        except Exception as exc:
            logger.debug("[%s] Processing-complete reaction failed: %s", self._log_tag, exc)

    def _dedup_check(self, message_id: str) -> bool:
        """Return True if *message_id* has not been seen recently.

        Uses an OrderedDict for O(1) insertion-order eviction instead of
        rebuilding the entire dict on every overflow.
        """
        if not message_id:
            return True  # no ID — can't dedup
        if message_id in self._seen_messages:
            logger.debug("[%s] Duplicate message %s — skipping", self._log_tag, message_id)
            self._obs.metrics.dedup_skipped += 1
            return False

        self._seen_messages[message_id] = time.monotonic()
        # Evict oldest entries when over capacity (O(1) pop from front)
        while len(self._seen_messages) > DEDUP_MAX_SIZE:
            self._seen_messages.popitem(last=False)
        return True

    async def _cache_local_file(self, path: str, ext: str = "") -> str | None:
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

    async def _download_to_cache(self, url: str, ext: str = "") -> str | None:
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

    def _should_reply(self) -> bool:
        """Return True if reply_to_mode allows quoting received messages."""
        return self._reply_to_mode != "off"

    def _maybe_wrap_reply(
        self,
        segments: List[Dict[str, Any]],
        reply_to: str | None,
    ) -> List[Dict[str, Any]]:
        """Prepend a reply segment when reply mode is active and *reply_to* is set.

        Args:
            segments: The outgoing message segment list to potentially wrap.
            reply_to: The message ID to quote, or ``None`` to skip.

        Returns:
            The original *segments* list prepended with a ``reply`` segment
            when ``NAPCAT_REPLY_MODE != "off"`` and *reply_to* is non-empty;
            otherwise the original list unchanged.
        """
        if reply_to and self._should_reply():
            return build_reply_message(reply_to, segments)
        return segments

    def format_message(self, content: str) -> str:
        """Strip markdown formatting before sending to QQ.

        QQ renders plain text only; markdown syntax (headings, bold, code
        fences, etc.) would appear as literal characters.  This method
        delegates to :func:`gateway.platforms.helpers.strip_markdown`.
        """
        return strip_markdown(content)

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: str | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> SendResult:
        """Send a plain-text message, splitting it into chunks when necessary.

        Markdown is stripped before sending (see :meth:`format_message`).
        Messages longer than :attr:`MAX_MESSAGE_LENGTH` are split and sent
        sequentially with a :data:`CHUNK_SEND_DELAY`-second delay between
        chunks to avoid hitting NapCat's rate limit.  Only the first chunk
        carries the reply quote when ``NAPCAT_REPLY_MODE`` is ``"first"``
        or ``"all"``.

        Args:
            chat_id: Target chat — a QQ number (private chat) or group number.
            content: The message body.  Markdown will be stripped.
            reply_to: Optional message ID to quote (honours ``NAPCAT_REPLY_MODE``).
            metadata: Opaque dict forwarded from the Hermes gateway (unused).

        Returns:
            :class:`SendResult` with ``success=True`` and the NapCat
            ``message_id`` on success, or ``success=False`` with an error
            description on failure.
        """
        if not self._http_client:
            return SendResult(success=False, error="Not connected")

        # Strip markdown and split long messages
        formatted = self.format_message(content)
        chunks = self.truncate_message(formatted, self.MAX_MESSAGE_LENGTH)

        if len(chunks) == 1:
            segments = build_text_message(formatted)
            segments = self._maybe_wrap_reply(segments, reply_to)
            return await self._send_segments(chat_id, segments, metadata)

        # Send chunks sequentially; only the first chunk gets the reply
        last_result: SendResult | None = None
        for i, chunk in enumerate(chunks):
            segments = build_text_message(chunk)
            if i == 0:
                segments = self._maybe_wrap_reply(segments, reply_to)
            last_result = await self._send_segments(chat_id, segments, metadata)
            if last_result and not last_result.success:
                break
            if i < len(chunks) - 1:
                await asyncio.sleep(CHUNK_SEND_DELAY)  # Rate-limit between chunks
        return last_result or SendResult(success=False, error="No chunks sent")

    async def send_image(
        self,
        chat_id: str,
        image_url: str,
        caption: str | None = None,
        reply_to: str | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> SendResult:
        """Send an image with an optional text caption.

        Args:
            chat_id: Target chat (QQ number or group number).
            image_url: HTTP(S) URL or ``file:///`` URI of the image.
                NapCat will download the image when a URL is supplied.
            caption: Optional text appended after the image segment.
            reply_to: Optional message ID to quote.
            metadata: Opaque gateway metadata (unused).

        Returns:
            :class:`SendResult` describing success or failure.
        """
        if not self._http_client:
            return SendResult(success=False, error="Not connected")

        segments = build_image_message(image_url, caption)
        segments = self._maybe_wrap_reply(segments, reply_to)

        return await self._send_segments(chat_id, segments, metadata)

    async def send_image_file(
        self,
        chat_id: str,
        image_path: str,
        caption: str | None = None,
        reply_to: str | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> SendResult:
        """Send a local image file by converting its path to a ``file:///`` URI.

        Delegates to :meth:`send_image` after URI conversion.  The path is
        URL-encoded so spaces and special characters are handled correctly on
        all platforms.
        """
        file_uri = _local_file_uri(image_path)
        return await self.send_image(chat_id, file_uri, caption, reply_to, metadata)

    async def send_voice(
        self,
        chat_id: str,
        audio_path: str,
        caption: str | None = None,
        reply_to: str | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> SendResult:
        """Send a voice / audio message from a local file.

        The file is converted to a ``file:///`` URI and sent as an OneBot 11
        ``record`` segment.  NapCat accepts common audio formats (OGG, MP3,
        WAV, SILK, AMR, M4A).

        Args:
            chat_id: Target chat (QQ number or group number).
            audio_path: Absolute local path to the audio file.
            caption: Unused for voice messages; reserved for API compatibility.
            reply_to: Optional message ID to quote.
            metadata: Opaque gateway metadata (unused).

        Returns:
            :class:`SendResult` describing success or failure.
        """
        if not self._http_client:
            return SendResult(success=False, error="Not connected")

        file_uri = _local_file_uri(audio_path)
        segments = build_voice_message(file_uri)
        segments = self._maybe_wrap_reply(segments, reply_to)

        return await self._send_segments(chat_id, segments, metadata)

    async def send_video(
        self,
        chat_id: str,
        video_path: str,
        caption: str | None = None,
        reply_to: str | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> SendResult:
        """Send a video message from a local file.

        Args:
            chat_id: Target chat (QQ number or group number).
            video_path: Absolute local path to the video file (MP4, AVI, MKV, WebM).
            caption: Optional text appended after the video segment.
            reply_to: Optional message ID to quote.
            metadata: Opaque gateway metadata (unused).

        Returns:
            :class:`SendResult` describing success or failure.
        """
        if not self._http_client:
            return SendResult(success=False, error="Not connected")

        file_uri = _local_file_uri(video_path)
        segments = build_video_message(file_uri, caption)
        segments = self._maybe_wrap_reply(segments, reply_to)

        return await self._send_segments(chat_id, segments, metadata)

    async def send_document(
        self,
        chat_id: str,
        file_path: str,
        caption: str | None = None,
        file_name: str | None = None,
        reply_to: str | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> SendResult:
        """Send an arbitrary file as a document / attachment.

        Args:
            chat_id: Target chat (QQ number or group number).
            file_path: Absolute local path to the file to send.
            caption: Optional text appended after the file segment.
            file_name: Display name for the file.  Defaults to
                ``os.path.basename(file_path)``.
            reply_to: Optional message ID to quote.
            metadata: Opaque gateway metadata (unused).

        Returns:
            :class:`SendResult` describing success or failure.
        """
        if not self._http_client:
            return SendResult(success=False, error="Not connected")

        file_uri = _local_file_uri(file_path)
        name = file_name or os.path.basename(file_path)
        segments = build_document_message(file_uri, name, caption)
        segments = self._maybe_wrap_reply(segments, reply_to)

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
        metadata: Dict[str, Any] | None = None,
    ) -> SendResult:
        """Send a segment array to the given chat via the HTTP API.

        Guards outbound calls with the circuit breaker.  When the breaker is
        OPEN the call is fast-failed immediately without hitting the network.
        """
        if not self._http_client:
            return SendResult(success=False, error="Not connected")

        # Circuit breaker fast-fail
        if not self._obs.circuit.allow_request():
            logger.warning(
                "[%s] Circuit OPEN — send fast-failed for chat %s", self._log_tag, chat_id
            )
            self._obs.metrics.record_send_fail()
            return SendResult(success=False, error="circuit open", retryable=True)

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

        _t0 = time.monotonic()
        try:
            resp = await api_call(
                self._http_client,
                self._http_url,
                API_SEND_MSG,
                data=payload,
                token=self._token,
            )
            send_ms = (time.monotonic() - _t0) * 1000
            self._obs.metrics.record_send_latency(send_ms)
            self._obs.circuit.record_success()
            mid = resp.get("message_id")
            self._obs.metrics.record_send_ok()
            return SendResult(
                success=True,
                message_id=str(mid) if mid is not None else None,
            )
        except OneBotAPIError as exc:
            self._obs.circuit.record_failure()
            self._obs.metrics.record_send_fail()
            logger.error("[%s] Send failed: %s", self._log_tag, exc)
            return SendResult(success=False, error=str(exc))
        except Exception as exc:
            self._obs.circuit.record_failure()
            self._obs.metrics.record_send_fail()
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
