"""Markdown files: YAML frontmatter + body.

The model returns structured fields; this module is what turns them into a file.
Frontmatter is dumped with PyYAML rather than f-strings on purpose: model titles
contain colons constantly ("AI Receptionist: Never Miss a Call") and hand-rolled
YAML emits those as broken mappings that every downstream parser rejects.
"""

from __future__ import annotations

import re
import unicodedata

import yaml

from . import LazyBlogError

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
WORDS_PER_MINUTE = 220


def slugify(title: str) -> str:
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")
    if not SLUG_RE.match(slug):
        raise LazyBlogError(f"cannot build a usable slug from title {title!r}")
    return slug


def check_slug(slug: str) -> str:
    """Reject anything that would escape the drafts directory or a content dir."""
    if not SLUG_RE.match(slug):
        raise LazyBlogError(f"invalid slug {slug!r}: expected kebab-case like 'my-post'")
    return slug


def read_time(body: str) -> str:
    minutes = max(1, round(len(body.split()) / WORDS_PER_MINUTE))
    return f"{minutes} min read"


def compose(frontmatter: dict, body: str) -> str:
    front = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{front}\n---\n\n{body.strip()}\n"


def split(text: str) -> tuple[dict, str]:
    """Inverse of compose — used when sending a draft that is already on disk."""
    if not text.startswith("---\n"):
        raise LazyBlogError("markdown has no frontmatter block")
    try:
        _, front, body = text.split("---\n", 2)
    except ValueError as exc:
        raise LazyBlogError("markdown frontmatter is not terminated by '---'") from exc
    frontmatter = yaml.safe_load(front)
    if not isinstance(frontmatter, dict):
        raise LazyBlogError("markdown frontmatter is not a mapping")
    return frontmatter, body.strip()
