"""UTM parameter builder."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

#: Canonical UTM parameters, in canonical order.
UTM_PARAMS = ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content")


def build_utm(url: str, **params: str) -> str:
    """Append UTM parameters to *url*, preserving any existing query.

    ``?`` is used for the first parameter and ``&`` thereafter, values
    are percent-encoded, and pre-existing UTM keys are overwritten.
    """
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"expected an http(s) url, got {url!r}")
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key in UTM_PARAMS:
        long_key = key
        value = params.get(key)
        if value in (None, ""):
            continue
        query[long_key] = str(value)
    # drop any UTM keys the caller explicitly blanked
    for key, value in params.items():
        if value == "":
            query.pop(key, None)
    new_query = urlencode(query, doseq=True)
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment,
        )
    )


def parse_utm(url: str) -> dict[str, str]:
    """Extract the UTM parameters present on *url*."""
    parsed = urlparse(url)
    return {k: v for k, v in parse_qsl(parsed.query) if k.startswith("utm_")}
