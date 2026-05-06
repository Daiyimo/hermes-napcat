"""
NapCat outgoing message builder.

Constructs OneBot 11 message segment arrays that are posted to the NapCat
HTTP API via ``/send_msg``.

The module is split into two layers:

**Segment factories** (low-level)
    :func:`text_segment`, :func:`image_segment`, :func:`record_segment`,
    :func:`video_segment`, :func:`file_segment`, :func:`at_segment`,
    :func:`reply_segment` — each returns a single ``{"type": …, "data": …}``
    dict as defined by the OneBot 11 specification.

**Message builders** (high-level)
    :func:`build_text_message`, :func:`build_image_message`,
    :func:`build_voice_message`, :func:`build_video_message`,
    :func:`build_document_message`, :func:`build_reply_message`,
    :func:`build_mixed_message` — combine segments into complete message
    arrays ready for the API.

This module performs no I/O and has no side effects.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .constants import (
    SEG_AT,
    SEG_FILE,
    SEG_IMAGE,
    SEG_RECORD,
    SEG_REPLY,
    SEG_TEXT,
    SEG_VIDEO,
)

# ---------------------------------------------------------------------------
# Segment factories
# ---------------------------------------------------------------------------


def text_segment(text: str) -> Dict[str, Any]:
    """Build a text segment."""
    return {"type": SEG_TEXT, "data": {"text": text}}


def image_segment(file: str) -> Dict[str, Any]:
    """Build an image segment.

    *file* can be:
    - An HTTP(S) URL (NapCat will download it)
    - A ``file:///`` URI for a local file
    - A ``base64://`` data URI
    """
    return {"type": SEG_IMAGE, "data": {"file": file}}


def record_segment(file: str) -> Dict[str, Any]:
    """Build a voice / audio record segment."""
    return {"type": SEG_RECORD, "data": {"file": file}}


def video_segment(file: str) -> Dict[str, Any]:
    """Build a video segment."""
    return {"type": SEG_VIDEO, "data": {"file": file}}


def file_segment(file: str, name: str = "") -> Dict[str, Any]:
    """Build a file / document segment."""
    data: Dict[str, Any] = {"file": file}
    if name:
        data["name"] = name
    return {"type": SEG_FILE, "data": data}


def at_segment(qq: str) -> Dict[str, Any]:
    """Build an @mention segment.  Use ``qq="all"`` for @everyone."""
    return {"type": SEG_AT, "data": {"qq": str(qq)}}


def reply_segment(message_id: str) -> Dict[str, Any]:
    """Build a reply segment pointing to *message_id*."""
    return {"type": SEG_REPLY, "data": {"id": str(message_id)}}


# ---------------------------------------------------------------------------
# High-level message builders
# ---------------------------------------------------------------------------


def build_text_message(text: str) -> List[Dict[str, Any]]:
    """Build a plain text message array."""
    return [text_segment(text)]


def build_image_message(
    file: str,
    caption: str | None = None,
) -> List[Dict[str, Any]]:
    """Build a message with an image and optional caption text."""
    segments: List[Dict[str, Any]] = [image_segment(file)]
    if caption:
        segments.append(text_segment(caption))
    return segments


def build_voice_message(file: str) -> List[Dict[str, Any]]:
    """Build a voice / audio message."""
    return [record_segment(file)]


def build_video_message(
    file: str,
    caption: str | None = None,
) -> List[Dict[str, Any]]:
    """Build a video message with optional caption."""
    segments: List[Dict[str, Any]] = [video_segment(file)]
    if caption:
        segments.append(text_segment(caption))
    return segments


def build_document_message(
    file: str,
    name: str = "",
    caption: str | None = None,
) -> List[Dict[str, Any]]:
    """Build a file / document message with optional caption."""
    segments: List[Dict[str, Any]] = [file_segment(file, name)]
    if caption:
        segments.append(text_segment(caption))
    return segments


def build_reply_message(
    message_id: str,
    content_segments: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Prepend a reply segment to an existing segment list."""
    return [reply_segment(message_id)] + content_segments


def build_mixed_message(
    text: str,
    media_paths: List[str] | None = None,
    reply_to: str | None = None,
) -> List[Dict[str, Any]]:
    """Build a message that combines text with zero or more media attachments.

    Segment order: ``[reply?] [text?] [media…]``

    Media files are classified by their file extension (case-insensitive):

    ============ =============================================
    Extension     Segment type
    ============ =============================================
    jpg/jpeg/png/gif/webp/bmp  ``image``
    mp3/ogg/wav/silk/amr/m4a   ``record`` (voice)
    mp4/avi/mkv/webm           ``video``
    *anything else*            ``file``
    ============ =============================================

    Args:
        text: Plain text content.  Pass an empty string to omit the text
            segment.
        media_paths: Optional list of local file paths to attach.  Each path
            is classified and converted to a ``file:///`` URI automatically.
        reply_to: Optional message ID to quote; prepended as a ``reply``
            segment when provided.

    Returns:
        A list of OneBot 11 segment dicts ready for ``/send_msg``.
    """
    segments: List[Dict[str, Any]] = []

    if reply_to:
        segments.append(reply_segment(reply_to))

    if text:
        segments.append(text_segment(text))

    for path in media_paths or []:
        lower = path.lower()
        if any(lower.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")):
            segments.append(image_segment(path))
        elif any(lower.endswith(ext) for ext in (".mp3", ".ogg", ".wav", ".silk", ".amr", ".m4a")):
            segments.append(record_segment(path))
        elif any(lower.endswith(ext) for ext in (".mp4", ".avi", ".mkv", ".webm")):
            segments.append(video_segment(path))
        else:
            import os

            segments.append(file_segment(path, name=os.path.basename(path)))

    return segments


def _local_file_uri(path: str) -> str:
    """Convert a local file path to a ``file:///`` URI.

    Handles Windows drive-letter paths and URL-encodes spaces / special chars.
    """
    import os
    import sys
    from urllib.parse import quote

    abspath = os.path.abspath(path)
    if sys.platform == "win32":
        # Windows: C:\Users\foo bar\a.png → file:///C:/Users/foo%20bar/a.png
        encoded = quote(abspath.replace("\\", "/"), safe=":/")
        return f"file:///{encoded}"
    else:
        return f"file://{quote(abspath, safe='/')}"
