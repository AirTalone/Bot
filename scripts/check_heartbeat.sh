#!/sh
# Docker healthcheck helper: fail if heartbeat file is missing or too old.
set -eu
FILE="${HEARTBEAT_PATH:-/tmp/bot_heartbeat}"
MAX_AGE="${HEARTBEAT_MAX_AGE_SECONDS:-90}"
if [ ! -f "${FILE}" ]; then
  echo "missing heartbeat ${FILE}" >&2
  exit 1
fi
NOW="$(date +%s)"
MTIME="$(date -r "${FILE}" +%s 2>/dev/null || stat -c %Y "${FILE}")"
AGE=$((NOW - MTIME))
if [ "${AGE}" -gt "${MAX_AGE}" ]; then
  echo "stale heartbeat age=${AGE}s max=${MAX_AGE}s" >&2
  exit 1
fi
exit 0
