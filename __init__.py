"""
NapCat platform adapter package.

QQ messaging via the OneBot 11 protocol, backed by NapCat.

Re-exports:
    - ``NapCatAdapter`` — the main adapter class
    - ``check_napcat_requirements`` — runtime dependency check
"""

from .adapter import NapCatAdapter, check_napcat_requirements  # noqa: F401

__all__ = [
    "NapCatAdapter",
    "check_napcat_requirements",
]


# ---------------------------------------------------------------------------
# Platform registration — auto-discovered by "hermes gateway run"
# ---------------------------------------------------------------------------

def _register() -> None:
    """Register NapCat as a plugin platform with the Hermes gateway."""
    try:
        from gateway.platform_registry import platform_registry, PlatformEntry  # type: ignore[import-untyped]
    except ImportError:
        return  # Not running inside Hermes gateway

    platform_registry.register(PlatformEntry(
        name="napcat",
        label="NapCat (QQ)",
        description="QQ messaging via NapCat OneBot 11 protocol",
        adapter_factory=lambda cfg: NapCatAdapter(cfg),
        check_fn=check_napcat_requirements,
        validate_config=lambda cfg: bool(
            (cfg.extra or {}).get("http_url") and (cfg.extra or {}).get("ws_url")
        ),
        is_connected=lambda cfg: bool(
            (cfg.extra or {}).get("http_url") and (cfg.extra or {}).get("ws_url")
        ),
        required_env=["NAPCAT_HTTP_URL", "NAPCAT_WS_URL"],
        install_hint="pip install websockets httpx",
        allowed_users_env="NAPCAT_ALLOWED_USERS",
        allow_all_env="NAPCAT_ALLOW_ALL_USERS",
        max_message_length=4500,
        pii_safe=False,
    ))


_register()
