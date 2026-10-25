"""opensocial -- an open-source, local-first social content studio.

Compose, thread, schedule, review, and *export* social posts.
Local-first by design: SQLite storage, no API keys, no cloud, and
deliberately **no** network publishing.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .platforms import (  # noqa: F401
    DISPLAY_NAMES,
    MAX_HASHTAGS,
    PLATFORM_LIMITS,
    RECOMMENDED_HASHTAGS,
    platform_limit,
    platform_count,
    valid_platform,
)
from .store import Store  # noqa: F401

__all__ = [
    "__version__",
    "DISPLAY_NAMES",
    "PLATFORM_LIMITS",
    "RECOMMENDED_HASHTAGS",
    "MAX_HASHTAGS",
    "platform_limit",
    "platform_count",
    "valid_platform",
    "Store",
]
