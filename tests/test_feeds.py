"""Atom, RSS, Markdown exports and CSV import."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from opensocial.feeds import (
    ATOM_NS,
    atom_feed,
    import_csv,
    markdown_report,
    rss_feed,
)


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


def test_atom_is_wellformed_and_namespaced(store, seeded):
    doc = atom_feed(decorated(store))
    root = ET.fromstring(doc)
    assert root.tag == f"{{{ATOM_NS}}}feed"
    assert root.find(f"{{{ATOM_NS}}}title").text == "opensocial content calendar"
    updated = root.find(f"{{{ATOM_NS}}}updated").text
    assert updated.endswith("Z")


def test_atom_has_one_entry_per_post_with_unique_ids(store, seeded):
    root = ET.fromstring(atom_feed(decorated(store)))
    entries = root.findall(f"{{{ATOM_NS}}}entry")
    assert len(entries) == 4
    ids = [e.find(f"{{{ATOM_NS}}}id").text for e in entries]
    assert len(set(ids)) == 4
    assert all(i.startswith("urn:opensocial:post:") for i in ids)


def test_atom_entries_carry_required_children(store, seeded):
    root = ET.fromstring(atom_feed(decorated(store)))
    xhtml_div = "{http://www.w3.org/1999/xhtml}div"
    for entry in root.findall(f"{{{ATOM_NS}}}entry"):
        assert entry.find(f"{{{ATOM_NS}}}title") is not None
        assert entry.find(f"{{{ATOM_NS}}}updated") is not None
        assert entry.find(f"{{{ATOM_NS}}}author") is not None
        content = entry.find(f"{{{ATOM_NS}}}content")
        assert content is not None
        assert content.get("type") == "xhtml"
        assert content.find(xhtml_div) is not None


def test_atom_escapes_html_in_content(store, seeded):
    doc = atom_feed(decorated(store))
    assert "&" in doc or "<" in doc  # serialised markup is present
    ET.fromstring(doc)  # still parses


def test_atom_categories_come_from_tags(store, seeded):
    root = ET.fromstring(atom_feed(decorated(store)))
    terms = [c.get("term") for e in root.findall(f"{{{ATOM_NS}}}entry")
             for c in e.findall(f"{{{ATOM_NS}}}category")]
    assert "#launch" in terms


def test_rss_is_wellformed_with_items(store, seeded):
    doc = rss_feed(decorated(store))
    root = ET.fromstring(doc)
    assert root.tag == "rss"
    assert root.get("version") == "2.0"
    channel = root.find("channel")
    assert channel is not None
    items = channel.findall("item")
    assert len(items) == 4
    for item in items:
        assert item.find("title") is not None
        assert item.find("guid") is not None
    guids = [i.find("guid").text for i in items]
    assert len(set(guids)) == 4


def test_rss_channel_has_feed_metadata(store, seeded):
    root = ET.fromstring(rss_feed(decorated(store)))
    channel = root.find("channel")
    assert channel.find("title").text == "opensocial content calendar"
    assert channel.find("generator").text == "opensocial 0.1.0"
    assert channel.find("link").text.startswith("https://")


def test_markdown_report_renders_a_readable_calendar(store, seeded):
    md = markdown_report(decorated(store))
    assert md.startswith("# opensocial content calendar")
    assert "| Date | Time | Channel | Platform | Status | Reviewer |" in md
    assert md.count("### #") == 4
    assert "## Posts" in md
    assert "## Schedule" in md


def test_markdown_includes_first_comment_and_links(store, seeded):
    md = markdown_report(decorated(store))
    assert "First comment:" in md
    assert "https://example.com/launch" in md


def test_markdown_of_empty_calendar(store):
    md = markdown_report([])
    assert "_No posts yet._" in md


def test_import_csv_creates_posts_and_channels(store):
    text = (
        "body,platform,handle,status,tags,urls,scheduled_at\n"
        '"Bulk imported post, with commas",x,@bulk,draft,"launch open",https://a.example,2026-11-01T09:00:00Z\n'
        '"Second imported post",instagram,@ig,draft,"launch",,\n'
    )
    created = import_csv(store, text)
    assert len(created) == 2
    posts = store.list_posts()
    assert len(posts) == 2
    assert posts[0]["body"] == "Bulk imported post, with commas"
    assert posts[0]["tags"] == ["launch", "open"]
    assert posts[0]["urls"] == ["https://a.example"]
    assert posts[0]["status"] == "draft"
    assert len(store.list_channels()) == 2


def test_import_csv_reuses_existing_channels(store, x_channel):
    text = "body,platform,handle\none,x,@testlab\n"
    created = import_csv(store, text)
    assert len(store.list_channels()) == 1
    assert created[0]["channel_id"] == x_channel


def test_import_csv_rejects_rows_without_a_body(store):
    import pytest

    with pytest.raises(ValueError):
        import_csv(store, "body,platform,handle\n,x,@a\n")
