"use client";

import { useEffect, useState } from "react";
import { Activity, Clock, Database, Gauge, HardDriveDownload, MemoryStick, Radio } from "lucide-react";

import {
  ageSnapshot,
  fetchStats,
  formatCount,
  formatUptime,
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
 *  the minute-granularity age label. */
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
    <section aria-label="Live system status" className="bg-card/30 overflow-hidden rounded-2xl border">
      {/* Telemetry-readout header — a sibling instrument to the convergence bench, but kept in the
          system-status register (--ok / --warning), never the cultural/audio/seam retrieval accents,
          so "live" stays visually distinct from the "recorded" replays (the juxtaposition is the point). */}
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b px-4 py-2.5">
        {/* A real h2 (not a styled span) so the live panel — the page's only live surface — appears in
            the heading outline a screen-reader user navigates by, instead of being skipped. */}
        <h2 className="text-foreground inline-flex items-center gap-1.5 font-mono text-[11px] font-semibold tracking-[0.16em] uppercase">
          {/* The genuinely-live surface owns the strongest live cue: a green (--ok) pulsing broadcast
              marker, shown ONLY when the feed is fresh + the API is up. The recorded surfaces' subtler
              --seam pulses never out-rank this (invariant #8 — green/pulse here is correct, it IS live). */}
          {live ? (
            <span className="relative inline-flex size-3.5 items-center justify-center" aria-hidden>
              <span className="bg-ok/40 absolute inline-flex size-full rounded-full motion-safe:animate-ping" />
              <Radio className="text-ok relative size-3.5" />
            </span>
          ) : (
            <Radio
              className={cn(
                "size-3.5",
                stats && stats.api.status === "down" ? "text-destructive" : "text-muted-foreground",
              )}
              aria-hidden
            />
          )}
          Live · the real engine
        </h2>
        <span className="ml-auto font-mono text-[11px] tabular-nums">{feedStamp(feed)}</span>
      </div>

      <div className="p-5">
        <p className="text-muted-foreground mb-4 text-sm">
          The real engine, right now. This part is live, unlike the saved runs everywhere else on the
          site.
        </p>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Tile
          icon={<Activity className="size-4" aria-hidden />}
          label="API"
          // A stale snapshot only knows the API was up AS OF its timestamp — never assert live-up on
          // stale data (the cardinal rule): drop the green tone and qualify with the age. The `sub`
          // scopes the claim honestly: this is an HTTP **liveness** probe (/health is a static 200),
          // not a dependency-aware health check (Redis/worker not verified).
          value={stats ? (stats.api.status === "up" ? "online" : "offline") : "—"}
          sub={stats ? (stale ? `as of ${relativeAge(ok!.ageMs)}` : "responding") : undefined}
          tone={stats ? (stale ? "idle" : stats.api.status === "up" ? "good" : "bad") : "idle"}
        />
        <Tile
          icon={<Database className="size-4" aria-hidden />}
          label="Songs known"
          value={stats ? formatCount(stats.corpus.embeddings) : "—"}
          sub={stats ? "heard so far" : undefined}
        />
        <Tile
          icon={<Activity className="size-4" aria-hidden />}
          label="Searches run"
          value={stats ? formatCount(stats.usage.queries_completed) : "—"}
          sub={stats ? `of ${formatCount(stats.usage.queries_total)} started` : undefined}
        />
        <Tile
          icon={<HardDriveDownload className="size-4" aria-hidden />}
          label="Last backup"
          value={stats?.backup.last_success_at ? backupAge(stats.backup.last_success_at) : "—"}
          // The feed reports the newest LOCAL dump's mtime — written before the optional offsite
          // mirror, so this is "a local pg_dump ran", not "mirrored offsite" (the offsite path is
          // covered by the §9.2 healthchecks check). Don't imply object-store success here.
          sub={stats?.backup.last_success_at ? "saved locally" : undefined}
        />
      </div>

      {/* Phase-4 host vitals — only when the feed carries the optional `host` block (post §9.3 update);
          absent on older feeds or a non-Linux box, so the panel renders fine without this row. */}
      {stats?.host && (
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Tile
            icon={<Clock className="size-4" aria-hidden />}
            label="Uptime"
            value={formatUptime(stats.host.uptime_seconds)}
          />
          <Tile
            icon={<Gauge className="size-4" aria-hidden />}
            label="Load"
            value={stats.host.load_1m.toFixed(2)}
            sub={`${stats.host.load_5m.toFixed(2)} · ${stats.host.load_15m.toFixed(2)} · 5m/15m`}
          />
          <Tile
            icon={<MemoryStick className="size-4" aria-hidden />}
            label="Memory"
            value={`${stats.host.mem_used_pct}%`}
            sub="used"
          />
        </div>
      )}

      {stats && (
        <p className="text-muted-foreground mt-3 font-mono text-[11px]">
          Audio model: <span className="text-foreground">{stats.corpus.model_version}</span>
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

        <p className="text-muted-foreground mt-4 font-mono text-[11px] leading-relaxed">{feedNote(feed)}</p>
      </div>
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
      {sub && <div className="text-muted-foreground text-[11px]">{sub}</div>}
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
      return <span className="text-warning">can’t reach it</span>;
    case "unconfigured":
      return <span className="text-muted-foreground/80">not set up here</span>;
  }
}

function feedNote(feed: FeedState): string {
  switch (feed.kind) {
    case "ok":
      return feed.stale
        ? `Sent from the server every ${STATS_CADENCE_MIN} minutes, but this one is overdue, so the server may be down.`
        : `Sent from the server every ${STATS_CADENCE_MIN} minutes. Just counts, nothing private.`;
    case "loading":
      return "Getting the latest numbers the server sent…";
    case "error":
      return "Couldn't reach the live numbers. The server may be down, or just not reachable from here. The saved runs below are fine either way.";
    case "unconfigured":
      return "The live numbers aren't set up for this build. The saved runs below are the engine's real output either way.";
  }
}
