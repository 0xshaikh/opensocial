"""Typefully-style thread splitting for over-limit posts.

The splitter produces ``1/n``, ``2/n`` ... parts that each fit within the
platform limit **including their own prefix**.  It sizes the part count
first, then breaks preferring sentence boundaries, then spaces, and only
hard-cuts when nothing else works -- and never in the middle of a grapheme
cluster (an emoji ZWJ sequence, a flag, a skin-tone modifier, a combining
mark).
"""

from __future__ import annotations

import re

from .platforms import platform_count, platform_limit, thread_prefix

#: Sentence terminators; a break is allowed *after* one of these.
_SENTENCE_END = re.compile(r"[.!?\u2026\u00b7]")
_WHITESPACE = re.compile(r"\s+")

#: Code points that must stay glued to the character in front of them.
_CONTINUING = frozenset(
    (
        0x200B,  # zero width space
        0x200C,  # ZWNJ
        0x200D,  # ZWJ
        0x2060,  # word joiner
        0x2061,
        0xFE0E,  # variation selector 15
        0xFE0F,  # variation selector 16
        0x20E0, 0x20E1, 0x20E2, 0x20E3,  # enclosing marks
    )
)

_CONTINUING_RANGES = (
    (0x1F3FB, 0x1F3FF),  # emoji skin tones
    (0x20D0, 0x20FF),  # combining diacritical marks
    (0xFE00, 0xFE0F),  # variation selectors
    (0xE0100, 0xE01EF),  # tag characters
)


def _is_continuing(ch: str) -> bool:
    """True when *ch* may not start a new visual character."""
    if not ch:
        return False
    cp = ord(ch)
    if cp in _CONTINUING:
        return True
    for lo, hi in _CONTINUING_RANGES:
        if lo <= cp <= hi:
            return True
    return False


def _break_ok(text: str, idx: int) -> bool:
    """Whether cutting at *idx* avoids splitting a grapheme cluster."""
    if idx <= 0 or idx >= len(text):
        return False
    if _is_continuing(text[idx]):
        return False
    if text[idx - 1] == "\u200d":  # dangling ZWJ on the left side
        return False
    left, right = ord(text[idx - 1]), ord(text[idx])
    if 0x1F1E6 <= left <= 0x1F1FF and 0x1F1E6 <= right <= 0x1F1FF:
        return False  # regional-indicator pair (flag)
    return True


def _fits(text: str, budget: int, count_fn) -> int:
    """Farthest index so that ``text[:idx]`` fits within *budget*."""
    idx = len(text)
    while idx > 0 and count_fn(text[:idx]) > budget:
        idx -= 1
    return idx


def _find_cut(text: str, budget: int, count_fn) -> int:
    """Best cut index so that ``text[:cut]`` fits within *budget*."""
    n = len(text)
    if n == 0:
        return 0
    reach = _fits(text, budget, count_fn)
    if reach == 0:  # a single grapheme is wider than the budget
        return 1
    if reach >= n:
        return n

    # 1. sentence boundary (consumes trailing whitespace into this part)
    for m in reversed(list(_SENTENCE_END.finditer(text[:reach]))):
        idx = m.end()
        while idx < n and text[idx].isspace():
            idx += 1
        if idx <= reach and _break_ok(text, idx) and count_fn(text[:idx]) <= budget:
            return idx

    # 2. space boundary
    for m in reversed(list(_WHITESPACE.finditer(text[:reach]))):
        idx = m.end()
        if idx <= reach and _break_ok(text, idx):
            return idx

    # 3. furthest safe hard cut
    for idx in range(reach, 0, -1):
        if _break_ok(text, idx):
            return idx
    return reach


def _chunk(text: str, n: int, budget: int, count_fn) -> list[str]:
    """Split *text* into exactly *n* pieces, each within *budget*.

    Each cut targets a proportional share of the remaining content so the
    last piece cannot overflow.
    """
    pieces: list[str] = []
    rest = text
    remaining = count_fn(rest)
    left = n
    while left > 1:
        target = min(budget, remaining / left)
        cut = _find_cut(rest, target, count_fn)
        if cut <= 0:
            cut = 1
        chunk = rest[:cut].rstrip()
        if not chunk:
            chunk = rest[:1]
            cut = 1
        pieces.append(chunk)
        rest = rest[cut:].lstrip()
        remaining = count_fn(rest)
        left -= 1
    if rest:
        pieces.append(rest.rstrip())
    while len(pieces) < n:
        pieces.append("")
    return pieces


def split_thread(
    text: str,
    platform: str,
    *,
    limit: int | None = None,
    max_parts: int = 25,
) -> list[str]:
    """Split *text* into numbered parts, each within the platform limit.

    The prefix (``1/5 ``) counts against the limit, so the body budget for
    part *i* is the limit minus the length of that part's own prefix.
    Returns ``[text]`` unchanged when it already fits.
    """
    if text is None:
        raise ValueError("text is required")
    if limit is None:
        limit = platform_limit(platform)

    def count_fn(s: str) -> int:  # noqa: D401
        return platform_count(platform, s)

    normalised = re.sub(r"\n{3,}", "\n\n", text.replace("\r\n", "\n").replace("\r", "\n")).strip()
    if not normalised:
        return [normalised]
    if count_fn(normalised) <= limit:
        return [normalised]

    # Smallest part count that can hold the text at all.
    parts = 2
    while parts <= max_parts:
        budget = limit - count_fn(thread_prefix(parts, parts))
        if parts * budget >= count_fn(normalised):
            break
        parts += 1
    budget = limit - count_fn(thread_prefix(parts, parts))
    pieces = _chunk(normalised, parts, budget, count_fn)

    out = [f"{thread_prefix(i + 1, parts)}{piece}" for i, piece in enumerate(pieces)]
    # Safety net: if rounding pushed a piece over, shred it into an extra part.
    while out and any(count_fn(p) > limit for p in out):
        overflow = next(i for i, p in enumerate(out) if count_fn(p) > limit)
        prefix = thread_prefix(overflow + 1, len(out))
        body = out[overflow][len(prefix):].lstrip()
        avail = limit - count_fn(thread_prefix(overflow + 1, len(out) + 1))
        cut = _find_cut(body, avail, count_fn)
        if cut <= 0:
            cut = 1
        head = body[:cut].rstrip() or body[:1]
        tail = body[len(head):].lstrip()
        if not tail:
            break
        new_pieces = [p[len(thread_prefix(i + 1, len(out))):].lstrip() for i, p in enumerate(out)]
        new_pieces[overflow] = head
        new_pieces.insert(overflow + 1, tail)
        total = len(new_pieces)
        out = [f"{thread_prefix(i + 1, total)}{p}" for i, p in enumerate(new_pieces)]

    return out


def thread_preview(text: str, platform: str, *, limit: int | None = None) -> str:
    """A human-readable preview of the split thread."""
    from .platforms import platform_limit as _limit

    cap = limit if limit is not None else _limit(platform)
    parts = split_thread(text, platform, limit=limit)
    lines: list[str] = []
    for i, part in enumerate(parts, 1):
        used = platform_count(platform, part)
        lines.append(f"Part {i}/{len(parts)} ({used}/{cap})")
        lines.append(part)
        lines.append("")
    return "\n".join(lines).rstrip("\n")
