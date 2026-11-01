# One image per brick, built from one file. Three targets install only their own dependency group,
# so the RMES image carries no Elasticsearch driver, no scraping library and no `src/`; the
# aggregate stays the default target (the last stage), so an untargeted `docker build` is unchanged.
#
#   docker build --target insee-mcp -t insee-mcp:local .
#
# The layout is what makes that possible: a shared dependency layer first, then one sync per target
# that installs exactly the workspace packages it needs. `uv sync --package X` prunes the venv to
# X's dependency closure, so the group a brick declares is the group its image ships.
#
# The bricks' metadata -- names, ports, tags, dependency groups -- lives in bricks.yaml, and
# `scripts/render_bricks.py` renders the compose services that build these targets.

# ---- Dependency layer, shared by every target -----------------------------------------------------
FROM python:3.12-slim AS dependencies

# UV_LINK_MODE: uv hard-links from its cache into the venv, and hard links cannot cross filesystems.
# The cache mount below is a different mount, so uv would warn on every build. Copy instead.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Pinned rather than :latest -- a build stage that changes under you is not reproducible.
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/

# Dependencies before source: a one-line code edit must not invalidate the layer that installs them.
# Every member's pyproject must be present to resolve the workspace; no member's source is needed
# yet, so a code edit invalidates only the source layers, not this one.
COPY pyproject.toml uv.lock /app/
COPY packages/core/pyproject.toml /app/packages/core/pyproject.toml
COPY packages/insee/pyproject.toml /app/packages/insee/pyproject.toml
COPY packages/melodi/pyproject.toml /app/packages/melodi/pyproject.toml
COPY packages/rmes/pyproject.toml /app/packages/rmes/pyproject.toml

# The cache mount survives between builds without being stored in the image.
# --locked fails when uv.lock is not current for pyproject.toml. Plain `uv sync` would rewrite the
# lock and install versions nobody tested; --frozen would use a stale lock and silently omit a
# dependency that was added but never locked.
# --no-install-workspace keeps every workspace package out of this layer: it installs only the
# third-party dependencies, and each target's own sync below installs the workspace itself.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --no-install-workspace --locked

# ---- One build per target: that target's dependency group and nothing else -------------------------
FROM dependencies AS build-insee-mcp
COPY packages/ /app/packages/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --locked --package insee-mcp

FROM dependencies AS build-melodi-mcp
COPY packages/ /app/packages/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --locked --package melodi-mcp

FROM dependencies AS build-rmes-mcp
COPY packages/ /app/packages/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --locked --package rmes-mcp

FROM dependencies AS build-mcpdiffusion
COPY src/ /app/src/
COPY packages/ /app/packages/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --locked

# ---- Runtime base ---------------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# CI passes the real version; `dev` is honest for a local build.
ARG APP_VERSION=dev

LABEL org.opencontainers.image.source="https://github.com/InseeFrLab/McpDiffusion" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.licenses="Apache-2.0"

# PATH: `python` means the venv's python everywhere -- CMD, HEALTHCHECK, and docker exec.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

# Fixed UID/GID so a bind-mounted file keeps the same owner on the host.
RUN groupadd --gid 1000 app \
 && useradd --uid 1000 --gid 1000 --create-home --shell /usr/sbin/nologin app

# Readiness calls the same backend-aware endpoint as Kubernetes; liveness is configured separately there.
HEALTHCHECK --interval=15s --timeout=7s --start-period=30s --retries=3 \
    CMD python -c "import json, os, urllib.request; port = int(os.environ.get('MCP_PORT', 8000)); timeout = int(os.environ.get('HEALTH_PROBE_TIMEOUT_SECONDS', 5)) + 1; hosts = json.loads(os.environ.get('ALLOWED_HOSTS', '[]')); host = next((value for value in hosts if value != '*'), '127.0.0.1'); request = urllib.request.Request(f'http://127.0.0.1:{port}/health', headers={'Host': host}); urllib.request.urlopen(request, timeout=timeout).close()"

# ---- The insee.fr brick ---------------------------------------------------------------------------
FROM runtime AS insee-mcp

LABEL org.opencontainers.image.title="insee-mcp" \
      org.opencontainers.image.description="MCP server exposing INSEE publications, rapid releases and key figures from insee.fr"

# --chown during the copy, never a later chown: that would duplicate every file into a new layer.
# uv installs the workspace projects editable: the venv's .pth files point at /app/packages/insee/src
# and /app/packages/core/src, so both trees ship at exactly those paths alongside the venv.
COPY --from=build-insee-mcp --chown=app:app /app/.venv /app/.venv
COPY --from=build-insee-mcp --chown=app:app /app/packages /app/packages

USER app

EXPOSE 8001

# Exec form: the process runs as PID 1 and receives SIGTERM, so shutdown is clean.
CMD ["python", "-m", "insee_mcp.server"]

# ---- The MELODI brick -----------------------------------------------------------------------------
FROM runtime AS melodi-mcp

LABEL org.opencontainers.image.title="melodi-mcp" \
      org.opencontainers.image.description="MCP server exposing the INSEE MELODI dataset catalogue, modalities and observations"

COPY --from=build-melodi-mcp --chown=app:app /app/.venv /app/.venv
COPY --from=build-melodi-mcp --chown=app:app /app/packages /app/packages

USER app

EXPOSE 8002

CMD ["python", "-m", "melodi_mcp.server"]

# ---- The RMES brick: no Elasticsearch, no scraping library, nothing to connect to ------------------
FROM runtime AS rmes-mcp

LABEL org.opencontainers.image.title="rmes-mcp" \
      org.opencontainers.image.description="MCP server exposing INSEE statistical metadata, definitions and nomenclatures over SPARQL"

COPY --from=build-rmes-mcp --chown=app:app /app/.venv /app/.venv
COPY --from=build-rmes-mcp --chown=app:app /app/packages /app/packages

USER app

EXPOSE 8003

CMD ["python", "-m", "rmes_mcp.server"]

# ---- The aggregate: the three bricks in one process (default target) -------------------------------
FROM runtime AS mcpdiffusion

LABEL org.opencontainers.image.title="McpDiffusion" \
      org.opencontainers.image.description="MCP server exposing INSEE public data to LLM clients"

COPY --from=build-mcpdiffusion --chown=app:app /app/.venv /app/.venv
COPY --from=build-mcpdiffusion --chown=app:app /app/src /app/src
COPY --from=build-mcpdiffusion --chown=app:app /app/packages /app/packages

USER app

EXPOSE 8000

CMD ["python", "-m", "mcpdiffusion.server"]
