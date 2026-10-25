"""Local Flask web UI for opensocial.

Dark theme, hand-written CSS, vanilla JS only -- no frameworks and no CDN.
The composer talks to ``/api/count`` and ``/api/thread`` for live character
counting and thread previews.  Everything is local: the app never posts to
a social network.
"""

from __future__ import annotations

import json
from io import BytesIO

from flask import (
    Flask,
    abort,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from . import __version__
from .analytics import stats
from .calendar import build_csv, build_ics, calendar_grid, collect, render_grid
from .feeds import atom_feed, markdown_report, rss_feed
from .hashtags import count_hashtags, lint_posts
from .links import fetch_preview
from .platforms import (
    DISPLAY_NAMES,
    PLATFORM_LIMITS,
    platform_count,
    platform_limit,
    resolve_platform,
)
from .store import STATUSES, Store
from .threads import split_thread

EXPORT_MIME = {
    "ics": "text/calendar; charset=utf-8",
    "csv": "text/csv; charset=utf-8",
    "rss": "application/rss+xml; charset=utf-8",
    "atom": "application/atom+xml; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
}


def create_app(db_path: str | None = None) -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.config["OPENSOCIAL_DB"] = db_path

    @app.before_request
    def _init() -> None:
        g.store = Store(app.config["OPENSOCIAL_DB"])

    @app.teardown_request
    def _close(_exc):  # noqa: ANN001
        if hasattr(g, "store"):
            g.store.close()

    def _decorate(posts):
        channels = {c["id"]: c for c in g.store.list_channels()}
        out = []
        for post in posts:
            row = dict(post)
            channel = channels.get(post.get("channel_id")) or {}
            row["channel"] = channel.get("name") or f"@{channel.get('handle', '?')}"
            row["platform"] = channel.get("platform", "?")
            row["handle"] = channel.get("handle", "")
            row["body_length"] = platform_count(row["platform"], row.get("body") or "")
            row["limit"] = platform_limit(row["platform"])
            row["over"] = row["body_length"] > row["limit"]
            out.append(row)
        return out

    # ---------------------------------------------------------------- #
    # pages
    # ---------------------------------------------------------------- #
    @app.route("/")
    def index():
        days = int(request.args.get("days", 7))
        posts = _decorate(collect(g.store, days=days))
        return render_template(
            "index.html",
            rows=calendar_grid(posts, days=days),
            days=days,
            count=len(posts),
            text=render_grid(posts, days=days),
            version=__version__,
        )

    @app.route("/posts")
    def posts():
        status = request.args.get("status")
        items = g.store.list_posts(status=status)
        items = _decorate(items)
        items.reverse()
        return render_template(
            "posts.html",
            posts=items,
            statuses=STATUSES,
            current=status,
            version=__version__,
        )

    @app.route("/posts/new", methods=["GET", "POST"])
    def posts_new():
        channels = g.store.list_channels()
        error = None
        if request.method == "POST":
            platform = resolve_platform(request.form.get("platform", "x"))
            channel = next(
                (c for c in channels if c["platform"] == platform), None
            )
            if channel is None:
                error = "add a channel first: /channels/new"
            else:
                body = request.form.get("body", "").strip()
                if not body:
                    error = "post body must not be empty"
                else:
                    limit = platform_limit(platform)
                    length = platform_count(platform, body)
                    urls = [
                        u.strip()
                        for u in request.form.get("urls", "").splitlines()
                        if u.strip()
                    ]
                    tags = [
                        t.strip()
                        for t in request.form.get("tags", "").replace(",", " ").split()
                        if t.strip()
                    ]
                    post_id = g.store.add_post(
                        channel["id"],
                        body,
                        first_comment=request.form.get("first_comment", "").strip(),
                        urls=urls,
                        tags=tags,
                        status="scheduled"
                        if request.form.get("scheduled_at")
                        else "draft",
                        scheduled_at=request.form.get("scheduled_at") or None,
                    )
                    return redirect(url_for("post_detail", post_id=post_id))
        return render_template(
            "post_new.html",
            channels=channels,
            platforms=PLATFORM_LIMITS,
            display_names=DISPLAY_NAMES,
            error=error,
            version=__version__,
        )

    @app.route("/posts/<int:post_id>", methods=["GET", "POST"])
    def post_detail(post_id):
        post = g.store.get_post(post_id)
        if post is None:
            abort(404)
        decorated = _decorate([post])[0]
        channels = g.store.list_channels()
        previews = []
        for url in (post.get("urls") or [])[:5]:
            previews.append(fetch_preview(url, timeout=4.0))
        error = None
        message = None
        if request.method == "POST":
            action = request.form.get("action")
            if action == "status":
                new_status = request.form.get("status")
                if new_status not in STATUSES:
                    error = "unknown status"
                else:
                    by = request.form.get("reviewed_by", "").strip()
                    fields = {"status": new_status}
                    if by and new_status == "approved":
                        fields["reviewed_by"] = by
                        message = f"approved by {by}"
                    elif new_status == "published":
                        from .store import utcnow_iso

                        fields["published_at"] = utcnow_iso()
                        message = "published (local state only — nothing was posted)"
                    else:
                        message = f"status -> {new_status}"
                    g.store.update_post(post_id, **fields)
            elif action in ("schedule", "review", "publish", "draft", "review_queue"):
                if action == "schedule":
                    when = request.form.get("scheduled_at") or ""
                    tz = request.form.get("tz") or "UTC"
                    from .cli import _parse_when

                    try:
                        utc = _parse_when(when, tz if tz != "UTC" else None)
                    except ValueError as exc:
                        error = str(exc)
                    else:
                        g.store.update_post(
                            post_id,
                            scheduled_at=utc,
                            status="scheduled"
                            if post["status"] in ("draft", "review")
                            else post["status"],
                        )
                        message = f"scheduled for {utc}"
                elif action == "review":
                    by = request.form.get("reviewed_by", "").strip() or "reviewer"
                    g.store.update_post(
                        post_id, status="approved", reviewed_by=by
                    )
                    message = f"approved by {by}"
                elif action == "publish":
                    from .store import utcnow_iso

                    g.store.update_post(
                        post_id,
                        status="published",
                        published_at=utcnow_iso(),
                    )
                    message = "published (local state only — nothing was posted)"
                elif action == "draft":
                    g.store.update_post(post_id, status="draft")
                    message = "moved back to draft"
                elif action == "review_queue":
                    g.store.update_post(post_id, status="review")
                    message = "sent to the review queue"
            elif action == "edit":
                body = request.form.get("body", "").strip()
                if not body:
                    error = "body must not be empty"
                else:
                    g.store.update_post(
                        post_id,
                        body=body,
                        first_comment=request.form.get(
                            "first_comment", ""
                        ).strip(),
                        urls=[
                            u.strip()
                            for u in request.form.get("urls", "").splitlines()
                            if u.strip()
                        ],
                        tags=[
                            t.strip()
                            for t in request.form.get("tags", "")
                            .replace(",", " ")
                            .split()
                            if t.strip()
                        ],
                    )
                    message = "saved"
            elif action == "delete":
                g.store.delete_post(post_id)
                return redirect(url_for("posts"))
            return redirect(
                url_for("post_detail", post_id=post_id, error=error or "")
            )

        parts = split_thread(decorated["body"], decorated["platform"])
        return render_template(
            "post_detail.html",
            post=decorated,
            channels=channels,
            previews=previews,
            parts=parts,
            statuses=STATUSES,
            error=error or request.args.get("error") or None,
            message=message,
            hashtags=count_hashtags(decorated["body"]),
            limit=decorated["limit"],
            version=__version__,
        )

    @app.route("/channels")
    def channels():
        items = g.store.list_channels()
        return render_template(
            "channels.html",
            channels=items,
            display_names=DISPLAY_NAMES,
            limits=PLATFORM_LIMITS,
            version=__version__,
        )

    @app.route("/channels/new", methods=["GET", "POST"])
    def channels_new():
        error = None
        if request.method == "POST":
            platform = resolve_platform(request.form.get("platform", ""))
            handle = request.form.get("handle", "").strip()
            if platform is None or not handle:
                error = "platform and handle are required"
            else:
                g.store.add_channel(platform, handle, request.form.get("name") or None)
                return redirect(url_for("channels"))
        return render_template(
            "channels_new.html",
            platforms=PLATFORM_LIMITS,
            display_names=DISPLAY_NAMES,
            error=error,
            version=__version__,
        )

    @app.route("/hashtags")
    def hashtags():
        sets = g.store.list_hashtag_sets()
        findings = lint_posts(_decorate(g.store.list_posts()))
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            tags = [
                t.strip()
                for t in request.form.get("tags", "").replace(",", " ").split()
                if t.strip()
            ]
            if name and tags:
                g.store.add_hashtag_set(name, tags)
                return redirect(url_for("hashtags"))
        return render_template(
            "hashtags.html",
            sets=sets,
            findings=findings,
            version=__version__,
        )

    @app.route("/templates")
    def templates():
        items = g.store.list_templates()
        error = None
        rendered = None
        if request.method == "POST":
            if request.form.get("action") == "render":
                item = g.store.get_template(request.form.get("name", ""))
                if item:
                    from .templates import render as _render

                    values = {}
                    for key, value in request.form.items():
                        if key.startswith("var_"):
                            values[key[4:]] = value
                    rendered = _render(item["body"], **values)
            else:
                name = request.form.get("name", "").strip()
                body = request.form.get("body", "").strip()
                if name and body:
                    g.store.add_template(name, body)
                    return redirect(url_for("templates"))
                error = "name and body are required"
        return render_template(
            "templates.html",
            templates=items,
            error=error,
            rendered=rendered,
            version=__version__,
        )

    @app.route("/stats")
    def stats_page():
        payload = stats(g.store, days=int(request.args.get("days", 14)))
        per_day = payload["per_day"]
        top = payload["top_hashtags"]
        dow = payload["day_of_week"]
        return render_template(
            "stats.html",
            payload=payload,
            per_day_max=max(per_day.values()) if per_day else 0,
            top_max=max((c for _, c in top), default=0),
            dow_max=max(dow.values()) if dow else 0,
            version=__version__,
        )

    @app.route("/export/<fmt>")
    def export(fmt):
        if fmt not in EXPORT_MIME:
            abort(404)
        posts = _decorate(g.store.list_posts())
        builder = {
            "ics": lambda p: build_ics(p).encode("utf-8"),
            "csv": lambda p: build_csv(p).encode("utf-8"),
            "rss": lambda p: rss_feed(p).encode("utf-8"),
            "atom": lambda p: atom_feed(p).encode("utf-8"),
            "md": lambda p: markdown_report(p).encode("utf-8"),
        }[fmt]
        data = BytesIO(builder(posts))
        suffix = {"rss": ".rss"}.get(fmt, "." + fmt)
        return send_file(
            data,
            mimetype=EXPORT_MIME[fmt],
            as_attachment=True,
            download_name=f"opensocial-calendar{suffix}",
        )

    # ---------------------------------------------------------------- #
    # JSON API used by the live composer
    # ---------------------------------------------------------------- #
    @app.route("/api/count")
    def api_count():
        platform = resolve_platform(request.args.get("platform", "x"))
        if platform is None:
            return jsonify({"error": "unknown platform"}), 400
        text = request.args.get("text", "")
        limit = platform_limit(platform)
        length = platform_count(platform, text)
        return jsonify(
            {
                "platform": platform,
                "length": length,
                "limit": limit,
                "remaining": limit - length,
                "over": length > limit,
            }
        )

    @app.route("/api/thread")
    def api_thread():
        platform = resolve_platform(request.args.get("platform", "x"))
        if platform is None:
            return jsonify({"error": "unknown platform"}), 400
        text = request.args.get("text", "")
        parts = split_thread(text, platform)
        return jsonify(
            {
                "platform": platform,
                "parts": parts,
                "count": len(parts),
                "lengths": [platform_count(platform, p) for p in parts],
                "limit": platform_limit(platform),
            }
        )

    @app.route("/api/previews")
    def api_previews():
        urls = request.args.getlist("url")
        return jsonify([fetch_preview(u, timeout=4.0).as_dict() for u in urls])

    @app.errorhandler(404)
    def _not_found(_exc):
        return (
            render_template("404.html", version=__version__),
            404,
        )

    return app


app = create_app()
