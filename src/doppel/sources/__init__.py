"""External candidate/preview source adapters.

Each adapter wraps one upstream service behind a small async interface and keeps its
quirks (rate limits, query shapes, response parsing) local, emitting a typed
dataclass rather than raw JSON. ``deezer`` finds a track + preview + ISRC and
``musicbrainz`` canonicalizes to a recording-level MBID (the matcher's two halves);
``listenbrainz`` and ``lastfm`` surface cultural similar-track candidates that feed
the aggregator.
"""
