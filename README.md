# opensocial

**Open-source Buffer alternative — compose, thread, schedule and export social posts. Local-first, zero API keys, zero network posting.**

opensocial is a local-first content studio. It keeps every post, channel,
hashtag set and template in a single SQLite file on your machine, validates
each post against the real character limit of its platform, splits long-form
copy into numbered threads the way Typefully does, runs a named-reviewer
approval workflow, and exports the whole calendar as RFC 5545 ICS, RFC 4180
CSV, Atom, RSS 2.0 or Markdown.

**What this is not.** opensocial does not publish anything to any social
network, and it deliberately has no network publisher. There are no OAuth
client IDs, no platform credentials, and no fake "adapter" that pretends to
post to X or LinkedIn. Publishing adapters (Mastodon, Bluesky), webhooks and
image attachments are future work — see the [Roadmap](#roadmap). What you get
today is a real, verifiable compose → review → schedule → **export** pipeline:
hand the ICS or CSV to your own publishing backend, your internal tools, or
your colleagues.

---

## Install

```bash
# from source (works today)
git clone https://github.com/0xshaikh/opensocial.git
cd opensocial
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# the only runtime dependency is Flask; pytest is dev-only
pip install -e '.[dev]'
```

`opensocial == 0.1.0` requires Python 3.10+ and depends on **Flask only**.
Everything else — SQLite, timezone handling, XML feeds, CSV, HTTP link
previews, analytics — is the standard library.

## Quickstart

```console
$ opensocial init
opensocial 0.1.0
database: ~/.opensocial/opensocial.db
tables: channels, hashtag_sets, posts, templates
posts: 0   channels: 0
ready.

$ opensocial channels add --platform x --handle @launchlab
added channel #1: X (Twitter) @launchlab

$ opensocial channels add --platform instagram --handle @launchlab
added channel #2: Instagram @launchlab

$ opensocial add --platform x --handle @launchlab \
    --text "opensocial just shipped. A local-first content calendar: compose, thread, schedule, export. No API keys." \
    --tags launch --tags local-first \
    --urls https://example.com
added post #1 (x @launchlab): 104/280 chars, 2 tag(s) attached, 0 hashtag(s) in body, status=draft

$ opensocial schedule 1 --at "2026-10-26 09:00" --tz Asia/Kolkata
scheduled post #1 for 2026-10-26 09:00 (Asia/Kolkata) -> 2026-10-26T03:30:00Z (status=scheduled)

$ opensocial review 1 --by "Priya"
approved post #1 — reviewed by Priya

$ opensocial publish-due --now --json
{
  "published": [1],
  "count": 1
}

$ opensocial calendar --days 7
Content calendar — next 7 day(s)

2026-10-25  Sunday     —
2026-10-26  Monday     (1 post)
    #1   [published] x/@launchlab: opensocial just shipped. A local-first content calendar: com…
2026-10-27  Tuesday    —
...

$ opensocial export ics --out calendar.ics
exported 1 post(s) as ics (to calendar.ics)

$ opensocial stats
opensocial stats
======================

posts: 1   channels: 2

by status
  published     1

by platform
  x                 1
```

That is the whole loop: compose, validate, schedule, review, "publish"
(local state transition + timestamp — no network call), look at the calendar,
export it.

## Long-form → numbered threads

If a post exceeds its platform limit, `add` refuses by default and points you
at the splitter. Each part carries a `1/n` prefix that **counts against the
limit**, breaks prefer on sentence boundaries, then spaces, and never splits a
grapheme cluster (emoji ZWJ sequences, flags, skin-tone modifiers):

```console
$ opensocial thread 2
Part 1/2 (149/280)
1/2 It uses real platform limits: X counts emoji as two. Threads split automatically at sentence boundaries and keep the 1/n prefix inside the limit.

Part 2/2 (174/280)
2/2 Exports are RFC 5545 ICS, RFC 4180 CSV, Atom, RSS 2.0 and Markdown. Reviews stay local: a named reviewer moves a draft to approved. Nothing is ever posted to any network.
```

## Platform limits (the real numbers)

| Platform | Limit | X-style counting | Recommended hashtags | Max hashtags |
| --- | --- | --- | --- | --- |
| X | 280 | yes (emoji/CJK = 2) | 2 | — |
| Bluesky | 300 | no | unlimited | — |
| Mastodon | 500 | no | unlimited | — |
| Threads | 500 | no | 2 | — |
| TikTok | 2200 | no | 2 | — |
| Instagram | 2200 | no | 5 | 30 |
| Facebook | 5000 | no | 2 | — |
| LinkedIn | 3000 | no | 3 | — |
| Google Business | 1500 | no | — | — |
| YouTube | 5000 | no | — | — |
| Pinterest | 500 | no | 2 | — |

All of them come from one table in `opensocial/platforms.py`; the CLI, the
web composer and the analytics all read it, so nothing can drift.

## Buffer feature parity

Honest: "Implemented" means the code does it and a test proves it.

| Buffer feature | opensocial |
| --- | --- |
| Drafts | Implemented |
| Multi-account channels | Implemented (two X handles supported) |
| Threads / long-form splitting | Implemented |
| Scheduling queue | Implemented (timezone-aware, stored as UTC) |
| Approval workflows (Team plan) | Implemented (`review <id> --by <name>`) |
| First comment scheduling | Implemented |
| Templates | Implemented (`{variable}` substitution + render) |
| Tags | Implemented (attached tags + hashtags in body) |
| Hashtag manager | Implemented (named sets, apply, per-platform lint) |
| Content calendar | Implemented (CLI grid, web grid, 14-day per-day view) |
| Reports export — CSV | Implemented |
| Reports export — Markdown | Implemented |
| Reports export — PDF | Not applicable (no renderer) |
| Reports export — calendar (ICS) | Implemented (RFC 5545) |
| RSS / Atom syndication | Implemented (extra) |
| Bulk upload | Implemented (`import csv`) |
| Link shortening / preview | Partial (live OG/Twitter-card preview, no shortener) |
| Custom UTM parameters | Implemented (`utm` builder) |
| Network publishing | Not applicable (deliberately no network posting) |
| Ideas | Partial (templates + draft status) |
| Notes | Partial (first comment field) |
| API (REST) | Partial (internal JSON API for the web UI) |

## CLI reference

| Command | Purpose |
| --- | --- |
| `opensocial init` | create the DB, print its state |
| `opensocial doctor` | python / Flask / DB / table / row health |
| `opensocial channels add --platform X --handle @h` | register a channel (multi-account) |
| `opensocial channels list [--json]` / `delete <id>` | manage channels |
| `opensocial add --text T --tags t --urls u --first-comment c` | compose a draft (also `--file`, stdin) |
| `opensocial check [id] [--json]` | report over-limit posts per platform |
| `opensocial thread <id> [--json]` | preview the numbered split |
| `opensocial schedule <id> --at '2026-10-26 09:00' --tz Asia/Kolkata` | timezone-aware scheduling |
| `opensocial review <id> --by 'Priya'` | approval workflow → `approved` |
| `opensocial publish-due [--now] [--json]` | move due posts to `published` (local only) |
| `opensocial calendar [--days N] [--json]` | content-calendar grid |
| `opensocial export {ics,csv,rss,atom,md} [--out F] [--status s]` | exports |
| `opensocial import csv --in FILE` | bulk upload |
| `opensocial hashtags save/list/apply/lint` | hashtag sets + linter |
| `opensocial templates add/list/render` | `{variable}` templates |
| `opensocial link URL... [--json]` | live OG / Twitter-card preview |
| `opensocial utm --url U --source x --medium social --campaign c` | UTM builder |
| `opensocial stats [--days N] [--json]` | local analytics |
| `opensocial serve --host 127.0.0.1 --port 8731` | local Flask UI |
| `--db PATH` (global) | override the DB (else `$OPENSOCIAL_DB`) |

Exit codes: `0` ok, `1` bad input, `2` missing data. Read commands accept
`--json`.

## Exports

### ICS (RFC 5545)

`CRLF` line endings, UTC `DTSTART`/`DTSTAMP` in `YYYYMMDDTHHMMSSZ`, escaping of
`\` `,` `;` and newlines, 73-octet folding, one unique `UID` per post. It opens
in Google Calendar, Apple Calendar and ICal:

```
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//opensocial//opensocial 0.1.0//EN
CALSCALE:GREGORIAN
METHOD:PUBLISH
BEGIN:VEVENT
DTSTART:20261026T033000Z
DTSTAMP:20261025T191021Z
UID:post-1@opensocial
SUMMARY:[x @launchlab] published
DESCRIPTION:opensocial just shipped. A local-first content calendar: comp\
 ose\, thread\, schedule\, export. No API keys.\n\nLinks:\nhttps://example.com
END:VEVENT
END:VCALENDAR
```

### CSV (RFC 4180)

Flat row per post, `QUOTE_ALL`, CRLF terminators — it round-trips back through
`import csv`.

### Atom and RSS

Both are built with `xml.etree.ElementTree`, so the namespaces are correct and
the output always parses. Atom entries carry `urn:opensocial:post:<id>` ids,
`xhtml` content and `<category>` per tag:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:dc="http://purl.org/dc/elements/1.1/"
      xmlns:html="http://www.w3.org/1999/xhtml">
  <title>opensocial content calendar</title>
  <id>urn:opensocial:feed:calendar</id>
  <updated>2026-10-26T03:30:00Z</updated>
  <generator version="0.1.0">opensocial 0.1.0</generator>
  ...
```

### Markdown

A renderable content-calendar report: schedule table, then one section per post
with channel, timestamps, reviewer, tags, links and the quoted body.

## Web UI

```bash
opensocial serve --host 127.0.0.1 --port 8731
```

Dark theme, hand-written CSS, vanilla JavaScript — no frameworks, no CDN. The
composer calls `/api/count` and `/api/thread` so the character counter and the
thread-split preview update as you type. Charts on `/stats` are plain HTML/CSS
divs. `/export/{ics,csv,rss,atom,md}` serve the same files as the CLI.

```
  CLI ──────────────► cli.py ──────────► store.py (SQLite)
                                         ▲
  Flask app ─► web.py ─► templates/ ─────┘
                       │
                       └── analytics / calendar / feeds / hashtags / links
```

## Architecture

| Module | Responsibility |
| --- | --- |
| `platforms.py` | limit registry, X word-wrap counting, hashtag guidance |
| `threads.py` | grapheme-safe numbered thread splitting |
| `store.py` | schema, migration, CRUD, ISO-8601 helpers |
| `calendar.py` | calendar grid, ICS + CSV export |
| `feeds.py` | Atom, RSS, Markdown export, CSV import |
| `links.py` | Open Graph / Twitter Card preview fetcher (degrades to `(offline)`) |
| `hashtags.py` | sets + per-platform lint |
| `templates.py` | `{variable}` rendering with defaults |
| `utm.py` | UTM builder/reader with correct `?` and `&` placement |
| `analytics.py` | local stats from the rows only |
| `cli.py` | argparse entry point |
| `web.py` | Flask app + JSON API for the live composer |

## Why zero dependencies

Flask is the one exception and only for `serve`. The rest is stdlib on purpose:
a content calendar should be installable on any laptop in one command, reviewable
by hand, and exportable to a file with nothing to break in the supply chain.

## Tests

```bash
pip install -e '.[dev]'
pytest --cov=opensocial --cov-report=term-missing
```

147 tests, all green: platform counting (including X double-width emoji and
CJK), thread splitting (limits, prefix accounting, grapheme safety, no text
loss), store CRUD and JSON columns, ICS framing/folding/escaping, CSV
round-trips, Atom/RSS well-formedness, Markdown, CSV import, hashtags,
templates, analytics, UTM, live link preview, the full CLI workflow, and the
Flask app through `test_client`.

CI runs pytest on Python 3.11 and 3.12, builds the sdist + wheel, runs
`twine check`, and publishes to PyPI only from `v*` tags.

## Roadmap

- Real publishing adapters for Mastodon and Bluesky (the two platforms with
  openly documented APIs and no mandatory app approval)
- Webhooks that fire when a post becomes due, so an external publisher can pick
  it up
- Image and file attachments (metadata today, storage later)
- Multi-user auth for the web UI
- Draft notes and per-post comments
- Markdown → PDF report export

## Contributing

Fork, branch, `pip install -e '.[dev]'`, run `pytest`, open a PR. Keep the
zero-dependency rule — anything new must be stdlib unless it is genuinely the
only way to do the job. Never commit a `.db`, a token or an export artifact;
`.gitignore` already covers them.

## License

MIT © 2026 Anas Shaikh — see [LICENSE](LICENSE).
