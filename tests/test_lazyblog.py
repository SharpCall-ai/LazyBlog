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

from lazyblog import LazyBlogError, config, deliver, generate, markdown
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


def test_missing_secret_names_the_variable(site: config.Site, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LAZYBLOG_SECRET_DEMO")
    with pytest.raises(LazyBlogError, match="LAZYBLOG_SECRET_DEMO"):
        site.secret()


# --- topics ---------------------------------------------------------------


def test_topics_round_trip(site: config.Site) -> None:
    topics_mod.add(site, "First topic", author="Jane", sources="https://a.com;https://b.com")
    topics_mod.add(site, "Second topic")

    rows = topics_mod.read(site)
    assert [r["topic"] for r in rows] == ["First topic", "Second topic"]
    assert topics_mod.source_list(rows[0], site) == ["https://a.com", "https://b.com"]
    assert topics_mod.next_pending(site)["topic"] == "First topic"

    topics_mod.set_status(site, "First topic", topics_mod.DRAFTED, "first-topic")
    assert topics_mod.next_pending(site)["topic"] == "Second topic"
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

    def log_message(self, *_: object) -> None:
        pass


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


def test_generate_reports_non_json(site: config.Site, openrouter) -> None:
    openrouter.content = "Sure! Here's your blog post about widgets."
    topics_mod.add(site, "Chatty topic")

    with pytest.raises(LazyBlogError, match="did not return JSON"):
        generate.generate(site)


def test_generate_on_empty_queue(site: config.Site, openrouter) -> None:
    with pytest.raises(LazyBlogError, match="queue empty"):
        generate.generate(site)


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

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's API
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

    def log_message(self, *_: object) -> None:
        pass


@pytest.fixture
def receiver(site: config.Site):
    _Receiver.received = []
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

    with pytest.raises(LazyBlogError, match="401"):
        deliver.send(site, slug)
    assert receiver.received == []
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
