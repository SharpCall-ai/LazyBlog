"""Run with: python -m pytest tests/ -q

The delivery tests talk to a real HTTP server on a real socket. The contract is the
only thing other people integrate against, so mocking it would test nothing.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
import yaml

from datetime import datetime

from lazyblog import LazyBlogError, cli, config, deliver, generate, markdown
from lazyblog import topics as topics_mod

SECRET = "test-secret"


@pytest.fixture
def site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> config.Site:
    directory = tmp_path / "sites" / "demo"
    directory.mkdir(parents=True)
    (directory / "site.toml").write_text(
        'webhook_url = "http://127.0.0.1:1/hook"\nauthor = "Demo Team"\n'
    )
    (directory / "prompt.md").write_text("Write a post. Return JSON.")
    (directory / "topics.csv").write_text("topic,author,sources,status,slug\n")
    monkeypatch.setenv("LAZYBLOG_SITES_DIR", str(tmp_path / "sites"))
    monkeypatch.setenv("LAZYBLOG_SECRET_DEMO", SECRET)
    return config.load("demo")


# --- config ---------------------------------------------------------------


def test_load_rejects_unknown_keys(site: config.Site) -> None:
    (site.dir / "site.toml").write_text(
        'webhook_url = "http://x/hook"\nauthor = "A"\nwebhok_url = "typo"\n'
    )
    with pytest.raises(LazyBlogError, match="unknown keys"):
        config.load("demo")


def test_site_name_cannot_traverse(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(LazyBlogError, match="invalid site name"):
        config.load("../../etc")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://x/y", "/just/a/path"])
def test_webhook_url_must_be_http(site: config.Site, url: str) -> None:
    """urlopen accepts file:// and ftp://. A typo must not become a filesystem write."""
    (site.dir / "site.toml").write_text(f'webhook_url = "{url}"\nauthor = "A"\n')
    with pytest.raises(LazyBlogError, match="must be http"):
        config.load("demo")


def test_missing_secret_names_the_variable(site: config.Site, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LAZYBLOG_SECRET_DEMO")
    with pytest.raises(LazyBlogError, match="LAZYBLOG_SECRET_DEMO"):
        site.secret()


# --- managing sites -------------------------------------------------------


def test_set_field_changes_value_and_keeps_comments(site: config.Site) -> None:
    (site.dir / "site.toml").write_text(
        '# keep this comment\nwebhook_url = "http://x/hook"\nauthor = "A"\n'
        "publish_hour = 9\nauto_send = false\n"
    )
    config.set_field("demo", "publish_hour", "17")
    config.set_field("demo", "auto_send", "true")
    config.set_field("demo", "webhook_url", "https://new.example/hook")

    assert "# keep this comment" in (site.dir / "site.toml").read_text()
    reloaded = config.load("demo")
    assert reloaded.publish_hour == 17
    assert reloaded.auto_send is True
    assert reloaded.webhook_url == "https://new.example/hook"


def test_set_field_rejects_lists_and_unknown_keys(site: config.Site) -> None:
    with pytest.raises(LazyBlogError, match="list"):
        config.set_field("demo", "sources", "https://a.com")
    with pytest.raises(LazyBlogError, match="editable"):
        config.set_field("demo", "nope", "x")


def test_set_field_validates_the_result(site: config.Site) -> None:
    with pytest.raises(LazyBlogError, match="must be http"):
        config.set_field("demo", "webhook_url", "ftp://x/y")


def test_create_and_remove_a_site(site: config.Site) -> None:
    created = config.create("blog2", "https://blog2.example/hook", author="Me")
    assert created.webhook_url == "https://blog2.example/hook"
    assert created.author == "Me"
    assert config.load("blog2").name == "blog2"  # persisted and valid

    config.remove("blog2")
    with pytest.raises(LazyBlogError, match="no site"):
        config.load("blog2")


def test_create_rejects_a_non_http_url_without_leaving_a_folder(site: config.Site) -> None:
    with pytest.raises(LazyBlogError, match="http"):
        config.create("blog3", "ftp://x/y")
    assert not (config.sites_dir() / "blog3").exists()


def test_new_secret_line_matches_the_env_convention(site: config.Site) -> None:
    line = config.new_secret("my-blog")
    assert line.startswith("LAZYBLOG_SECRET_MY_BLOG=")
    assert len(line.split("=", 1)[1]) == 64  # token_hex(32)


# --- topics ---------------------------------------------------------------


def test_topics_round_trip(site: config.Site) -> None:
    topics_mod.add(site, "First topic", author="Jane", sources="https://a.com;https://b.com")
    topics_mod.add(site, "Second topic")

    rows = topics_mod.read(site)
    assert [r["topic"] for r in rows] == ["First topic", "Second topic"]
    assert topics_mod.source_list(rows[0], site) == ["https://a.com", "https://b.com"]

    first = topics_mod.next_pending(site)
    assert first is not None and first["topic"] == "First topic"

    topics_mod.set_status(site, "First topic", topics_mod.DRAFTED, "first-topic")
    second = topics_mod.next_pending(site)
    assert second is not None and second["topic"] == "Second topic"
    assert topics_mod.read(site)[0]["slug"] == "first-topic"


def test_topics_reject_duplicates(site: config.Site) -> None:
    topics_mod.add(site, "Same topic")
    with pytest.raises(LazyBlogError, match="already queued"):
        topics_mod.add(site, "same TOPIC")


def test_topics_survive_commas_and_quotes(site: config.Site) -> None:
    tricky = 'Widgets, "gadgets" and other things'
    topics_mod.add(site, tricky)
    assert topics_mod.read(site)[0]["topic"] == tricky


def test_empty_queue_is_not_an_error(site: config.Site) -> None:
    assert topics_mod.next_pending(site) is None


def test_missing_required_column_is_reported(site: config.Site) -> None:
    site.topics_path.write_text("topic,status\nA topic,pending\n")
    with pytest.raises(LazyBlogError, match="missing column"):
        topics_mod.read(site)


# --- user-defined columns -------------------------------------------------


def _sheet_with_extras(site: config.Site) -> None:
    site.topics_path.write_text("topic,author,sources,status,slug,tone,industry\n")


def test_user_columns_survive_a_rewrite(site: config.Site) -> None:
    _sheet_with_extras(site)
    topics_mod.add(site, "Why widgets jam", tone="blunt", industry="manufacturing")
    topics_mod.add(site, "Second topic", tone="warm", industry="retail")

    # Any write path must not drop or reorder the user's columns.
    topics_mod.set_status(site, "Why widgets jam", topics_mod.DRAFTED, "why-widgets-jam")

    assert topics_mod.columns(site) == [*topics_mod.REQUIRED, "tone", "industry"]
    rows = topics_mod.read(site)
    assert topics_mod.extras(rows[0]) == {"tone": "blunt", "industry": "manufacturing"}
    assert topics_mod.extras(rows[1]) == {"tone": "warm", "industry": "retail"}
    assert rows[0]["slug"] == "why-widgets-jam"
    assert site.topics_path.read_text().splitlines()[0].endswith("tone,industry")


def test_extras_ignores_required_and_blank_columns(site: config.Site) -> None:
    _sheet_with_extras(site)
    topics_mod.add(site, "Only tone", tone="blunt")

    assert topics_mod.extras(topics_mod.read(site)[0]) == {"tone": "blunt"}


def test_add_rejects_a_column_the_sheet_lacks(site: config.Site) -> None:
    with pytest.raises(LazyBlogError, match="no column"):
        topics_mod.add(site, "A topic", tone="blunt")


# --- markdown -------------------------------------------------------------


def test_frontmatter_survives_a_colon_in_the_title() -> None:
    title = "AI Receptionist: Never Miss a Call"
    text = markdown.compose({"title": title, "keywords": ["a", "b"]}, "## Body\n\ntext")

    front, body = markdown.split(text)
    assert front["title"] == title
    assert front["keywords"] == ["a", "b"]
    assert body == "## Body\n\ntext"


def test_frontmatter_round_trips_through_a_foreign_yaml_parser() -> None:
    """Receivers parse this with gray-matter, not with us. Keep it plain YAML."""
    text = markdown.compose({"title": "Tables: 100% #1", "date": "2026-07-17"}, "body")
    front = yaml.safe_load(text.split("---\n")[1])
    assert front == {"title": "Tables: 100% #1", "date": "2026-07-17"}


def test_body_containing_a_horizontal_rule_is_not_truncated() -> None:
    body = "## One\n\n---\n\n## Two"
    front, parsed = markdown.split(markdown.compose({"title": "T"}, body))
    assert parsed == body


def test_slugify_and_slug_validation() -> None:
    assert markdown.slugify("AI Receptionist: Never Miss a Call!") == "ai-receptionist-never-miss-a-call"
    for bad in ("../etc/passwd", "Has Spaces", "", "trailing-"):
        with pytest.raises(LazyBlogError):
            markdown.check_slug(bad)


def test_read_time_counts_words() -> None:
    assert markdown.read_time(" ".join(["word"] * 440)) == "2 min read"


# --- generation -----------------------------------------------------------


class _OpenRouter(BaseHTTPRequestHandler):
    content = ""
    prompts: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's API
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).prompts.append(body)
        reply = json.dumps({"choices": [{"message": {"content": type(self).content}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass  # silence the per-request stderr spam


@pytest.fixture
def openrouter(monkeypatch: pytest.MonkeyPatch):
    _OpenRouter.prompts = []
    server = HTTPServer(("127.0.0.1", 0), _OpenRouter)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(generate, "OPENROUTER_URL", f"http://127.0.0.1:{server.server_port}/v1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    yield _OpenRouter
    server.shutdown()


POST_JSON = {
    "title": "What a Missed Call Costs: The Real Number",
    "description": "A breakdown of what each unanswered call takes off the table.",
    "category": "Guide",
    "keywords": ["missed calls"],
    "body": "## The number\n\n| Calls | Cost |\n| --- | --- |\n| 10 | $500 |",
    "faqs": [{"q": "Does it apply to me?", "a": "Yes."}],
}


def test_generate_writes_a_draft_and_advances_the_queue(site: config.Site, openrouter) -> None:
    openrouter.content = json.dumps(POST_JSON)
    topics_mod.add(site, "What does a missed call cost?")

    draft = generate.generate(site)

    assert draft.name == "what-a-missed-call-costs-the-real-number.md"
    front, body = markdown.split(draft.read_text())
    assert front["title"] == POST_JSON["title"]
    assert front["author"] == "Demo Team"  # falls back to site.toml
    assert front["date"] and front["readTime"]
    assert front["faqs"] == POST_JSON["faqs"]
    assert "| Calls | Cost |" in body  # tables survive intact

    row = topics_mod.read(site)[0]
    assert row["status"] == topics_mod.DRAFTED
    assert row["slug"] == draft.stem


def test_generate_strips_code_fences(site: config.Site, openrouter) -> None:
    openrouter.content = f"```json\n{json.dumps(POST_JSON)}\n```"
    topics_mod.add(site, "Fenced topic")

    assert generate.generate(site).exists()


def test_generate_uses_the_row_author_and_sources(site: config.Site, openrouter) -> None:
    openrouter.content = json.dumps(POST_JSON)
    topics_mod.add(site, "Custom topic", author="Jane Doe", sources="https://a.com")

    draft = generate.generate(site)

    front, _ = markdown.split(draft.read_text())
    assert front["author"] == "Jane Doe"
    user_message = openrouter.prompts[0]["messages"][1]["content"]
    assert "Custom topic" in user_message
    assert "https://a.com" in user_message


def test_generate_sends_user_columns_to_the_model(site: config.Site, openrouter) -> None:
    openrouter.content = json.dumps(POST_JSON)
    site.topics_path.write_text("topic,author,sources,status,slug,tone,industry\n")
    topics_mod.add(site, "Why widgets jam", tone="blunt", industry="manufacturing")

    generate.generate(site)

    user_message = openrouter.prompts[0]["messages"][1]["content"]
    assert "tone: blunt" in user_message
    assert "industry: manufacturing" in user_message


def test_generate_refuses_an_incomplete_response(site: config.Site, openrouter) -> None:
    openrouter.content = json.dumps({"title": "Only a title"})
    topics_mod.add(site, "Bad topic")

    with pytest.raises(LazyBlogError, match="missing"):
        generate.generate(site)
    assert topics_mod.read(site)[0]["status"] == topics_mod.PENDING


def test_required_rejects_a_field_the_model_dropped(site: config.Site, openrouter) -> None:
    """A weak model answers the schema in prose: full body, no faqs. That draft must
    not become a page with the Q&A stranded in the body as raw tags."""
    site.required = ["title", "description", "body", "faqs"]
    openrouter.content = json.dumps(
        {**POST_JSON, "faqs": None, "body": "## Real body\n\n<faq><q>Q?</q><a>A.</a></faq>"}
    )
    topics_mod.add(site, "Faqless topic")

    with pytest.raises(LazyBlogError, match="faqs"):
        generate.generate(site)

    # Nothing written, topic still claimable on the next run.
    assert not list(site.drafts_dir.glob("*.md")) if site.drafts_dir.exists() else True
    assert topics_mod.read(site)[0]["status"] == topics_mod.PENDING


def test_required_defaults_do_not_demand_faqs(site: config.Site, openrouter) -> None:
    """Sites that never asked for faqs must not start failing."""
    openrouter.content = json.dumps({**POST_JSON, "faqs": None})
    topics_mod.add(site, "No faqs wanted")

    assert generate.generate(site).exists()


def test_generate_reports_non_json(site: config.Site, openrouter) -> None:
    openrouter.content = "Sure! Here's your blog post about widgets."
    topics_mod.add(site, "Chatty topic")

    with pytest.raises(LazyBlogError, match="did not return JSON"):
        generate.generate(site)


def test_generate_on_empty_queue(site: config.Site, openrouter) -> None:
    with pytest.raises(LazyBlogError, match="queue empty"):
        generate.generate(site)


# --- daemon ---------------------------------------------------------------


def test_tick_survives_a_broken_site_toml(site: config.Site, capsys) -> None:
    """A typo mid-edit must not kill a daemon that is meant to run for months."""
    (site.dir / "site.toml").write_text('webhook_url = "http://x/h"\nauthor = "A"\nnope = 1\n')

    cli._tick()  # must not raise

    assert "unknown keys" in capsys.readouterr().err


def test_tick_survives_a_site_that_explodes(
    site: config.Site, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """generate() raising something that is not a LazyBlogError must not kill the loop,
    and the site must still be marked so it does not retry all day."""
    monkeypatch.setattr(cli, "run", _boom)
    monkeypatch.setattr(cli, "_today", lambda: "2026-07-17")
    (site.dir / "site.toml").write_text(
        f'webhook_url = "http://x/h"\nauthor = "A"\npublish_hour = {datetime.now().hour}\n'
    )

    cli._tick()  # must not raise

    assert "kaboom" in capsys.readouterr().err
    assert site.last_run_path.read_text() == f"2026-07-17:{datetime.now().hour:02d}"


def _boom(_site: config.Site) -> None:
    raise RuntimeError("kaboom")


class _ClockAt:
    """cli calls datetime.now(); datetime itself is immutable, so swap the name."""

    def __init__(self, hour: int) -> None:
        self._hour = hour

    def now(self) -> datetime:
        return datetime.now().replace(hour=self._hour)


def test_two_posts_a_day_fire_in_both_slots_and_neither_twice(
    site: config.Site, monkeypatch: pytest.MonkeyPatch
) -> None:
    """publish_hours = [9, 17] must give exactly one post per slot, morning and evening."""
    (site.dir / "site.toml").write_text(
        'webhook_url = "http://x/h"\nauthor = "A"\npublish_hours = [9, 17]\n'
    )
    monkeypatch.setattr(cli, "_today", lambda: "2026-07-18")
    ran: list[str] = []
    monkeypatch.setattr(cli, "run", lambda s: ran.append(s.name))

    monkeypatch.setattr(cli, "datetime", _ClockAt(9))
    cli._tick()
    cli._tick()  # same slot, five minutes later: must not publish again
    assert ran == ["demo"]
    assert site.last_run_path.read_text() == "2026-07-18:09"

    # The evening slot is a different marker, so it publishes a second post.
    monkeypatch.setattr(cli, "datetime", _ClockAt(17))
    cli._tick()
    cli._tick()
    assert ran == ["demo", "demo"]
    assert site.last_run_path.read_text() == "2026-07-18:17"

    # A third tick at an hour that is not a slot does nothing.
    monkeypatch.setattr(cli, "datetime", _ClockAt(3))
    cli._tick()
    assert ran == ["demo", "demo"]


def test_publish_hour_still_means_once_a_day(site: config.Site) -> None:
    """Existing site.toml files that predate publish_hours must not change behaviour."""
    (site.dir / "site.toml").write_text(
        'webhook_url = "http://x/h"\nauthor = "A"\npublish_hour = 14\n'
    )
    assert config.load("demo").hours == [14]


def test_a_bad_publish_hour_is_a_config_error(site: config.Site) -> None:
    """Otherwise the daemon just silently never publishes."""
    (site.dir / "site.toml").write_text(
        'webhook_url = "http://x/h"\nauthor = "A"\npublish_hours = [9, 25]\n'
    )
    with pytest.raises(LazyBlogError, match="must be 0-23"):
        config.load("demo")


def test_tick_skips_a_site_outside_its_publish_hour(
    site: config.Site, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "run", _boom)  # would raise if it ran
    wrong_hour = (datetime.now().hour + 1) % 24
    (site.dir / "site.toml").write_text(
        f'webhook_url = "http://x/h"\nauthor = "A"\npublish_hour = {wrong_hour}\n'
    )

    cli._tick()

    assert not site.last_run_path.exists()


# --- delivery -------------------------------------------------------------


def test_signature_matches_a_fixed_vector() -> None:
    body = b'{"slug":"x"}'
    expected = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    assert deliver.sign(SECRET, body) == f"sha256={expected}"


def _draft(site: config.Site, slug: str = "hello-world") -> str:
    site.drafts_dir.mkdir(parents=True, exist_ok=True)
    (site.drafts_dir / f"{slug}.md").write_text(
        markdown.compose({"title": "Hello: World", "date": "2026-07-17"}, "## Body\n\ntext")
    )
    topics_mod.add(site, "Hello topic")
    topics_mod.set_status(site, "Hello topic", topics_mod.DRAFTED, slug)
    return slug


def test_payload_carries_markdown_and_parsed_frontmatter(site: config.Site) -> None:
    slug = _draft(site)
    sent = json.loads(deliver.payload(site, slug))
    assert sent["site"] == "demo"
    assert sent["slug"] == slug
    assert sent["frontmatter"]["title"] == "Hello: World"
    assert sent["markdown"].startswith("---\n")
    assert "## Body" in sent["markdown"]


def test_payload_refuses_a_traversing_slug(site: config.Site) -> None:
    with pytest.raises(LazyBlogError, match="invalid slug"):
        deliver.payload(site, "../../etc/passwd")


class _Receiver(BaseHTTPRequestHandler):
    status = 200
    received: list[dict] = []
    hits = 0  # every POST, including ones rejected for a bad signature

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's API
        type(self).hits += 1
        body = self.rfile.read(int(self.headers["Content-Length"]))
        expected = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        signature = self.headers.get(deliver.SIGNATURE_HEADER, "")
        if not hmac.compare_digest(signature, f"sha256={expected}"):
            self.send_response(401)
            self.end_headers()
            return
        type(self).received.append(json.loads(body))
        self.send_response(type(self).status)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass  # silence the per-request stderr spam


@pytest.fixture
def receiver(site: config.Site):
    _Receiver.received = []
    _Receiver.hits = 0
    _Receiver.status = 200
    server = HTTPServer(("127.0.0.1", 0), _Receiver)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    site.webhook_url = f"http://127.0.0.1:{server.server_port}/hook"
    yield _Receiver
    server.shutdown()


def test_send_delivers_a_verifiable_post(site: config.Site, receiver) -> None:
    slug = _draft(site)
    deliver.send(site, slug)

    assert len(receiver.received) == 1
    assert receiver.received[0]["slug"] == slug
    assert topics_mod.read(site)[0]["status"] == topics_mod.SENT


def test_wrong_secret_is_rejected_and_not_retried(
    site: config.Site, receiver, monkeypatch: pytest.MonkeyPatch
) -> None:
    slug = _draft(site)
    monkeypatch.setenv("LAZYBLOG_SECRET_DEMO", "wrong-secret")

    with pytest.raises(LazyBlogError, match="401") as raised:
        deliver.send(site, slug)

    assert receiver.received == []
    # A rejected signature will not fix itself: hammering it 3x is pointless, and
    # the error must not claim attempts it never made.
    assert receiver.hits == 1
    assert "after 1 attempt " in str(raised.value)
    assert topics_mod.read(site)[0]["status"] == topics_mod.DRAFTED


def test_server_error_retries_then_keeps_the_draft(
    site: config.Site, receiver, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(deliver.time, "sleep", lambda _: None)
    receiver.status = 500
    slug = _draft(site)

    with pytest.raises(LazyBlogError, match="failed after 3 attempts"):
        deliver.send(site, slug)

    assert len(receiver.received) == deliver.ATTEMPTS
    assert (site.drafts_dir / f"{slug}.md").exists()
    assert topics_mod.read(site)[0]["status"] == topics_mod.DRAFTED
