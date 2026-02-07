#!/bin/sh
# ---------------------------------------------------------------------------
# docker-entrypoint.sh
# Generates config.ini from environment variables if the file does not exist.
# If config.ini is already present (bind-mounted from the host) it is left untouched.
# ---------------------------------------------------------------------------
set -e

DATA="${DATA_DIR:-/app/data}"
mkdir -p "$DATA/thumbnails"

CONFIG="$DATA/config.ini"

if [ ! -f "$CONFIG" ]; then
  cat > "$CONFIG" <<EOF
[library]
path = ${LIBRARY_PATH:-/comics}
name = ${LIBRARY_NAME:-My Comic Library}

[server]
host = ${SERVER_HOST:-0.0.0.0}
port = ${SERVER_PORT:-8181}

[thumbnails]
width = ${THUMB_WIDTH:-300}
height = ${THUMB_HEIGHT:-450}
quality = ${THUMB_QUALITY:-85}
format = ${THUMB_FORMAT:-jpeg}

[scanner]
supported_formats = cbz,cbr
ignore_patterns = .DS_Store,Thumbs.db,@eaDir

[monitoring]
enabled = ${MONITORING_ENABLED:-true}
debounce_seconds = ${MONITORING_DEBOUNCE:-2}

[reader]
user = ${READER_USER:-}
password = ${READER_PASSWORD:-}
EOF
fi

exec "$@"
