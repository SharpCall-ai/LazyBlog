"""Site configuration — one folder per site under sites/."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import LazyBlogError

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def sites_dir() -> Path:
    return Path(os.getenv("LAZYBLOG_SITES_DIR", "sites"))


@dataclass
class Site:
    name: str
    dir: Path
    webhook_url: str
    author: str
    model: str = "anthropic/claude-sonnet-5"
    publish_hour: int = 9
    auto_send: bool = True
    sources: list[str] = field(default_factory=list)
    # Keys the model's JSON must contain, or the draft is rejected. Add the ones your
    # prompt.md asks for: a weaker model will quietly drop a field and answer in prose
    # instead, and an unchecked draft becomes a page with the field's content stranded
    # in the body as junk.
    required: list[str] = field(default_factory=lambda: ["title", "description", "body"])

    @property
    def prompt_path(self) -> Path:
        return self.dir / "prompt.md"

    @property
    def topics_path(self) -> Path:
        return self.dir / "topics.csv"

    @property
    def drafts_dir(self) -> Path:
        return self.dir / "drafts"

    @property
    def last_run_path(self) -> Path:
        return self.dir / ".last_run"

    def prompt(self) -> str:
        if not self.prompt_path.exists():
            raise LazyBlogError(f"{self.prompt_path} is missing")
        return self.prompt_path.read_text(encoding="utf-8")

    def secret(self) -> str:
        """Signing secret, by convention rather than config — site.toml gets committed."""
        var = f"LAZYBLOG_SECRET_{self.name.upper().replace('-', '_')}"
        secret = os.getenv(var)
        if not secret:
            raise LazyBlogError(f"{var} is not set; it signs every delivery for '{self.name}'")
        return secret


def load(name: str) -> Site:
    if not NAME_RE.match(name):
        raise LazyBlogError(f"invalid site name {name!r}: use lowercase letters, digits and dashes")

    directory = sites_dir() / name
    config_path = directory / "site.toml"
    if not config_path.exists():
        raise LazyBlogError(f"no site '{name}' — expected {config_path}")

    with config_path.open("rb") as fh:
        data = tomllib.load(fh)

    unknown = set(data) - {f.name for f in Site.__dataclass_fields__.values()} - {"name", "dir"}
    if unknown:
        raise LazyBlogError(f"{config_path}: unknown keys {sorted(unknown)}")

    for required in ("webhook_url", "author"):
        if not data.get(required):
            raise LazyBlogError(f"{config_path}: '{required}' is required")

    data.pop("name", None)
    data.pop("dir", None)
    return Site(name=name, dir=directory, **data)


def all_sites() -> list[Site]:
    root = sites_dir()
    if not root.is_dir():
        return []
    return [load(p.name) for p in sorted(root.iterdir()) if (p / "site.toml").exists()]
