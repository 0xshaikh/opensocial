"""SQLite persistence layer for opensocial.

One DB file, four tables, no framework.  Everything the CLI and the web
UI need is reachable through a single :class:`Store` object.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .platforms import platform_count

SCHEMA_VERSION = 1

#: Legal post statuses, in workflow order.
STATUSES = ("draft", "review", "scheduled", "approved", "published", "failed")

DEFAULT_DB = "~/.opensocial/opensocial.db"


def utcnow_iso() -> str:
    """Current time as a UTC ISO-8601 string with a trailing ``Z``."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO-8601 string (with ``Z`` or offset) into an aware datetime."""
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def db_path() -> Path:
    """Resolve the DB path from ``OPENSOCIAL_DB`` or the package default."""
    raw = os.environ.get("OPENSOCIAL_DB") or DEFAULT_DB
    return Path(os.path.expanduser(raw))


_SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    handle TEXT NOT NULL,
    name TEXT,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_channels_platform_handle
    ON channels (platform, handle);
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL,
    body TEXT NOT NULL,
    first_comment TEXT DEFAULT '',
    urls TEXT DEFAULT '[]',
    tags TEXT DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'draft',
    scheduled_at TEXT,
    published_at TEXT,
    reviewed_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (channel_id) REFERENCES channels (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_posts_channel ON posts (channel_id);
CREATE INDEX IF NOT EXISTS idx_posts_status ON posts (status);
CREATE INDEX IF NOT EXISTS idx_posts_scheduled ON posts (scheduled_at);
CREATE TABLE IF NOT EXISTS hashtag_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    hashtags TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class Store:
    """A thin, typed wrapper around the SQLite database."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else db_path()
        if self.path.parent and str(self.path.parent) not in ("", "."):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.migrate()

    # ------------------------------------------------------------------ #
    # schema
    # ------------------------------------------------------------------ #
    def migrate(self) -> None:
        self.conn.executescript(_SCHEMA)
        self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # small helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _loads(text: str | None, default: Any) -> Any:
        if not text:
            return default
        try:
            return json.loads(text)
        except (TypeError, ValueError):
            return default

    def _row_to_post(self, row: sqlite3.Row) -> dict:
        post = dict(row)
        post["urls"] = self._loads(post.get("urls"), [])
        post["tags"] = self._loads(post.get("tags"), [])
        post["body_length"] = platform_count(
            self.platform_of(post.get("channel_id")), post.get("body") or ""
        )
        return post

    def platform_of(self, channel_id: int | None) -> str:
        if channel_id is None:
            return "x"
        row = self.conn.execute(
            "SELECT platform FROM channels WHERE id = ?", (channel_id,)
        ).fetchone()
        return row["platform"] if row else "x"

    # ------------------------------------------------------------------ #
    # channels
    # ------------------------------------------------------------------ #
    def add_channel(self, platform: str, handle: str, name: str | None = None) -> int:
        now = utcnow_iso()
        cur = self.conn.execute(
            "INSERT INTO channels (platform, handle, name, created_at) VALUES (?,?,?,?)",
            (platform, handle, name or handle, now),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_channels(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM channels ORDER BY platform, handle"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_channel(self, channel_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM channels WHERE id = ?", (channel_id,)
        ).fetchone()
        return dict(row) if row else None

    def delete_channel(self, channel_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
        self.conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------ #
    # posts
    # ------------------------------------------------------------------ #
    def add_post(
        self,
        channel_id: int,
        body: str,
        *,
        first_comment: str = "",
        urls: Iterable[str] = (),
        tags: Iterable[str] = (),
        status: str = "draft",
        scheduled_at: str | None = None,
        published_at: str | None = None,
        reviewed_by: str | None = None,
    ) -> int:
        if status not in STATUSES:
            raise ValueError(f"invalid status {status!r}; expected one of {STATUSES}")
        if self.get_channel(channel_id) is None:
            raise ValueError(f"unknown channel {channel_id}")
        if not (body or "").strip():
            raise ValueError("post body must not be empty")
        now = utcnow_iso()
        urls = [str(u) for u in urls if str(u).strip()]
        tags = [str(t).lstrip("#") for t in tags if str(t).strip()]
        cur = self.conn.execute(
            """INSERT INTO posts
               (channel_id, body, first_comment, urls, tags, status,
                scheduled_at, published_at, reviewed_by, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                channel_id,
                body,
                first_comment or "",
                self._dumps(list(urls)),
                self._dumps(list(tags)),
                status,
                scheduled_at,
                published_at,
                reviewed_by,
                now,
                now,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_post(self, post_id: int, **fields: Any) -> bool:
        allowed = {
            "body",
            "first_comment",
            "urls",
            "tags",
            "status",
            "scheduled_at",
            "published_at",
            "reviewed_by",
            "channel_id",
        }
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return False
        if "status" in updates and updates["status"] not in STATUSES:
            raise ValueError(
                f"invalid status {updates['status']!r}; expected one of {STATUSES}"
            )
        if "urls" in updates and not isinstance(updates["urls"], str):
            updates["urls"] = self._dumps(list(updates["urls"]))
        if "tags" in updates and not isinstance(updates["tags"], str):
            updates["tags"] = self._dumps(list(updates["tags"]))
        updates["updated_at"] = utcnow_iso()
        assignments = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [post_id]
        cur = self.conn.execute(
            f"UPDATE posts SET {assignments} WHERE id = ?", values
        )
        self.conn.commit()
        return cur.rowcount > 0

    def get_post(self, post_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM posts WHERE id = ?", (post_id,)
        ).fetchone()
        return self._row_to_post(row) if row else None

    def list_posts(self, *, status: str | None = None, channel_id: int | None = None) -> list[dict]:
        query = "SELECT * FROM posts WHERE 1=1"
        args: list[Any] = []
        if status:
            query += " AND status = ?"
            args.append(status)
        if channel_id is not None:
            query += " AND channel_id = ?"
            args.append(channel_id)
        query += " ORDER BY id"
        return [self._row_to_post(r) for r in self.conn.execute(query, args).fetchall()]

    def delete_post(self, post_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        self.conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------ #
    # hashtag sets
    # ------------------------------------------------------------------ #
    def add_hashtag_set(self, name: str, hashtags: Iterable[str]) -> int:
        tags = [str(h).lstrip("#") for h in hashtags if str(h).strip()]
        tags = list(dict.fromkeys(tags))
        now = utcnow_iso()
        cur = self.conn.execute(
            "INSERT INTO hashtag_sets (name, hashtags, created_at) VALUES (?,?,?)",
            (name, self._dumps(tags), now),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_hashtag_sets(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM hashtag_sets ORDER BY name"
        ).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["hashtags"] = self._loads(item.pop("hashtags"), [])
            out.append(item)
        return out

    def get_hashtag_set(self, name: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM hashtag_sets WHERE LOWER(name) = LOWER(?)", (name,)
        ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["hashtags"] = self._loads(item.pop("hashtags"), [])
        return item

    def delete_hashtag_set(self, name: str) -> bool:
        cur = self.conn.execute(
            "DELETE FROM hashtag_sets WHERE LOWER(name) = LOWER(?)", (name,)
        )
        self.conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------ #
    # templates
    # ------------------------------------------------------------------ #
    def add_template(self, name: str, body: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO templates (name, body, created_at) VALUES (?,?,?)",
            (name, body, utcnow_iso()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_templates(self) -> list[dict]:
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM templates ORDER BY name"
            ).fetchall()
        ]

    def get_template(self, name: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM templates WHERE LOWER(name) = LOWER(?)", (name,)
        ).fetchone()
        return dict(row) if row else None

    def delete_template(self, name: str) -> bool:
        cur = self.conn.execute(
            "DELETE FROM templates WHERE LOWER(name) = LOWER(?)", (name,)
        )
        self.conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------ #
    # counts
    # ------------------------------------------------------------------ #
    def counts(self) -> dict[str, int]:
        out = {}
        for table in ("channels", "posts", "hashtag_sets", "templates"):
            out[table] = self.conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
        return out

    def tables(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        return [r["name"] for r in rows]
