"""Turn one topic into one draft, via OpenRouter."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from . import LazyBlogError
from .config import Site
from . import topics as topics_mod
from .markdown import compose, read_time, slugify

# Override to point at any OpenAI-compatible endpoint: a LiteLLM proxy, a gateway,
# a local model server.
OPENROUTER_URL = os.getenv(
    "OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions"
)
TIMEOUT = 300


def generate(site: Site) -> Path:
    """Draft the first pending topic. Returns the draft path."""
    row = topics_mod.next_pending(site)
    if row is None:
        raise LazyBlogError(f"queue empty for '{site.name}' — add topics to {site.topics_path}")

    post = _ask_model(site, row)
    body = post["body"].strip()
    slug = slugify(post.get("slug") or post["title"])

    frontmatter = {
        "title": post["title"],
        "description": post["description"],
        "date": date.today().isoformat(),
        "author": row["author"] or site.author,
        "readTime": read_time(body),
    }
    for optional in ("category", "keywords", "faqs"):
        if post.get(optional):
            frontmatter[optional] = post[optional]

    site.drafts_dir.mkdir(parents=True, exist_ok=True)
    draft = site.drafts_dir / f"{slug}.md"
    draft.write_text(compose(frontmatter, body), encoding="utf-8")

    topics_mod.set_status(site, row["topic"], topics_mod.DRAFTED, slug)
    return draft


def _ask_model(site: Site, row: dict[str, str]) -> dict:
    sources = topics_mod.source_list(row, site)
    instructions = [f"Topic: {row['topic']}"]
    if sources:
        # ponytail: the URLs are given to the model as link targets, not fetched. Fetching
        # and extracting article text is the "research the internet" feature, not this one.
        instructions.append(
            "Link naturally to these pages where they genuinely fit:\n"
            + "\n".join(f"- {s}" for s in sources)
        )
    # Whatever columns the user invented in topics.csv. LazyBlog does not need to know
    # what 'tone' or 'industry' mean - prompt.md tells the model that.
    if extra := topics_mod.extras(row):
        instructions.append("\n".join(f"{key}: {value}" for key, value in extra.items()))
    instructions.append("Return only the JSON object.")

    raw = _post_chat(site.model, site.prompt(), "\n\n".join(instructions))
    post = _parse_json(raw)
    missing = [f for f in site.required if not post.get(f)]
    if missing:
        raise LazyBlogError(
            f"model response is missing {missing}. Either {site.model} ignored the "
            f"schema in {site.prompt_path} (try a stronger model), or drop the field "
            f"from `required` in {site.dir / 'site.toml'}."
        )
    return post


def _post_chat(model: str, system: str, user: str) -> str:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise LazyBlogError("OPENROUTER_API_KEY is not set")

    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }
    ).encode()

    request = urllib.request.Request(
        OPENROUTER_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Title": "LazyBlog",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise LazyBlogError(f"OpenRouter returned {exc.code}: {exc.read().decode()[:500]}") from exc
    except urllib.error.URLError as exc:
        raise LazyBlogError(f"cannot reach OpenRouter: {exc.reason}") from exc

    try:
        return body["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise LazyBlogError(f"unexpected OpenRouter response: {json.dumps(body)[:500]}") from exc


def _parse_json(text: str) -> dict:
    """Models wrap JSON in code fences often enough to be worth one regex."""
    cleaned = re.sub(r"^\s*```[a-z]*\n|\n```\s*$", "", text.strip())
    try:
        post = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LazyBlogError(f"model did not return JSON: {cleaned[:300]}") from exc
    if not isinstance(post, dict):
        raise LazyBlogError("model returned JSON that is not an object")
    return post
