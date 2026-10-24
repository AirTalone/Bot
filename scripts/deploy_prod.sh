#!/sh
# Build and start the production compose stack.
# Usage: ./scripts/deploy_prod.sh
set -eu
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "missing .env — copy deploy/env.prod.example and fill secrets" >&2
  exit 1
fi

COMPOSE_FILE="${COMPOSE_FILE:-compose.prod.yml}"
docker compose -f "${COMPOSE_FILE}" up -d --build
docker compose -f "${COMPOSE_FILE}" ps
