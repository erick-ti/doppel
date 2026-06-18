"use client";

import { useSyncExternalStore } from "react";

import { FALLBACK_TZ, formatStamp, type StampMode } from "@/lib/datetime";

// The visitor's timezone is a client/server-divergent value, so useSyncExternalStore is the
// hydration-safe primitive for it (no setState-in-effect): the SERVER snapshot and the first hydration
// render both use the deterministic fallback zone — identical strings, so hydration matches — then
// React swaps to the CLIENT snapshot (the browser's resolved zone). The TZ never changes during a
// session, so `subscribe` is a no-op.
const subscribe = () => () => {};

function clientTz(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || FALLBACK_TZ;
  } catch {
    return FALLBACK_TZ;
  }
}

const serverTz = () => FALLBACK_TZ;

/**
 * A recorded timestamp shown in the VISITOR's local timezone, falling back to PST/PDT
 * (America/Los_Angeles). The <time dateTime> keeps the machine-readable ISO regardless of display.
 */
export function LocalStamp({ iso, mode = "date" }: { iso: string; mode?: StampMode }) {
  const tz = useSyncExternalStore(subscribe, clientTz, serverTz);
  return (
    <time dateTime={iso} suppressHydrationWarning>
      {formatStamp(iso, tz, mode)}
    </time>
  );
}
