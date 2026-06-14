import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="border-border/60 mt-20 border-t">
      <div className="text-muted-foreground mx-auto w-full max-w-6xl px-5 py-8 text-xs leading-relaxed">
        <p className="max-w-3xl">
          The recommendations shown are serializations of <strong>real</strong>{" "}
          pipeline output — derived CLAP audio scores, Deezer track-page links,
          and LLM rationales. No audio is persisted or served here; the live
          embedding pipeline is never invoked from this site. Each result page
          is a frozen snapshot stamped with the exact pipeline state that
          produced it.
        </p>
        <p className="mt-3 font-mono">
          Doppel — hybrid retrieve-then-rerank · cultural recall + CLAP audio
          rerank + LLM rationale.
        </p>
        <p className="mt-3">
          <Link
            href="/status"
            className="hover:text-foreground underline-offset-4 transition-colors hover:underline"
          >
            System status
          </Link>
        </p>
      </div>
    </footer>
  );
}
