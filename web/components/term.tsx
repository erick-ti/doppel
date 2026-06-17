"use client";

import { useEffect, useId, useRef, useState } from "react";

import { GLOSSARY } from "@/lib/glossary";
import { cn } from "@/lib/utils";

/**
 * A word with a plain-language definition that pops up on hover, tap, or keyboard focus. The trigger
 * is a real <button>, so it works for mouse, touch, and screen-reader/keyboard users alike (hover for
 * pointers, tap to toggle, Enter/Space + Escape for the keyboard). Pass `name` to pull a shared
 * definition from the glossary, or `define` to write one inline.
 */
export function Term({
  children,
  name,
  define,
  className,
}: {
  children: React.ReactNode;
  name?: keyof typeof GLOSSARY | string;
  define?: React.ReactNode;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const wrapRef = useRef<HTMLSpanElement>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const body = define ?? (name ? GLOSSARY[name] : null);

  const show = () => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
    setOpen(true);
  };
  // A brief delay before closing so a pointer can travel from the word into the popover without it
  // vanishing (both live inside the wrapper, so this mostly covers sub-pixel exits).
  const scheduleClose = () => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
    closeTimer.current = setTimeout(() => setOpen(false), 90);
  };

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    const onPointerDown = (e: PointerEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointerDown);
    };
  }, [open]);

  if (!body) return <>{children}</>;

  return (
    <span ref={wrapRef} className="relative inline-block" onMouseEnter={show} onMouseLeave={scheduleClose}>
      <button
        type="button"
        aria-describedby={open ? id : undefined}
        // Open on tap/click (not toggle): on touch, focus fires first and a toggle would immediately
        // close it. Close happens via Escape, blur, or an outside pointerdown.
        onClick={() => setOpen(true)}
        onFocus={show}
        onBlur={scheduleClose}
        className={cn(
          "decoration-seam/50 hover:decoration-seam cursor-help rounded-sm underline decoration-dotted underline-offset-[3px] outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
          className,
        )}
      >
        {children}
      </button>
      {open && (
        <span
          id={id}
          role="tooltip"
          className="bg-popover text-foreground absolute top-full left-1/2 z-50 mt-2 w-[min(18rem,calc(100vw-2rem))] -translate-x-1/2 rounded-lg border p-3 text-left font-sans text-sm leading-snug font-normal normal-case shadow-lg tracking-normal motion-safe:animate-in motion-safe:fade-in-0 motion-safe:zoom-in-95 motion-safe:duration-150"
        >
          {body}
        </span>
      )}
    </span>
  );
}
