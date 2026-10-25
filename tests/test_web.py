"""Flask UI tests using the test client (no real sockets)."""

from __future__ import annotations

import pytest

from opensocial.web import create_app


@pytest.fixture()
def client(tmp_path):
    app = create_app(str(tmp_path / "web.db"))
    app.config["TESTING"] = True
    return app.test_client()


def test_index_renders_200(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Content calendar" in response.data


def test_index_shows_compose_link(client):
    response = client.get("/")
    assert b"Compose" in response.data


def test_posts_page_renders(client):
    response = client.get("/posts")
    assert response.status_code == 200
    assert b"Posts" in response.data


def test_compose_page_renders_with_live_counter_js(client):
    response = client.get("/posts/new")
    assert response.status_code == 200
    assert b"/api/count" in response.data
    assert b"/api/thread" in response.data
    assert b"thread-preview" in response.data
    # dark theme stylesheet is linked, no CDN, no framework
    assert b"style.css" in response.data
    assert b"cdn" not in response.data.lower()


def test_compose_requires_a_channel(client):
    response = client.post("/posts/new", data={"platform": "x", "body": "hello"})
    assert response.status_code == 200  # error re-renders the form
    assert b"add a channel first" in response.data


def test_compose_requires_a_body(client):
    client.get("/channels/new")
    client.post("/channels/new", data={"platform": "x", "handle": "@lab"})
    response = client.post("/posts/new", data={"platform": "x", "body": "  "})
    assert b"must not be empty" in response.data


def test_full_compose_and_detail_flow(client):
    client.post("/channels/new", data={"platform": "x", "handle": "@lab", "name": "Lab"})
    response = client.post(
        "/posts/new",
        data={
            "platform": "x",
            "body": "Hello from the web composer.",
            "first_comment": "thanks everyone",
            "urls": "https://example.com",
            "tags": "launch open-source",
        },
    )
    assert response.status_code == 302
    detail = client.get(response.headers["Location"])
    assert detail.status_code == 200
    assert b"Hello from the web composer." in detail.data
    assert b"thanks everyone" in detail.data


def test_status_transition_to_published_via_form(client):
    client.post("/channels/new", data={"platform": "x", "handle": "@lab"})
    client.post("/posts/new", data={"platform": "x", "body": "publish me"})
    response = client.post(
        "/posts/1", data={"action": "publish"}
    )
    assert response.status_code == 302
    page = client.get("/posts/1")
    assert b"published" in page.data
    assert b"local state only" in page.data


def test_post_detail_404s_for_unknown_ids(client):
    response = client.get("/posts/999")
    assert response.status_code == 404


def test_channels_pages_render(client):
    assert client.get("/channels").status_code == 200
    assert client.get("/channels/new").status_code == 200
    response = client.post("/channels/new", data={"platform": "x", "handle": "@a"})
    assert response.status_code == 302
    page = client.get("/channels")
    assert b"@a" in page.data


def test_hashtags_and_templates_pages_render(client):
    assert client.get("/hashtags").status_code == 200
    assert b"within hashtag guidance" in client.get("/hashtags").data
    assert client.get("/templates").status_code == 200


def test_stats_page_renders_css_bars(client):
    client.post("/channels/new", data={"platform": "x", "handle": "@lab"})
    client.post("/posts/new", data={"platform": "x", "body": "hello"})
    response = client.get("/stats")
    assert response.status_code == 200
    assert b"chart" in response.data
    assert b"fill" in response.data
    assert b"By status" in response.data


def test_api_count_returns_platform_accuracy(client):
    response = client.get("/api/count?platform=x&text=hello")
    assert response.status_code == 200
    body = response.get_json()
    assert body["length"] == 5
    assert body["limit"] == 280
    assert body["remaining"] == 275
    assert body["over"] is False


def test_api_count_flags_over_limit(client):
    body = client.get("/api/count?platform=x&text=" + "x" * 300).get_json()
    assert body["over"] is True
    assert body["remaining"] < 0


def test_api_thread_splits_long_text(client):
    text = "Sentence one ends here. " * 30
    body = client.get(
        "/api/thread?platform=x&text=" + text.replace(" ", "%20")
    ).get_json()
    assert body["count"] >= 2
    assert all(length <= body["limit"] for length in body["lengths"])


def test_api_thread_unknown_platform_is_a_bad_request(client):
    assert client.get("/api/thread?platform=nope").status_code == 400
    assert client.get("/api/count?platform=nope").status_code == 400


def test_export_endpoints_stream_downloadable_files(client):
    client.post("/channels/new", data={"platform": "x", "handle": "@lab"})
    client.post("/posts/new", data={"platform": "x", "body": "export me"})
    response = client.get("/export/ics")
    assert response.status_code == 200
    assert "text/calendar" in response.content_type
    assert b"BEGIN:VCALENDAR" in response.data
    assert "attachment" in response.headers["Content-Disposition"]

    csv = client.get("/export/csv")
    assert csv.status_code == 200
    assert b'"id"' in csv.data

    rss = client.get("/export/rss")
    assert rss.status_code == 200
    assert b"<rss" in rss.data

    atom = client.get("/export/atom")
    assert atom.status_code == 200
    assert b"<feed" in atom.data

    md = client.get("/export/md")
    assert md.status_code == 200
    assert md.content_type.startswith("text/markdown")


def test_export_unknown_format_404s(client):
    assert client.get("/export/xml").status_code == 404


def test_404_page_renders(client):
    response = client.get("/definitely/not/a/route")
    assert response.status_code == 404
    assert b"404" in response.data


def test_static_css_is_served(client):
    response = client.get("/static/style.css")
    assert response.status_code == 200
    assert b"--bg:" in response.data
