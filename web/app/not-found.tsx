import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col items-start gap-4 px-5 py-24">
      <p className="text-muted-foreground font-mono text-sm">404</p>
      <h1 className="text-3xl font-bold tracking-tight">Seed not found</h1>
      <p className="text-muted-foreground max-w-md">
        That recommendation isn&rsquo;t in the curated showcase set.
      </p>
      <Link
        href="/"
        className="text-audio hover:text-audio/80 text-sm font-medium transition-colors"
      >
        ← Back to the seed gallery
      </Link>
    </div>
  );
}
