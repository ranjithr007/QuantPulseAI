#!/bin/sh
set -eu

# Railway can override the image ENV with an empty service variable. Keep the
# dashboard deployable in that case instead of rendering proxy_pass /ws/.
if [ -z "${QUANTPULSE_API_UPSTREAM:-}" ]; then
  QUANTPULSE_API_UPSTREAM="https://quantpulseai-staging.up.railway.app"
fi

case "$QUANTPULSE_API_UPSTREAM" in
  http://*|https://*) ;;
  *)
    echo "QUANTPULSE_API_UPSTREAM must be a full http:// or https:// URL" >&2
    exit 1
    ;;
esac

export QUANTPULSE_API_UPSTREAM
# Preserve the official nginx image entrypoint so its envsubst template step
# renders the Railway port and proxy configuration before nginx starts.
exec /docker-entrypoint.sh nginx -g "daemon off;"
