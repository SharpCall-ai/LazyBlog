# syntax=docker/dockerfile:1

# One container, one process. It opens no ports: the only traffic is outbound, to
# OpenRouter and to your webhook.
#
# CI builds and publishes this for linux/amd64 and linux/arm64 — you do not need to
# build it yourself. `docker compose up -d` pulls the published image; see
# docker-compose.dev.yml if you are hacking on LazyBlog itself.
#
# ~48MB, nearly all of it CPython and musl. The app is 2.5MB of that, so there is
# little left to win here without pruning the standard library, which is not worth
# the fragility.

FROM ghcr.io/astral-sh/uv:python3.13-alpine AS builder
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Dependencies resolve from the lockfile alone, so this layer survives every source
# edit. --no-dev keeps pytest out of the image.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


FROM python:3.13-alpine
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    LAZYBLOG_SITES_DIR=/app/sites

RUN addgroup -S lazyblog && adduser -S -G lazyblog lazyblog

COPY --from=builder --chown=lazyblog:lazyblog /app/.venv /app/.venv
COPY --from=builder --chown=lazyblog:lazyblog /app/src /app/src

# sites/ is a volume — drafts and queue state are written back into it and must
# outlive the container.
RUN mkdir -p /app/sites && chown lazyblog:lazyblog /app/sites
VOLUME /app/sites

USER lazyblog
RUN lazyblog --version

# OPENROUTER_API_KEY and LAZYBLOG_SECRET_<SITE> come from the environment at run
# time. Never bake them into the image.
CMD ["lazyblog", "daemon"]
