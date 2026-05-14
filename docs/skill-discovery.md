# Skill Auto-Discovery and Channel Prompts

The NapCat adapter now supports automatic skill loading and per-channel system prompts, enabling rich channel-specific behavior in your QQ bot.

## Overview

### Channel Prompts

Channel prompts are ephemeral system prompts that are applied at API call time, **overriding the default system prompt** for a specific channel. This allows you to customize the bot's behavior per group or user.

**Use cases:**
- Different personas per group (gaming group bot vs. work group bot)
- Specialized guidance per channel context
- Language-specific prompts for multilingual groups

### Skill Auto-Loading

Skill bindings automatically inject specified skills into conversations when a message arrives in a configured channel. The gateway's message processing engine loads and injects these skills at message processing time.

**Use cases:**
- Web search enabled only in certain channels
- Calculator available everywhere
- Translator only for international groups
- Different skill sets per community

## Configuration

All configuration is done via `config.yaml` under `platforms.napcat.extra`:

### Channel Prompts

```yaml
platforms:
  napcat:
    enabled: true
    token: "your_bot_token"
    extra:
      http_url: "http://127.0.0.1:3000"
      ws_url: "ws://127.0.0.1:3001"
      channel_prompts:
        "123456789": "You are a helpful assistant in the gaming group. Keep responses concise and fun."
        "987654321": "You are a professional assistant. Provide detailed, accurate information."
```

**Configuration reference:**

- `channel_prompts`: Dictionary mapping chat IDs to prompt strings
  - **Key**: Chat ID (string, group number or user QQ)
  - **Value**: System prompt text (will override default system prompt)

### Channel Skill Bindings

```yaml
platforms:
  napcat:
    enabled: true
    token: "your_bot_token"
    extra:
      http_url: "http://127.0.0.1:3000"
      ws_url: "ws://127.0.0.1:3001"
      channel_skill_bindings:
        # Single skill
        - id: "123456789"
          skill: "calculator"
        
        # Multiple skills
        - id: "987654321"
          skills: ["web-search", "translator", "image-analysis"]
        
        # User-specific
        - id: "111222333"
          skill: "web-search"
```

**Configuration reference:**

- `channel_skill_bindings`: List of binding rules
  - **id**: Chat ID (group number or user QQ)
  - **skill**: Single skill name (string) - use when binding one skill
  - **skills**: Multiple skill names (list) - use when binding multiple skills
  
Both `skill` and `skills` can be used in the same binding:

```yaml
channel_skill_bindings:
  - id: "123456789"
    skill: "calculator"
    skills: ["web-search", "translator"]  # All three skills will be loaded
```

## How It Works

### Message Flow

1. **Message arrives** in a channel → NapCat WebSocket event
2. **NapCatAdapter** receives the event
3. **Channel resolution** occurs:
   - `resolve_channel_prompt()` looks up channel-specific prompt
   - `resolve_channel_skills()` looks up channel-specific skill bindings
4. **MessageEvent created** with:
   - `channel_prompt`: Resolved prompt (or `None`)
   - `auto_skill`: List of skill names (or `None`)
5. **Gateway processes** the message:
   - Skills are loaded via `_load_skill_payload()`
   - Skills are injected into the conversation
   - Channel prompt is applied if present
6. **API call** includes loaded skills and channel prompt context

### Prompt Resolution

The adapter resolves prompts in this order:

1. **Exact match**: Look for the received chat ID in `channel_prompts`
2. **Parent fallback** (if applicable): Look for parent channel ID
3. **None**: No channel-specific prompt

### Skill Resolution

The adapter resolves skills by:

1. **Finding all bindings** where `binding.id == channel_id`
2. **Collecting skills** from both `skill` and `skills` fields
3. **Deduplicating** the skill list (preserves order)
4. **Returning** the deduplicated list, or `None` if no bindings matched

## Example Configurations

### Gaming Group with Web Search

```yaml
platforms:
  napcat:
    enabled: true
    token: "your_token"
    extra:
      http_url: "http://127.0.0.1:3000"
      ws_url: "ws://127.0.0.1:3001"
      channel_prompts:
        "123456789": |
          You are a gaming bot for our group.
          Help with game strategies, mechanics, and recommendations.
          Keep responses fun and engaging!
      channel_skill_bindings:
        - id: "123456789"
          skills: ["web-search", "game-wiki"]
```

### Multilingual Support

```yaml
platforms:
  napcat:
    enabled: true
    token: "your_token"
    extra:
      http_url: "http://127.0.0.1:3000"
      ws_url: "ws://127.0.0.1:3001"
      channel_prompts:
        "111111111": "你是一个有帮助的中文助手。"  # Chinese group
        "222222222": "You are a helpful English assistant."  # English group
      channel_skill_bindings:
        - id: "111111111"
          skills: ["translator", "web-search"]
        - id: "222222222"
          skills: ["web-search", "calculator"]
```

### Per-User Customization

```yaml
platforms:
  napcat:
    enabled: true
    token: "your_token"
    extra:
      http_url: "http://127.0.0.1:3000"
      ws_url: "ws://127.0.0.1:3001"
      channel_skill_bindings:
        # Power user gets more skills
        - id: "987654321"
          skills: ["code-executor", "web-search", "translator", "calculator"]
        
        # Regular users get basic skills
        - id: "111222333"
          skills: ["web-search", "calculator"]
        
        # Guest gets minimal skills
        - id: "444555666"
          skill: "calculator"
```

## Notes

- **Chat ID format**: Use the string representation of QQ numbers (groups and users)
- **Skill availability**: Skills must be installed and not globally disabled
- **Performance**: Channel resolution is O(n) in the number of bindings; optimize for small binding lists
- **Fallback**: If a channel is not configured, the bot uses default behavior
- **Deduplication**: Duplicate skills are automatically removed from bindings

## Troubleshooting

### Skills not loading?

1. Check `config.yaml` syntax (YAML indentation is critical)
2. Verify the chat ID in `channel_skill_bindings` matches exactly
3. Ensure the skill name is correct and installed
4. Check logs for "resolve_channel_skills" messages

### Prompt not applied?

1. Verify the chat ID in `channel_prompts` is correct
2. Check `config.yaml` formatting
3. Ensure the prompt text is valid
4. Check gateway logs for "resolve_channel_prompt" messages

### How to verify configuration?

Add debug logging to check resolved values:

```python
# In adapter logs, you should see entries like:
# [NapCat:123456] Resolved channel_prompt for chat 123456789: "..."
# [NapCat:123456] Resolved auto_skills for chat 123456789: ["skill1", "skill2"]
```

## See Also

- [Gateway Platform Integration](../../gateway/platforms/README.md)
- [Skills System](../../tools/skills_tool.py)
- [NapCat Adapter README](../README.md)
