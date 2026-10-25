"""Local analytics.  Everything is computed from the SQLite rows only."""

from __future__ import annotations

import calendar as _calendar
import statistics
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Iterable

from .hashtags import find_hashtags
from .platforms import platform_count, resolve_platform
from .store import Store, parse_iso

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _platform_of(post: dict, store: Store) -> str:
    platform = post.get("platform")
    if platform:
        return resolve_platform(platform) or platform
    return store.platform_of(post.get("channel_id"))


def stats(store: Store, *, top_hashtags: int = 10, days: int = 14) -> dict:
    """Aggregate the local calendar into an analytics payload."""
    posts = store.list_posts()
    channels = {c["id"]: c for c in store.list_channels()}

    by_status: Counter = Counter()
    by_platform: Counter = Counter()
    lengths: list[int] = []
    tag_counter: Counter = Counter()
    weekday_counter: Counter = Counter()
    per_day: dict[str, int] = {}
    over_limit = 0
    today = datetime.now(timezone.utc).date()
    for offset in range(days):
        per_day[(today - timedelta(days=offset)).isoformat()] = 0

    for post in posts:
        channel = channels.get(post.get("channel_id")) or {}
        platform = channel.get("platform") or post.get("platform") or "x"
        key = resolve_platform(platform) or platform
        by_status[post.get("status") or "draft"] += 1
        by_platform[key] += 1

        body = post.get("body") or ""
        length = platform_count(key, body)
        lengths.append(length)
        if length > platform_limit_of(key):
            over_limit += 1

        for tag in find_hashtags(body) + find_hashtags(post.get("first_comment") or ""):
            tag_counter[tag.lstrip("#").lower()] += 1

        dt = parse_iso(post.get("scheduled_at")) or parse_iso(post.get("created_at"))
        if dt is None:
            continue
        weekday_counter[DAY_NAMES[dt.weekday()]] += 1
        day_key = dt.date().isoformat()
        if day_key in per_day:
            per_day[day_key] += 1

    # per-channel cadence: median gap between consecutive scheduled posts
    cadence: dict[str, dict] = {}
    grouped: dict[str, list[datetime]] = {}
    for post in posts:
        channel = channels.get(post.get("channel_id")) or {}
        platform = channel.get("platform") or "x"
        key = resolve_platform(platform) or platform
        dt = parse_iso(post.get("scheduled_at"))
        if dt is None:
            continue
        label = f"{key}/{channel.get('handle', '?')}"
        grouped.setdefault(label, []).append(dt)
    for label, times in grouped.items():
        ordered = sorted(times)
        gaps = [
            (b - a).total_seconds() / 86400.0 for a, b in zip(ordered, ordered[1:])
        ]
        cadence[label] = {
            "scheduled": len(ordered),
            "median_gap_days": round(statistics.median(gaps), 2) if gaps else None,
        }

    return {
        "total_posts": len(posts),
        "total_channels": len(channels),
        "by_status": dict(by_status),
        "by_platform": dict(by_platform),
        "per_day": dict(sorted(per_day.items())),
        "window_days": days,
        "lengths": {
            "avg": round(statistics.fmean(lengths), 1) if lengths else 0,
            "median": statistics.median(lengths) if lengths else 0,
            "min": min(lengths) if lengths else 0,
            "max": max(lengths) if lengths else 0,
        },
        "top_hashtags": tag_counter.most_common(top_hashtags),
        "day_of_week": {DAY_NAMES[i]: weekday_counter.get(DAY_NAMES[i], 0) for i in range(7)},
        "cadence": cadence,
        "limit_compliance": {
            "over_limit": over_limit,
            "within_limit": len(posts) - over_limit,
            "total": len(posts),
        },
    }


def platform_limit_of(platform: str) -> int:
    from .platforms import PLATFORM_LIMITS

    return PLATFORM_LIMITS.get(resolve_platform(platform) or "", 280)


def render_stats(payload: dict, *, json_mode: bool = False) -> str:
    """Text or JSON rendering of an analytics payload."""
    import json as _json

    if json_mode:
        return _json.dumps(payload, indent=2, ensure_ascii=False)

    lines = ["opensocial stats", "=" * 22, ""]
    lines.append(f"posts: {payload['total_posts']}   channels: {payload['total_channels']}")
    lines.append("")
    lines.append("by status")
    for status, count in sorted(payload["by_status"].items()):
        lines.append(f"  {status:<11} {count}")
    lines.append("")
    lines.append("by platform")
    for platform, count in sorted(payload["by_platform"].items()):
        lines.append(f"  {platform:<15} {count}")
    lines.append("")
    lengths = payload["lengths"]
    lines.append(
        f"body length: avg {lengths['avg']}  median {lengths['median']}  "
        f"min {lengths['min']}  max {lengths['max']}"
    )
    compliance = payload["limit_compliance"]
    lines.append(
        f"limit compliance: {compliance['within_limit']}/{compliance['total']} "
        f"within limit ({compliance['over_limit']} over)"
    )
    lines.append("")
    lines.append(f"top hashtags (top {len(payload['top_hashtags'])})")
    for tag, count in payload["top_hashtags"]:
        lines.append(f"  #{tag:<20} {count}")
    lines.append("")
    lines.append("day of week")
    for day, count in payload["day_of_week"].items():
        lines.append(f"  {day:<4} {count}")
    lines.append("")
    lines.append("posts per day (last %d days)" % payload["window_days"])
    width = max([max(len(str(v)) for v in payload["per_day"].values()) or 1] + [1])
    for day, count in payload["per_day"].items():
        bar = "#" * count
        lines.append(f"  {day} {bar:<10} {count}")
    lines.append("")
    if payload["cadence"]:
        lines.append("cadence (median gap between scheduled posts)")
        for label, info in payload["cadence"].items():
            gap = f"{info['median_gap_days']} days" if info["median_gap_days"] is not None else "n/a"
            lines.append(f"  {label:<28} {gap}  ({info['scheduled']} scheduled)")
    return "\n".join(lines)
