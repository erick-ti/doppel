"""Candidate aggregation — fan out to cultural sources, dedupe, and rank.

Pulls similar-track candidates from the cultural sources (Last.fm, ListenBrainz),
conservatively dedupes them across sources (preserving recording variants — never
collapsing "live"/"remaster"/"remix" into the base title), and ranks the survivors
with Reciprocal Rank Fusion so cross-source consensus rises to the top. The ranked
candidates feed the matcher's ``resolve(title, artist)``.

``candidates`` holds the shared :class:`~doppel.aggregation.candidates.Candidate`
model every source emits; the dedupe / RRF / orchestration modules land here per
the Day 3 milestone.
"""
