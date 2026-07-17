"""The contract: one signed POST carrying markdown.

Everything past this function is the receiver's business — storing, rendering,
rebuilding. LazyBlog does not care and must never grow an opinion about it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request

from . import LazyBlogError
from .config import Site
from . import topics as topics_mod
from .markdown import check_slug, split

ATTEMPTS = 3
TIMEOUT = 30
SIGNATURE_HEADER = "X-LazyBlog-Signature"


def sign(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def payload(site: Site, slug: str) -> bytes:
    check_slug(slug)
    draft = site.drafts_dir / f"{slug}.md"
    if not draft.exists():
        raise LazyBlogError(f"no draft at {draft}")
    text = draft.read_text(encoding="utf-8")
    frontmatter, _ = split(text)
    return json.dumps(
        {
            "site": site.name,
            "slug": slug,
            "frontmatter": frontmatter,
            "markdown": text,
        }
    ).encode()


def send(site: Site, slug: str) -> None:
    """POST a draft to the site's webhook. Raises LazyBlogError if it never lands."""
    body = payload(site, slug)
    request = urllib.request.Request(
        site.webhook_url,
        data=body,
        headers={
            "Content-Type": "application/json",
            SIGNATURE_HEADER: sign(site.secret(), body),
            "User-Agent": "LazyBlog",
        },
    )

    last = ""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                if 200 <= response.status < 300:
                    _mark_sent(site, slug)
                    return
                last = f"HTTP {response.status}"
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:200]}"
            if 400 <= exc.code < 500 and exc.code != 429:
                break  # a bad signature or a rejected payload will not fix itself
        except urllib.error.URLError as exc:
            last = str(exc.reason)
        if attempt < ATTEMPTS:
            time.sleep(2**attempt)

    raise LazyBlogError(
        f"delivery of '{slug}' to {site.webhook_url} failed after {ATTEMPTS} attempts ({last}). "
        f"The draft is still at {site.drafts_dir / f'{slug}.md'} — rerun `lazyblog send`."
    )


def _mark_sent(site: Site, slug: str) -> None:
    for row in topics_mod.read(site):
        if row["slug"] == slug:
            topics_mod.set_status(site, row["topic"], topics_mod.SENT, slug)
            return
