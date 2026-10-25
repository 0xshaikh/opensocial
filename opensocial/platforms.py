"""Platform registry, canonical character limits and counting rules.

The limits below are the documented hard caps of each platform's post
composer.  Everything else in the package (thread splitting, validation,
analytics compliance, the live web composer) derives from this single
table, so it can never drift out of sync.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Hard composer limits (real platform numbers).
# ---------------------------------------------------------------------------
PLATFORM_LIMITS: dict[str, int] = {
    "x": 280,
    "bluesky": 300,
    "mastodon": 500,
    "threads": 500,
    "tiktok": 2200,
    "instagram": 2200,
    "facebook": 5000,
    "linkedin": 3000,
    "google_business": 1500,
    "youtube": 5000,
    "pinterest": 500,
}

# Friendly names used by the CLI/web UI when talking to humans.
DISPLAY_NAMES: dict[str, str] = {
    "x": "X (Twitter)",
    "bluesky": "Bluesky",
    "mastodon": "Mastodon",
    "threads": "Threads",
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "facebook": "Facebook",
    "linkedin": "LinkedIn",
    "google_business": "Google Business",
    "youtube": "YouTube",
    "pinterest": "Pinterest",
}

# Aliases accepted anywhere a platform key is expected.
ALIASES: dict[str, str] = {
    "twitter": "x",
    "google": "google_business",
    "google_business_profile": "google_business",
    "thread": "threads",
    "face": "facebook",
    "li": "linkedin",
    "bsky": "bluesky",
    "yt": "youtube",
    "pin": "pinterest",
}

# ---------------------------------------------------------------------------
# Hashtag guidance. ``None`` == the platform imposes no guidance at all.
# ---------------------------------------------------------------------------
RECOMMENDED_HASHTAGS: dict[str, int | None] = {
    "linkedin": 3,
    "x": 2,
    "instagram": 5,
    "threads": 2,
    "tiktok": 2,
    "facebook": 2,
    "pinterest": 2,
    "mastodon": None,
    "bluesky": None,
    "google_business": None,
    "youtube": None,
}

# Platforms that enforce a hard cap; everything else is uncapped (None).
MAX_HASHTAGS: dict[str, int | None] = {
    "instagram": 30,
}

X_ONLY = {"x", "twitter"}


def valid_platform(platform: str) -> bool:
    """Return ``True`` when *platform* resolves to a known platform."""
    return resolve_platform(platform) is not None


def resolve_platform(platform: str) -> str | None:
    """Normalise *platform* to a canonical key, or ``None`` if unknown."""
    key = (platform or "").strip().lower()
    if key in PLATFORM_LIMITS:
        return key
    return ALIASES.get(key)


def platform_limit(platform: str) -> int:
    """Return the character limit for *platform* (raises on unknown keys)."""
    key = resolve_platform(platform)
    if key is None:
        raise ValueError(
            f"unknown platform {platform!r}; expected one of "
            f"{', '.join(sorted(PLATFORM_LIMITS))}"
        )
    return PLATFORM_LIMITS[key]


def recommended_hashtags(platform: str) -> int | None:
    key = resolve_platform(platform)
    if key is None:
        raise ValueError(f"unknown platform {platform!r}")
    return RECOMMENDED_HASHTAGS.get(key)


def max_hashtags(platform: str) -> int | None:
    key = resolve_platform(platform)
    if key is None:
        raise ValueError(f"unknown platform {platform!r}")
    return MAX_HASHTAGS.get(key)


# ---------------------------------------------------------------------------
# Character counting.
# ---------------------------------------------------------------------------

#: Code points that occupy two columns of the X composer grid.
_X_DOUBLE_WIDTH_SETS = (
    (0x1100, 0x115F),  # Hangul Jamo
    (0x2600, 0x27BF),  # Misc symbols and dingbats
    (0x2B00, 0x2BFF),  # Misc symbols and arrows
    (0x1F000, 0x1FAFF),  # emoji + supplementals
    (0x3040, 0x30FF),  # Hiragana / Katakana
    (0x2E80, 0x9FFF),  # CJK block
    (0xAC00, 0xD7A3),  # Hangul syllables
    (0xF900, 0xFAFF),  # CJK compat ideographs
)
_X_SINGLE_CHARS = frozenset((0x200D, 0x20E3, 0xFE0F))


def _is_x_double_width(code_point: int) -> bool:
    if code_point > 0xFFFF:  # astral plane
        return True
    if code_point in _X_SINGLE_CHARS:
        return False
    for lo, hi in _X_DOUBLE_WIDTH_SETS:
        if lo <= code_point <= hi:
            return True
    return False


def count_x(text: str) -> int:
    """Count *text* the way X does (most code points cost 1, many cost 2)."""
    total = 0
    for ch in text:
        total += 2 if _is_x_double_width(ord(ch)) else 1
    return total


def platform_count(platform: str, text: str) -> int:
    """Length of *text* as the platform's composer would measure it.

    Most platforms count Unicode code points.  X uses a word-wrap
    counter where emoji and CJK are wider than ordinary characters.
    """
    if text is None:
        return 0
    key = resolve_platform(platform)
    if key is None:
        raise ValueError(f"unknown platform {platform!r}")
    if key in X_ONLY:
        return count_x(text)
    return len(text)


def thread_prefix(part: int, total: int) -> str:
    """The ``1/5 ``-style prefix used by numbered threads."""
    return f"{part}/{total} "
