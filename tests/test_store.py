"""Store: schema, CRUD, JSON columns, statuses, counts."""

from __future__ import annotations

import pytest

from opensocial.store import STATUSES, Store, parse_iso, utcnow_iso


def test_schema_creates_all_four_tables(store):
    assert set(store.tables()) >= {"channels", "posts", "hashtag_sets", "templates"}


def test_add_channel_and_duplicate_detection(store, x_channel):
    channel = store.get_channel(x_channel)
    assert channel["platform"] == "x"
    assert channel["handle"] == "@testlab"
    assert channel["name"] == "@testlab"
    second = store.add_channel("x", "@otherhandle")
    assert second != x_channel
    assert len(store.list_channels()) == 2


def test_add_post_stores_json_columns_round_trip(store, x_channel):
    post_id = store.add_post(
        x_channel,
        "hello",
        urls=["https://a.example", "https://b.example"],
        tags=["#launch", "open source"],
    )
    post = store.get_post(post_id)
    assert post["urls"] == ["https://a.example", "https://b.example"]
    assert post["tags"] == ["launch", "open source"]
    assert post["status"] == "draft"
    assert post["created_at"] == post["updated_at"]


def test_add_post_rejects_unknown_channel(store):
    with pytest.raises(ValueError):
        store.add_post(99, "hello")


def test_add_post_rejects_empty_body(store, x_channel):
    with pytest.raises(ValueError):
        store.add_post(x_channel, "   ")


def test_add_post_rejects_bad_status(store, x_channel):
    with pytest.raises(ValueError):
        store.add_post(x_channel, "hello", status="yolo")
    assert set(STATUSES) == {
        "draft",
        "review",
        "scheduled",
        "approved",
        "published",
        "failed",
    }


def test_update_post_touches_updated_at_and_status(store, x_channel):
    post_id = store.add_post(x_channel, "hello")
    before = store.get_post(post_id)
    store.update_post(post_id, status="review")
    after = store.get_post(post_id)
    assert after["status"] == "review"
    assert after["updated_at"] >= before["updated_at"]


def test_update_post_normalises_lists_to_json(store, x_channel):
    post_id = store.add_post(x_channel, "hello", tags=["a"])
    store.update_post(post_id, tags=["a", "b", "c"])
    assert store.get_post(post_id)["tags"] == ["a", "b", "c"]


def test_update_post_rejects_unknown_status(store, x_channel):
    post_id = store.add_post(x_channel, "hello")
    with pytest.raises(ValueError):
        store.update_post(post_id, status="nope")


def test_update_unknown_post_returns_false(store):
    assert store.update_post(12345, status="draft") is False


def test_list_posts_filters(store, seeded):
    all_posts = store.list_posts()
    assert len(all_posts) == 4
    scheduled = store.list_posts(status="scheduled")
    assert len(scheduled) == 1
    by_channel = store.list_posts(channel_id=seeded["instagram"])
    assert len(by_channel) == 1


def test_delete_post_and_channel_cascade(store, seeded):
    post_id = seeded["ids"][0]
    assert store.delete_post(post_id) is True
    assert store.get_post(post_id) is None
    assert store.delete_post(999) is False


def test_delete_channel_removes_its_posts(store, seeded):
    instagram = seeded["instagram"]
    assert store.delete_channel(instagram) is True
    assert store.list_posts(channel_id=instagram) == []


def test_hashtag_sets_round_trip(store):
    store.add_hashtag_set("launch", ["#launch", "launch"])
    assert store.get_hashtag_set("launch")["hashtags"] == ["launch"]
    with pytest.raises(Exception):
        store.add_hashtag_set("launch", ["again"])  # UNIQUE(name)


def test_hashtag_set_delete(store):
    store.add_hashtag_set("alpha", ["a", "b"])
    assert store.get_hashtag_set("alpha")["hashtags"] == ["a", "b"]
    assert store.delete_hashtag_set("alpha") is True
    assert store.get_hashtag_set("alpha") is None


def test_templates_round_trip(store):
    store.add_template("launch", "Shipped {product} today")
    assert store.get_template("launch")["body"] == "Shipped {product} today"
    assert store.list_templates()[0]["name"] == "launch"
    assert store.delete_template("launch") is True
    assert store.get_template("launch") is None


def test_counts_reflect_state(store, seeded):
    counts = store.counts()
    assert counts["channels"] == 2
    assert counts["posts"] == 4


def test_parse_iso_handles_zulu_and_offsets():
    assert parse_iso("2026-10-26T09:00:00Z").strftime("%Y-%m-%d") == "2026-10-26"
    assert parse_iso("2026-10-26T14:30:00+05:30").hour == 9
    assert parse_iso(None) is None
    assert parse_iso("not a date") is None


def test_utcnow_iso_is_zulu(store):
    value = utcnow_iso()
    assert value.endswith("Z")
    assert parse_iso(value) is not None
