"""External candidate/preview source adapters.

Each adapter wraps one upstream service behind a small async interface and keeps
its quirks (rate limits, query shapes, response parsing) local. ``deezer`` finds
a track + preview + ISRC; ``musicbrainz`` canonicalizes to a recording-level MBID.
"""
