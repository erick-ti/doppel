/**
 * Timestamp formatting in the VIEWER's timezone (client-safe — no server-only imports).
 *
 * The rest of the app's stamps were deterministic UTC slices to keep the static export hydration-safe.
 * To show each visitor their own local time we format with an explicit IANA `timeZone`: on the server
 * and the first client render we use the FALLBACK zone (deterministic — same string both sides, so no
 * hydration mismatch), then <LocalStamp> swaps to the browser's resolved zone after mount. The
 * timeZoneName is always shown so the zone is never ambiguous (e.g. "2026-06-12 PDT").
 */

/** Used on SSR + the first client render, and whenever the browser can't resolve its own zone. */
export const FALLBACK_TZ = "America/Los_Angeles";

export type StampMode = "date" | "datetime";

function partsIn(iso: string, tz: string, withTime: boolean): Record<string, string> | null {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const opts: Intl.DateTimeFormatOptions = {
    timeZone: tz,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZoneName: "short",
    ...(withTime ? { hour: "2-digit", minute: "2-digit", hour12: false } : {}),
  };
  const out: Record<string, string> = {};
  for (const p of new Intl.DateTimeFormat("en-CA", opts).formatToParts(d)) out[p.type] = p.value;
  return out;
}

/**
 * Format an ISO instant in `tz`. "date" → "YYYY-MM-DD TZ"; "datetime" → "YYYY-MM-DD HH:mm TZ".
 * A 24-hour clock and ISO-ordered date keep it culture-neutral and matched to the mono telemetry
 * voice. Falls back to the raw date slice if the ISO can't be parsed (never throws mid-render).
 */
export function formatStamp(iso: string, tz: string, mode: StampMode): string {
  const p = partsIn(iso, tz, mode === "datetime");
  if (!p) return iso.slice(0, 10);
  const date = `${p.year}-${p.month}-${p.day}`;
  const zone = p.timeZoneName ?? "";
  if (mode === "date") return `${date} ${zone}`.trim();
  return `${date} ${p.hour}:${p.minute} ${zone}`.trim();
}
