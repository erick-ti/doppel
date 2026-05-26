#!/usr/bin/env bash
# Daily Postgres backup for the Doppel VPS deploy (Day 7). Dumps the `postgres` compose service's
# database to a timestamped, compressed pg_dump archive on the host, then prunes old archives.
# Wire into cron — see DEPLOY.md ("Daily backups").
#
# pg_dump runs *inside* the container (so the client version matches the server) using the
# container's own POSTGRES_* env, so it needs no password on the host and works against both the dev
# and prod stacks. The archive streams to the host filesystem in custom format (-Fc → restore with
# pg_restore; see DEPLOY.md "Restore"). Keep BACKUP_DIR outside the repo and copy archives off-box
# for real disaster recovery — a backup that only lives on the VPS dies with the VPS.
#
# Config via env (sane defaults):
#   REPO_DIR    repo root with the compose files       (default: this script's parent directory)
#   BACKUP_DIR  where archives are written              (default: $HOME/doppel-backups)
#   KEEP        how many most-recent archives to keep   (default: 7)
set -euo pipefail
umask 077   # dumps are owner-only (600), and a freshly-created BACKUP_DIR is 700 — DB data isn't world-readable

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/doppel-backups}"
KEEP="${KEEP:-7}"

# Fail closed on a bad retention count BEFORE dumping or pruning. A 0 / negative / non-numeric KEEP
# makes `tail -n +$((KEEP + 1))` resolve to `+1`, which selects EVERY archive (including the one just
# written) for deletion — turning a config typo into total backup loss. Require a positive integer.
if ! [[ "$KEEP" =~ ^[1-9][0-9]*$ ]]; then
    echo "backup_db: KEEP must be a positive integer (got '$KEEP')" >&2
    exit 2
fi

cd "$REPO_DIR"
mkdir -p "$BACKUP_DIR"
out="$BACKUP_DIR/doppel-$(date +%Y%m%d-%H%M%S).dump"
tmp="$out.partial"

# Dump with the container's own credentials, so this works whether local auth is trust or password
# and never needs the secret on the host. -T keeps the binary -Fc stream uncorrupted (no TTY). Write
# to a temp file and atomically rename on success, so a reader (restore / off-box copy) never sees a
# partial archive; umask 077 (above) keeps the temp + final files owner-only.
if ! docker compose -f docker-compose.yml exec -T postgres \
        sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' \
        > "$tmp"; then
    echo "backup_db: pg_dump failed; removing partial archive" >&2
    rm -f "$tmp"
    exit 1
fi

# A valid -Fc archive is never empty; guard against a clean exit that wrote nothing.
if [[ ! -s "$tmp" ]]; then
    echo "backup_db: archive is empty; removing" >&2
    rm -f "$tmp"
    exit 1
fi

mv "$tmp" "$out"
echo "backup_db: wrote $out ($(du -h "$out" | cut -f1))"

# Retention: keep the $KEEP most-recent archives, delete older ones. A plain pipe (no `mapfile`)
# stays portable to the macOS bash 3.2 used for dev testing; `|| true` absorbs the empty-glob exit
# under `set -o pipefail`.
ls -1t "$BACKUP_DIR"/doppel-*.dump 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r old; do
    echo "backup_db: pruning $old"
    rm -f "$old"
done || true
