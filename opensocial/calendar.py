"""Content-calendar views plus ICS and CSV export.

ICS output follows RFC 5545: ``CRLF`` line endings, UTC ``DTSTART``/
``DTSTAMP`` stamps in ``YYYYMMDDTHHMMSSZ`` form, escaping of text fields,
and 73-octet line folding.
"""

from __future__ import annotations

import calendar as _calendar
import csv
import io
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

from .store import Store, parse_iso, utcnow_iso

ICS_PROPERTIES = (
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//opensocial//opensocial 0.1.0//EN",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
)


def _escape_ics(value: str) -> str:
    """Escape a TEXT value per RFC 5545 section 3.3.11."""
    if value is None:
        return ""
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _fold_ics_line(line: str, limit: int = 73) -> list[str]:
    """Fold a content line at 73 octets, continuing lines with a space."""
    if len(line.encode("utf-8")) <= limit:
        return [line]
    out: list[str] = []
    current = ""
    budget = limit
    for ch in line:
        width = len(ch.encode("utf-8"))
        if len(current.encode("utf-8")) + width > budget:
            out.append(current)
            current = " " + ch
            budget = limit
        else:
            current += ch
    if current:
        out.append(current)
    return out


def _ics_dt(value: str | None) -> str:
    dt = parse_iso(value) or datetime.now(timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ics_event(post: dict, title_extra: str = "") -> list[str]:
    """Build the ``VEVENT`` lines for a single post."""
    channel = f"{post.get('platform', '')} @{post.get('handle', '')}"
    stamp = _ics_dt(utcnow_iso())
    title = f"Post {post['id']} · {post['status']}"
    if title_extra:
        title += f" · {title_extra}"
    summary = f"[{channel}] {post.get('status', 'draft')}"
    body = post.get("body") or ""
    description = body
    if post.get("first_comment"):
        description += "\n\nFirst comment:\n" + post["first_comment"]
    urls = post.get("urls") or []
    if urls:
        description += "\n\nLinks:\n" + "\n".join(urls)
    if post.get("tags"):
        description += "\n\nTags:\n" + " ".join(f"#{t}" for t in post["tags"])

    uid = f"post-{post['id']}@opensocial"
    lines = [
        "BEGIN:VEVENT",
        f"DTSTART:{_ics_dt(post.get('scheduled_at'))}",
        f"DTSTAMP:{stamp}",
        f"UID:{uid}",
        f"SUMMARY:{_escape_ics(summary)}",
        f"DESCRIPTION:{_escape_ics(description)}",
        f"CATEGORIES:{_escape_ics(channel)}",
    ]
    if post.get("reviewed_by"):
        lines.append(f"X-REVIEWED-BY:{_escape_ics(post['reviewed_by'])}")
    lines.append("END:VEVENT")
    return lines


def build_ics(posts: Iterable[dict]) -> str:
    """Render a full ``VCALENDAR`` document for *posts* (CRLF terminated)."""
    lines: list[str] = list(ICS_PROPERTIES)
    for post in posts:
        lines.extend(ics_event(post))
    lines.append("END:VCALENDAR")
    folded: list[str] = []
    for line in lines:
        folded.extend(_fold_ics_line(line))
    return "\r\n".join(folded) + "\r\n"


def ics_to_bytes(text: str) -> bytes:
    """Encode an ICS string, expanding any ``\\n`` escapes back to CRLF."""
    return text.replace("\\n", "\r\n").encode("utf-8")


#: CSV column order.  Flat, RFC 4180 quoting, one row per post.
CSV_FIELDS = (
    "id",
    "channel",
    "platform",
    "handle",
    "status",
    "body",
    "body_length",
    "first_comment",
    "urls",
    "tags",
    "scheduled_at",
    "published_at",
    "reviewed_by",
    "created_at",
    "updated_at",
)


def build_csv(posts: Iterable[dict]) -> str:
    """Render posts as RFC 4180 CSV (``QUOTE_ALL``, CRLF, UTF-8 BOM-free)."""
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(
        buf, fieldnames=list(CSV_FIELDS), quoting=csv.QUOTE_ALL, lineterminator="\r\n"
    )
    writer.writeheader()
    for post in posts:
        writer.writerow(
            {
                "id": post.get("id"),
                "channel": post.get("channel"),
                "platform": post.get("platform"),
                "handle": post.get("handle"),
                "status": post.get("status"),
                "body": post.get("body"),
                "body_length": post.get("body_length"),
                "first_comment": post.get("first_comment") or "",
                "urls": "; ".join(post.get("urls") or []),
                "tags": " ".join(f"#{t}" for t in (post.get("tags") or [])),
                "scheduled_at": post.get("scheduled_at") or "",
                "published_at": post.get("published_at") or "",
                "reviewed_by": post.get("reviewed_by") or "",
                "created_at": post.get("created_at") or "",
                "updated_at": post.get("updated_at") or "",
            }
        )
    return buf.getvalue()


def load_csv(text: str) -> list[dict]:
    """Parse CSV produced by :func:`build_csv` back into row dicts."""
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for row in reader:
        row = {k: v for k, v in row.items() if k}
        if row.get("urls"):
            row["urls"] = [u.strip() for u in row["urls"].split(";") if u.strip()]
        if row.get("tags"):
            row["tags"] = [
                t.strip().lstrip("#") for t in row["tags"].split() if t.strip()
            ]
        rows.append(row)
    return rows


# --------------------------------------------------------------------------- #
# calendar grid
# --------------------------------------------------------------------------- #
def _decorate(posts: list[dict], store: Store) -> list[dict]:
    """Attach channel/platform/handle info to post rows."""
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


def collect(store: Store, *, days: int = 7, statuses: Iterable[str] | None = None) -> list[dict]:
    """Posts that fall inside a window starting today (UTC), *days* wide."""
    wanted = list(statuses) if statuses else None
    posts = store.list_posts()
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=1)).date()
    end = (now + timedelta(days=days)).date()
    out = []
    for post in posts:
        if wanted and post.get("status") not in wanted:
            continue
        dt = parse_iso(post.get("scheduled_at")) or parse_iso(post.get("created_at"))
        if dt is None:
            continue
        if start <= dt.date() <= end:
            out.append(post)
    out.sort(key=lambda p: (parse_iso(p.get("scheduled_at")) or datetime.min.replace(tzinfo=timezone.utc)))
    return _decorate(out, store)


def calendar_grid(posts: list[dict], *, days: int = 7) -> list[dict]:
    """Group *posts* into ``[{date, iso, weekday, posts: [...]}]`` rows."""
    rows = {d: [] for d in _days(today=datetime.now(timezone.utc).date(), days=days)}
    for post in posts:
        dt = parse_iso(post.get("scheduled_at")) or parse_iso(post.get("created_at"))
        if dt is None:
            continue
        key = dt.date().isoformat()
        if key in rows:
            rows[key].append(post)
    out = []
    for iso, day in rows.items():
        d = datetime.strptime(iso, "%Y-%m-%d").date()
        out.append(
            {
                "date": iso,
                "weekday": _calendar.day_name[d.weekday()],
                "posts": day,
            }
        )
    return out


def _days(*, today, days: int) -> list[str]:
    start = today if isinstance(today, date) else today.date()
    return [(start + timedelta(days=i)).isoformat() for i in range(days + 1)]


def render_grid(posts: list[dict], *, days: int = 7, json_mode: bool = False) -> str:
    """A text calendar grouped by day, then by channel."""
    rows = calendar_grid(posts, days=days)
    if json_mode:
        import json as _json

        payload = [
            {
                "date": row["date"],
                "weekday": row["weekday"],
                "posts": [
                    {
                        "id": p["id"],
                        "channel": p.get("channel"),
                        "platform": p.get("platform"),
                        "status": p.get("status"),
                        "body": p.get("body"),
                    }
                    for p in row["posts"]
                ],
            }
            for row in rows
        ]
        return _json.dumps(payload, indent=2, ensure_ascii=False)

    lines = [f"Content calendar — next {days} day(s)", ""]
    for row in rows:
        if row["posts"]:
            lines.append(
                f"{row['date']}  {row['weekday']:9s}  "
                f"({len(row['posts'])} post{'s' if len(row['posts']) != 1 else ''})"
            )
            for post in row["posts"]:
                snippet = (post.get("body") or "").replace("\n", " ")
                snippet = snippet[:60] + ("…" if len(snippet) > 60 else "")
                lines.append(
                    f"    #{post['id']:<3} [{post.get('status'):<9}] "
                    f"{post.get('platform')}/{post.get('channel')}: {snippet}"
                )
        else:
            lines.append(f"{row['date']}  {row['weekday']:9s}  —")
    return "\n".join(lines)
