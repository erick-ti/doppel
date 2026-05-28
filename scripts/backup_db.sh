#!/usr/bin/env bash
# Daily Postgres backup for the Doppel VPS deploy (Day 7). Dumps the `postgres` compose service's
# database to a timestamped, compressed pg_dump archive on the host, prunes old archives, then
# (opt-in) uploads the new archive to an off-box rclone remote and prunes the remote by age.
# Wire into cron — see DEPLOY.md ("Daily backups" + "Off-box backups").
#
# pg_dump runs *inside* the container (so the client version matches the server) using the
# container's own POSTGRES_* env, so it needs no password on the host and works against both the dev
# and prod stacks. The archive streams to the host filesystem in custom format (-Fc → restore with
# pg_restore; see DEPLOY.md "Restore"). Keep BACKUP_DIR outside the repo; set BACKUP_REMOTE for
# real disaster recovery — a backup that only lives on the VPS dies with the VPS.
#
# Config via env (sane defaults):
#   REPO_DIR           repo root with the compose files       (default: this script's parent directory)
#   BACKUP_DIR         where archives are written              (default: $HOME/doppel-backups)
#   KEEP               how many most-recent local archives    (default: 7)
#   BACKUP_REMOTE      rclone remote to mirror to             (unset = local-only; the no-op default)
#   OFFSITE_KEEP_DAYS  off-box retention in days              (default: 30)
set -euo pipefail
umask 077   # dumps are owner-only (600), and a freshly-created BACKUP_DIR is 700 — DB data isn't world-readable

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/doppel-backups}"
KEEP="${KEEP:-7}"
BACKUP_REMOTE="${BACKUP_REMOTE:-}"
OFFSITE_KEEP_DAYS="${OFFSITE_KEEP_DAYS:-30}"

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

# Off-box mirror (opt-in, gated on $BACKUP_REMOTE). All off-box validation lives in this block — NOT
# as a pre-flight before the dump — so a misconfigured optional add-on (typo'd OFFSITE_KEEP_DAYS,
# package drift hiding rclone) can never disable the core local backup. The local dump above is
# already durable on disk + pruned and survives any failure here; the script still exits non-zero so
# cron mail / backup.log surface the issue. (Contrast: the KEEP guard above stays in pre-flight
# because KEEP governs the local prune — a bad value would `rm` local archives, so it must validate
# before any state mutation. The off-box knobs govern only the remote phase, a different risk shape.)
# We `copy` (not `sync`) the just-written file so off-box retention (OFFSITE_KEEP_DAYS) outlives the
# local KEEP — the whole point of mirroring is that off-box durability is *longer*, not equal.
# --no-traverse skips listing the destination; the timestamped basename can't collide. Remote prune
# is filtered to our naming pattern, so a misconfigured remote (pointed at a directory with unrelated
# files) cannot delete anything outside the backup set.
if [[ -n "$BACKUP_REMOTE" ]]; then
    if ! [[ "$OFFSITE_KEEP_DAYS" =~ ^[1-9][0-9]*$ ]]; then
        echo "backup_db: OFFSITE_KEEP_DAYS must be a positive integer (got '$OFFSITE_KEEP_DAYS') — off-box mirror skipped, local dump retained at $out" >&2
        exit 2
    fi
    if ! command -v rclone >/dev/null 2>&1; then
        echo "backup_db: BACKUP_REMOTE is set but rclone is not installed — off-box mirror skipped, local dump retained at $out" >&2
        exit 2
    fi
    echo "backup_db: uploading to $BACKUP_REMOTE"
    if ! rclone copy --no-traverse "$out" "$BACKUP_REMOTE"; then
        echo "backup_db: rclone copy to $BACKUP_REMOTE failed — local dump retained at $out" >&2
        exit 1
    fi
    echo "backup_db: pruning remote archives older than ${OFFSITE_KEEP_DAYS}d on $BACKUP_REMOTE"
    if ! rclone delete --min-age "${OFFSITE_KEEP_DAYS}d" --include "doppel-*.dump" "$BACKUP_REMOTE"; then
        echo "backup_db: rclone remote prune on $BACKUP_REMOTE failed (upload succeeded)" >&2
        exit 1
    fi
fi
