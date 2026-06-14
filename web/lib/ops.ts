/**
 * Live ops data for the v1.2 ops panel (client-safe — no server-only imports).
 *
 * The showcase is a static export with NO server, so "live" data is fetched in the browser at
 * runtime from PUBLIC URLs the VPS pushes to (outbound-push model — no inbound surface, no
 * client-held secrets; DECISIONS.md 2026-06-12 v1.2):
 *
 *   - `stats.json` — corpus/usage/api/backup counts the VPS cron writes to a public Cloudflare R2
 *     bucket (scripts/push_stats.sh). One controlled shape, one controlled CORS origin.
 *   - the healthchecks.io SVG badge — an independent third-party uptime monitor, embedded as an
 *     `<img>` (zero-JS, zero-CORS), shown only when its public badge URL is configured.
 *
 * Honesty model: staleness IS the liveness signal. If the VPS is down the cron stops pushing and
 * the file ages; the panel surfaces "updated Nh ago" in amber past 2× the push cadence rather than
 * implying freshness. Every config value is operator-provided via `NEXT_PUBLIC_*` (Vercel build
 * env) and absent by default — the panel renders a truthful "not configured / unavailable" state
 * with no fabricated numbers, so the repo carries no infrastructure identifiers.
 */

/** The push cadence the VPS cron runs at (minutes); drives the staleness threshold. */
export const STATS_CADENCE_MIN = 15;

/** Abort a fetch that hasn't resolved in this long — a hung R2/network connection must fail (→ the
 *  panel ages the last snapshot) rather than freeze the displayed freshness (Codex review 2026-06-13). */
export const FETCH_TIMEOUT_MS = 8_000;

/** Public URLs, operator-set in Vercel (NEXT_PUBLIC_* is inlined at build). Null when unconfigured. */
const RAW_STATS_URL = process.env.NEXT_PUBLIC_STATS_URL ?? null;
/** Gated through safeStatsUrl (below) so a mis-pasted ping credential never gets fetched — a rejected
 *  URL is null, which the panel treats as unconfigured and never fetches (Codex review 2026-06-13). */
export const STATS_URL = safeStatsUrl(RAW_STATS_URL);
export const HEALTHCHECK_BADGE_URL = process.env.NEXT_PUBLIC_HEALTHCHECK_BADGE_URL ?? null;

if (RAW_STATS_URL && !STATS_URL) {
  // Surfaces in the Vercel build log + the browser console, so a mis-set URL is diagnosable.
  console.warn(
    "[ops] NEXT_PUBLIC_STATS_URL rejected — it must be an https://…/….json feed, never a " +
      "healthchecks ping/badge URL. The live panel is disabled until it's fixed.",
  );
}

export interface OpsStats {
  schema_version: number;
  generated_at: string;
  corpus: { tracks: number; embeddings: number; model_version: string };
  usage: { queries_total: number; queries_completed: number };
  api: { status: "up" | "down" };
  backup: { last_success_at: string | null };
}

/**
 * Fail-closed allowlist for the healthchecks badge `<img src>`. ONLY a canonical read-only
 * healthchecks.io SVG **badge** URL may ever be embedded — healthchecks serves these at both the long
 * `/badge/<key>/<sig>/<tag>.svg` form and the short `/b/<n>/<uuid>.svg` form, so both path prefixes are
 * accepted. NEVER a **ping** URL (`hc-ping.com/<uuid>`), which is a credential a per-visitor `<img>` GET
 * would spoof into a permanent "success", silencing real backup alerts (DEPLOY.md §9.2/§9.3); the hard
 * `healthchecks.io` host lock excludes the `hc-ping.com` host. Returns null on anything else, so the
 * panel renders no badge rather than a footgun. (Self-hosted healthchecks on another host ⇒ widen this
 * one regex, deliberately — the default locks to the documented host.)
 */
export function safeBadgeUrl(url: string | null): string | null {
  if (!url) return null;
  return /^https:\/\/healthchecks\.io\/(badge|b)\/[\w./-]+\.svg(\?[\w=&.-]*)?$/.test(url) ? url : null;
}

/**
 * Fail-closed gate for the stats feed URL — symmetric to safeBadgeUrl (Codex review 2026-06-13).
 * The feed URL is GETed on mount and every poll, so a mis-pasted healthchecks **ping** credential
 * (`hc-ping.com/<uuid>`) would be hit by every visitor, silently spoofing the dead-man's switch
 * green. The stats feed is a public JSON object — never a healthchecks URL — so require https + a
 * `.json` path and reject any healthchecks/ping host. Returns null on anything else, so the panel
 * treats it as unconfigured and NEVER fetches it. (Self-hosting at a non-`.json` path ⇒ widen the
 * path check deliberately; the host denylist stays.)
 */
export function safeStatsUrl(url: string | null): string | null {
  if (!url) return null;
  let u: URL;
  try {
    u = new URL(url);
  } catch {
    return null;
  }
  if (u.protocol !== "https:") return null;
  const host = u.hostname.toLowerCase();
  if (host === "hc-ping.com" || host.endsWith(".hc-ping.com")) return null;
  if (host === "healthchecks.io" || host.endsWith(".healthchecks.io")) return null;
  if (!u.pathname.toLowerCase().endsWith(".json")) return null;
  return url;
}

/** Tolerance for a `generated_at` ahead of the viewer's clock. Must stay WELL under the stale window
 *  (2× cadence = 30 min): a wider tolerance would let a clock-jumped/bad-write future stamp read
 *  age-0/fresh and mask staleness for tolerance+30 min (Codex review 2026-06-13 — 60 min did exactly
 *  that). 5 min absorbs benign VPS↔browser skew (incl. a mildly-wrong visitor clock) while keeping the
 *  worst-case false-fresh window near the stale threshold; beyond it the feed is treated as invalid. */
const FUTURE_SKEW_MS = 5 * 60_000;

function isOpsStats(v: unknown): v is OpsStats {
  if (typeof v !== "object" || v === null) return false;
  const o = v as Record<string, unknown>;
  const count = (x: unknown): boolean => typeof x === "number" && Number.isFinite(x) && x >= 0;
  const corpus = o.corpus as Record<string, unknown> | undefined;
  const usage = o.usage as Record<string, unknown> | undefined;
  const api = o.api as Record<string, unknown> | undefined;
  const backup = o.backup as Record<string, unknown> | undefined;
  return (
    o.schema_version === 1 &&
    typeof o.generated_at === "string" &&
    !!corpus && count(corpus.tracks) && count(corpus.embeddings) && typeof corpus.model_version === "string" &&
    !!usage && count(usage.queries_total) && count(usage.queries_completed) &&
    !!api && (api.status === "up" || api.status === "down") &&
    !!backup && (backup.last_success_at === null || typeof backup.last_success_at === "string")
  );
}

export type FeedState =
  | { kind: "unconfigured" } // no NEXT_PUBLIC_STATS_URL — local dev / not yet wired
  | { kind: "loading" }
  | { kind: "error" } // configured but the FIRST fetch failed (no prior snapshot to keep)
  // `refreshError` = a later poll failed but we're still showing the last good snapshot (aging).
  | { kind: "ok"; stats: OpsStats; ageMs: number; stale: boolean; refreshError?: boolean };

/** Age past 2× the push cadence ⇒ stale (the VPS likely stopped pushing). */
export function isStale(ageMs: number): boolean {
  return ageMs > STATS_CADENCE_MIN * 60_000 * 2;
}

/**
 * Build an `ok` state from an ALREADY-VALIDATED snapshot, recomputing age/staleness against `nowMs`.
 * Used to fail soft on a transient refresh error (the active v1.2 decision: live fetches degrade to
 * labeled last-known values, not to dashes) — the preserved numbers are real and previously
 * validated; only their age advances, and `refreshError` lets the panel label the stale-ing feed.
 */
export function ageSnapshot(stats: OpsStats, nowMs: number, refreshError: boolean): FeedState {
  const generatedMs = Date.parse(stats.generated_at);
  const ageMs = Number.isNaN(generatedMs) ? Infinity : Math.max(0, nowMs - generatedMs);
  return { kind: "ok", stats, ageMs, stale: isStale(ageMs), refreshError };
}

/**
 * Fetch the live stats once, client-side. Never throws — every failure maps to a FeedState the
 * panel renders honestly. `nowMs` is passed in (not read here) so the caller controls the clock and
 * the result stays deterministic for testing.
 */
export async function fetchStats(nowMs: number): Promise<FeedState> {
  if (!STATS_URL) return { kind: "unconfigured" };
  // Bound the fetch: a hung connection must reject (→ error → the panel ages the last snapshot),
  // never hang forever and freeze the displayed freshness. Manual AbortController for broad support.
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS);
  try {
    const res = await fetch(STATS_URL, { cache: "no-store", signal: ctrl.signal });
    if (!res.ok) return { kind: "error" };
    // The feed is public JSON — validate its shape BEFORE trusting it as OpsStats, so a stale
    // schema / mispointed URL / partial upload degrades to the documented "unavailable" state
    // instead of throwing mid-render on a missing nested field (no app error boundary; the panel
    // is on the homepage). Codex review 2026-06-13.
    const raw: unknown = await res.json();
    if (!isOpsStats(raw)) return { kind: "error" };
    const generatedMs = Date.parse(raw.generated_at);
    // Reject unparseable or far-future stamps — both would otherwise read as fresh/live dishonestly.
    if (Number.isNaN(generatedMs) || generatedMs - nowMs > FUTURE_SKEW_MS) return { kind: "error" };
    const ageMs = Math.max(0, nowMs - generatedMs);
    return { kind: "ok", stats: raw, ageMs, stale: isStale(ageMs) };
  } catch {
    return { kind: "error" }; // network error, abort/timeout, or bad JSON — all degrade honestly
  } finally {
    clearTimeout(timer);
  }
}

/** "just now" / "3m ago" / "2h ago" / "1d ago" — relative-age label for the fetch stamp. */
export function relativeAge(ageMs: number): string {
  if (!Number.isFinite(ageMs)) return "unknown";
  const min = Math.floor(ageMs / 60_000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return `${Math.floor(hr / 24)}d ago`;
}

export function formatCount(n: number): string {
  return n.toLocaleString("en-US");
}
