"""The sheet — sites/<name>/topics.csv.

Required columns: topic, author, sources, status, slug

Add any other column you like. LazyBlog keeps columns it does not recognise and
hands them to the model as context for that post, so a sheet like

    topic,author,sources,status,slug,tone,industry
    Why widgets jam,,,pending,,blunt,manufacturing

needs no code change here — say what the column means in prompt.md and the model
will use it. status moves pending -> drafted -> sent. Blank author/sources fall back
to site.toml. sources is ';'-separated so the file stays a plain one-row-per-topic
CSV that opens in any spreadsheet.
"""

from __future__ import annotations

import csv
from pathlib import Path

from . import LazyBlogError
from .config import Site

REQUIRED = ["topic", "author", "sources", "status", "slug"]
PENDING, DRAFTED, SENT = "pending", "drafted", "sent"


def read(site: Site) -> list[dict[str, str]]:
    if not site.topics_path.exists():
        return []
    with site.topics_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        found = reader.fieldnames or []
        rows = list(reader)

    missing = [c for c in REQUIRED if c not in found]
    if missing:
        raise LazyBlogError(f"{site.topics_path}: missing column(s) {missing}")

    for row in rows:
        # csv parks surplus values from an over-long row under a None key.
        row.pop(None, None)
        # A hand-edited sheet leaves None for short rows and stray spaces everywhere.
        # Unknown columns get the same treatment as known ones - they are user data.
        for column in found:
            row[column] = (row.get(column) or "").strip()
        row["status"] = row["status"] or PENDING
    return rows


def columns(site: Site) -> list[str]:
    """Sheet columns in file order, so rewriting never reorders or drops the user's."""
    if not site.topics_path.exists():
        return list(REQUIRED)
    with site.topics_path.open(newline="", encoding="utf-8") as fh:
        found = list(csv.DictReader(fh).fieldnames or [])
    return found + [c for c in REQUIRED if c not in found]


def extras(row: dict[str, str]) -> dict[str, str]:
    """The user's own columns for this row. This is what makes the sheet extensible."""
    return {k: v for k, v in row.items() if k not in REQUIRED and v}


def write(site: Site, rows: list[dict[str, str]]) -> None:
    _atomic_write(site.topics_path, rows, columns(site))


def next_pending(site: Site) -> dict[str, str] | None:
    return next((r for r in read(site) if r["status"] == PENDING), None)


def add(site: Site, topic: str, author: str = "", sources: str = "", **extra: str) -> None:
    topic = topic.strip()
    if not topic:
        raise LazyBlogError("topic is empty")

    known = columns(site)
    unknown = [k for k in extra if k not in known]
    if unknown:
        raise LazyBlogError(
            f"{site.topics_path} has no column(s) {unknown} — add them to the header "
            f"row first. Known columns: {known}"
        )

    rows = read(site)
    if any(r["topic"].lower() == topic.lower() for r in rows):
        raise LazyBlogError(f"topic already queued: {topic}")

    rows.append(
        {
            **{c: "" for c in known},
            "topic": topic,
            "author": author,
            "sources": sources,
            "status": PENDING,
            "slug": "",
            **extra,
        }
    )
    write(site, rows)


def set_status(site: Site, topic: str, status: str, slug: str = "") -> None:
    rows = read(site)
    for row in rows:
        if row["topic"] == topic:
            row["status"] = status
            if slug:
                row["slug"] = slug
            write(site, rows)
            return
    raise LazyBlogError(f"topic not found in {site.topics_path}: {topic}")


def source_list(row: dict[str, str], site: Site) -> list[str]:
    if row.get("sources"):
        return [s.strip() for s in row["sources"].split(";") if s.strip()]
    return site.sources


def _atomic_write(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    """Write via a temp file so an interrupted run never truncates the queue."""
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows({f: row.get(f, "") for f in fieldnames} for row in rows)
    tmp.replace(path)
