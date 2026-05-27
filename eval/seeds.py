"""Benchmark seeds for the Day-7 evaluation.

Grouped by the genres BRAINDUMP flags as the Deezer-coverage risk surface (the project's #1 risk):
pop, R&B, hip-hop, indie rock, electronic, jazz, pre-2000 classics, non-English. ``PILOT_SEEDS`` is
the small set the harness is validated on first; ``FULL_SEEDS`` is the later multi-hour benchmark.
A ``vibe`` exercises the CLAP text leg (the weak encoder BRAINDUMP calls out).

Seeds are editable — recall and Deezer coverage hinge on the exact ``(title, artist)`` credit, so
swap any that resolve poorly (the harness reports per-seed coverage so a bad credit is visible).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Seed:
    title: str
    artist: str
    genre: str
    vibe: str | None = None

    @property
    def label(self) -> str:
        base = f"{self.title} — {self.artist}"
        return f"{base} [vibe: {self.vibe}]" if self.vibe else base


# Small set to validate the harness + get a first signal (run at a reduced RESOLVE_CANDIDATE_LIMIT).
PILOT_SEEDS: list[Seed] = [
    Seed("Take Five", "The Dave Brubeck Quartet", "jazz"),
    Seed("HUMBLE.", "Kendrick Lamar", "hip-hop"),
    Seed("Midnight City", "M83", "electronic"),
    Seed("Midnight City", "M83", "electronic", vibe="melancholic, late-night driving"),
    Seed("good 4 u", "Olivia Rodrigo", "pop"),
]

# Full benchmark — ~2 seeds per coverage genre + three vibe-text seeds. Multi-hour cold.
FULL_SEEDS: list[Seed] = [
    Seed("Blinding Lights", "The Weeknd", "pop"),
    Seed("good 4 u", "Olivia Rodrigo", "pop"),
    Seed("Pink + White", "Frank Ocean", "r&b"),
    Seed("Cranes in the Sky", "Solange", "r&b"),
    Seed("HUMBLE.", "Kendrick Lamar", "hip-hop"),
    Seed("Passionfruit", "Drake", "hip-hop"),
    Seed("The Less I Know the Better", "Tame Impala", "indie"),
    Seed("Two Weeks", "Grizzly Bear", "indie"),
    Seed("Midnight City", "M83", "electronic"),
    Seed("Strobe", "deadmau5", "electronic"),
    Seed("Take Five", "The Dave Brubeck Quartet", "jazz"),
    Seed("So What", "Miles Davis", "jazz"),
    Seed("Bohemian Rhapsody", "Queen", "pre-2000"),
    Seed("Dreams", "Fleetwood Mac", "pre-2000"),
    Seed("Despacito", "Luis Fonsi", "non-english"),
    Seed("La Vie en rose", "Édith Piaf", "non-english"),
    Seed("Midnight City", "M83", "electronic", vibe="melancholic, late-night driving"),
    Seed("HUMBLE.", "Kendrick Lamar", "hip-hop", vibe="stripped back, acoustic, intimate"),
    Seed("Take Five", "The Dave Brubeck Quartet", "jazz", vibe="rainy day, contemplative"),
]

SEED_SETS = {"pilot": PILOT_SEEDS, "full": FULL_SEEDS}
