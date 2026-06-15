import type { Metadata } from "next";
import { Space_Grotesk, IBM_Plex_Mono, Inter, Fraunces } from "next/font/google";
import { Analytics } from "@vercel/analytics/next";
import { SpeedInsights } from "@vercel/speed-insights/next";

import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import "./globals.css";

/*
 * The authored type system (replaces the create-next-app default Geist + Geist Mono):
 *   display (Space Grotesk) -> the engine's voice: headings, instrument labels, the masthead.
 *   mono    (IBM Plex Mono) -> the readout: every measured number, stamp, counter, clock.
 *   sans    (Inter)         -> the human explanation: long-form prose + captions.
 *   serif   (Fraunces ital) -> used EXACTLY ONCE — the masthead word "feeling" — the lone warm,
 *                              hand-set gesture against the cold telemetry (the hybrid tension).
 */
const display = Space_Grotesk({
  variable: "--font-space-grotesk",
  subsets: ["latin"],
  weight: ["500", "600", "700"],
});

const mono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

const sans = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

const serif = Fraunces({
  variable: "--font-fraunces",
  subsets: ["latin"],
  weight: ["400", "500"],
  style: ["italic"],
});

export const metadata: Metadata = {
  title: {
    default: "Doppel — vibe-matched song recommendations",
    template: "%s — Doppel",
  },
  description:
    "Find songs that sound like the one you love — a hybrid retrieve-then-rerank engine combining cultural recall, perceptual CLAP audio scoring, and grounded LLM rationales. A static showcase of real, frozen pipeline output.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`dark ${sans.variable} ${mono.variable} ${display.variable} ${serif.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col">
        <SiteHeader />
        <main className="flex-1">{children}</main>
        <SiteFooter />
        {/* Vercel Web Analytics + Speed Insights — privacy-friendly, no-op off Vercel. */}
        <Analytics />
        <SpeedInsights />
      </body>
    </html>
  );
}
