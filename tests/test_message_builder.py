"""
Tests for napcat/message_builder.py
"""

from __future__ import annotations

import sys

import pytest
from napcat.message_builder import (
    _local_file_uri,
    at_segment,
    build_document_message,
    build_image_message,
    build_mixed_message,
    build_reply_message,
    build_text_message,
    build_video_message,
    build_voice_message,
    file_segment,
    image_segment,
    record_segment,
    reply_segment,
    text_segment,
    video_segment,
)

# ---------------------------------------------------------------------------
# Segment factories
# ---------------------------------------------------------------------------


class TestSegmentFactories:
    def test_text_segment(self):
        s = text_segment("hello")
        assert s == {"type": "text", "data": {"text": "hello"}}

    def test_image_segment(self):
        s = image_segment("http://example.com/img.png")
        assert s["type"] == "image"
        assert s["data"]["file"] == "http://example.com/img.png"

    def test_record_segment(self):
        s = record_segment("file:///audio.ogg")
        assert s["type"] == "record"

    def test_video_segment(self):
        s = video_segment("file:///video.mp4")
        assert s["type"] == "video"

    def test_file_segment_with_name(self):
        s = file_segment("file:///doc.pdf", name="report.pdf")
        assert s["type"] == "file"
        assert s["data"]["name"] == "report.pdf"

    def test_file_segment_without_name(self):
        s = file_segment("file:///doc.pdf")
        assert "name" not in s["data"]

    def test_at_segment_qq(self):
        s = at_segment("123456")
        assert s["type"] == "at"
        assert s["data"]["qq"] == "123456"

    def test_at_segment_all(self):
        s = at_segment("all")
        assert s["data"]["qq"] == "all"

    def test_reply_segment(self):
        s = reply_segment("999")
        assert s["type"] == "reply"
        assert s["data"]["id"] == "999"


# ---------------------------------------------------------------------------
# High-level builders
# ---------------------------------------------------------------------------


class TestBuildTextMessage:
    def test_single_text_segment(self):
        result = build_text_message("hi there")
        assert len(result) == 1
        assert result[0]["type"] == "text"
        assert result[0]["data"]["text"] == "hi there"


class TestBuildImageMessage:
    def test_image_only(self):
        result = build_image_message("http://img.test/x.png")
        assert len(result) == 1
        assert result[0]["type"] == "image"

    def test_image_with_caption(self):
        result = build_image_message("http://img.test/x.png", caption="A caption")
        assert len(result) == 2
        assert result[1]["type"] == "text"
        assert result[1]["data"]["text"] == "A caption"

    def test_none_caption_omitted(self):
        assert len(build_image_message("url", caption=None)) == 1


class TestBuildVoiceMessage:
    def test_single_record_segment(self):
        result = build_voice_message("file:///voice.silk")
        assert len(result) == 1
        assert result[0]["type"] == "record"


class TestBuildVideoMessage:
    def test_video_with_caption(self):
        result = build_video_message("file:///v.mp4", caption="watch")
        assert result[0]["type"] == "video"
        assert result[1]["data"]["text"] == "watch"


class TestBuildDocumentMessage:
    def test_doc_with_name_and_caption(self):
        result = build_document_message("file:///a.pdf", name="a.pdf", caption="here")
        assert result[0]["type"] == "file"
        assert result[0]["data"]["name"] == "a.pdf"
        assert result[1]["data"]["text"] == "here"


class TestBuildReplyMessage:
    def test_prepends_reply_segment(self):
        content = [text_segment("hello")]
        result = build_reply_message("42", content)
        assert result[0]["type"] == "reply"
        assert result[0]["data"]["id"] == "42"
        assert result[1] == content[0]

    def test_original_list_not_mutated(self):
        content = [text_segment("hi")]
        build_reply_message("1", content)
        assert len(content) == 1


class TestBuildMixedMessage:
    def test_text_only(self):
        result = build_mixed_message("hello")
        assert len(result) == 1
        assert result[0]["type"] == "text"

    def test_image_by_ext(self):
        result = build_mixed_message("", media_paths=["/tmp/photo.png"])
        assert any(s["type"] == "image" for s in result)

    def test_audio_by_ext(self):
        result = build_mixed_message("", media_paths=["/tmp/voice.mp3"])
        assert any(s["type"] == "record" for s in result)

    def test_video_by_ext(self):
        result = build_mixed_message("", media_paths=["/tmp/clip.mp4"])
        assert any(s["type"] == "video" for s in result)

    def test_unknown_ext_is_file(self):
        result = build_mixed_message("", media_paths=["/tmp/data.xyz"])
        assert any(s["type"] == "file" for s in result)

    def test_reply_to_prepended(self):
        result = build_mixed_message("txt", reply_to="77")
        assert result[0]["type"] == "reply"

    def test_no_media_no_extra_segments(self):
        result = build_mixed_message("only text", media_paths=[])
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _local_file_uri
# ---------------------------------------------------------------------------


class TestLocalFileUri:
    def test_unix_path(self):
        if sys.platform == "win32":
            pytest.skip("Unix-only")
        uri = _local_file_uri("/home/user/photo.png")
        assert uri == "file:///home/user/photo.png"

    def test_unix_space_encoded(self):
        if sys.platform == "win32":
            pytest.skip("Unix-only")
        uri = _local_file_uri("/home/user/my file.png")
        assert "%20" in uri
        assert " " not in uri

    def test_windows_path(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        import os

        monkeypatch.setattr(os.path, "abspath", lambda p: r"C:\Users\foo\bar baz.png")
        uri = _local_file_uri(r"C:\Users\foo\bar baz.png")
        assert uri.startswith("file:///C:/Users/foo/")
        assert "%20" in uri
        assert "\\" not in uri
