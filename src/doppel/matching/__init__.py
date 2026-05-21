"""Matcher / resolver — the pipeline's foundation.

Canonicalizes messy upstream strings into recording-level MusicBrainz identities,
fetches Deezer previews for them, and verifies that what Deezer returned is
actually the *same recording* (not a cover, karaoke, live take, remix, or
remaster). `verify.py` holds the verification logic and its data model.
"""
