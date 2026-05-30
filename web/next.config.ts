import type { NextConfig } from "next";

/**
 * Fully static showcase: `output: "export"` emits a pure static `out/` with NO server runtime.
 * This is the architecture (DECISIONS.md 2026-05-29 — static-precompute): the site serves the
 * frozen `public/seeds/*.json` only, never touches the live backend, and can be hosted anywhere.
 * `images.unoptimized` keeps a future `next/image` compatible with static export.
 */
const nextConfig: NextConfig = {
  output: "export",
  images: { unoptimized: true },
};

export default nextConfig;
