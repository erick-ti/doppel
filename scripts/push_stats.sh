#!/usr/bin/env bash
# Push a sanitized live-stats JSON from the Doppel VPS to a PUBLIC-read object store (v1.2 Phase 3 —
# the showcase's live ops panel fetches it client-side). Wire into cron (e.g. */15 min) — see
# DEPLOY.md §9.3.
#
# Design (outbound-push only — never a new inbound surface on the loopback+SSH-only box):
#   - reads counts from the `postgres` compose service using the CONTAINER's own POSTGRES_* env over
#     its local socket (no host password; matches backup_db.sh), and the API's loopback /health;
#   - assembles a SANITIZED JSON — corpus/usage counts, api status, last-backup time ONLY. Never an
#     IP, hostname, path, token, or any identifier (the box stays unadvertised);
#   - `rclone copyto`s it to a SEPARATE PUBLIC bucket — NOT the encrypted backup remote. The stats
#     file is the only object there; it carries nothing secret.
# Failure is non-fatal and silent-by-design: a stale stats.json is itself the "VPS may be down"
# signal the panel renders (staleness = liveness), and healthchecks.io owns the actual alerting.
#
# Config via env (sane defaults; set the non-defaults in the crontab top-of-file, off-repo):
#   REPO_DIR        repo root with the compose files     (default: this script's parent directory)
#   STATS_REMOTE    rclone remote:path for the JSON      (REQUIRED to push; unset = assemble + print only)
#   STATS_TMP       local scratch path for the JSON      (default: $HOME/doppel-stats.json)
#   API_HEALTH_URL  loopback health endpoint             (default: http://127.0.0.1:8000/health)
#   BACKUP_DIR      where backup archives land           (default: $HOME/doppel-backups; for last-backup time)
#   COMPOSE_FILES   compose -f args for the prod overlay (default: the prod overlay pair)
#   LOCK_FILE       single-instance flock path           (default: $HOME/.doppel-push-stats.lock)
#   CALL_TIMEOUT    per docker-exec timeout, seconds     (default: 30)
#   RCLONE_TIMEOUT  rclone copyto timeout, seconds       (default: 120)
set -euo pipefail
umask 077

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
STATS_REMOTE="${STATS_REMOTE:-}"
STATS_TMP="${STATS_TMP:-$HOME/doppel-stats.json}"
API_HEALTH_URL="${API_HEALTH_URL:-http://127.0.0.1:8000/health}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/doppel-backups}"
COMPOSE_FILES="${COMPOSE_FILES:--f docker-compose.yml -f docker-compose.prod.yml}"
LOCK_FILE="${LOCK_FILE:-$HOME/.doppel-push-stats.lock}"
CALL_TIMEOUT="${CALL_TIMEOUT:-30}"   # seconds; bounds each hang-prone docker exec
RCLONE_TIMEOUT="${RCLONE_TIMEOUT:-120}"  # seconds; bounds the network rclone copyto

# Single-instance guard (Codex review 2026-06-13): a */15-min cron must never pile up. Take a
# NON-BLOCKING exclusive lock on fd 9; if a prior run still holds it (e.g. a hung dependency), skip
# this tick rather than spawning an overlapping copy that would race on STATS_TMP. The lock auto-
# releases when this process exits. Paired with the per-call `timeout`s below so a hung run dies and
# frees the lock instead of wedging every future tick (so a single fixed STATS_TMP stays safe — flock
# guarantees one writer at a time; no per-run mktemp needed). `flock` is util-linux (present on the
# Linux VPS where the cron runs); a dev box without it just runs unlocked (no cron, no pile-up risk).
if command -v flock >/dev/null 2>&1; then
    exec 9>"$LOCK_FILE"
    if ! flock -n 9; then
        echo "push_stats: another run holds $LOCK_FILE — skipping this tick"
        exit 0
    fi
else
    echo "push_stats: flock unavailable — running without a single-instance lock (dev only)" >&2
fi

cd "$REPO_DIR"

# Bound a hang-prone call with `timeout` (GNU coreutils, on the Linux VPS); where it's absent (a dev
# box) run unbounded. First arg is the duration; the rest is the command.
if command -v timeout >/dev/null 2>&1; then
    _timeout() { timeout "$@"; }
else
    _timeout() { shift; "$@"; }
fi

# psql inside the container, peer/trust over the local socket using the container's own env — no host
# password, works against dev and prod overlays alike (same approach as backup_db.sh's pg_dump).
# Returns the scalar on success (an empty string is a VALID result — e.g. an empty corpus). FAILS
# (non-zero, via pipefail) on a docker/compose/psql/timeout error, so the caller can abort rather
# than publish fabricated zeros — `set -e` is held off by the caller's `|| _abort_db` (Codex review
# 2026-06-13: do NOT swallow DB failures into 0; that would overwrite the last good public snapshot
# with a fresh, misleading "healthy, corpus 0").
_count() {
    # shellcheck disable=SC2086
    _timeout "$CALL_TIMEOUT" docker compose $COMPOSE_FILES exec -T postgres \
        sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tA -c "'"$1"'"' 2>/dev/null | tr -d '[:space:]'
}

# A DB read failed (Postgres/compose down, schema drift, or timeout). Abort BEFORE publishing so the
# last public snapshot is preserved and ages to "stale" — the honest down signal — instead of being
# overwritten with fresh fabricated zeros. The lock auto-releases on exit; the next tick retries.
_abort_db() {
    echo "push_stats: a DB read failed/timed out — NOT publishing. The last public snapshot ages to " \
         "'stale' (the honest signal); fresh zeros would hide the failure. Check Postgres/compose." >&2
    exit 1
}

# Resolve an rclone remote arg ("alias:bucket/path…") to its underlying S3/R2 bucket, following ONE
# level of crypt indirection (crypt's `remote = backing:bucket/prefix`). Prints the bucket, or empty
# if it can't be determined (no rclone, unknown alias, crypt-on-crypt) — the caller treats empty as
# "couldn't verify" and leaves the cheap alias/crypt guards + the documented operator discipline.
_remote_bucket() {
    local arg="$1" alias rest type backing
    alias="${arg%%:*}"
    rest="${arg#*:}"
    type="$(_timeout 10 rclone config show "$alias" 2>/dev/null | sed -n 's/^[[:space:]]*type[[:space:]]*=[[:space:]]*//p' | head -1)"
    if [[ "$type" == "crypt" ]]; then
        backing="$(_timeout 10 rclone config show "$alias" 2>/dev/null | sed -n 's/^[[:space:]]*remote[[:space:]]*=[[:space:]]*//p' | head -1)"
        [[ -z "$backing" ]] && return 0   # can't follow → empty (unverifiable)
        rest="${backing#*:}"
    fi
    printf '%s' "${rest%%/*}"   # first path segment of an s3/R2 remote = the bucket
}

tracks="$(_count 'SELECT count(*) FROM tracks')" || _abort_db
# Corpus = what the live engine can actually SERVE: the `servable_embeddings` view (source asset still
# status='found') scoped to the ACTIVE CLAP contract — NOT raw `embeddings` (counts rejected-asset
# rows) and NOT the dominant stored contract (after a model/pooling change or a mid-flight re-embed,
# old rows can stay dominant while the engine reads only the configured version — Codex review
# 2026-06-13). The active version is read from the running app's OWN config (no duplicated derivation
# of CLAP_MODEL_ID+CLAP_EMBED_POOLING); this only matters when the app is up-and-serving, which is
# exactly when the exec succeeds. If the app is unreachable (already shown as api.status=down, so no
# active serving to misrepresent) fall back to the dominant servable contract rather than blanking
# the whole panel.
# `timeout` + `|| true`: a down/unreachable/hung app must not abort or stall the push under
# `set -euo pipefail` — it falls back to the dominant servable contract.
# shellcheck disable=SC2086
active_version="$(_timeout "$CALL_TIMEOUT" docker compose $COMPOSE_FILES exec -T app \
    python -c 'from doppel.config import CLAP_MODEL_VERSION; print(CLAP_MODEL_VERSION)' 2>/dev/null \
    | tr -cd 'A-Za-z0-9._/+-' || true)"
if [[ -n "$active_version" ]]; then
    model_version="$active_version"
else
    model_version="$(_count "SELECT model_version FROM servable_embeddings GROUP BY model_version ORDER BY count(*) DESC, model_version LIMIT 1")" || _abort_db
    model_version="$(printf '%s' "$model_version" | tr -cd 'A-Za-z0-9._/+-')"
fi
# model_version is a config token (no JSON metacharacters by contract), but this is a hand-rolled JSON
# writer + it's interpolated into the next query — sanitized above; re-strip the fallback path too.
embeddings="$(_count "SELECT count(*) FROM servable_embeddings WHERE model_version = '${model_version}'")" || _abort_db
queries_total="$(_count 'SELECT count(*) FROM query_logs')" || _abort_db
queries_completed="$(_count "SELECT count(*) FROM query_logs WHERE status='succeeded'")" || _abort_db

# API HTTP liveness from the loopback health endpoint (the box never exposes this publicly). NB:
# /health is a static 200 — this is process liveness, NOT a dependency-aware check (Redis/worker/
# enqueue are not verified). The panel labels the tile "liveness probe" so it can't be read as
# full-engine health; a deep /health is a separate backend decision (Codex review 2026-06-13).
if curl --silent --show-error --max-time 5 --fail "$API_HEALTH_URL" >/dev/null 2>&1; then
    api_status="up"
else
    api_status="down"
fi

# Last LOCAL backup = mtime of the newest archive (sanitized to a UTC date-time, never the path).
# NB: backup_db.sh writes the dump BEFORE the optional offsite mirror and keeps it if the mirror
# fails — so this reflects "a local pg_dump ran", NOT offsite-mirror success. The panel labels it
# "local pg_dump" accordingly; offsite-inclusive alerting is the §9.2 healthchecks check's job.
last_backup="null"
if [[ -d "$BACKUP_DIR" ]]; then
    newest="$(find "$BACKUP_DIR" -maxdepth 1 -type f -name '*.dump' -printf '%T@\n' 2>/dev/null | sort -nr | head -1 || true)"
    if [[ -n "$newest" ]]; then
        last_backup="\"$(date -u -d "@${newest%.*}" +%Y-%m-%dT%H:%M:%SZ)\""
    fi
fi

generated_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Build the JSON by hand (no jq dependency). Every value is a count / enum / ISO timestamp / a
# model-version string from our own config — no free text, no host identifiers, no injection surface.
cat > "$STATS_TMP" <<JSON
{
  "schema_version": 1,
  "generated_at": "${generated_at}",
  "corpus": {
    "tracks": ${tracks:-0},
    "embeddings": ${embeddings:-0},
    "model_version": "${model_version:-unknown}"
  },
  "usage": {
    "queries_total": ${queries_total:-0},
    "queries_completed": ${queries_completed:-0}
  },
  "api": { "status": "${api_status}" },
  "backup": { "last_success_at": ${last_backup} }
}
JSON

echo "push_stats: assembled ${STATS_TMP} (tracks=${tracks:-0} embeddings=${embeddings:-0} api=${api_status})"

if [[ -z "$STATS_REMOTE" ]]; then
    echo "push_stats: STATS_REMOTE unset — assembled only, not pushed (set it to enable the public push)"
    exit 0
fi

# Enforce the privacy boundary: the PUBLIC stats object must never land in the encrypted backup's
# bucket (a shared crontab makes a copy-paste typo realistic; a collision would expose backup
# ciphertext if that bucket is public, or hide the stats where the panel can't read them). Three
# guards, cheap→thorough (Codex review 2026-06-13):
#   (1) STATS_REMOTE sharing an rclone alias with BACKUP_REMOTE.
if [[ -n "${BACKUP_REMOTE:-}" && "${STATS_REMOTE%%:*}" == "${BACKUP_REMOTE%%:*}" ]]; then
    echo "push_stats: STATS_REMOTE ('${STATS_REMOTE%%:*}:') shares an rclone remote with BACKUP_REMOTE — " \
         "use a SEPARATE public bucket (DEPLOY.md §9.3)" >&2
    exit 2
fi
#   (2) STATS_REMOTE being a `crypt` remote — the public feed must be plaintext, and a crypt remote IS
#       the backup's encryption layer; catches `STATS_REMOTE=r2-crypt:…` regardless of BACKUP_REMOTE.
if command -v rclone >/dev/null 2>&1 \
   && rclone config show "${STATS_REMOTE%%:*}" 2>/dev/null | grep -qiE '^type[[:space:]]*=[[:space:]]*crypt'; then
    echo "push_stats: STATS_REMOTE ('${STATS_REMOTE%%:*}:') is a crypt remote — the public stats feed must " \
         "be plaintext in a SEPARATE public bucket, never the encrypted backup remote (DEPLOY.md §9.3)" >&2
    exit 2
fi
#   (3) STATS and BACKUP resolving to the SAME underlying bucket via DIFFERENT aliases — the case (1)
#       misses (e.g. STATS=r2-base:doppel-backups/… vs BACKUP=r2-crypt:→r2-base:doppel-backups). Best
#       -effort: an unresolvable bucket (empty) leaves (1)/(2) + the documented operator discipline.
if command -v rclone >/dev/null 2>&1 && [[ -n "${BACKUP_REMOTE:-}" ]]; then
    _stats_bucket="$(_remote_bucket "$STATS_REMOTE")"
    _backup_bucket="$(_remote_bucket "$BACKUP_REMOTE")"
    if [[ -n "$_stats_bucket" && "$_stats_bucket" == "$_backup_bucket" ]]; then
        echo "push_stats: STATS_REMOTE and BACKUP_REMOTE resolve to the SAME bucket ('$_stats_bucket') — " \
             "the public stats feed needs its OWN bucket, never the encrypted backup's (DEPLOY.md §9.3)" >&2
        exit 2
    fi
fi

# Push to the PUBLIC stats bucket. --no-traverse: a single-file copyto. `timeout` bounds a hung
# network upload (so it can't hold the lock past the next tick). A push failure is non-fatal (the
# panel treats a stale file as the down signal); we surface it on stderr for the cron mail.
if _timeout "$RCLONE_TIMEOUT" rclone copyto --no-traverse "$STATS_TMP" "$STATS_REMOTE" 2>&1; then
    echo "push_stats: pushed to the public stats remote"
else
    echo "push_stats: rclone push failed/timed out (non-fatal; stale stats.json is itself the down signal)" >&2
    exit 1
fi
