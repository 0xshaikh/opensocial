"""Open Graph / Twitter Card link previews.

A genuinely live network fetch with a short timeout.  Any failure --
DNS error, TLS error, timeout, missing tags -- degrades to an
``(offline)`` marker instead of raising, so offline use is always safe.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

#: Tags we look for, in preference order.
_OG_TAGS = (
    "og:title",
    "og:description",
    "og:image",
    "og:url",
    "og:site_name",
)
_TWITTER_TAGS = (
    "twitter:title",
    "twitter:description",
    "twitter:image",
    "twitter:site",
)

_TAG_RE = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
_ATTR_RE = re.compile(r"""(\w[\w:.-]*)\s*=\s*"([^"]*)"|(\w[\w:.-]*)\s*=\s*'([^']*)'""", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_LINK_ICON_RE = re.compile(
    r'<link[^>]*rel=["\'](?:icon|apple-touch-icon|shortcut icon)["\'][^>]*/?>',
    re.IGNORECASE,
)


@dataclass
class LinkPreview:
    """A single resolved preview."""

    url: str
    title: str = ""
    description: str = ""
    image: str = ""
    canonical: str = ""
    site: str = ""
    offline: bool = False
    error: str = ""
    extra: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "url": self.url,
            "title": self.title or "(offline)",
            "description": self.description or "",
            "image": self.image or "",
            "canonical": self.canonical or self.url,
            "site": self.site or "",
            "offline": self.offline,
            "error": self.error,
        }


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def _extract_tags(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for match in _TAG_RE.finditer(text):
        tag_text = match.group(0)
        attrs: dict[str, str] = {}
        for am in _ATTR_RE.finditer(tag_text):
            key = am.group(1) or am.group(3)
            val = am.group(2) if am.group(1) else am.group(4)
            attrs[key.lower()] = val
        name = attrs.get("property") or attrs.get("name") or ""
        content = attrs.get("content")
        if name and content:
            found[name.lower()] = content
    # fallback: name= / property= in any order is already covered above
    return found


def _first_relative(base: str, value: str) -> str:
    """Resolve a relative URL against *base* (stdlib only)."""
    if not value or value.startswith(("http://", "https://", "//")):
        return value
    parsed = urlparse(base)
    if parsed.scheme not in ("http", "https"):
        return ""
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if value.startswith("/"):
        return origin + value
    if value.startswith("../") or value.startswith("./"):
        stripped = value.lstrip("./")
        path = parsed.path.rsplit("/", 1)[0]
        return origin + path + "/" + stripped
    return origin + "/" + value


def fetch_preview(url: str, *, timeout: float = 6.0, user_agent: str = "opensocial/0.1.0") -> LinkPreview:
    """Fetch and parse preview tags for *url*; never raises on network failure."""
    preview = LinkPreview(url=url)
    if not url or not urlparse(url).scheme.startswith("http"):
        preview.offline = True
        preview.error = "not an http(s) url"
        return preview
    request = Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            charset = response.headers.get_content_charset() or "utf-8"
            raw = response.read(400_000)
    except HTTPError as exc:
        preview.offline = True
        preview.error = f"http {exc.code}"
        return preview
    except (TimeoutError, URLError, OSError, ValueError) as exc:
        preview.offline = True
        preview.error = f"{type(exc).__name__}: {exc}"
        return preview
    except Exception as exc:  # defensive: network code can raise anything
        preview.offline = True
        preview.error = f"{type(exc).__name__}: {exc}"
        return preview

    try:
        body = raw.decode(charset, errors="replace")
    except LookupError:
        body = raw.decode("utf-8", errors="replace")

    tags = _extract_tags(body)
    title_match = _TITLE_RE.search(body)
    preview.title = _clean(tags.get("og:title") or (title_match.group(1) if title_match else "") or "")
    preview.description = _clean(tags.get("og:description") or "")
    preview.site = _clean(tags.get("og:site_name") or "")
    preview.canonical = _clean(tags.get("og:url") or url)

    image = tags.get("og:image") or tags.get("twitter:image") or ""
    if not image:
        icon = _LINK_ICON_RE.search(body)
        if icon:
            for am in _ATTR_RE.finditer(icon.group(0)):
                key = am.group(1) or am.group(3)
                val = am.group(2) if am.group(1) else am.group(4)
                if key.lower() == "href":
                    image = val
                    break
    preview.image = _first_relative(url, _clean(image))

    for key, value in tags.items():
        if key.startswith("twitter:") and value:
            preview.extra[key] = _clean(value)
    return preview


def fetch_previews(urls: Iterable[str], **kwargs) -> list[LinkPreview]:
    """Resolve a batch of URLs, preserving order and de-duplicating."""
    seen: set[str] = set()
    out: list[LinkPreview] = []
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        out.append(fetch_preview(url, **kwargs))
    return out


def render_previews(previews: Iterable[LinkPreview]) -> str:
    """Human-readable preview block for the CLI."""
    lines: list[str] = []
    for preview in previews:
        if preview.offline and not preview.title:
            lines.append(f"• {preview.url}")
            lines.append(f"    (offline) {preview.error}")
            continue
        lines.append(f"• {preview.url}")
        lines.append(f"    {preview.title or '(no title)'}")
        if preview.description:
            lines.append(f"    {preview.description}")
        if preview.image:
            lines.append(f"    img: {preview.image}")
        if preview.offline:
            lines.append(f"    (offline) {preview.error}")
    return "\n".join(lines)
