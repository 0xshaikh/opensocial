"""Analytics: aggregates computed from local rows only."""

from __future__ import annotations

from opensocial.analytics import render_stats, stats


def test_stats_counts_by_status_and_platform(store, seeded):
    payload = stats(store)
    assert payload["total_posts"] == 4
    assert payload["total_channels"] == 2
    assert payload["by_status"]["draft"] == 1
    assert payload["by_status"]["scheduled"] == 1
    assert payload["by_status"]["approved"] == 1
    assert payload["by_status"]["published"] == 1
    assert payload["by_platform"]["x"] == 3
    assert payload["by_platform"]["instagram"] == 1


def test_stats_length_summary(store, seeded):
    payload = stats(store)
    lengths = payload["lengths"]
    assert lengths["max"] >= lengths["min"]
    assert lengths["avg"] >= 0
    assert lengths["median"] > 0


def test_stats_top_hashtags(store, seeded):
    payload = stats(store, top_hashtags=5)
    tags = dict(payload["top_hashtags"])
    assert tags["launch"] == 1  # only the instagram body carries #launch
    assert tags["open"] == 1
    assert tags["source"] == 1
    assert sum(tags.values()) == 5


def test_stats_day_of_week_covers_all_seven_days(store, seeded):
    payload = stats(store)
    assert set(payload["day_of_week"]) == {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}


def test_stats_per_day_window(store, seeded):
    payload = stats(store, days=14)
    assert len(payload["per_day"]) == 14
    assert payload["window_days"] == 14
    assert all(isinstance(v, int) for v in payload["per_day"].values())


def test_stats_limit_compliance(store, seeded):
    payload = stats(store)
    assert payload["limit_compliance"]["total"] == 4
    assert payload["limit_compliance"]["over_limit"] == 0
    assert payload["limit_compliance"]["within_limit"] == 4


def test_stats_counts_over_limit_posts(store, seeded):
    x_channel = seeded["x_channel"]
    store.add_post(x_channel, "y" * 400)
    payload = stats(store)
    assert payload["limit_compliance"]["over_limit"] == 1
    assert payload["total_posts"] == 5


def test_stats_cadence_reports_median_gap(store, seeded):
    x_channel = seeded["x_channel"]
    store.add_post(x_channel, "a", scheduled_at="2026-10-01T00:00:00Z")
    store.add_post(x_channel, "b", scheduled_at="2026-10-04T00:00:00Z")
    store.add_post(x_channel, "c", scheduled_at="2026-10-10T00:00:00Z")
    payload = stats(store)
    cadence = payload["cadence"]
    assert any("x/" in label for label in cadence)
    label = next(label for label in cadence if label.startswith("x/"))
    assert cadence[label]["scheduled"] >= 3
    assert cadence[label]["median_gap_days"] is not None


def test_stats_empty_database(store):
    payload = stats(store)
    assert payload["total_posts"] == 0
    assert payload["lengths"]["avg"] == 0
    assert payload["cadence"] == {}
    assert payload["top_hashtags"] == []


def test_render_stats_text_and_json(store, seeded):
    payload = stats(store)
    text = render_stats(payload)
    assert "opensocial stats" in text
    assert "by status" in text
    assert "cadence" in text
    import json as _json

    parsed = _json.loads(render_stats(payload, json_mode=True))
    assert parsed["total_posts"] == 4
