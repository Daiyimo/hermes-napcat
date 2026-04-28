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
