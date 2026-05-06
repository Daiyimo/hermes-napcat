"""
Tests for napcat/event_parser.py
"""

from __future__ import annotations

import pytest
from napcat.event_parser import (
    _FACE_MAP,
    _clean_cq_codes,
    check_at_bot,
    extract_forward_ids,
    extract_reply_id,
    parse_message_segments,
)

# ---------------------------------------------------------------------------
# check_at_bot
# ---------------------------------------------------------------------------


class TestCheckAtBot:
    def test_returns_true_when_self_mentioned(self):
        segs = [{"type": "at", "data": {"qq": "12345"}}]
        assert check_at_bot(segs, "12345") is True

    def test_returns_false_for_different_qq(self):
        segs = [{"type": "at", "data": {"qq": "99999"}}]
        assert check_at_bot(segs, "12345") is False

    def test_at_all_does_not_match_self_id(self):
        # "all" is a broadcast — it should never count as mentioning the bot's QQ
        segs = [{"type": "at", "data": {"qq": "all"}}]
        assert check_at_bot(segs, "12345") is False

    def test_empty_segments(self):
        assert check_at_bot([], "12345") is False

    def test_non_at_segment_ignored(self):
        segs = [{"type": "text", "data": {"text": "@12345"}}]
        assert check_at_bot(segs, "12345") is False


# ---------------------------------------------------------------------------
# extract_reply_id
# ---------------------------------------------------------------------------


class TestExtractReplyId:
    def test_finds_reply_id(self):
        segs = [{"type": "reply", "data": {"id": "555"}}]
        assert extract_reply_id(segs) == "555"

    def test_returns_none_when_absent(self):
        assert extract_reply_id([{"type": "text", "data": {"text": "hi"}}]) is None

    def test_returns_none_on_empty(self):
        assert extract_reply_id([]) is None

    def test_converts_int_id_to_str(self):
        segs = [{"type": "reply", "data": {"id": 42}}]
        result = extract_reply_id(segs)
        assert result == "42" and isinstance(result, str)


# ---------------------------------------------------------------------------
# extract_forward_ids
# ---------------------------------------------------------------------------


class TestExtractForwardIds:
    def test_single_id(self):
        segs = [{"type": "forward", "data": {"id": "abc"}}]
        assert extract_forward_ids(segs) == ["abc"]

    def test_multiple_ids(self):
        segs = [
            {"type": "forward", "data": {"id": "id1"}},
            {"type": "text", "data": {"text": "hi"}},
            {"type": "forward", "data": {"id": "id2"}},
        ]
        assert extract_forward_ids(segs) == ["id1", "id2"]

    def test_empty(self):
        assert extract_forward_ids([]) == []


# ---------------------------------------------------------------------------
# _clean_cq_codes
# ---------------------------------------------------------------------------


class TestCleanCQCodes:
    def test_face_replaced_with_placeholder(self):
        result = _clean_cq_codes("[CQ:face,id=14]hello")
        assert "[表情]" in result
        assert "CQ:face" not in result

    def test_image_replaced_with_placeholder(self):
        result = _clean_cq_codes("[CQ:image,file=abc.png]text")
        assert "[图片]" in result
        assert "CQ:image" not in result

    def test_unknown_cq_code_removed(self):
        result = _clean_cq_codes("[CQ:poke,qq=123]hello")
        assert "CQ:poke" not in result
        assert "hello" in result

    def test_plain_text_unchanged(self):
        assert _clean_cq_codes("just plain text") == "just plain text"

    def test_strips_surrounding_whitespace(self):
        assert _clean_cq_codes("  hello  ") == "hello"


# ---------------------------------------------------------------------------
# parse_message_segments
# ---------------------------------------------------------------------------


class TestParseMessageSegments:
    def test_empty_returns_empty(self):
        text, media = parse_message_segments([])
        assert text == "" and media == []

    def test_text_segment(self):
        segs = [{"type": "text", "data": {"text": "Hello, world!"}}]
        text, media = parse_message_segments(segs)
        assert text == "Hello, world!"
        assert media == []

    def test_image_http_url(self):
        segs = [{"type": "image", "data": {"url": "http://example.com/img.jpg"}}]
        text, media = parse_message_segments(segs)
        assert len(media) == 1
        assert media[0]["type"] == "image"
        assert media[0]["url"] == "http://example.com/img.jpg"

    def test_at_segment_with_name(self):
        segs = [{"type": "at", "data": {"qq": "123", "name": "Alice"}}]
        text, _ = parse_message_segments(segs)
        assert "@Alice" in text

    def test_at_segment_no_name(self):
        segs = [{"type": "at", "data": {"qq": "999"}}]
        text, _ = parse_message_segments(segs)
        assert "@999" in text

    def test_at_all(self):
        segs = [{"type": "at", "data": {"qq": "all"}}]
        text, _ = parse_message_segments(segs)
        assert "@all" in text

    def test_known_face_id(self):
        face_id = 76  # thumbs up
        segs = [{"type": "face", "data": {"id": str(face_id)}}]
        text, _ = parse_message_segments(segs)
        assert _FACE_MAP[face_id] in text

    def test_unknown_face_uses_placeholder(self):
        segs = [{"type": "face", "data": {"id": "9999"}}]
        text, _ = parse_message_segments(segs)
        assert "[face:9999]" in text

    def test_forward_no_texts_placeholder(self):
        segs = [{"type": "forward", "data": {"id": "fwd1"}}]
        text, _ = parse_message_segments(segs)
        assert "[转发消息]" in text

    def test_forward_with_texts_expanded(self):
        segs = [{"type": "forward", "data": {"id": "fwd1"}}]
        text, _ = parse_message_segments(segs, forward_texts={"fwd1": "expanded"})
        assert "expanded" in text

    def test_mixed_text_and_image(self):
        segs = [
            {"type": "text", "data": {"text": "Look: "}},
            {"type": "image", "data": {"url": "http://x.com/a.png"}},
        ]
        text, media = parse_message_segments(segs)
        assert "Look:" in text
        assert len(media) == 1
