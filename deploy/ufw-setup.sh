#!/sh
# Host firewall for the bot VPS. Open SSH before enabling.
# Usage: sudo ./deploy/ufw-setup.sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "run as root: sudo $0" >&2
  exit 1
fi

ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH

# Optional HTTP(S) for Caddy / future webhook. Comment out if unused.
ufw allow 80/tcp
ufw allow 443/tcp

ufw --force enable
ufw status verbose
echo "Note: Postgres and the bot container stay on the Docker network (not published in compose.prod.yml)."
