"""Site configuration — one folder per site under sites/."""

from __future__ import annotations

import os
import re
import secrets
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from . import LazyBlogError

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def sites_dir() -> Path:
    return Path(os.getenv("LAZYBLOG_SITES_DIR", "sites"))


def _valid_name(name: str) -> None:
    if not NAME_RE.match(name):
        raise LazyBlogError(f"invalid site name {name!r}: use lowercase letters, digits and dashes")


def secret_var(name: str) -> str:
    """The env var that signs a site's deliveries. site.toml is committed; this is not."""
    return f"LAZYBLOG_SECRET_{name.upper().replace('-', '_')}"


@dataclass
class Site:
    name: str
    dir: Path
    webhook_url: str
    author: str
    model: str = "anthropic/claude-sonnet-5"
    publish_hour: int = 9
    # Two posts a day: publish_hours = [9, 17]. Overrides publish_hour when set, which
    # stays as the one-a-day shorthand so existing site.toml files keep working.
    publish_hours: list[int] = field(default_factory=list)
    auto_send: bool = True
    sources: list[str] = field(default_factory=list)
    # Keys the model's JSON must contain, or the draft is rejected. Add the ones your
    # prompt.md asks for: a weaker model will quietly drop a field and answer in prose
    # instead, and an unchecked draft becomes a page with the field's content stranded
    # in the body as junk.
    required: list[str] = field(default_factory=lambda: ["title", "description", "body"])

    @property
    def hours(self) -> list[int]:
        """The hours this site publishes at, earliest first."""
        return sorted(set(self.publish_hours)) or [self.publish_hour]

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
        var = secret_var(self.name)
        value = os.getenv(var)
        if not value:
            raise LazyBlogError(f"{var} is not set; it signs every delivery for '{self.name}'")
        return value


def load(name: str) -> Site:
    _valid_name(name)

    directory = sites_dir() / name
    config_path = directory / "site.toml"
    if not config_path.exists():
        raise LazyBlogError(f"no site '{name}' — expected {config_path}")

    with config_path.open("rb") as fh:
        data = tomllib.load(fh)

    unknown = set(data) - {f.name for f in Site.__dataclass_fields__.values()} - {"name", "dir"}
    if unknown:
        raise LazyBlogError(f"{config_path}: unknown keys {sorted(unknown)}")

    for key in ("webhook_url", "author"):
        if not data.get(key):
            raise LazyBlogError(f"{config_path}: '{key}' is required")

    # urlopen will happily accept file:// or ftp://. A typo here should be a config
    # error, not an attempt to POST a blog post at the local filesystem.
    scheme = urlparse(str(data["webhook_url"])).scheme
    if scheme not in ("http", "https"):
        raise LazyBlogError(
            f"{config_path}: webhook_url must be http(s), got {scheme or 'no'} scheme"
        )

    data.pop("name", None)
    data.pop("dir", None)
    site = Site(name=name, dir=directory, **data)

    # A bad hour would otherwise mean a daemon that silently never publishes.
    for hour in site.hours:
        if not isinstance(hour, int) or not 0 <= hour <= 23:
            raise LazyBlogError(f"{config_path}: publish hour {hour!r} must be 0-23")
    return site


def all_sites() -> list[Site]:
    root = sites_dir()
    if not root.is_dir():
        return []
    return [load(p.name) for p in sorted(root.iterdir()) if (p / "site.toml").exists()]


# --- managing sites from the CLI -----------------------------------------
# Sites are folders; these are thin wrappers so a shell isn't required. set()
# edits site.toml line by line on purpose: the comments in that file are the
# docs, and a TOML re-serializer would delete every one of them.

_TEMPLATE = "example"


def _editable() -> set[str]:
    """site.toml keys `set` may change (everything on Site except what load() fills)."""
    return {f.name for f in Site.__dataclass_fields__.values()} - {"name", "dir"}


def new_secret(name: str) -> str:
    """A ready-to-paste .env line. token_hex(32) = 256 bits, same as `openssl rand -hex 32`."""
    _valid_name(name)
    return f"{secret_var(name)}={secrets.token_hex(32)}"


def create(name: str, webhook_url: str, author: str = "", model: str = "") -> Site:
    _valid_name(name)
    if urlparse(webhook_url).scheme not in ("http", "https"):
        raise LazyBlogError(f"--url must be http(s), got {webhook_url!r}")
    directory = sites_dir() / name
    if directory.exists():
        raise LazyBlogError(f"site '{name}' already exists at {directory}")

    template = sites_dir() / _TEMPLATE
    directory.mkdir(parents=True)
    if template.is_dir():
        shutil.copyfile(template / "site.toml", directory / "site.toml")
        shutil.copyfile(template / "prompt.md", directory / "prompt.md")
    else:
        (directory / "site.toml").write_text('webhook_url = ""\nauthor = "Your Name"\n', encoding="utf-8")
        (directory / "prompt.md").write_text("Who you are. Who reads you. What a good post looks like.\n", encoding="utf-8")
    (directory / "topics.csv").write_text("topic,author,sources,status,slug\n", encoding="utf-8")

    set_field(name, "webhook_url", webhook_url)
    if author:
        set_field(name, "author", author)
    if model:
        set_field(name, "model", model)
    return load(name)  # validates the finished folder


def remove(name: str) -> Path:
    _valid_name(name)
    directory = sites_dir() / name
    if not (directory / "site.toml").exists():
        raise LazyBlogError(f"no site '{name}' — expected {directory / 'site.toml'}")
    shutil.rmtree(directory)
    return directory


def set_field(name: str, key: str, value: str) -> None:
    editable = _editable()
    if key not in editable:
        raise LazyBlogError(f"cannot set {key!r}; editable keys: {sorted(editable)}")
    path = sites_dir() / name / "site.toml"
    if not path.exists():
        raise LazyBlogError(f"no site '{name}' — expected {path}")

    formatted = _toml_value(key, value)
    lines = path.read_text(encoding="utf-8").splitlines()
    pattern = re.compile(rf"^(\s*){re.escape(key)}\s*=")
    for i, line in enumerate(lines):
        if match := pattern.match(line):
            lines[i] = f"{match.group(1)}{key} = {formatted}"
            break
    else:
        lines.append(f"{key} = {formatted}")
    # The bad value stays visible in the file if load() rejects it (e.g. a non-http
    # url); the raised error names the problem and another `set` fixes it.
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    load(name)


def _toml_value(key: str, value: str) -> str:
    ann = Site.__dataclass_fields__[key].type
    if ann == "int":
        try:
            return str(int(value))
        except ValueError:
            raise LazyBlogError(f"{key} must be a whole number, got {value!r}") from None
    if ann == "bool":
        low = value.strip().lower()
        if low in ("true", "1", "yes", "on"):
            return "true"
        if low in ("false", "0", "no", "off"):
            return "false"
        raise LazyBlogError(f"{key} must be true or false, got {value!r}")
    if ann.startswith("list"):
        raise LazyBlogError(f"{key} is a list — edit {sites_dir()}/{{site}}/site.toml by hand")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
