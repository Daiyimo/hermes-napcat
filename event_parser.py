"""
NapCat event parser.

Converts incoming OneBot 11 event payloads into plain Python structures
that the adapter can forward to the Hermes gateway.  The key public
functions are:

* :func:`parse_message_segments` — turn a segment array into ``(text, media_list)``
* :func:`extract_reply_id` — find the quoted message ID, if any
* :func:`extract_forward_ids` — collect IDs for forwarded-message expansion
* :func:`extract_forward_text` — format an expanded forward payload as text
* :func:`check_at_bot` — detect whether the bot's QQ was @-mentioned
* :func:`_extract_json_text` — surface card title from a ``json`` segment
* :func:`_extract_xml_text` — surface card title from an ``xml`` segment

No network I/O is performed here; all data comes from the already-parsed
event dict received over WebSocket.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from .constants import (
    MSG_TYPE_GROUP,
    MSG_TYPE_PRIVATE,
    SEG_AT,
    SEG_FACE,
    SEG_FILE,
    SEG_FORWARD,
    SEG_IMAGE,
    SEG_JSON,
    SEG_RECORD,
    SEG_REPLY,
    SEG_TEXT,
    SEG_VIDEO,
    SEG_XML,
)

logger = logging.getLogger(__name__)

# QQ built-in face emoji → rough unicode mapping (subset)
_FACE_MAP: Dict[int, str] = {
    0: "\U0001f62e",  # Surprised
    1: "\U0001f621",  # Tut-tut
    2: "\U0001f60d",  # Heart eyes
    4: "\U0001f60e",  # Cool
    5: "\U0001f62d",  # Cry
    6: "\U0001f633",  # Embarrassed
    7: "\U0001f636",  # Shutup
    8: "\U0001f634",  # Sleep
    9: "\U0001f62d",  # Cry loudly
    10: "\U0001f616",  # Embarrassed
    11: "\U0001f620",  # Angry
    12: "\U0001f61c",  # Tongue out
    13: "\U0001f601",  # Grin
    14: "\U0001f642",  # Smile
    15: "\U0001f641",  # Sad
    16: "\U0001f60e",  # Cool
    18: "\U0001f624",  # Fight
    19: "\U0001f604",  # Laugh
    20: "\U0001f60f",  # Smirk
    21: "\U0001f60c",  # Relieved
    23: "\U0001f615",  # Confused
    25: "\U0001f637",  # Mask
    26: "\U0001f628",  # Panic
    27: "\U0001f631",  # Scream
    28: "\U0001f622",  # Tears
    29: "\U0001f608",  # Devil
    30: "\U0001f910",  # Zipper mouth
    31: "\U0001f914",  # Thinking
    32: "\U0001f92b",  # Shh
    33: "\U0001f60b",  # Yum
    34: "\U0001f623",  # Persevere
    46: "\U0001f437",  # Pig
    49: "\U0001f917",  # Hugs
    53: "\U0001f382",  # Cake
    56: "\U0001f4aa",  # Muscle
    59: "\U0001f4a9",  # Poop
    63: "\U0001f339",  # Rose
    66: "\U00002764",  # Heart
    67: "\U0001f494",  # Broken heart
    74: "\u2600\ufe0f",  # Sun
    75: "\U0001f319",  # Moon
    76: "\U0001f44d",  # Thumbs up
    77: "\U0001f44e",  # Thumbs down
    78: "\U0001f44c",  # OK
    79: "\u270c\ufe0f",  # Victory
    85: "\U0001f48a",  # Pill
    86: "\U0001f52b",  # Gun
    89: "\U0001f4a3",  # Bomb
    96: "\U0001f622",  # Cold sweat
    97: "\U0001f613",  # Shame
    98: "\U0001f604",  # Happy
    99: "\U0001f612",  # Unamused
    100: "\U0001f624",  # Triumph
    101: "\U0001f62a",  # Sleepy
    104: "\U0001f609",  # Wink
    106: "\U0001f60a",  # Blush
    109: "\U0001f48b",  # Kiss
    111: "\U0001f4a8",  # Scared
    116: "\U0001f44b",  # Wave
    118: "\U0001f64f",  # Pray
    120: "\U0001f4aa",  # Flex
    122: "\U0001f44a",  # Punch
    123: "\U0001f91e",  # Crossed fingers
    124: "\U0001f64f",  # Folded hands
    147: "\U0001f382",  # Birthday cake
    171: "\U00002615",  # Tea
    174: "\U0001f381",  # Gift
    178: "\U0001f680",  # Rocket
    179: "\U0001f3b5",  # Music
}


def _guess_extension(url: str, default: str = ".jpg") -> str:
    """Guess an image file extension from a URL path component.

    Args:
        url: The URL to inspect (only the path is examined).
        default: Fallback extension when none is recognised.

    Returns:
        The lowercase extension string including the leading dot,
        e.g. ``".png"``.
    """
    parsed = urlparse(url)
    path = parsed.path.lower()
    for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"):
        if path.endswith(ext):
            return ext
    return default


def _guess_audio_extension(url: str, default: str = ".silk") -> str:
    """Guess an audio file extension from a URL path component.

    Args:
        url: The URL to inspect.
        default: Fallback extension; defaults to ``".silk"`` (QQ native format).

    Returns:
        The lowercase extension string including the leading dot.
    """
    parsed = urlparse(url)
    path = parsed.path.lower()
    for ext in (".silk", ".amr", ".mp3", ".ogg", ".wav", ".m4a"):
        if path.endswith(ext):
            return ext
    return default


def _resolve_media_url(data: Dict[str, Any]) -> tuple[str, bool]:
    """Pick the best URL/path from a NapCat media segment's data dict.

    NapCat may populate these fields in an incoming event:
    - ``url``  : CDN download URL (http/https) — preferred, always downloadable
    - ``file`` : Local absolute path, a file:/// URI, or a bare file_id string
    - ``path`` : Local absolute path (NapCat 4.18+, more reliable than ``file``)

    Returns:
        (url_or_path, is_local) where *is_local* is True when the value
        is a local filesystem path (should be read directly, not downloaded).
    """
    # CDN URL — best option
    cdn_url = data.get("url", "")
    if cdn_url and cdn_url.startswith(("http://", "https://")):
        return cdn_url, False

    # Explicit local path field (NapCat 4.18+)
    path_field = data.get("path", "")
    if path_field and (
        path_field.startswith("/") or (len(path_field) > 1 and path_field[1] == ":")
    ):
        return path_field, True

    # file field — could be local path, file:/// URI, or file_id
    file_field = data.get("file", "")
    if file_field:
        if file_field.startswith("file:///"):
            # Strip file:/// to get a plain path
            local = file_field[7:]  # keep leading /
            return local, True
        if file_field.startswith(("http://", "https://")):
            return file_field, False
        if file_field.startswith("/") or (len(file_field) > 1 and file_field[1] == ":"):
            return file_field, True
        # Bare file_id or relative path — treat as non-local (caller must use API)
        return file_field, False

    return "", False


def _clean_cq_codes(text: str) -> str:
    """Strip CQ-code tags from a plain-string message.

    NapCat occasionally sends messages in legacy CQ-code string format even
    when ``messagePostFormat`` is set to ``array``.  This function normalises
    those strings so they are human-readable:

    * ``[CQ:face,id=N]`` → ``[表情]``
    * ``[CQ:image,…]`` → ``[图片]``
    * All other ``[CQ:…]`` tags are removed entirely.

    Args:
        text: Raw message string potentially containing CQ codes.

    Returns:
        Cleaned plain text with CQ codes replaced or removed.
    """
    # Replace face codes with placeholder
    text = re.sub(r"\[CQ:face,id=\d+\]", "[表情]", text)
    # Replace image codes with placeholder
    text = re.sub(r"\[CQ:image[^\]]*\]", "[图片]", text)
    # Remove other CQ codes
    text = re.sub(r"\[CQ:[^\]]+\]", "", text)
    return text.strip()


def _extract_json_text(data: Dict[str, Any]) -> str:
    """Extract a human-readable label from a OneBot 11 ``json`` segment.

    QQ rich-content cards (music shares, mini-programs, URL previews …) arrive
    as ``{"type": "json", "data": {"data": "<JSON string>"}}``.  We try to
    surface the most descriptive field available so the LLM can acknowledge the
    shared content instead of seeing an empty message.

    Priority order: ``desc`` → ``prompt`` → ``title`` → ``tag``.
    Falls back to ``[分享]`` when no field is found or the payload cannot be
    decoded.

    Args:
        data: The ``data`` dict of a ``json`` segment (not the outer segment).

    Returns:
        A short text label like ``"[分享: 告白气球 - 周杰伦]"`` or ``"[分享]"``.
    """
    raw = data.get("data", "")
    if not raw:
        return "[分享]"
    try:
        payload: Dict[str, Any] = json.loads(raw) if isinstance(raw, str) else raw
        # Nested meta block present in most QQ card formats
        meta = payload.get("meta", {})
        if isinstance(meta, dict):
            # music / news / app cards store details one level deeper
            for submeta in meta.values():
                if isinstance(submeta, dict):
                    for key in ("desc", "title", "tag"):
                        val = submeta.get(key, "")
                        if val and isinstance(val, str):
                            return f"[分享: {val.strip()}]"
        # Top-level fields (simpler card formats)
        for key in ("desc", "prompt", "title", "tag"):
            val = payload.get(key, "")
            if val and isinstance(val, str):
                return f"[分享: {val.strip()}]"
    except (json.JSONDecodeError, AttributeError, TypeError):
        logger.debug("Failed to decode json segment payload")
    return "[分享]"


def _extract_xml_text(data: Dict[str, Any]) -> str:
    """Extract a human-readable label from a OneBot 11 ``xml`` segment.

    XML cards (older QQ mini-programs, group notices, …) carry a ``data``
    field with a raw XML string.  Full XML parsing would require ``xml.etree``
    which is fine, but the field names vary significantly.  A targeted regex
    approach is more robust for the malformed fragments NapCat sometimes emits.

    Looks for ``<title>`` / ``<summary>`` / ``<brief>`` in that order.

    Args:
        data: The ``data`` dict of an ``xml`` segment.

    Returns:
        A short text label like ``"[卡片: 群公告更新]"`` or ``"[卡片]"``.
    """
    raw = data.get("data", "")
    if not raw or not isinstance(raw, str):
        return "[卡片]"
    for tag in ("title", "summary", "brief"):
        m = re.search(rf"<{tag}>([^<]{{1,120}})</{tag}>", raw, re.IGNORECASE)
        if m:
            return f"[卡片: {m.group(1).strip()}]"
    return "[卡片]"


def extract_forward_text(forward_data: Any, max_items: int = 10, max_preview: int = 200) -> str:
    """Convert a ``/get_forward_msg`` response payload into a readable text block.

    Args:
        forward_data: The ``data`` dict returned by the ``/get_forward_msg`` API.
            Expected shape: ``{"messages": [{"sender": {...}, "content": ...}, ...]}``.
        max_items: Maximum number of child messages to include.
        max_preview: Maximum character length per child message preview.

    Returns:
        A multi-line string summarising the forwarded messages, or
        ``"[转发消息: 内容为空]"`` when nothing useful was found.
    """
    if not forward_data:
        return "[转发消息: 内容为空]"

    messages = forward_data.get("messages") or forward_data.get("msgs") or []
    if not messages:
        return "[转发消息: 内容为空]"

    lines: List[str] = ["[转发聊天记录]:"]
    for msg in messages[:max_items]:
        sender_info = msg.get("sender") or {}
        sender_name = (
            sender_info.get("card")
            or sender_info.get("nickname")
            or str(sender_info.get("user_id", "未知"))
        )

        # content field can be a string (CQ-code), a list of segments, or a dict
        content = msg.get("content") or msg.get("raw_message") or msg.get("message") or ""

        if isinstance(content, list):
            # Segment array — extract text inline (skip nested forwards to avoid recursion)
            parts: List[str] = []
            for seg in content:
                seg_type = seg.get("type", "")
                d = seg.get("data") or {}
                if seg_type == "text":
                    parts.append(d.get("text", ""))
                elif seg_type == "image":
                    parts.append("[图片]")
                elif seg_type == "record":
                    parts.append("[语音]")
                elif seg_type == "video":
                    parts.append("[视频]")
                elif seg_type == "at":
                    parts.append(f"@{d.get('qq', '')}")
                elif seg_type == "face":
                    parts.append("[表情]")
                elif seg_type == "forward":
                    parts.append("[嵌套转发]")
                elif seg_type == "file":
                    parts.append(f"[文件:{d.get('name', '')}]")
            preview = "".join(parts).strip()
        elif isinstance(content, str):
            preview = _clean_cq_codes(content)
        else:
            preview = str(content)

        # Skip empty or nested-forward-only messages
        if not preview or preview == "[嵌套转发]":
            continue

        if len(preview) > max_preview:
            preview = preview[:max_preview] + "…"

        lines.append(f"{sender_name}: {preview}")

    if len(lines) == 1:
        return "[转发消息: 内容为空]"
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Segment parser
# ---------------------------------------------------------------------------


def parse_message_segments(
    segments: list,
    forward_texts: Dict[str, str] | None = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """Parse an OneBot 11 message segment array.

    Args:
        segments: List of ``{"type": ..., "data": {...}}`` dicts from an
            incoming OneBot 11 message event.
        forward_texts: Optional pre-fetched mapping of forward-ID → expanded
            text (populated by the adapter before calling this function).
            When provided, ``forward`` segments are replaced with the
            corresponding expanded text instead of a placeholder.

    Returns:
        A tuple of ``(text, media_list)`` where:
        - *text* is the concatenated text content.
        - *media_list* is a list of dicts with keys ``url``, ``type``,
          ``ext``, and optionally ``file_name``.
    """
    text_parts: List[str] = []
    media_list: List[Dict[str, Any]] = []

    for seg in segments:
        seg_type = seg.get("type", "")
        data = seg.get("data") or {}

        if seg_type == SEG_TEXT:
            text_parts.append(data.get("text", ""))

        elif seg_type == SEG_IMAGE:
            url, is_local = _resolve_media_url(data)
            if url:
                ext = _guess_extension(url)
                media_list.append(
                    {
                        "url": url,
                        "type": "image",
                        "ext": ext,
                        "is_local": is_local,
                    }
                )
            # Some clients also put text in the "summary" field
            summary = data.get("summary")
            if summary:
                text_parts.append(f"[Image: {summary}]")

        elif seg_type == SEG_RECORD:
            url, is_local = _resolve_media_url(data)
            if url:
                ext = _guess_audio_extension(url)
                media_list.append(
                    {
                        "url": url,
                        "type": "audio",
                        "ext": ext,
                        "is_local": is_local,
                    }
                )

        elif seg_type == SEG_VIDEO:
            url, is_local = _resolve_media_url(data)
            if url:
                # Try to guess extension from local path; default to .mp4
                ext = os.path.splitext(url)[1].lower() or ".mp4"
                if ext not in (".mp4", ".avi", ".mkv", ".mov", ".webm"):
                    ext = ".mp4"
                media_list.append(
                    {
                        "url": url,
                        "type": "video",
                        "ext": ext,
                        "is_local": is_local,
                    }
                )

        elif seg_type == SEG_FILE:
            url, is_local = _resolve_media_url(data)
            name = data.get("name", "file")
            if url:
                ext = os.path.splitext(name)[1] or ""
                media_list.append(
                    {
                        "url": url,
                        "type": "document",
                        "ext": ext,
                        "file_name": name,
                        "is_local": is_local,
                    }
                )

        elif seg_type == SEG_AT:
            qq = data.get("qq", "")
            name = data.get("name", "")
            if qq == "all":
                text_parts.append("@all")
            elif name:
                text_parts.append(f"@{name}")
            else:
                text_parts.append(f"@{qq}")

        elif seg_type == SEG_REPLY:
            pass  # reply ID is extracted separately by extract_reply_id()

        elif seg_type == SEG_FACE:
            face_id = data.get("id")
            if face_id is not None:
                try:
                    face_id = int(face_id)
                except (ValueError, TypeError):
                    face_id = -1
                emoji = _FACE_MAP.get(face_id, f"[face:{face_id}]")
                text_parts.append(emoji)

        elif seg_type == SEG_FORWARD:
            forward_id = str(data.get("id", ""))
            if forward_texts and forward_id and forward_id in forward_texts:
                text_parts.append("\n" + forward_texts[forward_id])
            else:
                text_parts.append("[转发消息]")

        elif seg_type == SEG_JSON:
            text_parts.append(_extract_json_text(data))

        elif seg_type == SEG_XML:
            text_parts.append(_extract_xml_text(data))

        else:
            # Unknown segment type — log and skip
            logger.debug("Ignoring unknown segment type: %s", seg_type)

    text = "".join(text_parts).strip()
    return text, media_list


def extract_reply_id(segments: list) -> str | None:
    """Extract the reply-to message ID from a segment array, if present."""
    for seg in segments:
        if seg.get("type") == SEG_REPLY:
            data = seg.get("data") or {}
            reply_id = data.get("id")
            if reply_id is not None:
                return str(reply_id)
    return None


def extract_forward_ids(segments: list) -> List[str]:
    """Extract all forward message IDs from a segment array."""
    ids: List[str] = []
    for seg in segments:
        if seg.get("type") == SEG_FORWARD:
            data = seg.get("data") or {}
            fid = data.get("id")
            if fid:
                ids.append(str(fid))
    return ids


def check_at_bot(segments: list, self_id: str) -> bool:
    """Return True if the segment array contains an @mention of *self_id*."""
    for seg in segments:
        if seg.get("type") == SEG_AT:
            data = seg.get("data") or {}
            qq = str(data.get("qq", ""))
            if qq == self_id:
                return True
    return False
