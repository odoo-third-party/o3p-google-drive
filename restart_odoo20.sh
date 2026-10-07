#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
DEPLOY_DIR=${DEPLOY_DIR:-/opt/odoo20/o3p-google-drive}
ADDONS_DIR=${ADDONS_DIR:-/opt/odoo20/addons}
ODOO_USER=${ODOO_USER:-odoo20}
ODOO_SERVICE=${ODOO_SERVICE:-odoo20}
ODOO_MODULE=${ODOO_MODULE:-o3p_google_drive}
REPO_URL=${REPO_URL:-$(git -C "$SCRIPT_DIR" remote get-url origin)}
ADDON_SOURCE="$DEPLOY_DIR/$ODOO_MODULE"
ADDON_LINK="$ADDONS_DIR/$ODOO_MODULE"

if [ ! -d "$DEPLOY_DIR/.git" ]; then
  if [ -e "$DEPLOY_DIR" ]; then
    printf 'Deployment path exists but is not a Git checkout: %s\n' "$DEPLOY_DIR" >&2
    exit 1
  fi

  printf 'Cloning %s into %s...\n' "$REPO_URL" "$DEPLOY_DIR"
  git clone "$REPO_URL" "$DEPLOY_DIR"
  chown -R "$ODOO_USER:$ODOO_USER" "$DEPLOY_DIR"
else
  printf 'Pulling latest code in %s...\n' "$DEPLOY_DIR"
  git -c safe.directory="$DEPLOY_DIR" -C "$DEPLOY_DIR" pull --ff-only
fi

if [ ! -f "$ADDON_SOURCE/__manifest__.py" ]; then
  printf 'Odoo addon was not found at %s\n' "$ADDON_SOURCE" >&2
  exit 1
fi

if [ -L "$ADDON_LINK" ]; then
  if [ "$(readlink "$ADDON_LINK")" != "$ADDON_SOURCE" ]; then
    printf 'Addon link points somewhere unexpected: %s -> %s\n' \
      "$ADDON_LINK" "$(readlink "$ADDON_LINK")" >&2
    exit 1
  fi
elif [ -e "$ADDON_LINK" ]; then
  printf 'Addon path exists and is not a symlink: %s\n' "$ADDON_LINK" >&2
  exit 1
else
  printf 'Linking %s into the Odoo addons directory...\n' "$ODOO_MODULE"
  ln -s "$ADDON_SOURCE" "$ADDON_LINK"
  chown -h "$ODOO_USER:$ODOO_USER" "$ADDON_LINK"
fi

find "$ADDON_SOURCE" -type d -name "__pycache__" -prune -exec rm -rf {} +
find "$ADDON_SOURCE" -type f -name "*.pyc" -delete

printf 'Restarting %s...\n' "$ODOO_SERVICE"
systemctl restart "$ODOO_SERVICE"

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
