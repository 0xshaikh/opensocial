"""Hashtag sets, the hashtag linter, and template rendering."""

from __future__ import annotations

import pytest

from opensocial.hashtags import (
    HASHTAG_RE,
    count_hashtags,
    find_hashtags,
    lint_posts,
    lint_report,
)
from opensocial.templates import render, variable_names


def test_find_hashtags_extracts_and_dedupes():
    tags = find_hashtags("hello #launch and #launch plus #open-source")
    assert tags == ["#launch", "#open-source"]
    assert count_hashtags("no tags here") == 0


def test_find_hashtags_handles_unicode_and_punct():
    assert "#café" in find_hashtags("bon #café !")
    assert find_hashtags("see #a and #a.") == ["#a"]


def test_hashtag_regex_ignores_email_and_bare_hashes():
    assert find_hashtags("mail me at a@b.com") == []
    assert find_hashtags("#") == []


def test_lint_flags_over_recommendation(store, seeded):
    """Five hashtags on instagram equals the recommendation -> no finding."""
    posts = decorated(store)
    findings = lint_posts(posts)
    assert isinstance(findings, list)
    assert seeded["ids"][2] not in {f["id"] for f in findings}


def test_lint_reports_hard_cap_violation(store, seeded):
    instagram = seeded["instagram"]
    store.add_post(
        instagram,
        " ".join(f"#t{i}" for i in range(35)),
    )
    findings = lint_posts(decorated(store))
    errors = [f for f in findings if f["severity"] == "error"]
    assert errors
    assert errors[0]["platform"] == "instagram"
    assert errors[0]["count"] == 35
    assert errors[0]["max"] == 30


def test_lint_reports_warning_above_recommendation(store, seeded):
    x_channel = seeded["x_channel"]
    store.add_post(x_channel, "launch day #one #two #three #four")
    findings = lint_posts(decorated(store))
    warnings = [f for f in findings if f["severity"] == "warn"]
    assert warnings
    assert warnings[0]["platform"] == "x"
    assert warnings[0]["recommended"] == 2


def test_lint_skips_platforms_without_guidance(store):
    mastodon = store.add_channel("mastodon", "@testlab@bsky.social")
    store.add_post(mastodon, " ".join(f"#t{i}" for i in range(20)))
    assert lint_posts(decorated(store)) == []


def test_lint_report_is_human_readable(store):
    assert "within hashtag guidance" in lint_report([])
    out = lint_report([{"id": 1, "platform": "x", "count": 5, "severity": "warn",
                        "recommended": 2, "max": None, "reason": "too many"}])
    assert "#1" in out and "warn" in out and "1 finding" in out


def test_hashtag_sets_apply_merges_without_dropping(store, seeded):
    x_channel = seeded["x_channel"]
    post_id = store.add_post(x_channel, "hello #launch")
    store.add_hashtag_set("social", ["self-hosted", "local-first", "#launch"])
    store.update_post(post_id, tags=["launch"])
    # emulate the CLI apply behaviour
    item = store.get_hashtag_set("social")
    existing = store.get_post(post_id)["tags"]
    merged = list(dict.fromkeys(existing + item["hashtags"]))
    store.update_post(post_id, tags=merged)
    assert store.get_post(post_id)["tags"] == ["launch", "self-hosted", "local-first"]


def test_template_variable_names():
    assert variable_names("Hi {name}, {product} is great") == ["name", "product"]
    assert variable_names("{a} {a} {b}") == ["a", "b"]


def test_template_render_substitutes_variables():
    body = "Shipped {product} for {region} today."
    out = render(body, product="opensocial", region="Europe")
    assert out == "Shipped opensocial for Europe today."


def test_template_render_keeps_missing_variables_visible():
    out = render("Hello {name}", **{})
    assert out == "Hello {name}"


def test_template_render_supports_defaults():
    out = render("Hello {name:Fallback}", **{})
    assert out == "Hello Fallback"
    out2 = render("Hello {name:Fallback}", name="Ana")
    assert out2 == "Hello Ana"


def test_template_render_coerces_values_to_str():
    assert render("v={n}", n=42) == "v=42"


def test_template_render_does_not_escape_html():
    assert render("{x}", x="<script>") == "<script>"


# --------------------------------------------------------------------------- #
def decorated(store):
    channels = {c["id"]: c for c in store.list_channels()}
    out = []
    for post in store.list_posts():
        row = dict(post)
        ch = channels.get(post["channel_id"]) or {}
        row["channel"] = ch.get("name") or f"@{ch.get('handle', '?')}"
        row["platform"] = ch.get("platform", "?")
        row["handle"] = ch.get("handle", "")
        out.append(row)
    return out
