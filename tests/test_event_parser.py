"""
Tests for napcat/event_parser.py
"""

from __future__ import annotations

import pytest
from napcat.event_parser import (
    _FACE_MAP,
    _clean_cq_codes,
    _extract_json_text,
    _extract_xml_text,
    _guess_audio_extension,
    _guess_extension,
    _resolve_media_url,
    check_at_bot,
    extract_forward_ids,
    extract_forward_text,
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


# ---------------------------------------------------------------------------
# _guess_extension
# ---------------------------------------------------------------------------


class TestGuessExtension:
    def test_jpg(self):
        assert _guess_extension("http://cdn.qq.com/img/photo.jpg") == ".jpg"

    def test_jpeg(self):
        assert _guess_extension("http://cdn.qq.com/img/photo.jpeg") == ".jpeg"

    def test_png(self):
        assert _guess_extension("http://cdn.qq.com/img/photo.png") == ".png"

    def test_gif(self):
        assert _guess_extension("http://cdn.qq.com/img/anim.gif") == ".gif"

    def test_webp(self):
        assert _guess_extension("http://cdn.qq.com/img/photo.webp") == ".webp"

    def test_bmp(self):
        assert _guess_extension("http://cdn.qq.com/img/photo.bmp") == ".bmp"

    def test_unknown_returns_default(self):
        assert _guess_extension("http://cdn.qq.com/img/photo.xyz") == ".jpg"

    def test_custom_default(self):
        assert _guess_extension("http://cdn.qq.com/img/photo.xyz", default=".png") == ".png"

    def test_case_insensitive(self):
        # URL path is lowercased before matching
        assert _guess_extension("http://cdn.qq.com/img/PHOTO.PNG") == ".png"

    def test_query_string_ignored(self):
        # Query params should not affect extension matching
        result = _guess_extension("http://cdn.qq.com/img/photo.jpg?x=1&y=2")
        assert result == ".jpg"


# ---------------------------------------------------------------------------
# _guess_audio_extension
# ---------------------------------------------------------------------------


class TestGuessAudioExtension:
    def test_silk(self):
        assert _guess_audio_extension("http://cdn.qq.com/voice/file.silk") == ".silk"

    def test_amr(self):
        assert _guess_audio_extension("http://cdn.qq.com/voice/file.amr") == ".amr"

    def test_mp3(self):
        assert _guess_audio_extension("http://cdn.qq.com/voice/file.mp3") == ".mp3"

    def test_ogg(self):
        assert _guess_audio_extension("http://cdn.qq.com/voice/file.ogg") == ".ogg"

    def test_wav(self):
        assert _guess_audio_extension("http://cdn.qq.com/voice/file.wav") == ".wav"

    def test_m4a(self):
        assert _guess_audio_extension("http://cdn.qq.com/voice/file.m4a") == ".m4a"

    def test_unknown_returns_default_silk(self):
        assert _guess_audio_extension("http://cdn.qq.com/voice/file.xyz") == ".silk"

    def test_custom_default(self):
        assert _guess_audio_extension("http://cdn.qq.com/voice/file.xyz", default=".ogg") == ".ogg"


# ---------------------------------------------------------------------------
# _resolve_media_url
# ---------------------------------------------------------------------------


class TestResolveMediaUrl:
    # ── CDN URL（最高优先级）──────────────────────────────────────

    def test_cdn_http_url_preferred(self):
        data = {
            "url": "http://cdn.qq.com/img.jpg",
            "path": "/local/path/img.jpg",
            "file": "file:///local/path/img.jpg",
        }
        url, is_local = _resolve_media_url(data)
        assert url == "http://cdn.qq.com/img.jpg"
        assert is_local is False

    def test_cdn_https_url(self):
        data = {"url": "https://cdn.qq.com/img.jpg"}
        url, is_local = _resolve_media_url(data)
        assert url == "https://cdn.qq.com/img.jpg"
        assert is_local is False

    def test_cdn_url_not_matched_if_not_http(self):
        # url 字段不是 http/https 时不应作为 CDN URL
        data = {"url": "ftp://cdn.qq.com/img.jpg", "file": "file_id_123"}
        url, is_local = _resolve_media_url(data)
        # 应降级到 file 字段
        assert url == "file_id_123"

    # ── path 字段（NapCat 4.18+ 本地路径）───────────────────────

    def test_path_unix_local(self):
        data = {"path": "/var/napcat/cache/img.jpg"}
        url, is_local = _resolve_media_url(data)
        assert url == "/var/napcat/cache/img.jpg"
        assert is_local is True

    def test_path_windows_local(self):
        data = {"path": "C:/napcat/cache/img.jpg"}
        url, is_local = _resolve_media_url(data)
        assert url == "C:/napcat/cache/img.jpg"
        assert is_local is True

    def test_path_ignored_if_not_absolute(self):
        # 相对路径不应被当作本地路径
        data = {"path": "relative/path/img.jpg", "file": "file_id_123"}
        url, is_local = _resolve_media_url(data)
        assert url == "file_id_123"

    # ── file 字段（多种格式）────────────────────────────────────

    def test_file_uri_stripped_to_local_path(self):
        data = {"file": "file:///var/napcat/cache/img.jpg"}
        url, is_local = _resolve_media_url(data)
        assert url == "/var/napcat/cache/img.jpg"
        assert is_local is True

    def test_file_http_url(self):
        data = {"file": "http://cdn.qq.com/img.jpg"}
        url, is_local = _resolve_media_url(data)
        assert url == "http://cdn.qq.com/img.jpg"
        assert is_local is False

    def test_file_unix_absolute_path(self):
        data = {"file": "/var/napcat/cache/img.jpg"}
        url, is_local = _resolve_media_url(data)
        assert url == "/var/napcat/cache/img.jpg"
        assert is_local is True

    def test_file_windows_absolute_path(self):
        data = {"file": "C:/napcat/cache/img.jpg"}
        url, is_local = _resolve_media_url(data)
        assert url == "C:/napcat/cache/img.jpg"
        assert is_local is True

    def test_file_bare_id_treated_as_non_local(self):
        # 裸 file_id（没有路径特征）应当作远程 ID，由 API 处理
        data = {"file": "abc123def456"}
        url, is_local = _resolve_media_url(data)
        assert url == "abc123def456"
        assert is_local is False

    # ── 空/缺字段 ───────────────────────────────────────────────

    def test_all_empty_returns_empty(self):
        url, is_local = _resolve_media_url({})
        assert url == ""
        assert is_local is False

    def test_empty_url_falls_through_to_file(self):
        data = {"url": "", "file": "http://cdn.qq.com/img.jpg"}
        url, is_local = _resolve_media_url(data)
        assert url == "http://cdn.qq.com/img.jpg"
        assert is_local is False


# ---------------------------------------------------------------------------
# extract_forward_text
# ---------------------------------------------------------------------------


class TestExtractForwardText:
    def test_none_returns_empty_placeholder(self):
        assert extract_forward_text(None) == "[转发消息: 内容为空]"

    def test_empty_dict_returns_empty_placeholder(self):
        assert extract_forward_text({}) == "[转发消息: 内容为空]"

    def test_empty_messages_list(self):
        assert extract_forward_text({"messages": []}) == "[转发消息: 内容为空]"

    def test_single_text_message(self):
        data = {
            "messages": [
                {
                    "sender": {"nickname": "Alice"},
                    "content": [{"type": "text", "data": {"text": "Hello"}}],
                }
            ]
        }
        result = extract_forward_text(data)
        assert "[转发聊天记录]:" in result
        assert "Alice" in result
        assert "Hello" in result

    def test_sender_card_preferred_over_nickname(self):
        data = {
            "messages": [
                {
                    "sender": {"card": "群昵称", "nickname": "真实昵称"},
                    "content": "text",
                }
            ]
        }
        result = extract_forward_text(data)
        assert "群昵称" in result
        assert "真实昵称" not in result

    def test_fallback_to_user_id_when_no_name(self):
        data = {
            "messages": [
                {
                    "sender": {"user_id": 99999},
                    "content": "some text",
                }
            ]
        }
        result = extract_forward_text(data)
        assert "99999" in result

    def test_string_content_cleaned(self):
        data = {
            "messages": [
                {
                    "sender": {"nickname": "Bob"},
                    "content": "[CQ:face,id=14]hello",
                }
            ]
        }
        result = extract_forward_text(data)
        assert "hello" in result
        assert "CQ:face" not in result

    def test_image_segment_replaced(self):
        data = {
            "messages": [
                {
                    "sender": {"nickname": "Bob"},
                    "content": [{"type": "image", "data": {}}],
                }
            ]
        }
        result = extract_forward_text(data)
        assert "[图片]" in result

    def test_max_items_respected(self):
        messages = [{"sender": {"nickname": f"User{i}"}, "content": f"msg{i}"} for i in range(20)]
        result = extract_forward_text({"messages": messages}, max_items=3)
        assert "msg0" in result
        assert "msg2" in result
        assert "msg3" not in result

    def test_long_preview_truncated(self):
        data = {
            "messages": [
                {
                    "sender": {"nickname": "Alice"},
                    "content": "x" * 300,
                }
            ]
        }
        result = extract_forward_text(data, max_preview=50)
        # 每行格式是 "Name: content"，content 被截断后会有 "…"
        assert "…" in result

    def test_msgs_key_fallback(self):
        # 某些 NapCat 版本返回 msgs 而不是 messages
        data = {"msgs": [{"sender": {"nickname": "Charlie"}, "content": "hi there"}]}
        result = extract_forward_text(data)
        assert "Charlie" in result
        assert "hi there" in result

    def test_nested_forward_skipped(self):
        data = {
            "messages": [
                {
                    "sender": {"nickname": "Alice"},
                    "content": [{"type": "forward", "data": {"id": "nested"}}],
                }
            ]
        }
        result = extract_forward_text(data)
        # 嵌套转发内容被跳过，不会导致递归；整体结果为空占位符
        assert result == "[转发消息: 内容为空]"


# ---------------------------------------------------------------------------
# _extract_json_text
# ---------------------------------------------------------------------------


class TestExtractJsonText:
    def test_desc_field_in_meta(self):
        """Music share cards embed desc inside a meta sub-object."""
        import json

        payload = {"meta": {"music": {"desc": "告白气球 - 周杰伦", "title": "告白气球"}}}
        data = {"data": json.dumps(payload)}
        result = _extract_json_text(data)
        assert result == "[分享: 告白气balloon - 周杰伦]" or "告白气球" in result

    def test_desc_field_in_meta_real(self):
        import json

        payload = {"meta": {"music": {"desc": "告白气球 - 周杰伦"}}}
        data = {"data": json.dumps(payload)}
        assert _extract_json_text(data) == "[分享: 告白气球 - 周杰伦]"

    def test_prompt_top_level(self):
        import json

        payload = {"prompt": "查看链接"}
        data = {"data": json.dumps(payload)}
        assert _extract_json_text(data) == "[分享: 查看链接]"

    def test_title_top_level(self):
        import json

        payload = {"title": "B站视频"}
        data = {"data": json.dumps(payload)}
        assert _extract_json_text(data) == "[分享: B站视频]"

    def test_empty_data_returns_fallback(self):
        assert _extract_json_text({}) == "[分享]"
        assert _extract_json_text({"data": ""}) == "[分享]"

    def test_invalid_json_returns_fallback(self):
        assert _extract_json_text({"data": "{not valid json"}) == "[分享]"

    def test_no_known_fields_returns_fallback(self):
        import json

        payload = {"app": "com.tencent.something", "ver": "1.0"}
        data = {"data": json.dumps(payload)}
        assert _extract_json_text(data) == "[分享]"

    def test_json_segment_in_parse_message_segments(self):
        import json

        payload = {"meta": {"detail_1": {"title": "GitHub Trending"}}}
        segs = [{"type": "json", "data": {"data": json.dumps(payload)}}]
        text, media = parse_message_segments(segs)
        assert "GitHub Trending" in text
        assert media == []


# ---------------------------------------------------------------------------
# _extract_xml_text
# ---------------------------------------------------------------------------


class TestExtractXmlText:
    def test_title_tag(self):
        data = {"data": "<msg><title>群公告更新</title></msg>"}
        assert _extract_xml_text(data) == "[卡片: 群公告更新]"

    def test_summary_tag(self):
        data = {"data": "<msg><summary>活动通知内容</summary></msg>"}
        assert _extract_xml_text(data) == "[卡片: 活动通知内容]"

    def test_brief_tag(self):
        data = {"data": "<msg><brief>简短说明</brief></msg>"}
        assert _extract_xml_text(data) == "[卡片: 简短说明]"

    def test_title_preferred_over_summary(self):
        data = {"data": "<msg><title>主标题</title><summary>副标题</summary></msg>"}
        # title has higher priority
        assert _extract_xml_text(data) == "[卡片: 主标题]"

    def test_empty_data_returns_fallback(self):
        assert _extract_xml_text({}) == "[卡片]"
        assert _extract_xml_text({"data": ""}) == "[卡片]"

    def test_no_known_tags_returns_fallback(self):
        data = {"data": "<msg><action>click</action></msg>"}
        assert _extract_xml_text(data) == "[卡片]"

    def test_xml_segment_in_parse_message_segments(self):
        segs = [{"type": "xml", "data": {"data": "<msg><title>红包</title></msg>"}}]
        text, media = parse_message_segments(segs)
        assert "红包" in text
        assert media == []
