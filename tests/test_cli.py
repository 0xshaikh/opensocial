"""End-to-end CLI tests: exit codes, stdout, and the whole workflow."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from opensocial.cli import main


def run(argv, capsys):
    code = main(["--db", *argv])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def run_out(argv, capsys):
    code = main(["--db", *argv])
    return code, capsys.readouterr().out


def test_init_creates_and_reports_the_database(capsys, tmp_path):
    db = str(tmp_path / "cli.db")
    code, out = run([db, "init"], capsys)
    assert code == 0
    assert "database: " + db in out
    assert "tables: channels, hashtag_sets, posts, templates" in out
    assert db.endswith(".db")


def test_doctor_reports_flask_and_tables(capsys, tmp_path):
    db = str(tmp_path / "cli.db")
    main(["--db", db, "init"])
    capsys.readouterr()
    code, out = run([db, "doctor"], capsys)
    assert code == 0
    assert "python   :" in out
    assert "flask    :" in out
    assert "database :" in out


def test_add_requires_a_channel_first(capsys, tmp_path):
    """An unknown channel is missing data -> exit code 2."""
    db = str(tmp_path / "cli.db")
    main(["--db", db, "init"])
    capsys.readouterr()
    code, out = run([db, "add", "--platform", "x", "--handle", "@nobody",
                     "--text", "hello"], capsys)
    assert code == 2
    assert "unknown channel" in out


def test_channels_add_list_delete(capsys, tmp_path):
    db = str(tmp_path / "cli.db")
    main(["--db", db, "init"])
    capsys.readouterr()
    code, out = run_out([db, "channels", "add", "--platform", "x", "--handle", "@a"], capsys)
    assert code == 0
    assert "channel #1" in out
    code, out = run_out([db, "channels", "add", "--platform", "x", "--handle", "@b"], capsys)
    assert code == 0
    assert "channel #2" in out
    code, out = run_out([db, "channels", "list", "--json"], capsys)
    assert code == 0
    data = json.loads(out)
    assert len(data) == 2
    code, out = run_out([db, "channels", "delete", "2"], capsys)
    assert code == 0
    code, out = run([db, "channels", "delete", "2"], capsys)
    assert code == 2


def test_unknown_platform_is_bad_input(capsys, tmp_path):
    db = str(tmp_path / "cli.db")
    code, out = run([db, "channels", "add", "--platform", "myspace",
                     "--handle", "@a"], capsys)
    assert code == 1
    assert "unknown platform" in out


def test_full_workflow_end_to_end(capsys, tmp_path):
    db = str(tmp_path / "cli.db")
    main(["--db", db, "init"])
    capsys.readouterr()
    run([db, "channels", "add", "--platform", "x", "--handle", "@lab"], capsys)
    code, out = run([db, "add", "--platform", "x", "--handle", "@lab",
                     "--text", "Hello from opensocial. Second sentence here.",
                     "--tags", "launch", "--tags", "local-first",
                     "--urls", "https://example.com"], capsys)
    assert code == 0
    assert "added post #1" in out
    assert "2 tag(s) attached" in out
    assert "0 hashtag(s) in body" in out

    code, out = run([db, "schedule", "1", "--at", "2026-10-26 09:00",
                     "--tz", "Asia/Kolkata"], capsys)
    assert code == 0
    assert "2026-10-26T03:30:00Z" in out  # IST is UTC+5:30
    assert "status=scheduled" in out

    code, out = run([db, "review", "1", "--by", "Priya"], capsys)
    assert code == 0
    assert "approved" in out

    code, out = run([db, "publish-due", "--now", "--json"], capsys)
    assert code == 0
    assert json.loads(out) == {"published": [1], "count": 1}

    code, out = run([db, "stats", "--json"], capsys)
    assert code == 0
    payload = json.loads(out)
    assert payload["by_status"]["published"] == 1
    assert payload["total_posts"] == 1


def test_check_reports_zero_over_limit_for_valid_input(capsys, tmp_path):
    db = str(tmp_path / "cli.db")
    main(["--db", db, "init"])
    capsys.readouterr()
    run([db, "channels", "add", "--platform", "x", "--handle", "@lab"], capsys)
    run([db, "add", "--platform", "x", "--handle", "@lab",
         "--text", "short and sweet"], capsys)
    code, out = run([db, "check"], capsys)
    assert code == 0
    assert "0 over-limit" in out


def test_add_refuses_over_limit_without_the_flag(capsys, tmp_path):
    db = str(tmp_path / "cli.db")
    main(["--db", db, "init"])
    capsys.readouterr()
    run([db, "channels", "add", "--platform", "x", "--handle", "@lab"], capsys)
    code, out = run([db, "add", "--platform", "x", "--handle", "@lab",
                     "--text", "x" * 400], capsys)
    assert code == 1
    assert "over the limit" in out


def test_thread_command_splits_and_each_part_fits(capsys, tmp_path):
    db = str(tmp_path / "cli.db")
    main(["--db", db, "init"])
    capsys.readouterr()
    run([db, "channels", "add", "--platform", "x", "--handle", "@lab"], capsys)
    long = "Sentence one ends here. " * 30
    code, out = run([db, "thread", "--platform", "x", "--text", long, "--json"], capsys)
    assert code == 0
    parts = json.loads(out)
    assert len(parts) >= 2
    from opensocial.platforms import platform_count

    for part in parts:
        assert platform_count("x", part) <= 280


def test_thread_command_previews_a_saved_post(capsys, tmp_path):
    db = str(tmp_path / "cli.db")
    main(["--db", db, "init"])
    capsys.readouterr()
    run([db, "channels", "add", "--platform", "x", "--handle", "@lab"], capsys)
    run([db, "add", "--platform", "x", "--handle", "@lab", "--text", "x" * 400,
         "--allow-over-limit"], capsys)
    code, out = run([db, "thread", "1"], capsys)
    assert code == 0
    assert "Part 1/" in out


def test_calendar_and_exports(capsys, tmp_path):
    db = str(tmp_path / "cli.db")
    main(["--db", db, "init"])
    capsys.readouterr()
    run([db, "channels", "add", "--platform", "x", "--handle", "@lab"], capsys)
    run([db, "add", "--platform", "x", "--handle", "@lab", "--text", "hello"], capsys)
    run([db, "schedule", "1", "--at", "2026-10-26 09:00"], capsys)

    code, out = run([db, "calendar", "--json"], capsys)
    assert code == 0
    assert isinstance(json.loads(out), list)

    code, out = run([db, "export", "ics"], capsys)
    assert code == 0
    assert "BEGIN:VCALENDAR" in out
    assert "BEGIN:VEVENT" in out

    code, out = run([db, "export", "csv"], capsys)
    assert code == 0
    assert '"id"' in out

    code, out = run([db, "export", "rss"], capsys)
    assert code == 0
    assert "<rss" in out

    code, out = run([db, "export", "atom"], capsys)
    assert code == 0
    assert "<feed" in out

    code, out = run([db, "export", "md"], capsys)
    assert code == 0
    assert "# opensocial content calendar" in out


def test_export_to_a_file(capsys, tmp_path):
    db = str(tmp_path / "cli.db")
    main(["--db", db, "init"])
    capsys.readouterr()
    run([db, "channels", "add", "--platform", "x", "--handle", "@lab"], capsys)
    run([db, "add", "--platform", "x", "--handle", "@lab", "--text", "hello"], capsys)
    target = tmp_path / "out.ics"
    code, out = run([db, "export", "ics", "--out", str(target)], capsys)
    assert code == 0
    assert target.exists()
    assert "BEGIN:VCALENDAR" in target.read_text()


def test_export_requires_posts(capsys, tmp_path):
    db = str(tmp_path / "cli.db")
    main(["--db", db, "init"])
    capsys.readouterr()
    code, out = run([db, "export", "ics"], capsys)
    assert code == 2


def test_import_csv_round_trip(capsys, tmp_path):
    db = str(tmp_path / "cli.db")
    main(["--db", db, "init"])
    capsys.readouterr()
    csv_path = tmp_path / "bulk.csv"
    csv_path.write_text(
        "body,platform,handle,status\n"
        "First bulk row,x,@bulk,draft\n"
        "Second bulk row,instagram,@ig,draft\n"
    )
    code, out = run([db, "import", "csv", "--in", str(csv_path)], capsys)
    assert code == 0
    assert "imported 2 post(s)" in out
    code, out = run([db, "stats", "--json"], capsys)
    assert json.loads(out)["total_posts"] == 2


def test_hashtags_save_list_apply_lint(capsys, tmp_path):
    db = str(tmp_path / "cli.db")
    main(["--db", db, "init"])
    capsys.readouterr()
    run([db, "channels", "add", "--platform", "x", "--handle", "@lab"], capsys)
    run([db, "add", "--platform", "x", "--handle", "@lab", "--text", "hello"], capsys)
    code, out = run([db, "hashtags", "save", "launch", "launch", "local-first"], capsys)
    assert code == 0
    assert "2 tags" in out
    code, out = run([db, "hashtags", "list", "--json"], capsys)
    assert json.loads(out)[0]["name"] == "launch"
    code, out = run([db, "hashtags", "apply", "launch", "1"], capsys)
    assert code == 0
    assert "2 tags total" in out
    code, out = run([db, "hashtags", "lint", "--json"], capsys)
    assert code == 0
    assert json.loads(out) == []


def test_templates_add_list_render(capsys, tmp_path):
    db = str(tmp_path / "cli.db")
    main(["--db", db, "init"])
    capsys.readouterr()
    code, out = run([db, "templates", "add", "launch", "--body",
                     "Shipped {product} today"], capsys)
    assert code == 0
    code, out = run([db, "templates", "render", "launch",
                     "--var", "product=opensocial"], capsys)
    assert code == 0
    assert "Shipped opensocial today" in out
    code, out = run([db, "templates", "render", "missing"], capsys)
    assert code == 2


def test_utm_and_stats_commands(capsys, tmp_path):
    db = str(tmp_path / "cli.db")
    code, out = run([db, "utm", "--url", "https://example.com", "--source", "x",
                     "--medium", "social", "--campaign", "launch"], capsys)
    assert code == 0
    assert "utm_source=x" in out and "utm_medium=social" in out
    code, out = run([db, "stats", "--json"], capsys)
    assert code == 2  # nothing to report


def test_no_command_prints_help_and_errors(capsys, tmp_path):
    code = main([])
    assert code == 1


def test_console_script_entry_point(tmp_path):
    """`python -m opensocial.cli` must behave like the installed script."""
    db = str(tmp_path / "mod.db")
    env = {"OPENSOCIAL_DB": db}
    proc = subprocess.run(
        [sys.executable, "-m", "opensocial.cli", "init"],
        capture_output=True, text=True, env={**__import__("os").environ, **env},
    )
    assert proc.returncode == 0
    assert "ready." in proc.stdout
