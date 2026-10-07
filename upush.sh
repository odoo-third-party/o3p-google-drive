#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 1 ]; then
  printf 'Usage: %s "commit message"\n' "$0" >&2
  exit 1
fi

COMMIT_MSG=$1
BRANCH=$(git rev-parse --abbrev-ref HEAD)
REMOTE=${REMOTE:-origin}

printf 'Staging changes...\n'
git add -A

printf 'Committing with message: %s\n' "$COMMIT_MSG"
git commit -m "$COMMIT_MSG"

printf 'Pulling latest from %s/%s...\n' "$REMOTE" "$BRANCH"
git pull --ff-only "$REMOTE" "$BRANCH"

printf 'Pushing branch to %s/%s...\n' "$REMOTE" "$BRANCH"
git push "$REMOTE" "$BRANCH"

printf 'Restart odoo20? [y/N] (auto-skip in 5s): '
if read -r -t 5 answer; then
  case "$answer" in
    [yY]|[yY][eE][sS])
      ./restart_odoo20.sh
      ;;
    *)
      printf 'Skipping restart.\n'
      ;;
  esac
else
  printf '\nNo response in time. Skipping restart.\n'
fi
