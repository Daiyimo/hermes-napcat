# NapCat Adapter: Skill Auto-Discovery Integration Summary

## What Was Changed

This document summarizes the integration of skill auto-discovery and channel-specific system prompts into the NapCat adapter.

### Files Modified

#### 1. `adapter.py`

**Imports Added (lines 61-62):**
```python
resolve_channel_prompt,
resolve_channel_skills,
```

**Channel Resolution Code (lines 910-916):**
```python
# ------------------------------------------------------------------
# Resolve channel-specific prompts and skills
# ------------------------------------------------------------------
config_extra = self.config.extra or {}
channel_prompt = resolve_channel_prompt(config_extra, chat_id)
auto_skills = resolve_channel_skills(config_extra, chat_id)
```

**MessageEvent Creation Updated (lines 928-929):**
```python
event = MessageEvent(
    text=text,
    message_type=msg_type,
    source=source,
    raw_message=data,
    message_id=message_id,
    media_urls=media_urls,
    media_types=media_types,
    reply_to_message_id=reply_to_id,
    channel_prompt=channel_prompt,      # NEW
    auto_skill=auto_skills,              # NEW
)
```

**Module Docstring Updated (lines 21-42):**
- Added documentation for `channel_prompts` configuration
- Added documentation for `channel_skill_bindings` configuration
- Added example `config.yaml` showing both features

### Files Created

#### 1. `tests/test_skill_discovery.py`

Comprehensive test suite covering:
- Channel prompt resolution (exact match, no match, empty config)
- Channel skill resolution (single, multiple, deduplication, mixed formats)
- Mock implementations of resolve functions
- Test coverage: 6 tests, all passing ✓

#### 2. `docs/skill-discovery.md`

Detailed documentation covering:
- Overview and use cases
- Configuration reference
- How it works (message flow, resolution logic)
- Example configurations (gaming, multilingual, per-user)
- Troubleshooting guide

## Integration Points

### 1. Channel Prompts

- **Source**: `config.yaml` → `platforms.napcat.extra.channel_prompts`
- **Lookup**: `resolve_channel_prompt(config_extra, chat_id)`
- **Behavior**: 
  - Overrides default system prompt for the channel
  - Applied at gateway API call time
  - Enables per-channel personas

### 2. Skill Auto-Discovery

- **Source**: `config.yaml` → `platforms.napcat.extra.channel_skill_bindings`
- **Lookup**: `resolve_channel_skills(config_extra, chat_id)`
- **Behavior**:
  - Auto-loads skills when message arrives in configured channel
  - Supports both single (`skill`) and multiple (`skills`) formats
  - Gateway injects skills into conversation context
  - Deduplicates skill names

### 3. MessageEvent

Enhanced with two new optional fields:
- `channel_prompt: str | None` - Channel-specific system prompt
- `auto_skill: list[str] | None` - Auto-loaded skill names

These fields are populated by the adapter and passed to the gateway's message processing pipeline.

## Configuration Example

```yaml
platforms:
  napcat:
    enabled: true
    token: "your_bot_token"
    extra:
      http_url: "http://127.0.0.1:3000"
      ws_url: "ws://127.0.0.1:3001"
      
      # Per-channel system prompts
      channel_prompts:
        "123456789": "You are helpful in this gaming group"
        "987654321": "Professional assistant for work discussions"
      
      # Per-channel skill bindings
      channel_skill_bindings:
        - id: "123456789"
          skills: ["web-search", "calculator"]
        - id: "987654321"
          skill: "translator"
```

## How Skills Get Loaded

1. **NapCat receives message** → `_handle_message_event_inner()`
2. **Adapter resolves** `channel_prompt` and `auto_skills`
3. **MessageEvent created** with these fields
4. **Gateway processes** the event via `handle_message()`
5. **Gateway's `_process_message()`** checks `event.auto_skill`
6. **For each skill**: 
   - `_load_skill_payload(skill_name)` loads the skill
   - `_build_skill_message()` builds the skill context
   - Skill is injected into the conversation
7. **API call includes** the loaded skills and channel prompt

## Testing

All functionality tested with 6 passing tests:
```
tests/test_skill_discovery.py::TestChannelPromptResolution::test_resolve_channel_prompt_exact_match PASSED
tests/test_skill_discovery.py::TestChannelPromptResolution::test_resolve_channel_prompt_no_match PASSED
tests/test_skill_discovery.py::TestChannelPromptResolution::test_resolve_channel_prompt_empty_config PASSED
tests/test_skill_discovery.py::TestChannelPromptResolution::test_resolve_channel_skills_single_skill PASSED
tests/test_skill_discovery.py::TestChannelPromptResolution::test_resolve_channel_skills_multiple_skills PASSED
tests/test_skill_discovery.py::TestChannelPromptResolution::test_resolve_channel_skills_mixed_formats PASSED
```

## Backward Compatibility

✓ **Fully backward compatible**
- Both fields are optional (default to `None`)
- Existing configurations work unchanged
- New features activate only when configured
- No breaking changes to API

## Benefits

1. **Per-Channel Customization**: Different bot behavior per group
2. **Skill Management**: Enable/disable skills per channel
3. **Context-Aware Responses**: Channel-specific system prompts
4. **Flexible Configuration**: YAML-based, no code changes needed
5. **Gateway Integration**: Works seamlessly with existing infrastructure

## References

- **Source**: `gateway/platforms/base.py` (resolve_channel_prompt, resolve_channel_skills)
- **Gateway Processing**: `gateway/run.py` (auto_skill injection in _process_message)
- **Skills System**: `tools/skills_tool.py` (_load_skill_payload)
- **Configuration**: `gateway/config.py` (PlatformConfig.extra)
