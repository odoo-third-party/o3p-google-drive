#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 1 ]; then
  printf 'Usage: %s "commit message"\n' "$0" >&2
  exit 1
fi

COMMIT_MSG=$1
ODOO_CONF=${ODOO_CONF:-/etc/odoo20.conf}
ODOO_DB=${ODOO_DB:-persona.standalone.io}
ODOO_USER=${ODOO_USER:-odoo20}
ODOO_SERVICE=${ODOO_SERVICE:-odoo20}
ODOO_BIN=${ODOO_BIN:-/opt/odoo20/odoo-bin}
ODOO_PYTHON=${ODOO_PYTHON:-/opt/odoo20/venv/bin/python3}
ODOO_MODULE=${ODOO_MODULE:-o3p_google_drive}
POSTGRES_USER=${POSTGRES_USER:-postgres}

printf 'Committing and pushing without an intermediate restart...\n'
printf 'n\n' | bash upush.sh "$COMMIT_MSG"

printf 'Deploying code and restarting Odoo...\n'
./restart_odoo20.sh

module_state=$(sudo -u "$POSTGRES_USER" psql -d "$ODOO_DB" -Atqc \
  "SELECT state FROM ir_module_module WHERE name = '$ODOO_MODULE' LIMIT 1;")

if [ "$module_state" = "installed" ] || [ "$module_state" = "to upgrade" ]; then
  module_flag=-u
  module_action=Upgrading
else
  module_flag=-i
  module_action=Installing
fi

printf '%s Odoo module %s on database %s...\n' \
  "$module_action" "$ODOO_MODULE" "$ODOO_DB"

service_stopped=0
restore_service() {
  if [ "$service_stopped" -eq 1 ]; then
    printf 'Restoring %s after an interrupted deployment...\n' "$ODOO_SERVICE" >&2
    systemctl start "$ODOO_SERVICE" || true
  fi
}
trap restore_service EXIT

systemctl stop "$ODOO_SERVICE"
service_stopped=1

sudo -u "$ODOO_USER" "$ODOO_PYTHON" "$ODOO_BIN" \
  -c "$ODOO_CONF" \
  -d "$ODOO_DB" \
  "$module_flag" "$ODOO_MODULE" \
  --stop-after-init \
  --workers=0

printf 'Starting %s...\n' "$ODOO_SERVICE"
systemctl start "$ODOO_SERVICE"
service_stopped=0
trap - EXIT

status=""
for _ in {1..10}; do
  status=$(systemctl is-active "$ODOO_SERVICE" || true)
  if [ "$status" = "active" ]; then
    break
  fi
  sleep 1
done

printf '%s: %s\n' "$ODOO_SERVICE" "$status"
if [ "$status" != "active" ]; then
  systemctl status "$ODOO_SERVICE" --no-pager -n 50
  exit 1
fi
