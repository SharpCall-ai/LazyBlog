# LazyBlog

A topic goes in a sheet. A markdown post comes out. It gets POSTed to your site.

That's the whole tool. LazyBlog renders no HTML, serves no API, opens no port and has no database. The entire contract is one signed HTTP POST carrying markdown — so anything that can receive a POST can use it, whatever it's written in.

```
topics.csv  ->  OpenRouter  ->  post.md  ->  POST your-site.com/api/lazyblog
```

## Why

Most blog automation either locks you into a CMS or generates a UI that never matches your site. LazyBlog does neither. Your app already knows how to render your navbar, your footer and your type scale. It just needs the words. LazyBlog writes the words and hands them over.

## Quick start

Nothing builds on your machine — CI publishes a multi-arch image (amd64 + arm64) to GHCR.

```bash
git clone https://github.com/Gurkirat-Singh-bit/LazyBlog
cd LazyBlog

cp -r sites/example sites/mysite      # your site's folder
$EDITOR sites/mysite/site.toml        # webhook_url, author, model
$EDITOR sites/mysite/prompt.md        # who you are, who reads you

cp .env.example .env                  # OPENROUTER_API_KEY, LAZYBLOG_SECRET_MYSITE
docker compose pull

docker compose run --rm lazyblog topics mysite add "What does a missed call cost?"
docker compose run --rm lazyblog generate mysite    # -> sites/mysite/drafts/<slug>.md
docker compose run --rm lazyblog send mysite <slug> # -> POST to your webhook
```

Happy with the drafts? Set `auto_send = true`, then `docker compose up -d` and it posts one article a day at `publish_hour`, forever.

## Commands

| Command | What it does |
|---|---|
| `lazyblog sites` | list configured sites and pending counts |
| `lazyblog topics <site>` | show the queue |
| `lazyblog topics <site> add "..."` | queue a topic (`--author`, `--sources`) |
| `lazyblog generate <site>` | draft the first pending topic |
| `lazyblog send <site> <slug>` | POST a draft to the webhook |
| `lazyblog run <site>` | generate, then send if `auto_send` |
| `lazyblog daemon` | one post per site per day (the container's job) |

This CLI is also the agent interface. Agents have a shell — there's no API to learn, no key to mint, no dashboard to log into.

## Configuration

One folder per site. That folder is the only thing you edit.

```
sites/mysite/
├── site.toml     # webhook_url, author, model, publish_hour, auto_send, sources
├── prompt.md     # who you are and what a good post looks like
├── topics.csv    # the queue
└── drafts/       # generated posts, before they're sent
```

`topics.csv` is a plain sheet — open it in Excel, edit it by hand, or let an agent append rows:

```csv
topic,author,sources,status,slug
What does a missed call cost a business?,,,pending,
How to pick a supplier,Jane Doe,https://a.com;https://b.com,drafted,how-to-pick-a-supplier
```

Blank `author`/`sources` fall back to `site.toml`. Status moves `pending` → `drafted` → `sent`.

### Your own columns

Those five columns are the only ones LazyBlog requires. **Add any column you want** — LazyBlog keeps it and hands it to the model as context for that post:

```csv
topic,author,sources,status,slug,tone,industry
Why widgets jam,,,pending,,blunt,manufacturing
```

```bash
lazyblog topics mysite add "Why widgets jam" --set tone=blunt --set industry=manufacturing
```

The model receives `tone: blunt` and `industry: manufacturing` alongside the topic. LazyBlog has no idea what they mean and doesn't need to — explain them in `prompt.md`:

```markdown
- `tone`: `blunt` means short sentences and no throat-clearing.
```

That's the extension point. No code change, no schema, no migration — a column in a spreadsheet.

**Secrets never go in `site.toml`** — it gets committed. LazyBlog reads the signing secret from `LAZYBLOG_SECRET_<SITENAME>` (uppercase, dashes become underscores).

| Variable | Purpose |
|---|---|
| `OPENROUTER_API_KEY` | required, generation |
| `LAZYBLOG_SECRET_<SITE>` | required, signs that site's deliveries |
| `LAZYBLOG_SITES_DIR` | optional, defaults to `sites` |

## The contract

`POST <webhook_url>`

```http
Content-Type: application/json
X-LazyBlog-Signature: sha256=<hmac-sha256 of the raw body>
```
```json
{
  "site": "mysite",
  "slug": "what-a-missed-call-costs",
  "frontmatter": { "title": "...", "date": "2026-07-17", "author": "...", "keywords": [], "faqs": [] },
  "markdown": "---\ntitle: ...\n---\n\n## Heading\n\nBody with tables and lists.\n"
}
```

`markdown` is the complete file, frontmatter included — write it to disk as-is and you're done. `frontmatter` is that same data pre-parsed, so a receiver in Go or PHP never needs a YAML parser.

**Always verify the signature.** Your receiver is a public endpoint that accepts content; the HMAC is what proves the request came from you and not from someone who found the URL. Use a constant-time compare. There's a working example in [`examples/nextjs-receiver/`](examples/nextjs-receiver/).

Delivery retries 3 times with backoff. If it never lands, the draft stays on disk and the row stays `drafted` — rerun `lazyblog send` and nothing is lost or paid for twice.

## Writing a receiver

Your endpoint does three things: verify the signature, store the markdown, trigger a rebuild. Storage is the part people get wrong — **a container filesystem is ephemeral**, so a receiver that only writes into its own app directory loses every post on the next deploy. Pick one that actually persists:

- **commit to your repo** — the post lands in git, your existing CI rebuilds. Durable, reviewable, revertable.
- **write to a mounted volume** — simplest, as long as the volume outlives the container.
- **push into whatever store you already have** — S3, a database, your CMS.

LazyBlog has no opinion on which. That's the point of the split.

## Deploying

```bash
cp .env.example .env    # fill in the keys
docker compose pull
docker compose up -d
```

One container, one process, one volume for `sites/`. It opens no ports and needs no inbound access — it only makes outbound calls to OpenRouter and to your webhook.

```bash
docker compose run --rm lazyblog topics mysite      # same CLI, running container or not
docker compose logs -f
```

Images are published to `ghcr.io/gurkirat-singh-bit/lazyblog` for **linux/amd64 and linux/arm64**, so the same tag runs on an x86 box and an ARM VM. Pin a version, or point at your own fork:

```bash
LAZYBLOG_IMAGE=ghcr.io/you/lazyblog:v0.1.0 docker compose up -d
```

> **Forking?** GHCR makes a new package **private** on first publish, and `docker compose pull` will fail with a 401 until you change that. Repo → Packages → your package → *Package settings* → *Change visibility* → **Public**. It's a one-time click that no workflow permission can do for you. Keeping it private is fine too — then run `docker login ghcr.io` wherever you deploy.

## Development

```bash
uv sync
uv run pytest -q
uv run lazyblog --help
```

The delivery tests run a real HTTP server on a real socket and verify a real signature — the contract is the only thing other people integrate against, so it isn't mocked.

To run your changes in the container instead of pulling the published one:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

CI runs the tests on every push and PR, and publishes the multi-arch image only from `main` and tags, only if the tests pass.

## Not included

- **Topic research.** You pick the topics; that's the good part. Auto-discovery would just append rows to `topics.csv`, and nothing else would change.
- **Rendering.** Your app already does this better than a Python template ever will.
- **A database.** Files in a folder, readable with `cat`, diffable with `git`.

## License

MIT
