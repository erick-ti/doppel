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
#   REPO_DIR                repo root with the compose files       (default: this script's parent directory)
#   BACKUP_DIR              where archives are written              (default: $HOME/doppel-backups)
#   KEEP                    how many most-recent local archives    (default: 7)
#   BACKUP_REMOTE           rclone remote to mirror to             (unset = local-only; the no-op default)
#   OFFSITE_KEEP_DAYS       off-box retention in days              (default: 30)
#   BACKUP_HEALTHCHECK_URL  healthchecks.io-style URL to ping      (unset = no pings; the no-op default)
set -euo pipefail
umask 077   # dumps are owner-only (600), and a freshly-created BACKUP_DIR is 700 — DB data isn't world-readable

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/doppel-backups}"
KEEP="${KEEP:-7}"
BACKUP_REMOTE="${BACKUP_REMOTE:-}"
OFFSITE_KEEP_DAYS="${OFFSITE_KEEP_DAYS:-30}"
BACKUP_HEALTHCHECK_URL="${BACKUP_HEALTHCHECK_URL:-}"

# Passive dead-man's-switch notifier: ping <URL>/start after pre-flight, <URL> on success, and
# <URL>/fail on any non-zero exit (via the EXIT trap below). Default-off, so this is a no-op for
# installs that haven't wired up a notifier; the URL itself is the credential and lives on the VPS
# only (crontab top-of-file, alongside BACKUP_REMOTE — DEPLOY.md §9.2). The trap fires for both
# pre-flight (KEEP/OFFSITE_KEEP_DAYS guards) and mid-script failures so a config typo alarms
# immediately instead of waiting on the healthchecks.io grace timer. curl errors are intentionally
# swallowed: a notifier outage must never fail an otherwise-good backup. (A failed *success* ping
# leaves no signal at all, which healthchecks.io alerts on once the grace timer elapses — the
# right shape; a wrong-but-loud signal would be worse than a delayed-but-correct one.) Logs never
# echo the URL — it's a credential.
_healthcheck_ping() {
    local suffix="${1:-}"
    if [[ -z "$BACKUP_HEALTHCHECK_URL" ]]; then
        return 0
    fi
    if curl --silent --show-error --max-time 10 --retry 3 --retry-connrefused --fail \
            "${BACKUP_HEALTHCHECK_URL}${suffix}" >/dev/null 2>&1; then
        echo "backup_db: healthcheck ${suffix:-success} ping ok"
    else
        echo "backup_db: healthcheck ${suffix:-success} ping failed (non-fatal)" >&2
    fi
}
_on_exit() {
    local rc=$?
    if [[ $rc -ne 0 ]]; then
        _healthcheck_ping /fail
    fi
    exit "$rc"
}
trap _on_exit EXIT

# Fail closed on a bad retention count BEFORE dumping or pruning. A 0 / negative / non-numeric KEEP
# makes `tail -n +$((KEEP + 1))` resolve to `+1`, which selects EVERY archive (including the one just
# written) for deletion — turning a config typo into total backup loss. Require a positive integer.
if ! [[ "$KEEP" =~ ^[1-9][0-9]*$ ]]; then
    echo "backup_db: KEEP must be a positive integer (got '$KEEP')" >&2
    exit 2
fi

# Tell the notifier we're starting AFTER pre-flight passes — a pre-flight failure already pings
# /fail via the EXIT trap, and we don't want a phantom "started but never finished" state from a
# config typo. Healthchecks.io accepts /fail standalone (no prior /start required).
_healthcheck_ping /start

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

# Retention: keep the $KEEP most-recent archives, prune the rest. The dump filenames embed a
# zero-padded UTC timestamp; we sort them EXPLICITLY under a fixed (C) collation so the prune order is
# chronological (oldest first) and CANNOT depend on the shell's glob sort — bash 5.3+
# `GLOBSORT=-mtime`/`nosort` could otherwise reorder the array and delete the NEWEST dumps (incl. the
# one just written). FAILS CLOSED two ways, because for a backup a silently-skipped prune that fills the
# disk is worse than a loud abort: (1) a non-readable / non-traversable BACKUP_DIR is caught by an
# explicit preflight — a bare glob would expand to EMPTY there (the dir can't be listed) and skip
# pruning behind a green healthcheck; (2) a real `rm` error sets `prune_failed`. `nullglob` builds the
# array (empty dir → empty array, no error) — no list/sort/tail pipeline with a `|| true` to swallow a
# failure. Both set `prune_failed` and fail closed at the END (deferred past the off-box mirror, so a
# local-prune problem can't also skip off-box durability). bash-3.2-portable.
prune_failed=0
if [[ ! -r "$BACKUP_DIR" || ! -x "$BACKUP_DIR" ]]; then
    echo "backup_db: BACKUP_DIR '$BACKUP_DIR' is not readable+traversable — cannot enumerate archives to prune; failing closed" >&2
    prune_failed=1
else
    shopt -s nullglob
    _dumps=("$BACKUP_DIR"/doppel-*.dump)
    shopt -u nullglob
    if (( ${#_dumps[@]} > KEEP )); then
        # Re-sort by filename under a FIXED collation so deletion order is deterministic regardless of
        # the shell's glob sort (GLOBSORT) or locale; oldest first, so we prune the leading count-KEEP.
        _sorted=()
        while IFS= read -r _d; do _sorted+=("$_d"); done < <(printf '%s\n' "${_dumps[@]}" | LC_ALL=C sort)
        for (( _i = 0; _i < ${#_sorted[@]} - KEEP; _i++ )); do
            echo "backup_db: pruning ${_sorted[_i]}"
            rm -f "${_sorted[_i]}" || { echo "backup_db: failed to prune ${_sorted[_i]}" >&2; prune_failed=1; }
        done
    fi
fi

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

# Fail CLOSED if the local retention prune hit a real error earlier (deferred to here so the off-box
# mirror still ran). The new dump and any off-box copy are intact; only the LOCAL prune is stuck, so old
# archives could pile up — surface it instead of reporting success. exit 1 → the EXIT trap pings /fail.
if (( prune_failed )); then
    echo "backup_db: retention prune failed — failing closed (new dump + off-box mirror OK; local prune needs attention)" >&2
    exit 1
fi

# Final success ping. Reaching this means: local dump landed + pruned, and (if BACKUP_REMOTE is
# set) off-box mirror succeeded too. A failed success ping is non-fatal (the notifier outage path);
# the trap below sees rc=0 and skips /fail, so healthchecks.io eventually alerts via grace-timer.
_healthcheck_ping
