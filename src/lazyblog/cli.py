"""The whole interface. Humans and agents both call this."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime

from . import LazyBlogError, __version__
from . import config, deliver, topics as topics_mod
from .generate import generate

TICK_SECONDS = 300


def cmd_sites(_: argparse.Namespace) -> None:
    sites = config.all_sites()
    if not sites:
        print(f"no sites configured in {config.sites_dir()}/")
        return
    for site in sites:
        queued = sum(1 for r in topics_mod.read(site) if r["status"] == topics_mod.PENDING)
        print(f"{site.name:20} {queued:3} pending  {site.webhook_url}")


def cmd_topics(args: argparse.Namespace) -> None:
    site = config.load(args.site)
    rows = topics_mod.read(site)
    if not rows:
        print(f"{site.topics_path} is empty")
        return
    for row in rows:
        print(f"[{row['status']:7}] {row['topic']}" + (f"  -> {row['slug']}" if row["slug"] else ""))


def cmd_topics_add(args: argparse.Namespace) -> None:
    site = config.load(args.site)
    extra = dict(_split_pair(pair) for pair in args.set or [])
    topics_mod.add(site, args.topic, args.author or "", ";".join(args.sources or []), **extra)
    print(f"queued: {args.topic}")


def _split_pair(pair: str) -> tuple[str, str]:
    key, sep, value = pair.partition("=")
    if not sep or not key:
        raise LazyBlogError(f"--set expects column=value, got {pair!r}")
    return key.strip(), value.strip()


def cmd_generate(args: argparse.Namespace) -> None:
    draft = generate(config.load(args.site))
    print(draft)


def cmd_send(args: argparse.Namespace) -> None:
    site = config.load(args.site)
    deliver.send(site, args.slug)
    print(f"sent {args.slug} -> {site.webhook_url}")


def cmd_run(args: argparse.Namespace) -> None:
    run(config.load(args.site))


def run(site: config.Site) -> None:
    draft = generate(site)
    print(draft)
    if site.auto_send:
        deliver.send(site, draft.stem)
        print(f"sent {draft.stem} -> {site.webhook_url}")
    else:
        print(f"auto_send is off — review it, then `lazyblog send {site.name} {draft.stem}`")


def cmd_daemon(_: argparse.Namespace) -> None:
    """One post per site per day, at that site's publish_hour.

    ponytail: a 5-minute tick plus a .last_run file, rather than cron inside the
    container. Restart-safe because the marker lives on the volume. If you ever need
    minute precision or backfills, that is a real scheduler and this is not it.
    """
    print(f"lazyblog {__version__} daemon — checking every {TICK_SECONDS}s", flush=True)
    while True:
        _tick()
        time.sleep(TICK_SECONDS)


def _tick() -> None:
    """One pass over every site. Must never raise: this runs unattended for months.

    Nothing in here is worth dying for. A typo in a site.toml, a full disk, an LLM
    that 500s - all are things a human fixes tomorrow, and none should take the other
    sites down with them or leave the container restart-looping.
    """
    try:
        sites = config.all_sites()
    except LazyBlogError as exc:
        # Someone is mid-edit in site.toml. Complain, look again in 5 minutes.
        print(f"[config] {exc}", file=sys.stderr, flush=True)
        return

    for site in sites:
        try:
            if datetime.now().hour != site.publish_hour:
                continue
            if site.last_run_path.exists() and site.last_run_path.read_text() == _today():
                continue
            try:
                run(site)
            except Exception as exc:  # noqa: BLE001 - see the docstring
                # An empty queue today must not stop this site running tomorrow.
                print(f"[{site.name}] {exc}", file=sys.stderr, flush=True)
            # Marked even on failure: one attempt per day, not a retry storm against
            # a paid API. `lazyblog run <site>` forces one by hand.
            site.last_run_path.write_text(_today())
        except OSError as exc:
            print(f"[{site.name}] {exc}", file=sys.stderr, flush=True)


def _today() -> str:
    return date.today().isoformat()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lazyblog", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("sites", help="list configured sites").set_defaults(func=cmd_sites)

    topics = sub.add_parser("topics", help="show or add topics")
    topics.add_argument("site")
    topics.set_defaults(func=cmd_topics)
    topics_sub = topics.add_subparsers(dest="topics_command")
    add = topics_sub.add_parser("add", help="queue a topic")
    add.add_argument("topic")
    add.add_argument("--author", help="override the site author for this post")
    add.add_argument("--sources", nargs="*", help="link targets for this post")
    add.add_argument(
        "--set",
        action="append",
        metavar="COLUMN=VALUE",
        help="set one of your own topics.csv columns, e.g. --set tone=blunt",
    )
    add.set_defaults(func=cmd_topics_add)

    generate_cmd = sub.add_parser("generate", help="draft the first pending topic")
    generate_cmd.add_argument("site")
    generate_cmd.set_defaults(func=cmd_generate)

    send = sub.add_parser("send", help="POST a draft to the site webhook")
    send.add_argument("site")
    send.add_argument("slug")
    send.set_defaults(func=cmd_send)

    run_cmd = sub.add_parser("run", help="generate, then send if auto_send")
    run_cmd.add_argument("site")
    run_cmd.set_defaults(func=cmd_run)

    sub.add_parser("daemon", help="one post per site per day").set_defaults(func=cmd_daemon)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except LazyBlogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0
