"""Named hashtag sets plus a per-platform hashtag linter."""

from __future__ import annotations

import re
from typing import Iterable

from .platforms import max_hashtags, recommended_hashtags, resolve_platform

#: A hashtag is ``#`` followed by word characters (letters incl. non-ASCII,
#: digits, underscores), optionally hyphenated.  Unicode-aware.
HASHTAG_RE = re.compile(
    r"#([A-Za-z0-9\u00c0-\uffff]+(?:-[A-Za-z0-9\u00c0-\uffff]+)*)",
    re.UNICODE,
)


def find_hashtags(text: str) -> list[str]:
    """Return hashtags found in *text*, in order, deduplicated."""
    seen: set[str] = set()
    out: list[str] = []
    for match in HASHTAG_RE.finditer(text or ""):
        tag = match.group(0)
        if tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out


def count_hashtags(text: str) -> int:
    """How many distinct hashtags *text* contains."""
    return len(find_hashtags(text))


def normalise(tag: str) -> str:
    """Strip whitespace and a leading ``#``."""
    return (tag or "").strip().lstrip("#")


def lint_posts(posts: Iterable[dict]) -> list[dict]:
    """Report posts whose hashtag count breaks platform guidance.

    Each finding carries a ``severity`` of ``error`` (platform hard cap)
    or ``warn`` (exceeds the recommended number).  Posts on platforms
    with no guidance are skipped.
    """
    findings: list[dict] = []
    for post in posts:
        platform = resolve_platform(post.get("platform", "") or "")
        if platform is None:
            continue
        body = post.get("body") or ""
        first_comment = post.get("first_comment") or ""
        count = count_hashtags(body) + count_hashtags(first_comment)
        cap = max_hashtags(platform)
        rec = recommended_hashtags(platform)
        if cap is not None and count > cap:
            findings.append(
                {
                    "id": post.get("id"),
                    "platform": platform,
                    "count": count,
                    "recommended": rec,
                    "max": cap,
                    "severity": "error",
                    "reason": f"{count} hashtags exceeds the {cap} cap for {platform}",
                }
            )
        elif rec is not None and count > rec:
            findings.append(
                {
                    "id": post.get("id"),
                    "platform": platform,
                    "count": count,
                    "recommended": rec,
                    "max": cap,
                    "severity": "warn",
                    "reason": f"{count} hashtags, more than the {rec} recommended for {platform}",
                }
            )
    return findings


def lint_report(findings: Iterable[dict]) -> str:
    """Human-readable linter output."""
    findings = list(findings)
    if not findings:
        return "All posts are within hashtag guidance for their platforms."
    lines = ["Hashtag lint:", ""]
    for f in findings:
        lines.append(
            f"  #{f['id']} [{f['severity']}] {f['platform']}: {f['reason']}"
        )
    lines.append("")
    lines.append(f"{len(findings)} finding(s).")
    return "\n".join(lines)
