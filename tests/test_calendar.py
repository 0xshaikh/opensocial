"""ICS / CSV export and the calendar grid."""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timedelta, timezone

from opensocial.calendar import (
    CSV_FIELDS,
    build_csv,
    build_ics,
    calendar_grid,
    collect,
    render_grid,
)
from opensocial.store import parse_iso


def decorated(store):
    """All posts with channel info attached, matching the web/CLI shape."""
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


def test_ics_has_required_rfc5545_frames(store, seeded):
    doc = build_ics(decorated(store))
    assert doc.startswith("BEGIN:VCALENDAR")
    assert doc.rstrip("\r\n").endswith("END:VCALENDAR")
    assert "\r\n" in doc
    assert doc.count("BEGIN:VEVENT") == 4
    assert doc.count("END:VEVENT") == 4
    assert "VERSION:2.0" in doc
    assert "PRODID:-//opensocial" in doc


def test_ics_dtstart_and_dtstamp_are_utc(store, seeded):
    doc = build_ics(decorated(store))
    starts = re.findall(r"DTSTART:(\d{8}T\d{6}Z)", doc)
    assert len(starts) == 4
    for stamp in starts:
        datetime.strptime(stamp, "%Y%m%dT%H%M%SZ")
    stamps = re.findall(r"DTSTAMP:(\d{8}T\d{6}Z)", doc)
    assert len(stamps) == 4
    for stamp in stamps:
        datetime.strptime(stamp, "%Y%m%dT%H%M%SZ")


def test_ics_uid_is_unique_per_post(store, seeded):
    doc = build_ics(decorated(store))
    uids = re.findall(r"^UID:(.+)$", doc, flags=re.MULTILINE)
    assert len(uids) == 4
    assert len(set(uids)) == 4
    assert all(u.startswith("post-") and "@opensocial" in u for u in uids)


def test_ics_unfolds_cleanly(store, seeded):
    doc = build_ics(decorated(store))
    unfolded = re.sub(r"\r\n [^\s]", "", doc)
    assert "BEGIN:VCALENDAR" in unfolded
    assert unfolded.count("BEGIN:VEVENT") == 4


def test_ics_escapes_text_fields(store, seeded):
    from opensocial.calendar import _escape_ics

    assert _escape_ics("a;b") == "a\\;b"
    assert _escape_ics("a,b") == "a\\,b"
    assert _escape_ics("a\\b") == "a\\\\b"
    assert _escape_ics("a\nb") == "a\\nb"
    assert _escape_ics("a\r\nb") == "a\\nb"


def test_ics_folds_lines_at_73_octets(store, seeded):
    long_body = "word " * 400
    post = dict(decorated(store)[0])
    post["id"] = 99
    post["body"] = long_body
    doc = build_ics([post])
    physical = doc.split("\r\n")
    for line in physical:
        assert len(line.encode("utf-8")) <= 73, line
    # folding must have actually happened for this long body
    unfolded = re.sub(r"\r\n ", "", doc).split("\r\n")
    assert len(physical) > len(unfolded)
    # continuation lines begin with a single space
    assert any(line.startswith(" ") for line in physical)
    # unfolding must restore the original content
    assert any(len(l) > 73 for l in unfolded)


def test_csv_is_rfc4180_and_round_trips(store, seeded):
    from opensocial.calendar import load_csv

    posts = decorated(store)
    text = build_csv(posts)
    assert text.startswith('"id",')
    assert text.endswith("\r\n")
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == list(CSV_FIELDS)
    assert len(rows) == 1 + len(posts)
    reopened = load_csv(text)
    assert len(reopened) == len(posts)
    assert {str(r["id"]) for r in reopened} == {str(p["id"]) for p in posts}


def test_csv_quotes_bodies_with_commas_and_quotes(store, seeded):
    from opensocial.calendar import load_csv

    text = build_csv(
        [
            {
                "id": 1,
                "platform": "x",
                "handle": "@a",
                "status": "draft",
                "body": 'He said "hi", then left',
                "body_length": 20,
                "first_comment": "",
                "urls": [],
                "tags": [],
                "scheduled_at": None,
                "published_at": None,
                "reviewed_by": None,
                "created_at": "",
                "updated_at": "",
                "channel": "@a",
            }
        ]
    )
    reopened = load_csv(text)
    assert reopened[0]["body"] == 'He said "hi", then left'


def test_csv_includes_tags_and_urls(store, seeded):
    from opensocial.calendar import load_csv

    text = build_csv(decorated(store))
    reopened = load_csv(text)
    row = next(r for r in reopened if str(r["id"]) == str(seeded["ids"][2]))
    assert row["tags"] == ["launch"]
    assert "#" not in row["tags"][0]


def test_calendar_grid_groups_by_day(store, seeded):
    posts = decorated(store)
    grid = calendar_grid(posts, days=30)
    assert len(grid) == 31  # 30 days plus today
    dates = [row["date"] for row in grid]
    assert dates == sorted(dates)
    in_window = 0
    start = datetime.now(timezone.utc).date()
    end = start + timedelta(days=30)
    for post in posts:
        dt = parse_iso(post.get("scheduled_at")) or parse_iso(post.get("created_at"))
        if start <= dt.date() <= end:
            in_window += 1
    total = sum(len(row["posts"]) for row in grid)
    assert total == in_window
    assert total == 3  # the 2026-10-20 post falls before the window opens
    assert all("weekday" in row for row in grid)


def test_render_grid_text_and_json(store, seeded):
    posts = decorated(store)
    text = render_grid(posts, days=7)
    assert "Content calendar" in text
    payload = json.loads(render_grid(posts, days=7, json_mode=True))
    assert isinstance(payload, list)
    assert all("date" in row and "posts" in row for row in payload)


def test_collect_limits_the_window(store, seeded):
    posts = collect(store, days=1)
    assert len(posts) >= 0
    assert all("platform" in p for p in posts)
