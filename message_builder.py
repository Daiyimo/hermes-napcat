"""
NapCat outgoing message builder.

Constructs OneBot 11 message segment arrays for sending via the HTTP API.
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
    caption: Optional[str] = None,
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
    caption: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Build a video message with optional caption."""
    segments: List[Dict[str, Any]] = [video_segment(file)]
    if caption:
        segments.append(text_segment(caption))
    return segments


def build_document_message(
    file: str,
    name: str = "",
    caption: Optional[str] = None,
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
    media_paths: Optional[List[str]] = None,
    reply_to: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Build a message combining text and optional media attachments.

    Media paths are classified by extension:
    - ``.jpg``, ``.png``, ``.gif``, ``.webp`` → image
    - ``.mp3``, ``.ogg``, ``.wav``, ``.silk``, ``.amr`` → voice
    - ``.mp4``, ``.avi``, ``.mkv`` → video
    - Everything else → file
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
    """Convert a local file path to a ``file:///`` URI."""
    import os
    abspath = os.path.abspath(path)
    # On Windows, paths start with drive letter — need extra slash
    if not abspath.startswith("/"):
        abspath = "/" + abspath.replace("\\", "/")
    return f"file://{abspath}"
