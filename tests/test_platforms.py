"""Platform registry and character counting."""

from __future__ import annotations

import pytest

from opensocial.platforms import (
    DISPLAY_NAMES,
    MAX_HASHTAGS,
    PLATFORM_LIMITS,
    RECOMMENDED_HASHTAGS,
    count_x,
    platform_count,
    platform_limit,
    recommended_hashtags,
    resolve_platform,
    thread_prefix,
    valid_platform,
)


def test_limit_table_matches_documented_platform_limits():
    assert PLATFORM_LIMITS["x"] == 280
    assert PLATFORM_LIMITS["bluesky"] == 300
    assert PLATFORM_LIMITS["mastodon"] == 500
    assert PLATFORM_LIMITS["threads"] == 500
    assert PLATFORM_LIMITS["tiktok"] == 2200
    assert PLATFORM_LIMITS["instagram"] == 2200
    assert PLATFORM_LIMITS["facebook"] == 5000
    assert PLATFORM_LIMITS["linkedin"] == 3000
    assert PLATFORM_LIMITS["google_business"] == 1500
    assert PLATFORM_LIMITS["youtube"] == 5000
    assert PLATFORM_LIMITS["pinterest"] == 500
    assert len(PLATFORM_LIMITS) == 11


def test_non_x_platforms_count_code_points():
    text = "héllo 🚀"  # 5 code points + emoji
    assert platform_count("facebook", text) == len(text)
    assert platform_count("linkedin", "abc") == 3


def test_x_counts_emoji_and_cjk_as_two():
    assert count_x("abc") == 3
    assert count_x("a🚀") == 3          # 'a' is 1, the rocket is 2
    assert count_x("日本") == 4          # CJK occupies two columns
    assert platform_count("x", "a🚀日本") == 7  # 1 + 2 + 2 + 2


def test_x_counts_plain_ascii_as_one():
    assert platform_count("x", "hello world") == 11


def test_x_counts_asian_hangul_and_emoji_ranges_as_two():
    assert count_x("\uac00") == 2       # 가 Hangul syllable
    assert count_x("\u30f3") == 2       # ㇳ halfwidth katakana
    assert count_x("\u1f0a0") == 2      # ㋠ supplementals
    assert count_x("\u2e80") == 2       # cjk radical supplement
    assert count_x("\uf900") == 2       # cjk compat ideograph
    assert count_x("\u26a1") == 2       # ⚡ dingbat


def test_emoji_vs_combiners_do_not_double_count_themselves():
    assert count_x("\u200d") == 1       # ZWJ itself is width 1
    assert count_x("\ufe0f") == 1       # variation selector-16 is width 1
    assert count_x("\U0001F31F\ufe0f") == 3  # globe (2) + VS16 (1)


def test_resolve_platform_accepts_aliases():
    assert resolve_platform("twitter") == "x"
    assert resolve_platform("X") == "x"
    assert resolve_platform("google") == "google_business"
    assert resolve_platform("nope") is None
    assert valid_platform("x") is True
    assert valid_platform("nope") is False


def test_platform_limit_raises_on_unknown_key():
    with pytest.raises(ValueError):
        platform_limit("nope")


def test_hashtag_guidance_values():
    assert recommended_hashtags("linkedin") == 3
    assert recommended_hashtags("x") == 2
    assert recommended_hashtags("instagram") == 5
    assert MAX_HASHTAGS["instagram"] == 30
    assert recommended_hashtags("mastodon") is None
    assert recommended_hashtags("bluesky") is None


def test_display_names_cover_every_platform():
    assert set(DISPLAY_NAMES) == set(PLATFORM_LIMITS)


def test_thread_prefix_format():
    assert thread_prefix(1, 5) == "1/5 "
    assert thread_prefix(5, 5) == "5/5 "


def test_limit_lookup_via_public_helper():
    assert platform_limit("x") == 280
    assert platform_limit("twitter") == 280
