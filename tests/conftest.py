"""Shared fixtures: every test gets a throwaway SQLite file in tmp_path."""

from __future__ import annotations

import pytest

from opensocial.store import Store


@pytest.fixture()
def db_path(tmp_path) -> str:
    """A fresh, empty database path inside the test's tmp dir."""
    return str(tmp_path / "test.db")


@pytest.fixture()
def store(db_path):
    """An open Store bound to the throwaway database."""
    s = Store(db_path)
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def x_channel(store):
    """A channel id for X, ready to accept posts."""
    return store.add_channel("x", "@testlab")


@pytest.fixture()
def seeded(store, x_channel):
    """Two channels and four posts covering the whole workflow."""
    ig = store.add_channel("instagram", "@testlab", "Test Lab")
    p1 = store.add_post(
        x_channel,
        "Hello world from opensocial. This is the first post.",
        tags=["launch", "opensocial"],
        status="draft",
    )
    p2 = store.add_post(
        x_channel,
        "Second post with a link and a first comment.",
        first_comment="@testlab — thanks!",
        urls=["https://example.com/launch"],
        tags=["launch"],
        scheduled_at="2026-10-26T01:00:00Z",
        status="scheduled",
    )
    p3 = store.add_post(
        ig,
        "Instagram post with #launch #open #source #local #first hashtags.",
        tags=["launch"],
        scheduled_at="2026-10-27T12:00:00Z",
        status="approved",
        reviewed_by="Priya",
    )
    p4 = store.add_post(
        x_channel,
        "Published post.",
        status="published",
        published_at="2026-10-20T09:00:00Z",
        scheduled_at="2026-10-20T09:00:00Z",
    )
    return {
        "channels": store.list_channels(),
        "ids": [p1, p2, p3, p4],
        "x_channel": x_channel,
        "instagram": ig,
    }
