import { Clapperboard, Film } from "lucide-react";

import { DEEP_DIVE_VIDEO } from "@/lib/deep-dive";

/**
 * The deep-dive video surface. Two states, switched by `DEEP_DIVE_VIDEO`:
 *
 *  - null (today)  → an honest placeholder. The v1.2 replay console superseded the screencast as the
 *    "it actually runs" proof (DECISIONS.md 2026-06-12); a recording remains an optional companion,
 *    and this slot + the one-line swap stay available if one is ever made.
 *  - set (later)   → the actual embed (YouTube iframe or a self-hosted <video>), poster + click-to-play,
 *    never autoplay. Setting the constant is the only change needed to ship it.
 *
 * Server component — no client JS in either state (native <video controls> / a plain iframe).
 */
export function VideoSlot() {
  const video = DEEP_DIVE_VIDEO;

  if (!video) {
    return (
      <div className="bg-card/40 flex aspect-video w-full flex-col items-center justify-center gap-3 rounded-xl border border-dashed p-6 text-center">
        <Clapperboard className="text-muted-foreground size-8" aria-hidden />
        <p className="text-sm font-medium">Screencast — optional companion</p>
        <p className="text-muted-foreground max-w-md text-xs leading-relaxed">
          The interactive replay console now carries the cold-run story from recorded telemetry; a
          screencast remains an optional add and would slot in here unchanged. The act-by-act
          walkthrough below describes the live run in prose.
        </p>
      </div>
    );
  }

  return (
    <div className="bg-card overflow-hidden rounded-xl border">
      {video.provider === "youtube" ? (
        <iframe
          className="aspect-video w-full"
          src={`https://www.youtube-nocookie.com/embed/${video.src}`}
          title="Doppel deep-dive screencast"
          loading="lazy"
          allow="accelerometer; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
          allowFullScreen
        />
      ) : (
        // When recording the mp4: add a <track kind="captions" srcLang="en" src=...> (and an
        // aria-label if the surrounding text isn't enough) — captions can only be authored once the
        // screencast exists, so they're part of the same one-line-swap step, not shippable now.
        <video
          className="aspect-video w-full"
          controls
          preload="none"
          poster={video.poster}
        >
          <source src={video.src} type="video/mp4" />
          Your browser doesn&rsquo;t support embedded video — the file is at{" "}
          <a href={video.src}>{video.src}</a>.
        </video>
      )}
      {video.duration && (
        <div className="text-muted-foreground flex items-center gap-1.5 border-t px-4 py-2 font-mono text-xs">
          <Film className="size-3.5" aria-hidden />
          {video.duration} · driven against the real backend over an SSH tunnel
        </div>
      )}
    </div>
  );
}
