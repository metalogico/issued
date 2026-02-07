# ---------------------------------------------------------------------------
# Stage 1 — builder: install Python deps into an isolated venv
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

# Build-only system deps.
# gcc + libjpeg-dev + zlib1g-dev are required to compile Pillow's C extension.
# They are intentionally absent from the runtime stage.
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libjpeg-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Isolated venv with --copies so the directory is self-contained
# and can be moved wholesale into the runtime image.
RUN python -m venv --copies /opt/venv

# Install dependencies before any application source.
# requirements.txt also contains PyInstaller packages (used by BUILD.md);
# those are build-time-only and excluded here by filtering them out.
COPY requirements.txt /tmp/requirements.txt
RUN grep -v -E '^(pyinstaller|macholib|altgraph|setuptools)' /tmp/requirements.txt > /tmp/runtime-requirements.txt && \
    /opt/venv/bin/pip install --no-cache-dir -r /tmp/runtime-requirements.txt

# ---------------------------------------------------------------------------
# Stage 2 — runtime image
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# OCI image metadata
LABEL org.opencontainers.image.source="https://github.com/metalogico/issued"
LABEL org.opencontainers.image.description="Personal comic library server — OPDS + web reader for CBZ/CBR"
LABEL org.opencontainers.image.licenses="MIT"

# Enable non-free component and install unrar (proprietary).
# rarfile shells out to the unrar binary for CBR extraction;
# without it every CBR comic silently fails to open.
RUN sed -i 's/main$/main non-free/' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
        unrar \
    && rm -rf /var/lib/apt/lists/*

# Pull the complete venv from the builder — nothing else crosses the boundary.
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

# ---------------------------------------------------------------------------
# Non-root user
# ---------------------------------------------------------------------------
RUN groupadd -r issued && useradd -r -g issued -d /app issued

# ---------------------------------------------------------------------------
# Application source
# ---------------------------------------------------------------------------
# WORKDIR = PROJECT_ROOT.  server/config.py resolves it as
#   Path(__file__).resolve().parents[1]  →  /app/server/config.py → /app
# config.ini, library.db, and thumbnails/ are all anchored here.
WORKDIR /app

# Copy in dependency order for layer caching:
#   1. config.ini.example  – static template, rarely changes
#   2. server/ + reader/   – package code
#   3. main.py             – entry point, often the last file touched
COPY --chown=issued:issued config.ini.example .
COPY --chown=issued:issued alembic.ini        .
COPY --chown=issued:issued server/            server/
COPY --chown=issued:issued reader/            reader/
COPY --chown=issued:issued migrations/        migrations/
COPY --chown=issued:issued main.py            .

# Pre-create data/ for persistent state (config.ini, library.db, thumbnails/).
RUN mkdir -p /app/data/thumbnails && chown -R issued:issued /app/data

# Entrypoint script: generates config.ini from env vars if not already present.
COPY --chown=issued:issued docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

USER issued

# ---------------------------------------------------------------------------
# Volumes — mutable runtime state
# ---------------------------------------------------------------------------
# All persistent state lives in /app/data/ (config.ini, library.db, thumbnails/).
VOLUME /app/data

# ---------------------------------------------------------------------------
# Network & health
# ---------------------------------------------------------------------------
EXPOSE 8181

# /opds/ exercises config load → DB query → XML serialisation end-to-end.
# start-period=60s gives a large library time to finish its first scan.
# wget is available in python:3.12-slim without extra packages.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD wget -qO- http://localhost:8181/opds/ || exit 1

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
# docker-entrypoint.sh generates config.ini from env vars (if absent),
# then exec's the CMD so SIGTERM is delivered directly to the process.
# CMD can be overridden to run other subcommands (scan, …).
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["python", "main.py", "serve"]
