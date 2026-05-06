# Changelog

All notable changes to **hermes-napcat** are documented here.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Added
- `tests/` directory with 101 unit tests covering `utils`, `message_builder`, `event_parser`, `group_commands` (99 pass, 2 skipped on non-Unix)
- Runtime statistics counters in `NapCatAdapter` (`messages_received`, `messages_sent`, `errors`, `dedup_skipped`, `latency_samples`)
- `/status` command now shows live message statistics and average processing latency
- `_maybe_wrap_reply()` helper method — eliminates duplicated reply-wrapping logic across `send_image`, `send_voice`, `send_video`, `send_document`
- New constants: `EMOJI_THINKING`, `EMOJI_SUCCESS`, `EMOJI_FAILURE`, `MUTE_MAX_MINUTES`, `CHUNK_SEND_DELAY`
- `AdminCmdContext.stats` field — adapter passes live stats into command context
- `CONTRIBUTING.md` — developer guide, test instructions, code conventions

### Fixed
- **Critical**: `utils.api_call` error detection used `and` instead of `or`; a response with `retcode != 0` but `status == "ok"` (or vice-versa) was silently accepted as success
- `_dedup_check` rebuilt the entire dict on every overflow (O(n)); replaced with `collections.OrderedDict` for O(1) eviction
- `_local_file_uri` on Windows produced an incorrectly encoded URI for paths containing spaces or special characters; now uses `urllib.parse.quote`
- Admin list was re-parsed from the environment variable on every `is_admin()` call; now cached after first load
- `/mute` and `/kick` used `logger.warning` for unexpected exceptions; changed to `logger.error` with `exc_info=True`

### Changed
- `import httpx` moved from function-local scope to module top-level in `utils.py`; `api_call` / `api_call_raw` parameters annotated as `httpx.AsyncClient`
- Magic emoji IDs `"76"` / `"326"` replaced by `EMOJI_SUCCESS` / `EMOJI_FAILURE` constants
- Hard-coded `asyncio.sleep(0.3)` between message chunks replaced by `CHUNK_SEND_DELAY` constant
- `MUTE_MAX_MINUTES` constant replaces the bare literal `43200` in `/mute` command

---

## [1.0.0] — 2026-04-01

### Added
- Initial public release
- OneBot 11 adapter for NapCat with forward and reverse WebSocket modes
- Full message support: text, image, voice, video, file, reply, @mention, QQ face emoji
- Forwarded-message expansion (`/get_forward_msg`)
- Processing-state emoji reactions (thinking → 👍 / 😡)
- Group admin commands: `/mute`, `/ban`, `/kick`, `/status`, `/ping`, `/help`
- User allowlist and per-group allowlist authorization
- Message deduplication (5-second window, up to 1000 cached IDs)
- Long-message chunking (>4500 chars split with 300 ms inter-chunk delay)
- SSRF protection on media downloads
- Exponential-backoff reconnection (up to 100 attempts, capped at 60 s)
- `plugin.yaml` for automatic platform discovery — no manual patching required
- Full suite of operational scripts: `install.sh`, `diagnose.sh`, `health-check.sh`, `logs-tail.sh`, `quick-setup-env.sh`, `test-message.sh`
- Comprehensive README covering installation, configuration, NapCat setup, Docker, troubleshooting
