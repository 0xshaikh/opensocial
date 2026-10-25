"""Atom, RSS, Markdown exports and CSV import.

Every feed is built with :mod:`xml.etree.ElementTree` so the output is
always namespace-correct and well-formed.  HTML in ``<content>`` is
escaped by the serializer rather than hand-concatenated.
"""

from __future__ import annotations

import csv
import html
from datetime import datetime, timezone
from typing import Iterable
from xml.etree import ElementTree as ET

from .store import Store, parse_iso, utcnow_iso

ATOM_NS = "http://www.w3.org/2005/Atom"
DC_NS = "http://purl.org/dc/elements/1.1/"
XHTML_NS = "http://www.w3.org/1999/xhtml"


def _stamp(value: str | None) -> str:
    dt = parse_iso(value) or datetime.now(timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _el(parent, tag: str, text: str | None = None):
    """Append a child element with text content."""
    element = ET.SubElement(parent, tag)
    if text is not None:
        element.text = text
    return element


def _decorate(posts: list[dict], store: Store) -> list[dict]:
    channels = {c["id"]: c for c in store.list_channels()}
    out = []
    for post in posts:
        row = dict(post)
        ch = channels.get(post.get("channel_id")) or {}
        row["channel"] = ch.get("name") or f"@{ch.get('handle', '?')}"
        row["platform"] = ch.get("platform", "?")
        row["handle"] = ch.get("handle", "")
        out.append(row)
    return out


def atom_feed(posts: Iterable[dict], *, title: str = "opensocial content calendar") -> str:
    """Render an Atom 0.3 feed with one entry per post."""
    ET.register_namespace("", ATOM_NS)
    feed = ET.Element(f"{{{ATOM_NS}}}feed")
    _el(feed, f"{{{ATOM_NS}}}title", title)
    _el(feed, f"{{{ATOM_NS}}}id", "urn:opensocial:feed:calendar")
    now = datetime.now(timezone.utc)
    latest = now
    for post in posts:
        dt = parse_iso(post.get("scheduled_at")) or parse_iso(post.get("published_at"))
        if dt:
            latest = max(latest, dt)
    _el(
        feed,
        f"{{{ATOM_NS}}}updated",
        latest.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    generator = _el(feed, f"{{{ATOM_NS}}}generator", "opensocial 0.1.0")
    generator.set("version", "0.1.0")

    for post in posts:
        channel = f"{post.get('platform', '')} @{post.get('handle', '')}"
        entry = ET.SubElement(feed, f"{{{ATOM_NS}}}entry")
        ET.SubElement(entry, f"{{{ATOM_NS}}}title").text = (
            f"[{channel}] #{post['id']} {post.get('status', 'draft')}"
        )
        ET.SubElement(entry, f"{{{ATOM_NS}}}id").text = (
            f"urn:opensocial:post:{post['id']}"
        )
        ET.SubElement(entry, f"{{{ATOM_NS}}}updated").text = _stamp(post.get("updated_at"))
        ET.SubElement(entry, f"{{{ATOM_NS}}}published").text = _stamp(post.get("created_at"))
        author = ET.SubElement(entry, f"{{{ATOM_NS}}}author")
        ET.SubElement(author, f"{{{ATOM_NS}}}name").text = channel
        ET.SubElement(entry, f"{{{DC_NS}}}date").text = _stamp(post.get("scheduled_at"))
        content = ET.SubElement(
            entry, f"{{{ATOM_NS}}}content", type="xhtml"
        )
        div = ET.SubElement(content, f"{{{XHTML_NS}}}div")
        paragraphs = [p for p in (post.get("body") or "").split("\n") if p.strip()]
        for para in paragraphs:
            ET.SubElement(div, f"{{{XHTML_NS}}}p").text = para
        if post.get("first_comment"):
            ET.SubElement(
                div, f"{{{XHTML_NS}}}p"
            ).text = f"First comment: {post['first_comment']}"
        if post.get("tags"):
            ET.SubElement(
                div, f"{{{XHTML_NS}}}p"
            ).text = "Tags: " + " ".join(f"#{t}" for t in post["tags"])
        for tag in post.get("tags") or []:
            cat = ET.SubElement(entry, f"{{{ATOM_NS}}}category")
            cat.set("term", f"#{tag}")
            cat.set("label", f"#{tag}")
        for url in post.get("urls") or []:
            link = ET.SubElement(entry, f"{{{ATOM_NS}}}link", href=url)
            link.set("rel", "alternate")

    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        feed, encoding="unicode"
    ) + "\n"


def rss_feed(posts: Iterable[dict], *, title: str = "opensocial content calendar") -> str:
    """Render an RSS 2.0 feed with one item per post."""
    root = ET.Element("rss", version="2.0")
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = title
    ET.SubElement(channel, "link").text = "https://github.com/0xshaikh/opensocial"
    ET.SubElement(channel, "description").text = (
        "Local-first content calendar for social posts"
    )
    ET.SubElement(channel, "lastBuildDate").text = datetime.now(
        timezone.utc
    ).strftime("%a, %d %b %Y %H:%M:%S +0000")
    ET.SubElement(channel, "generator").text = "opensocial 0.1.0"

    for post in posts:
        platform = post.get("platform", "")
        handle = post.get("handle", "")
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = (
            f"[{platform} @{handle}] #{post['id']} {post.get('status', 'draft')}"
        )
        ET.SubElement(item, "link").text = f"#post-{post['id']}"
        ET.SubElement(item, "guid", isPermaLink="false").text = (
            f"urn:opensocial:post:{post['id']}"
        )
        body = post.get("body") or ""
        if post.get("first_comment"):
            body += "\n\nFirst comment: " + post["first_comment"]
        ET.SubElement(item, "description").text = body
        pub = parse_iso(post.get("scheduled_at")) or parse_iso(post.get("created_at"))
        if pub:
            ET.SubElement(item, "pubDate").text = pub.astimezone(
                timezone.utc
            ).strftime("%a, %d %b %Y %H:%M:%S +0000")
        ET.SubElement(item, "category").text = f"{platform} @{handle}"
        if post.get("reviewed_by"):
            ET.SubElement(item, "author").text = post["reviewed_by"]

    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        root, encoding="unicode"
    ) + "\n"


def markdown_report(
    posts: Iterable[dict], *, title: str = "opensocial content calendar"
) -> str:
    """Render a Markdown content-calendar report, newest first."""
    ordered = sorted(
        list(posts),
        key=lambda p: parse_iso(p.get("scheduled_at")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    lines = [f"# {title}", "", f"_Generated by opensocial {utcnow_iso()}_", ""]
    if not ordered:
        lines.append("_No posts yet._")
        return "\n".join(lines) + "\n"
    lines.append("## Schedule")
    lines.append("")
    lines.append("| Date | Time | Channel | Platform | Status | Reviewer |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for post in ordered:
        dt = parse_iso(post.get("scheduled_at"))
        if dt:
            date_s = dt.astimezone(timezone.utc).strftime("%Y-%m-%d")
            time_s = dt.astimezone(timezone.utc).strftime("%H:%M UTC")
        else:
            date_s = "unscheduled"
            time_s = ""
        lines.append(
            f"| {date_s} | {time_s} | {post.get('channel', '')} | "
            f"{post.get('platform', '')} | {post.get('status', '')} | "
            f"{post.get('reviewed_by') or '—'} |"
        )
    lines.append("")
    lines.append("## Posts")
    lines.append("")
    for post in ordered:
        dt = parse_iso(post.get("scheduled_at"))
        when = (
            dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            if dt
            else "unscheduled"
        )
        lines.append(f"### #{post['id']} — {post.get('status')}")
        lines.append("")
        lines.append(
            f"- **Channel:** {post.get('channel')} ({post.get('platform')})"
        )
        lines.append(f"- **Scheduled:** {when}")
        if post.get("published_at"):
            lines.append(
                f"- **Published:** {parse_iso(post['published_at']).astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
            )
        if post.get("reviewed_by"):
            lines.append(f"- **Approved by:** {post['reviewed_by']}")
        if post.get("tags"):
            lines.append(
                "- **Tags:** " + " ".join(f"#{t}" for t in post["tags"])
            )
        if post.get("urls"):
            lines.append("- **Links:**")
            for url in post["urls"]:
                lines.append(f"  - <{url}>")
        lines.append("")
        lines.append("> " + html.escape(post.get("body") or "").replace("\n", "\n> "))
        if post.get("first_comment"):
            lines.append("")
            lines.append(
                "> _First comment:_ " + html.escape(post["first_comment"]).replace("\n", "\n> ")
            )
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


# --------------------------------------------------------------------------- #
# CSV import (Buffer-style bulk upload)
# --------------------------------------------------------------------------- #
IMPORT_FIELDS = ("body", "platform", "handle", "status", "first_comment", "urls", "tags", "scheduled_at")


def import_csv(store: Store, text: str) -> list[dict]:
    """Bulk-upload posts from CSV text; creates missing channels as needed."""
    reader = csv.DictReader(io_split(text))
    rows = list(reader)
    created: list[dict] = []
    for idx, row in enumerate(rows):
        body = (row.get("body") or row.get("text") or "").strip()
        if not body:
            raise ValueError(f"row {idx + 2}: missing body")
        platform = (row.get("platform") or "x").strip()
        handle = (row.get("handle") or row.get("channel") or platform).strip()
        channel_id = _find_or_create_channel(store, platform, handle)
        urls = _split_list(row.get("urls"))
        tags = _split_list(row.get("tags"))
        status = (row.get("status") or "draft").strip().lower() or "draft"
        post_id = store.add_post(
            channel_id,
            body,
            first_comment=(row.get("first_comment") or "").strip(),
            urls=urls,
            tags=tags,
            status=status,
            scheduled_at=(row.get("scheduled_at") or "").strip() or None,
        )
        created.append(
            {
                "id": post_id,
                "channel_id": channel_id,
                "platform": platform,
                "handle": handle,
                "status": status,
            }
        )
    return created


def io_split(text: str):
    import io as _io

    return _io.StringIO(text)


def _split_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    raw = raw.strip()
    if not raw:
        return []
    if ";" in raw:
        parts = raw.split(";")
    elif "\n" in raw:
        parts = raw.split("\n")
    else:
        parts = raw.split()
    return [p.strip().lstrip("#") for p in parts if p.strip()]


def _find_or_create_channel(store: Store, platform: str, handle: str) -> int:
    for channel in store.list_channels():
        if (
            channel["platform"] == platform
            and channel["handle"].lower() == handle.lower()
        ):
            return channel["id"]
    return store.add_channel(platform, handle)
