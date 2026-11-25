#!/bin/sh
# Runs at container start (nginx image entrypoint hook).
# Writes the backend URL from the API_BASE_URL env var into /config.js, so one
# image works for any environment without rebuilding.
set -eu
target=/usr/share/nginx/html/config.js
# escape backslashes and double quotes for a JS string literal
url=$(printf '%s' "${API_BASE_URL:-}" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')
printf 'window.__APP_CONFIG__ = { API_BASE_URL: "%s" };\n' "$url" > "$target"
echo "runtime-config: API_BASE_URL=${API_BASE_URL:-<empty>}"
