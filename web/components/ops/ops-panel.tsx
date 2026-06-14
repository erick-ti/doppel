"use client";

import { useEffect, useState } from "react";
import { Activity, Database, HardDriveDownload, Radio } from "lucide-react";

import {
  ageSnapshot,
  fetchStats,
  formatCount,
  HEALTHCHECK_BADGE_URL,
  relativeAge,
  safeBadgeUrl,
  STATS_CADENCE_MIN,
  STATS_URL,
  type FeedState,
} from "@/lib/ops";
import { cn } from "@/lib/utils";

/** Re-fetch faster than the push cadence so a new snapshot lands promptly on a long-open tab. */
const POLL_MS = 5 * 60_000;
/** Re-age the displayed snapshot on the wall clock INDEPENDENT of fetches — so staleness advances
 *  (and the green marker drops) even when refreshes hang, not just when a poll resolves. 60s matches
 *  the minute-granularity age label (Codex review 2026-06-13). */
const TICK_MS = 60_000;

/** Validated once at module load: only a real read-only badge URL survives (never a ping credential). */
const BADGE_URL = safeBadgeUrl(HEALTHCHECK_BADGE_URL);

/**
 * The LIVE ops panel — a register deliberately distinct from the RECORDED replay surface (that
 * juxtaposition is the story: the real system is up and monitored; the replays are accurate
 * recordings of it). Neutral card chrome + the dedicated system-status tokens (--ok / --warning),
 * so it never borrows the cultural/audio retrieval-leg accents.
 *
 * It fetches the VPS-pushed stats.json client-side; SSR and the first client render show the same
 * state (seeded from the build-inlined STATS_URL, identical on both sides — no hydration mismatch),
 * then the real numbers fill in. Every non-ok state is truthful and carries no fabricated values.
 * Staleness is the down signal: a stale snapshot never asserts live-up.
 */
export function OpsPanel() {
  // Seed from the build-time constant so the prerendered/no-JS page is already truthful: "loading"
  // only when a feed URL exists, else "unconfigured" outright (no connecting→unconfigured flash).
  // STATS_URL is inlined identically server- and client-side, so this hydrates clean.
  const [feed, setFeed] = useState<FeedState>(STATS_URL ? { kind: "loading" } : { kind: "unconfigured" });

  useEffect(() => {
    if (!STATS_URL) return; // nothing to poll; the seeded "unconfigured" state stands
    let alive = true;
    let inFlight = false;

    // Fetch a new snapshot (bounded by fetchStats's timeout). On success → fresh ok. On failure,
    // fail soft (v1.2 decision): keep the last good snapshot and flag the failed refresh — the
    // aging tick below advances its age regardless. A first-fetch failure surfaces the error state.
    const refresh = async () => {
      if (inFlight) return; // single-in-flight guard against timer drift / throttle catch-up
      inFlight = true;
      const next = await fetchStats(Date.now());
      inFlight = false;
      if (!alive) return;
      setFeed((prev) =>
        next.kind === "ok" ? next : prev.kind === "ok" ? { ...prev, refreshError: true } : next,
      );
    };

    // Wall-clock aging — runs whether or not a fetch ever resolves, so a frozen/hung feed still
    // crosses the stale threshold and the green marker drops on schedule.
    const age = () =>
      setFeed((prev) =>
        prev.kind === "ok" ? ageSnapshot(prev.stats, Date.now(), prev.refreshError ?? false) : prev,
      );

    refresh();
    const fetchId = setInterval(refresh, POLL_MS);
    const ageId = setInterval(age, TICK_MS);
    // A backgrounded tab throttles both timers; on refocus, re-age + re-fetch immediately so the
    // visitor never sees a frozen-fresh panel after the tab was hidden.
    const onVisible = () => {
      if (document.visibilityState === "visible") {
        age();
        refresh();
      }
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      alive = false;
      clearInterval(fetchId);
      clearInterval(ageId);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  const ok = feed.kind === "ok" ? feed : null;
  const stats = ok?.stats;
  const stale = ok?.stale ?? false;
  // The headline marker is green ONLY when the snapshot is fresh AND the API reported up — never on
  // a fresh api:down or a stale snapshot (the most-scannable signal must not overclaim liveness).
  const live = !!stats && !stale && stats.api.status === "up";

  return (
    <section aria-label="Live system status" className="bg-card/40 rounded-xl border p-5">
      <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-foreground inline-flex items-center gap-1.5 font-mono text-xs font-semibold tracking-wide uppercase">
          <Radio
            className={cn(
              "size-3.5",
              live ? "text-ok" : stats && stats.api.status === "down" ? "text-destructive" : "text-muted-foreground",
            )}
            aria-hidden
          />
          Live
        </span>
        <span className="text-muted-foreground text-sm">the production engine, right now</span>
        <span className="ml-auto font-mono text-[11px] tabular-nums">{feedStamp(feed)}</span>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Tile
          icon={<Activity className="size-4" aria-hidden />}
          label="API"
          // A stale snapshot only knows the API was up AS OF its timestamp — never assert live-up on
          // stale data (the cardinal rule): drop the green tone and qualify with the age. The `sub`
          // scopes the claim honestly: this is an HTTP **liveness** probe (/health is a static 200),
          // not a dependency-aware health check (Redis/worker not verified) — Codex review 2026-06-13.
          value={stats ? (stats.api.status === "up" ? "online" : "offline") : "—"}
          sub={stats ? (stale ? `as of ${relativeAge(ok!.ageMs)}` : "liveness probe") : undefined}
          tone={stats ? (stale ? "idle" : stats.api.status === "up" ? "good" : "bad") : "idle"}
        />
        <Tile
          icon={<Database className="size-4" aria-hidden />}
          label="Corpus"
          value={stats ? formatCount(stats.corpus.embeddings) : "—"}
          sub={stats ? "embeddings" : undefined}
        />
        <Tile
          icon={<Activity className="size-4" aria-hidden />}
          label="Queries served"
          value={stats ? formatCount(stats.usage.queries_completed) : "—"}
          sub={stats ? `of ${formatCount(stats.usage.queries_total)} logged` : undefined}
        />
        <Tile
          icon={<HardDriveDownload className="size-4" aria-hidden />}
          label="Last backup"
          value={stats?.backup.last_success_at ? backupAge(stats.backup.last_success_at) : "—"}
          // The feed reports the newest LOCAL dump's mtime — written before the optional offsite
          // mirror, so this is "a local pg_dump ran", not "mirrored offsite" (the offsite path is
          // covered by the §9.2 healthchecks check). Don't imply object-store success here.
          sub={stats?.backup.last_success_at ? "local pg_dump" : undefined}
        />
      </div>

      {stats && (
        <p className="text-muted-foreground/70 mt-3 font-mono text-[11px]">
          CLAP contract: <span className="text-muted-foreground">{stats.corpus.model_version}</span>
        </p>
      )}

      {/* Independent third-party uptime monitor (healthchecks.io), embedded as a zero-JS SVG badge.
          Rendered only when the configured URL passes safeBadgeUrl — a mis-pasted ping credential
          never reaches an <img src> (which would auto-spoof success on every visit). */}
      {BADGE_URL && (
        <div className="text-muted-foreground mt-4 flex items-center gap-2 text-xs">
          {/* Honest label: the component can't verify WHICH check a badge tracks, so it doesn't claim
              "uptime" — the operator points it at a backup or an API-heartbeat check (DEPLOY.md §9.3). */}
          <span>Independent monitor (healthchecks.io):</span>
          {/* eslint-disable-next-line @next/next/no-img-element -- external SVG badge, not a local asset */}
          <img src={BADGE_URL} alt="healthchecks.io status" className="h-[20px] w-auto" />
        </div>
      )}

      <p className="text-muted-foreground/70 mt-4 font-mono text-[11px] leading-relaxed">{feedNote(feed)}</p>
    </section>
  );
}

type Tone = "idle" | "good" | "bad";

function Tile({
  icon,
  label,
  value,
  sub,
  tone = "idle",
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
  tone?: Tone;
}) {
  return (
    <div className="bg-card/50 rounded-lg border p-3">
      <div className="text-muted-foreground flex items-center gap-1.5 text-xs">
        {icon}
        {label}
      </div>
      <div
        className={cn(
          "mt-1.5 font-mono text-lg font-semibold tabular-nums",
          tone === "good" && "text-ok",
          tone === "bad" && "text-destructive",
        )}
      >
        {value}
      </div>
      {sub && <div className="text-muted-foreground/70 text-[11px]">{sub}</div>}
    </div>
  );
}

function backupAge(iso: string): string {
  const ms = Date.now() - Date.parse(iso);
  return Number.isNaN(ms) ? "—" : relativeAge(Math.max(0, ms));
}

/** The fetch stamp in the header — neutral when fresh, amber (--warning) when stale. */
function feedStamp(feed: FeedState): React.ReactNode {
  switch (feed.kind) {
    case "ok":
      return (
        <span className={feed.stale || feed.refreshError ? "text-warning" : "text-muted-foreground/80"}>
          updated {relativeAge(feed.ageMs)}
          {feed.stale ? " · stale" : ""}
          {feed.refreshError ? " · refresh failed" : ""}
        </span>
      );
    case "loading":
      return <span className="text-muted-foreground/80">connecting…</span>;
    case "error":
      return <span className="text-warning">feed unavailable</span>;
    case "unconfigured":
      return <span className="text-muted-foreground/80">feed not configured</span>;
  }
}

function feedNote(feed: FeedState): string {
  switch (feed.kind) {
    case "ok":
      return feed.stale
        ? `Pushed from the Hetzner VPS every ${STATS_CADENCE_MIN} min via Cloudflare R2 — this snapshot is overdue, so the box may be offline (staleness is the signal, not freshness).`
        : `Pushed from the Hetzner VPS every ${STATS_CADENCE_MIN} min via Cloudflare R2 — sanitized counts only, no request-time inference.`;
    case "loading":
      return "Fetching the latest snapshot the VPS pushed to Cloudflare R2…";
    case "error":
      return "The live snapshot couldn't be fetched — the VPS may be offline, or the feed isn't reachable from here. The recorded replays below are unaffected.";
    case "unconfigured":
      return "Live feed not configured for this deployment. The recorded replays below are the engine's real output regardless.";
  }
}
