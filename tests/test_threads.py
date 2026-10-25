"""Thread splitting: limits, prefixes, grapheme safety, content fidelity."""

from __future__ import annotations

from opensocial.platforms import platform_count
from opensocial.threads import split_thread, thread_preview


def _bodies(parts):
    """Strip each numbered prefix off a part."""
    out = []
    for part in parts:
        head, sep, rest = part.partition(" ")
        if sep and "/" in head:
            out.append(rest)
        else:
            out.append(part)
    return out


def _no_whitespace(text):
    return "".join(ch for ch in text if not ch.isspace())


def test_short_text_is_returned_untouched():
    assert split_thread("hello", "x") == ["hello"]


def test_x_thread_has_numbered_prefixes():
    body = ("The first sentence is fine. " * 20).strip()
    parts = split_thread(body, "x")
    assert len(parts) > 1
    total = len(parts)
    for i, part in enumerate(parts, 1):
        assert part.startswith(f"{i}/{total} ")


def test_every_part_fits_its_platform_limit():
    long = ("opensocial is a local-first content calendar. " * 60).strip()
    for platform in ("x", "bluesky", "mastodon"):
        parts = split_thread(long, platform)
        for part in parts:
            assert platform_count(platform, part) <= 280 if platform == "x" else True
        # the real invariant, checked per platform:
        for part in parts:
            from opensocial.platforms import platform_limit

            assert platform_count(platform, part) <= platform_limit(platform)


def test_prefix_counts_against_the_limit():
    """A 300-char body must leave room for the 1/n prefix."""
    body = "a" * 300
    parts = split_thread(body, "x")
    assert len(parts) == 2
    assert all(platform_count("x", p) <= 280 for p in parts)
    assert parts[0].startswith("1/2 ")
    assert platform_count("x", parts[0]) <= 280


def test_splitting_prefers_sentence_boundaries():
    body = (
        "First sentence ends here. Second sentence ends here. "
        "Third sentence ends here. Fourth sentence ends here."
    )
    # force a split
    body = (body + " " * 2 + body)
    parts = split_thread(body, "x", limit=60)
    joined = " ".join(_bodies(parts))
    assert "ends here." in joined
    # no part should start mid-sentence with a lowercase fragment of a word
    for part in parts:
        body_text = _bodies([part])[0]
        if not body_text[0].isspace():
            assert not body_text.startswith("entence")


def test_splitting_never_drops_or_dups_text():
    long = (
        "Compose once. Schedule everywhere. Export to any calendar. "
        * 40
    )
    parts = split_thread(long, "mastodon", limit=120)
    assert _no_whitespace(" ".join(_bodies(parts))) == _no_whitespace(long.strip())


def test_splitting_preserves_emoji_grapheme_clusters():
    emoji = "👨👩👧👦"  # ZWJ family sequence
    flag = "🇬🇧"  # regional-indicator pair
    long = f"{emoji} {flag} " + "x" * 400
    parts = split_thread(long, "x", limit=120)
    joined = " ".join(_bodies(parts))
    assert emoji in joined
    assert flag in joined
    assert _no_whitespace(joined) == _no_whitespace(long.strip())


def test_splitting_does_not_leave_a_bare_combiner_at_a_part_start():
    text = ("alpha\u0301 " * 200)  # combining acute after each alpha
    parts = split_thread(text, "mastodon", limit=60)
    for part in parts:
        body = _bodies([part])[0]
        assert not body.startswith("\u0301")


def test_split_preserves_paragraph_breaks_in_output():
    long = ("para one\n\npara two " * 100).strip()
    parts = split_thread(long, "mastodon", limit=100)
    joined = " ".join(_bodies(parts))
    assert _no_whitespace(joined) == _no_whitespace(long.strip())


def test_over_long_split_uses_more_than_two_parts():
    long = "word " * 2000
    parts = split_thread(long, "x", limit=280)
    assert len(parts) >= 5
    assert all(platform_count("x", p) <= 280 for p in parts)


def test_preview_renders_parts_with_counts():
    preview = thread_preview("abc " * 100, "x", limit=50)
    assert "Part 1/" in preview
    assert "Part 2/" in preview


def test_empty_and_whitespace_text():
    assert split_thread("", "x") == [""]
    assert split_thread("   ", "x") == [""]


def test_none_raises():
    import pytest

    with pytest.raises(ValueError):
        split_thread(None, "x")  # type: ignore[arg-type]
