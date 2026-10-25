"""Command-line interface for opensocial."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import __version__
from .analytics import render_stats, stats
from .calendar import (
    build_csv,
    build_ics,
    collect,
    render_grid,
)
from .feeds import atom_feed, import_csv, markdown_report, rss_feed
from .hashtags import count_hashtags, lint_posts, lint_report
from .links import fetch_previews, render_previews
from .platforms import (
    DISPLAY_NAMES,
    PLATFORM_LIMITS,
    platform_count,
    platform_limit,
    resolve_platform,
)
from .store import STATUSES, Store
from .threads import split_thread, thread_preview
from .utm import build_utm

EXIT_OK = 0
EXIT_BAD_INPUT = 1
EXIT_MISSING_DATA = 2


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _store(args: argparse.Namespace) -> Store:
    return Store(getattr(args, "db", None))


def _decorate(posts: list[dict], store: Store) -> list[dict]:
    channels = {c["id"]: c for c in store.list_channels()}
    out = []
    for post in posts:
        row = dict(post)
        channel = channels.get(post.get("channel_id")) or {}
        row["channel"] = channel.get("name") or f"@{channel.get('handle', '?')}"
        row["platform"] = channel.get("platform", "?")
        row["handle"] = channel.get("handle", "")
        out.append(row)
    return out


def _emit(payload, *, as_json: bool, text) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(text)


def _read_text(args) -> str:
    if getattr(args, "file", None):
        return Path(args.file).read_text(encoding="utf-8")
    if getattr(args, "text", None) is not None:
        return args.text
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise ValueError("nothing to compose: pass --text, --file, or pipe stdin")


def _parse_when(at: str, tz_name: str | None) -> str:
    """'2026-10-26 09:00' + tz -> UTC ISO-8601 with trailing Z."""
    tz = ZoneInfo(tz_name) if tz_name else timezone.utc
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            naive = datetime.strptime(at.strip(), fmt)
            break
        except ValueError:
            continue
    else:
        # tolerate ISO input with its own offset
        try:
            parsed = datetime.fromisoformat(at.strip())
            naive = parsed.replace(tzinfo=None) if parsed.tzinfo is None else parsed
        except ValueError as exc:
            raise ValueError(
                f"cannot parse {at!r} as 'YYYY-MM-DD HH:MM' "
                f"(or ISO-8601); e.g. '2026-10-26 09:00'"
            ) from exc
    aware = naive if naive.tzinfo else naive.replace(tzinfo=tz)
    utc = aware.astimezone(timezone.utc).replace(microsecond=0)
    return utc.isoformat().replace("+00:00", "Z")


def _over_limit_report(store: Store, post_id: int | None = None) -> list[dict]:
    posts = store.list_posts()
    if post_id is not None:
        posts = [p for p in posts if p["id"] == post_id]
    channels = {c["id"]: c for c in store.list_channels()}
    offenders: list[dict] = []
    for post in _decorate(posts, store):
        key = resolve_platform(post["platform"]) or post["platform"]
        limit = PLATFORM_LIMITS.get(key, 280)
        length = platform_count(key, post.get("body") or "")
        if length > limit:
            offenders.append(
                {
                    "id": post["id"],
                    "platform": post["platform"],
                    "handle": post.get("handle"),
                    "length": length,
                    "limit": limit,
                    "over_by": length - limit,
                }
            )
    return offenders


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #
def cmd_init(args) -> int:
    store = _store(args)
    counts = store.counts()
    print(f"opensocial {__version__}")
    print(f"database: {store.path}")
    print("tables: " + ", ".join(store.tables()))
    print(f"posts: {counts['posts']}   channels: {counts['channels']}")
    print("ready.")
    return EXIT_OK


def cmd_doctor(args) -> int:
    lines = [f"opensocial {__version__}", "=" * 33]
    lines.append(f"python   : {sys.version.split()[0]} ({sys.version.split()[1]})")
    try:
        import flask  # type: ignore

        lines.append(f"flask    : installed {getattr(flask, '__version__', '?')}")
        flask_ok = True
    except Exception as exc:  # noqa: BLE001
        lines.append(f"flask    : NOT installed ({exc.__class__.__name__})")
        flask_ok = False
    store = _store(args)
    lines.append(f"database : {store.path} ({'exists' if store.path.exists() else 'missing'})")
    expected = {"channels", "posts", "hashtag_sets", "templates"}
    present = set(store.tables())
    missing = sorted(expected - present)
    lines.append(f"tables   : {', '.join(sorted(present))}")
    if missing:
        lines.append(f"MISSING TABLES: {', '.join(missing)}")
    counts = store.counts()
    for name in ("channels", "posts", "hashtag_sets", "templates"):
        lines.append(f"{name + 's' if name != 'posts' else name:15}: {counts[name]}")
    verdict = "ok" if (flask_ok and not missing) else "degraded"
    lines.append(f"status   : {verdict}")
    print("\n".join(lines))
    return EXIT_OK


def cmd_channels_add(args) -> int:
    key = resolve_platform(args.platform)
    if key is None:
        print(f"unknown platform {args.platform!r}", file=sys.stderr)
        return EXIT_BAD_INPUT
    store = _store(args)
    for channel in store.list_channels():
        if (
            channel["platform"] == key
            and channel["handle"].lower() == args.handle.lower()
        ):
            print(f"channel already exists: {key} @{args.handle.lstrip('@')} (id {channel['id']})")
            return EXIT_OK
    channel_id = store.add_channel(key, args.handle, args.name)
    print(f"added channel #{channel_id}: {DISPLAY_NAMES[key]} @{args.handle.lstrip('@')}")
    return EXIT_OK


def cmd_channels_list(args) -> int:
    store = _store(args)
    channels = store.list_channels()
    if args.json:
        print(json.dumps(channels, indent=2, ensure_ascii=False))
        return EXIT_OK
    if not channels:
        print("no channels yet — `opensocial channels add --platform x --handle @you`")
        return EXIT_MISSING_DATA
    print(f"{'id':>3}  {'platform':<16} {'handle':<24} name")
    for channel in channels:
        print(
            f"{channel['id']:>3}  {channel['platform']:<16} "
            f"{channel['handle']:<24} {channel.get('name') or ''}"
        )
    return EXIT_OK


def cmd_channels_delete(args) -> int:
    store = _store(args)
    if not store.delete_channel(args.id):
        print(f"no channel #{args.id}", file=sys.stderr)
        return EXIT_MISSING_DATA
    print(f"deleted channel #{args.id}")
    return EXIT_OK


def cmd_add(args) -> int:
    store = _store(args)
    if not (args.text or args.file or not sys.stdin.isatty()):
        print("nothing to compose: pass --text, --file, or pipe stdin", file=sys.stderr)
        return EXIT_BAD_INPUT
    try:
        body = _read_text(args)
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_BAD_INPUT
    body = body.rstrip("\n")
    if not body.strip():
        print("post body must not be empty", file=sys.stderr)
        return EXIT_BAD_INPUT

    if args.channel_id:
        channel = store.get_channel(args.channel_id)
        if channel is None:
            print(f"unknown channel #{args.channel_id}", file=sys.stderr)
            return EXIT_MISSING_DATA
        channel_id = args.channel_id
    else:
        key = resolve_platform(args.platform)
        if key is None:
            print(f"unknown platform {args.platform!r}", file=sys.stderr)
            return EXIT_BAD_INPUT
        match = next(
            (
                c
                for c in store.list_channels()
                if c["platform"] == key
                and c["handle"].lower() == args.handle.lower()
            ),
            None,
        )
        if match is None:
            print(
                f"unknown channel {key} @{args.handle} — "
                f"`opensocial channels add --platform {key} --handle {args.handle}` first",
                file=sys.stderr,
            )
            return EXIT_MISSING_DATA
        channel_id = match["id"]

    urls = [u.strip() for u in (args.urls or []) if u.strip()]
    tags = [t.strip() for t in (args.tags or []) if t.strip()]
    platform = store.platform_of(channel_id)
    length = platform_count(platform, body)
    limit = platform_limit(platform)
    if length > limit:
        parts = split_thread(body, platform)
        print(
            f"NOTE: {length}/{limit} characters on {platform} — over the limit. "
            f"`opensocial thread --platform {platform} --text '…'` shows the "
            f"{len(parts)}-part numbered split; use --allow-over-limit to save anyway.",
            file=sys.stderr,
        )
        if not args.allow_over_limit:
            return EXIT_BAD_INPUT

    post_id = store.add_post(
        channel_id,
        body,
        first_comment=args.first_comment or "",
        urls=urls,
        tags=tags,
        status=args.status if args.status in STATUSES else "draft",
    )
    channel = store.get_channel(channel_id)
    display = channel.get("name") or f"@{channel['handle'].lstrip('@')}"
    print(
        f"added post #{post_id} ({channel['platform']} {display}): "
        f"{length}/{limit} chars, {len(tags)} tag(s) attached, "
        f"{count_hashtags(body)} hashtag(s) in body, status={args.status or 'draft'}"
    )
    if args.json:
        print(json.dumps(store.get_post(post_id), indent=2, ensure_ascii=False))
    return EXIT_OK


def cmd_check(args) -> int:
    store = _store(args)
    if args.id:
        post = store.get_post(args.id)
        if post is None:
            print(f"no post #{args.id}", file=sys.stderr)
            return EXIT_MISSING_DATA
        posts = _decorate([post], store)
    else:
        posts = _decorate(store.list_posts(), store)
    offenders = _over_limit_report(store, args.id)
    if args.json:
        print(json.dumps(offenders, indent=2, ensure_ascii=False))
        return EXIT_OK
    if not offenders:
        print(
            f"all {len(posts)} post(s) are within their platform limits (0 over-limit)"
        )
        return EXIT_OK
    print(f"{len(offenders)} post(s) exceed their platform limit:")
    for item in offenders:
        print(
            f"  #{item['id']} {item['platform']} @{(item['handle'] or '').lstrip('@')}: "
            f"{item['length']}/{item['limit']} (+{item['over_by']})"
        )
    return EXIT_BAD_INPUT


def cmd_thread(args) -> int:
    store = _store(args)
    if args.id:
        post = store.get_post(args.id)
        if post is None:
            print(f"no post #{args.id}", file=sys.stderr)
            return EXIT_MISSING_DATA
        body = post["body"]
        platform = store.platform_of(post["channel_id"])
    else:
        body = _read_text(args)
        key = resolve_platform(args.platform)
        if key is None:
            print(f"unknown platform {args.platform!r}", file=sys.stderr)
            return EXIT_BAD_INPUT
        platform = key
    parts = split_thread(body, platform)
    if args.json:
        print(json.dumps(parts, indent=2, ensure_ascii=False))
        return EXIT_OK
    print(thread_preview(body, platform))
    return EXIT_OK


def cmd_schedule(args) -> int:
    store = _store(args)
    post = store.get_post(args.id)
    if post is None:
        print(f"no post #{args.id}", file=sys.stderr)
        return EXIT_MISSING_DATA
    try:
        utc = _parse_when(args.at, args.tz)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_BAD_INPUT
    status = "scheduled" if post["status"] in ("draft", "review") else post["status"]
    store.update_post(args.id, scheduled_at=utc, status=status)
    when = f"{args.at}" + (f" ({args.tz})" if args.tz else "")
    print(f"scheduled post #{args.id} for {when} -> {utc} (status={status})")
    return EXIT_OK


def cmd_review(args) -> int:
    store = _store(args)
    post = store.get_post(args.id)
    if post is None:
        print(f"no post #{args.id}", file=sys.stderr)
        return EXIT_MISSING_DATA
    store.update_post(
        args.id, status="approved", reviewed_by=args.by,
        published_at=post["published_at"],
    )
    print(f"approved post #{args.id} — reviewed by {args.by}")
    return EXIT_OK


def cmd_publish_due(args) -> int:
    store = _store(args)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    stamp = now.isoformat().replace("+00:00", "Z")
    eligible = store.list_posts(status="scheduled") + store.list_posts(status="approved")
    published = []
    for post in eligible:
        when = post.get("scheduled_at")
        due = True if args.now else (when is not None and datetime.fromisoformat(when.replace("Z", "+00:00")) <= now)
        if not due:
            continue
        store.update_post(post["id"], status="published", published_at=stamp)
        published.append(post["id"])
    if args.json:
        print(json.dumps({"published": published, "count": len(published)}, indent=2))
        return EXIT_OK
    if not published:
        print("nothing due to publish")
        return EXIT_OK
    print(f"published {len(published)} post(s): " + ", ".join(f"#{i}" for i in published))
    return EXIT_OK


def cmd_calendar(args) -> int:
    store = _store(args)
    posts = collect(store, days=args.days)
    print(render_grid(posts, days=args.days, json_mode=args.json))
    return EXIT_OK


def cmd_export(args) -> int:
    store = _store(args)
    posts = _decorate(store.list_posts(), store)
    if args.status:
        posts = [p for p in posts if p["status"] == args.status]
    formatter = {
        "ics": build_ics,
        "csv": build_csv,
        "rss": rss_feed,
        "atom": atom_feed,
        "md": markdown_report,
    }.get(args.format)
    if formatter is None:
        print(f"unknown export format {args.format!r}", file=sys.stderr)
        return EXIT_BAD_INPUT
    if not posts:
        print(f"no posts to export (status={args.status or 'any'})", file=sys.stderr)
        return EXIT_MISSING_DATA
    payload = formatter(posts)
    _write(args.out, payload)
    print(
        f"exported {len(posts)} post(s) as {args.format} "
        f"({'to ' + args.out if args.out else 'to stdout'})"
    )
    return EXIT_OK


def _write(path: str | None, content: str) -> None:
    if not path:
        sys.stdout.write(content)
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def cmd_import(args) -> int:
    store = _store(args)
    try:
        text = Path(args.in_file).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"cannot read {args.in_file}: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT
    try:
        created = import_csv(store, text)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_BAD_INPUT
    print(f"imported {len(created)} post(s): " + ", ".join(f"#{p['id']}" for p in created))
    if args.json:
        print(json.dumps(created, indent=2, ensure_ascii=False))
    return EXIT_OK


def cmd_hashtags_save(args) -> int:
    store = _store(args)
    tags = [t.strip() for t in args.tags if t.strip()]
    if not tags:
        print("no hashtags given", file=sys.stderr)
        return EXIT_BAD_INPUT
    store.add_hashtag_set(args.name, tags)
    print(f"saved hashtag set {args.name!r} with {len(tags)} tags")
    return EXIT_OK


def cmd_hashtags_list(args) -> int:
    store = _store(args)
    sets = store.list_hashtag_sets()
    if args.json:
        print(json.dumps(sets, indent=2, ensure_ascii=False))
        return EXIT_OK
    if not sets:
        print("no hashtag sets yet")
        return EXIT_MISSING_DATA
    for item in sets:
        print(f"{item['name']:<24} " + " ".join(f"#{t}" for t in item["hashtags"]))
    return EXIT_OK


def cmd_hashtags_apply(args) -> int:
    store = _store(args)
    item = store.get_hashtag_set(args.name)
    if item is None:
        print(f"no hashtag set named {args.name!r}", file=sys.stderr)
        return EXIT_MISSING_DATA
    post = store.get_post(args.id)
    if post is None:
        print(f"no post #{args.id}", file=sys.stderr)
        return EXIT_MISSING_DATA
    merged = list(dict.fromkeys((post.get("tags") or []) + item["hashtags"]))
    store.update_post(args.id, tags=merged)
    print(f"applied {args.name} to post #{args.id} ({len(merged)} tags total)")
    return EXIT_OK


def cmd_hashtags_lint(args) -> int:
    store = _store(args)
    posts = _decorate(store.list_posts(), store)
    findings = lint_posts(posts)
    if args.json:
        print(json.dumps(findings, indent=2, ensure_ascii=False))
        return EXIT_OK
    print(lint_report(findings))
    return EXIT_BAD_INPUT if findings else EXIT_OK


def cmd_templates_add(args) -> int:
    store = _store(args)
    if args.file:
        try:
            body = Path(args.file).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"cannot read {args.file}: {exc}", file=sys.stderr)
            return EXIT_BAD_INPUT
    else:
        body = args.body or ""
    if not body.strip():
        print("template body must not be empty", file=sys.stderr)
        return EXIT_BAD_INPUT
    store.add_template(args.name, body)
    print(f"saved template {args.name!r}")
    return EXIT_OK


def cmd_templates_list(args) -> int:
    store = _store(args)
    items = store.list_templates()
    if args.json:
        print(json.dumps(items, indent=2, ensure_ascii=False))
        return EXIT_OK
    if not items:
        print("no templates yet")
        return EXIT_MISSING_DATA
    for item in items:
        print(f"{item['name']:<24} {item['body'][:60]}")
    return EXIT_OK


def cmd_templates_render(args) -> int:
    store = _store(args)
    from .templates import render

    item = store.get_template(args.name)
    if item is None:
        print(f"no template named {args.name!r}", file=sys.stderr)
        return EXIT_MISSING_DATA
    values = dict(kv.split("=", 1) for kv in (args.var or []) if "=" in kv)
    out = render(item["body"], **values)
    if args.out:
        _write(args.out, out)
        print(f"rendered {args.name} to {args.out}")
    else:
        print(f"template {args.name} ->")
        print(out)
    return EXIT_OK


def cmd_link(args) -> int:
    previews = fetch_previews(args.url, timeout=args.timeout)
    if args.json:
        print(json.dumps([p.as_dict() for p in previews], indent=2, ensure_ascii=False))
        return EXIT_OK
    print(render_previews(previews))
    return EXIT_OK


def cmd_utm(args) -> int:
    try:
        out = build_utm(
            args.url,
            utm_source=args.source,
            utm_medium=args.medium,
            utm_campaign=args.campaign,
            utm_term=args.term,
            utm_content=args.content,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_BAD_INPUT
    print(out)
    return EXIT_OK


def cmd_stats(args) -> int:
    store = _store(args)
    if not store.list_posts():
        print("no posts yet — nothing to report", file=sys.stderr)
        return EXIT_MISSING_DATA
    payload = stats(store, days=args.days)
    print(render_stats(payload, json_mode=args.json))
    return EXIT_OK


def cmd_serve(args) -> int:
    try:
        from .web import create_app
    except ImportError as exc:
        print(f"cannot start the web UI: {exc}", file=sys.stderr)
        print("install it with `pip install flask`", file=sys.stderr)
        return EXIT_BAD_INPUT
    app = create_app(getattr(args, "db", None))
    print(f"opensocial {__version__} serving on http://{args.host}:{args.port}")
    print("(local only — no network publishing, no external calls)")
    app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=False)
    return EXIT_OK


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opensocial",
        description=(
            "Open-source, local-first Buffer alternative: compose, thread, "
            "schedule, review and export social posts. SQLite only, no API "
            "keys, and deliberately no network publishing."
        ),
    )
    parser.add_argument("--version", action="version", version=f"opensocial {__version__}")
    parser.add_argument(
        "--db",
        default=None,
        help="path to the SQLite database (default: $OPENSOCIAL_DB or ~/.opensocial/opensocial.db)",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    sub.add_parser("init", help="create the database and show its state")
    sub.add_parser("doctor", help="environment and database health check")

    # channels ---------------------------------------------------------
    channels = sub.add_parser("channels", help="manage publishing channels (multi-account)")
    channels_sub = channels.add_subparsers(dest="action", required=True)
    ch_add = channels_sub.add_parser("add", help="add a channel, e.g. two X handles")
    ch_add.add_argument("--platform", required=True, help="x, bluesky, mastodon, threads, ...")
    ch_add.add_argument("--handle", required=True, help="handle, e.g. @launchlab")
    ch_add.add_argument("--name", help="display name (defaults to the handle)")
    ch_list = channels_sub.add_parser("list", help="list channels")
    ch_list.add_argument("--json", action="store_true")
    ch_del = channels_sub.add_parser("delete", help="delete a channel")
    ch_del.add_argument("id", type=int)

    # compose ----------------------------------------------------------
    add = sub.add_parser("add", help="compose a draft post from --text, --file or stdin")
    add.add_argument("--text", help="post body inline")
    add.add_argument("--file", help="read the post body from a file")
    add.add_argument("--channel-id", type=int, help="channel id")
    add.add_argument("--platform", help="channel platform (when --channel-id is omitted)")
    add.add_argument("--handle", help="channel handle (when --channel-id is omitted)")
    add.add_argument("--urls", action="append", help="links to attach (repeatable)")
    add.add_argument("--tags", action="append", help="hashtags to attach (repeatable)")
    add.add_argument("--first-comment", help="first comment to schedule (Buffer parity)")
    add.add_argument("--status", choices=STATUSES, help="initial status (default: draft)")
    add.add_argument("--allow-over-limit", action="store_true", help="save even if over the platform limit")
    add.add_argument("--json", action="store_true")

    check = sub.add_parser("check", help="report over-limit posts per platform")
    check.add_argument("id", type=int, nargs="?")
    check.add_argument("--json", action="store_true")

    thread = sub.add_parser("thread", help="preview the numbered thread split of a post")
    thread.add_argument("id", type=int, nargs="?")
    thread.add_argument("--platform", help="platform for a piped/inline body")
    thread.add_argument("--text", help="inline body to split")
    thread.add_argument("--file", help="file to split")
    thread.add_argument("--json", action="store_true")

    schedule = sub.add_parser("schedule", help="schedule a post at a timezone-aware time")
    schedule.add_argument("id", type=int)
    schedule.add_argument("--at", required=True, help="'2026-10-26 09:00' or ISO-8601")
    schedule.add_argument("--tz", help="IANA timezone, e.g. Asia/Kolkata (default UTC)")

    review = sub.add_parser("review", help="move a post to approved by a named reviewer")
    review.add_argument("id", type=int)
    review.add_argument("--by", required=True, help="reviewer name")

    pub = sub.add_parser("publish-due", help="move due scheduled/approved posts to published")
    pub.add_argument("--now", action="store_true", help="publish everything due, ignoring the clock")
    pub.add_argument("--json", action="store_true")

    cal = sub.add_parser("calendar", help="print the content calendar grid")
    cal.add_argument("--days", type=int, default=7, help="window length (default 7)")
    cal.add_argument("--json", action="store_true")

    export = sub.add_parser("export", help="export the calendar as ics/csv/rss/atom/md")
    export.add_argument("format", choices=["ics", "csv", "rss", "atom", "md"])
    export.add_argument("--status", help="only export posts with this status")
    export.add_argument("--out", help="write to a file instead of stdout")

    imp = sub.add_parser("import", help="bulk-upload posts from CSV")
    imp.add_argument("subcommand", choices=["csv"], help="currently only csv")
    imp.add_argument("--in", dest="in_file", required=True, help="CSV file to import")
    imp.add_argument("--json", action="store_true")

    # hashtags ---------------------------------------------------------
    tags_cmd = sub.add_parser("hashtags", help="named hashtag sets and a per-platform linter")
    tags_sub = tags_cmd.add_subparsers(dest="action", required=True)
    t_save = tags_sub.add_parser("save", help="save a named hashtag set")
    t_save.add_argument("name")
    t_save.add_argument("tags", nargs="+")
    t_list = tags_sub.add_parser("list", help="list hashtag sets")
    t_list.add_argument("--json", action="store_true")
    t_apply = tags_sub.add_parser("apply", help="apply a set to a post")
    t_apply.add_argument("name")
    t_apply.add_argument("id", type=int)
    t_lint = tags_sub.add_parser("lint", help="report posts exceeding hashtag guidance")
    t_lint.add_argument("--json", action="store_true")

    # templates --------------------------------------------------------
    tmpl = sub.add_parser("templates", help="{variable} templates with a render command")
    tmpl_sub = tmpl.add_subparsers(dest="action", required=True)
    tml_add = tmpl_sub.add_parser("add", help="save a template")
    tml_add.add_argument("name")
    tml_add.add_argument("--body", help="template body")
    tml_add.add_argument("--file", help="read the template body from a file")
    tml_list = tmpl_sub.add_parser("list", help="list templates")
    tml_list.add_argument("--json", action="store_true")
    tml_render = tmpl_sub.add_parser("render", help="render a template with variables")
    tml_render.add_argument("name")
    tml_render.add_argument("--var", action="append", help="'name=value' (repeatable)")
    tml_render.add_argument("--out", help="write the render to a file")

    link = sub.add_parser("link", help="fetch Open Graph / Twitter Card previews")
    link.add_argument("url", nargs="+")
    link.add_argument("--timeout", type=float, default=6.0)
    link.add_argument("--json", action="store_true")

    utm = sub.add_parser("utm", help="append UTM parameters to a URL")
    utm.add_argument("--url", required=True)
    utm.add_argument("--source", required=True)
    utm.add_argument("--medium", required=True)
    utm.add_argument("--campaign", required=True)
    utm.add_argument("--term")
    utm.add_argument("--content")

    st = sub.add_parser("stats", help="local analytics from the SQLite rows")
    st.add_argument("--days", type=int, default=14, help="per-day window (default 14)")
    st.add_argument("--json", action="store_true")

    serve = sub.add_parser("serve", help="run the local Flask UI (no network publishing)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8731)
    serve.add_argument("--debug", action="store_true")

    return parser


def cmd_hashtags_dispatch(args) -> int:
    handlers = {
        "save": cmd_hashtags_save,
        "list": cmd_hashtags_list,
        "apply": cmd_hashtags_apply,
        "lint": cmd_hashtags_lint,
    }
    handler = handlers.get(args.action)
    if handler is None:
        print(f"unknown hashtags action {args.action!r}", file=sys.stderr)
        return EXIT_BAD_INPUT
    return handler(args)


def cmd_templates_dispatch(args) -> int:
    handlers = {
        "add": cmd_templates_add,
        "list": cmd_templates_list,
        "render": cmd_templates_render,
    }
    handler = handlers.get(args.action)
    if handler is None:
        print(f"unknown templates action {args.action!r}", file=sys.stderr)
        return EXIT_BAD_INPUT
    return handler(args)


def cmd_channels_dispatch(args) -> int:
    handlers = {
        "add": cmd_channels_add,
        "list": cmd_channels_list,
        "delete": cmd_channels_delete,
    }
    handler = handlers.get(args.action)
    if handler is None:
        print(f"unknown channels action {args.action!r}", file=sys.stderr)
        return EXIT_BAD_INPUT
    return handler(args)


HANDLERS = {
    "init": cmd_init,
    "doctor": cmd_doctor,
    "add": cmd_add,
    "check": cmd_check,
    "thread": cmd_thread,
    "schedule": cmd_schedule,
    "review": cmd_review,
    "publish-due": cmd_publish_due,
    "calendar": cmd_calendar,
    "export": cmd_export,
    "import": cmd_import,
    "hashtags": cmd_hashtags_dispatch,
    "templates": cmd_templates_dispatch,
    "link": cmd_link,
    "utm": cmd_utm,
    "stats": cmd_stats,
    "serve": cmd_serve,
}
HANDLERS["channels"] = cmd_channels_dispatch


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return EXIT_BAD_INPUT
    handler = HANDLERS.get(args.command)
    if handler is None:
        parser.print_help()
        return EXIT_BAD_INPUT
    try:
        return handler(args) or EXIT_OK
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EXIT_BAD_INPUT


if __name__ == "__main__":
    raise SystemExit(main())
