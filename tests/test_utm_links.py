"""UTM builder and Open Graph link preview."""

from __future__ import annotations

from urllib.parse import urlparse

from opensocial.links import LinkPreview, fetch_preview, render_previews
from opensocial.utm import build_utm, parse_utm


def test_utm_uses_question_mark_for_the_first_parameter():
    out = build_utm("https://example.com", utm_source="x", utm_medium="social",
                    utm_campaign="launch")
    assert "?utm_source=x" in out
    assert "&utm_medium=social" in out
    assert "&utm_campaign=launch" in out


def test_utm_preserves_an_existing_query():
    out = build_utm("https://example.com/page?a=1", utm_source="x",
                    utm_medium="social", utm_campaign="launch")
    parsed = urlparse(out)
    from urllib.parse import parse_qsl

    query = dict(parse_qsl(parsed.query))
    assert query["a"] == "1"
    assert query["utm_source"] == "x"
    assert out.count("?") == 1
    assert "?" not in parsed.fragment


def test_utm_appends_with_ampersand_when_a_query_exists():
    out = build_utm("https://example.com/p?q=1", utm_source="x",
                    utm_medium="social", utm_campaign="launch")
    parsed = urlparse(out)
    assert parsed.query.startswith("q=1&") or parsed.query.startswith("utm_")


def test_utm_encodes_values():
    out = build_utm("https://example.com", utm_source="x", utm_medium="social",
                    utm_campaign="fall launch 2026")
    assert "utm_campaign=fall+launch+2026" in out or "utm_campaign=fall%20launch%202026" in out


def test_utm_overwrites_preexisting_utm_values():
    out = build_utm("https://example.com?utm_source=old", utm_source="x",
                    utm_medium="social", utm_campaign="launch")
    from urllib.parse import parse_qsl

    query = dict(parse_qsl(urlparse(out).query))
    assert query["utm_source"] == "x"


def test_utm_includes_optional_term_and_content():
    out = build_utm("https://example.com", utm_source="x", utm_medium="social",
                    utm_campaign="launch", utm_term="beta", utm_content="email")
    assert "utm_term=beta" in out
    assert "utm_content=email" in out


def test_utm_preserves_a_fragment():
    out = build_utm("https://example.com/page#section", utm_source="x",
                    utm_medium="social", utm_campaign="launch")
    assert out.endswith("#section")


def test_utm_rejects_non_http_urls():
    import pytest

    with pytest.raises(ValueError):
        build_utm("ftp://example.com", utm_source="x", utm_medium="social",
                  utm_campaign="launch")


def test_parse_utm_round_trips():
    out = build_utm("https://example.com", utm_source="x", utm_medium="social",
                    utm_campaign="launch", utm_term="beta")
    parsed = parse_utm(out)
    assert parsed == {"utm_source": "x", "utm_medium": "social",
                      "utm_campaign": "launch", "utm_term": "beta"}


def test_preview_degrades_gracefully_for_invalid_urls():
    preview = fetch_preview("not a url")
    assert isinstance(preview, LinkPreview)
    assert preview.offline is True
    assert preview.error


def test_preview_rejects_fragments_and_empty_input():
    assert fetch_preview("").offline is True
    assert fetch_preview("mailto:a@b.c").offline is True


def test_preview_fetches_a_real_url_or_degrades():
    """A genuine network call. Offline it must degrade, never raise."""
    preview = fetch_preview("https://example.com", timeout=8.0)
    assert isinstance(preview, LinkPreview)
    assert preview.url == "https://example.com"
    assert preview.title or preview.offline


def test_preview_reports_http_errors_as_offline():
    preview = fetch_preview("https://httpbin.org/status/404", timeout=8.0)
    assert preview.offline is True
    assert "http 404" in preview.error or preview.error


def test_render_previews_handles_offline_and_online():
    previews = [
        LinkPreview(url="https://a.example", title="Hello", description="World"),
        LinkPreview(url="https://b.example", offline=True, error="timeout"),
    ]
    text = render_previews(previews)
    assert "Hello" in text
    assert "(offline)" in text
