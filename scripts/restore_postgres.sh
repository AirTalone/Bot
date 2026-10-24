#!/sh
# Restore a gzipped pg_dump into compose service `db`.
# Usage: ./scripts/restore_postgres.sh backups/vpnbot_YYYYMMDDTHHMMSSZ.sql.gz
set -eu

FILE="${1:-}"
if [ -z "${FILE}" ] || [ ! -f "${FILE}" ]; then
  echo "usage: $0 path/to/vpnbot_*.sql.gz" >&2
  exit 1
fi
COMPOSE="${COMPOSE:-docker compose}"

echo "Restoring ${FILE} into db/vpnbot (destructive for current data)"
gzip -dc "${FILE}" | ${COMPOSE} exec -T db psql -U vpnbot -d vpnbot -v ON_ERROR_STOP=1
echo "restore complete"
