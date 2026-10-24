#!/sh
# Daily-friendly Postgres dump for docker compose service `db`.
# Usage: ./scripts/backup_postgres.sh [backup-dir]
set -eu

BACKUP_DIR="${1:-./backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="${BACKUP_DIR}/vpnbot_${STAMP}.sql.gz"
COMPOSE="${COMPOSE:-docker compose}"

mkdir -p "${BACKUP_DIR}"
${COMPOSE} exec -T db pg_dump -U vpnbot -d vpnbot --clean --if-exists | gzip > "${FILE}"
echo "wrote ${FILE}"

# Keep last 14 dumps by default.
KEEP="${BACKUP_KEEP:-14}"
ls -1t "${BACKUP_DIR}"/vpnbot_*.sql.gz 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
  rm -f "${old}"
done
