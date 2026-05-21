"""The matcher quality gate — match-verification edge cases.

BRAINDUMP calls this "the most important quality gate in the entire project":
a bad preview match poisons the corpus invisibly (a karaoke cover embedded under
the studio recording's MBID recommends wrong forever). So this suite is broad and
deliberate, covering feat. artists, remasters, live takes, remixes, covers,
karaoke, acoustic versions, non-English titles, and accented/special characters.

Every expected confidence here was calibrated against the real RapidFuzz scores
(see the module docstring for the formula). The two ``xfail`` cases document a
known residual gap rather than a bug — see ``TestKnownGaps``.
"""
from __future__ import annotations

import pytest

from doppel.matching.verify import (
    DURATION_UNKNOWN_SCORE,
    MATCH_ACCEPT_THRESHOLD,
    MatchReason,
    ProviderTrack,
    SeedRecording,
    score_match,
    verify_match,
)


def seed(title: str, artist: str, duration_ms: int | None = None, isrcs=()) -> SeedRecording:
    return SeedRecording(title, artist, duration_ms, frozenset(isrcs))


def track(title: str, artist: str, duration_ms: int | None = None, isrc: str | None = None) -> ProviderTrack:
    return ProviderTrack(title, artist, duration_ms, isrc)


# --------------------------------------------------------------------------- #
# ISRC — the definitive signal
# --------------------------------------------------------------------------- #

class TestISRC:
    def test_exact_isrc_match_is_total_confidence(self) -> None:
        s = seed("Blinding Lights", "The Weeknd", 200_000, {"USUG11904206"})
        c = track("Blinding Lights", "The Weeknd", 200_000, "USUG11904206")
        r = score_match(s, c)
        assert r.confidence == 1.0
        assert r.accepted
        assert r.reason is MatchReason.ISRC
        assert r.isrc_match

    def test_isrc_match_overrides_implausible_duration(self) -> None:
        # An ISRC names exactly one recording, so it wins even when the duration
        # looks wrong (e.g. provider reporting a clip length).
        s = seed("Take Five", "The Dave Brubeck Quartet", 324_000, {"USSM15900001"})
        c = track("Take Five", "The Dave Brubeck Quartet", 9_000, "USSM15900001")
        assert verify_match(s, c) == 1.0

    def test_isrc_match_is_case_and_hyphen_insensitive(self) -> None:
        s = seed("HUMBLE.", "Kendrick Lamar", 177_000, {"US-UM7-17-00001"})
        c = track("HUMBLE.", "Kendrick Lamar", 177_000, "usum71700001")
        assert score_match(s, c).reason is MatchReason.ISRC

    def test_nonmatching_isrc_does_not_short_circuit(self) -> None:
        # A different ISRC proves nothing (a recording can have several); fall
        # through to the weighted blend instead of penalizing.
        s = seed("One More Time", "Daft Punk", 320_000, {"GBDUW0000059"})
        c = track("One More Time", "Daft Punk", 320_000, "FRZ123456789")
        r = score_match(s, c)
        assert r.reason is MatchReason.WEIGHTED
        assert not r.isrc_match
        assert r.accepted  # title + artist + duration still agree

    def test_candidate_without_isrc_uses_weighted(self) -> None:
        s = seed("One More Time", "Daft Punk", 320_000, {"GBDUW0000059"})
        c = track("One More Time", "Daft Punk", 320_000, None)
        assert score_match(s, c).reason is MatchReason.WEIGHTED


# --------------------------------------------------------------------------- #
# Duration — the curve and the hard reject
# --------------------------------------------------------------------------- #

class TestDurationCurve:
    @pytest.mark.parametrize(
        "delta_s, expected",
        [
            (0, 1.0),
            (3, 1.0),    # boundary: full score up to 3 s
            (6, 0.75),
            (9, 0.5),
            (12, 0.25),
            (15, 0.0),   # boundary: linear bottom — scored, not hard-rejected
        ],
    )
    def test_duration_score_curve(self, delta_s: int, expected: float) -> None:
        s = seed("Song", "Artist", 200_000)
        c = track("Song", "Artist", 200_000 + delta_s * 1000)
        r = score_match(s, c)
        assert r.reason is MatchReason.WEIGHTED
        assert r.duration_score == pytest.approx(expected)
        assert r.duration_delta_ms == delta_s * 1000

    def test_delta_just_past_15s_is_hard_reject(self) -> None:
        s = seed("Song", "Artist", 200_000)
        c = track("Song", "Artist", 215_001)  # 15.001 s over
        r = score_match(s, c)
        assert r.reason is MatchReason.DURATION_HARD_REJECT
        assert r.confidence == 0.0
        assert not r.accepted
        assert r.duration_score is None
        assert r.duration_delta_ms == 15_001

    def test_hard_reject_ignores_perfect_strings(self) -> None:
        # Identical title + artist cannot rescue a recording minutes longer (the
        # live-take / extended-mix case, where the title is identical).
        s = seed("Take Five", "The Dave Brubeck Quartet", 324_000)
        c = track("Take Five", "The Dave Brubeck Quartet", 600_000)
        assert verify_match(s, c) == 0.0


# --------------------------------------------------------------------------- #
# Missing duration — neutral, never a free pass or a hard reject
# --------------------------------------------------------------------------- #

class TestMissingDuration:
    def test_seed_duration_missing_is_neutral(self) -> None:
        r = score_match(seed("Halo", "Beyoncé", None), track("Halo", "Beyoncé", 261_000))
        assert r.duration_score == DURATION_UNKNOWN_SCORE
        assert r.duration_delta_ms is None
        assert r.reason is MatchReason.WEIGHTED

    def test_candidate_duration_missing_is_neutral(self) -> None:
        r = score_match(seed("Halo", "Beyoncé", 261_000), track("Halo", "Beyoncé", None))
        assert r.duration_score == DURATION_UNKNOWN_SCORE

    def test_both_durations_missing_is_neutral(self) -> None:
        r = score_match(seed("Halo", "Beyoncé"), track("Halo", "Beyoncé"))
        assert r.duration_score == DURATION_UNKNOWN_SCORE

    def test_zero_duration_treated_as_missing(self) -> None:
        r = score_match(seed("Halo", "Beyoncé", 0), track("Halo", "Beyoncé", 261_000))
        assert r.duration_score == DURATION_UNKNOWN_SCORE

    def test_perfect_strings_with_unknown_duration_still_accept(self) -> None:
        # 0.5*0.40 + 1.0*0.35 + 1.0*0.25 = 0.80
        s = seed("Halo", "Beyoncé", None)
        c = track("Halo", "Beyoncé", None)
        assert verify_match(s, c) == pytest.approx(0.80)
        assert score_match(s, c).accepted


# --------------------------------------------------------------------------- #
# Same recording, messy metadata — must ACCEPT
# --------------------------------------------------------------------------- #

ACCEPT_CASES = [
    pytest.param(
        seed("Blinding Lights", "The Weeknd", 200_000),
        track("Blinding Lights", "The Weeknd", 200_000),
        id="exact-match",
    ),
    pytest.param(
        seed("One More Time", "Daft Punk", 320_000),
        track("One More Time (feat. Romanthony)", "Daft Punk", 320_000),
        id="feat-in-title",
    ),
    pytest.param(
        seed("One More Time", "Daft Punk", 320_000),
        track("One More Time", "Daft Punk, Romanthony", 320_000),
        id="feat-in-artist-comma",
    ),
    pytest.param(
        seed("One More Time", "Daft Punk", 320_000),
        track("One More Time", "Daft Punk feat. Romanthony", 320_000),
        id="feat-in-artist-word",
    ),
    pytest.param(
        seed("Take Five", "The Dave Brubeck Quartet", 324_000),
        track("Take Five (Remastered 1999)", "The Dave Brubeck Quartet", 325_500),  # +1.5 s
        id="remaster-suffix",
    ),
    pytest.param(
        seed("HUMBLE.", "Kendrick Lamar", 177_000),
        track("HUMBLE", "Kendrick Lamar", 177_000),
        id="punctuation-difference",
    ),
    pytest.param(
        seed("Blinding Lights", "The Weeknd", 200_000),
        track("blinding lights", "the weeknd", 200_000),
        id="case-difference",
    ),
    pytest.param(
        seed("The Less I Know the Better", "Tame Impala", 216_000),
        track("The Less I Know The Better - Edit", "Tame Impala", 216_000),
        id="edit-suffix-and-titlecase",
    ),
    pytest.param(
        seed("Halo", "Beyoncé", 261_000),
        track("Halo", "Beyonce", 261_000),  # accent dropped on the artist
        id="accent-dropped-artist",
    ),
    pytest.param(
        seed("Hoppípolla", "Sigur Rós", 268_000),
        track("Hoppipolla", "Sigur Ros", 268_000),  # accents dropped both sides
        id="accents-dropped-both",
    ),
    pytest.param(
        seed("La Vie en Rose", "Édith Piaf", 200_000),
        track("La Vie En Rose", "Edith Piaf", 200_000),
        id="non-english-accent-and-case",
    ),
    pytest.param(
        seed("Kickstart My Heart", "Mötley Crüe", 280_000),
        track("Kickstart My Heart", "Motley Crue", 280_000),  # umlauts dropped
        id="umlauts-dropped",
    ),
]


class TestAcceptedVariants:
    @pytest.mark.parametrize("s, c", ACCEPT_CASES)
    def test_same_recording_variants_accept(self, s: SeedRecording, c: ProviderTrack) -> None:
        r = score_match(s, c)
        assert r.accepted, f"expected accept, got {r.confidence:.3f} ({r.reason.value})"
        assert r.confidence >= MATCH_ACCEPT_THRESHOLD


# --------------------------------------------------------------------------- #
# Different recording — must REJECT
# --------------------------------------------------------------------------- #

REJECT_CASES = [
    pytest.param(
        seed("Blinding Lights", "The Weeknd", 200_000),
        track("Blinding Lights (Live at the BRIT Awards 2021)", "The Weeknd", 320_000),  # +120 s
        id="live-version-longer",
    ),
    pytest.param(
        seed("One More Time", "Daft Punk", 320_000),
        track("One More Time (Skrillex Remix)", "Daft Punk", 250_000),  # -70 s
        id="remix-different-length",
    ),
    pytest.param(
        seed("Take Five", "The Dave Brubeck Quartet", 324_000),
        track("Take Five (Acoustic)", "The Dave Brubeck Quartet", 285_000),  # -39 s
        id="acoustic-different-length",
    ),
    pytest.param(
        seed("Don't Stop Believin'", "Journey", 250_000),
        track("Don't Stop Believin'", "Glee Cast", 240_000),  # cover, artist differs, -10 s
        id="cover-different-artist",
    ),
    pytest.param(
        seed("Blinding Lights", "The Weeknd", 200_000),
        track("Blinding Lights", "Sing King Karaoke", 212_000),  # karaoke, +12 s
        id="karaoke-near-duration",
    ),
    pytest.param(
        seed("Blinding Lights", "The Weeknd", 200_000),
        track("Bohemian Rhapsody", "Queen", 200_000),  # different song and artist, same duration
        id="different-song-and-artist",
    ),
    pytest.param(
        seed("Blinding Lights", "The Weeknd", 200_000),
        track("Save Your Tears", "The Weeknd", 200_000),  # same artist + duration, different song
        id="different-song-same-artist",
    ),
    pytest.param(
        seed("Blinding Lights", "The Weeknd", 200_000),
        track("Blinding Lights", "Some Other Band", 211_000),  # wrong artist + 11 s
        id="wrong-artist-and-duration",
    ),
]


class TestRejectedVariants:
    @pytest.mark.parametrize("s, c", REJECT_CASES)
    def test_different_recordings_reject(self, s: SeedRecording, c: ProviderTrack) -> None:
        r = score_match(s, c)
        assert not r.accepted, f"expected reject, got {r.confidence:.3f} ({r.reason.value})"
        assert r.confidence < MATCH_ACCEPT_THRESHOLD

    def test_different_song_same_artist_is_rejected_on_title(self) -> None:
        # A same-artist, same-duration *different song* must reject on the title
        # signal alone (duration and artist both score 1.0 here). 0.720 < 0.75.
        s = seed("Blinding Lights", "The Weeknd", 200_000)
        c = track("Save Your Tears", "The Weeknd", 200_000)
        r = score_match(s, c)
        assert r.duration_score == 1.0 and r.artist_score == pytest.approx(1.0)
        assert not r.accepted

    def test_live_take_rejects_on_duration_despite_identical_title(self) -> None:
        s = seed("Blinding Lights", "The Weeknd", 200_000)
        c = track("Blinding Lights (Live at the BRIT Awards 2021)", "The Weeknd", 320_000)
        r = score_match(s, c)
        assert r.title_score == 1.0  # the title alone cannot tell it apart
        assert r.reason is MatchReason.DURATION_HARD_REJECT


# --------------------------------------------------------------------------- #
# Known residual gap — documented, not a bug
# --------------------------------------------------------------------------- #

class TestKnownGaps:
    """A cover/karaoke that shares the seed's *exact* title and duration but
    credits a different artist still clears 0.75: a perfect title (0.35) + duration
    (0.40) already sums to the threshold, and artist's 0.25 weight cannot pull it
    back down. These are marked ``xfail`` (asserting the *desired* reject) so the
    suite documents the gap and flags it as ``xpass`` the moment an artist floor —
    or a mandatory-ISRC-for-low-artist-similarity rule — closes it. See
    SESSION_NOTES.md / DECISIONS.md "artist floor" open question.
    """

    @pytest.mark.xfail(strict=True, reason="same-duration cover clears 0.75; artist weight too low to reject")
    def test_same_duration_cover_should_reject(self) -> None:
        s = seed("Don't Stop Believin'", "Journey", 250_000)
        c = track("Don't Stop Believin'", "Glee Cast", 250_000)  # identical duration
        assert verify_match(s, c) < MATCH_ACCEPT_THRESHOLD

    @pytest.mark.xfail(strict=True, reason="same-duration karaoke clears 0.75; artist weight too low to reject")
    def test_same_duration_karaoke_should_reject(self) -> None:
        s = seed("Blinding Lights", "The Weeknd", 200_000)
        c = track("Blinding Lights", "Karaoke Version", 200_000)  # identical duration
        assert verify_match(s, c) < MATCH_ACCEPT_THRESHOLD


# --------------------------------------------------------------------------- #
# API contract
# --------------------------------------------------------------------------- #

class TestApiContract:
    def test_verify_match_returns_score_match_confidence(self) -> None:
        s = seed("One More Time", "Daft Punk", 320_000)
        c = track("One More Time (feat. Romanthony)", "Daft Punk", 320_000)
        assert verify_match(s, c) == score_match(s, c).confidence

    def test_confidence_always_in_unit_interval(self) -> None:
        s = seed("Song", "Artist", 200_000, {"AAAAA0000001"})
        for c in (
            track("Song", "Artist", 200_000, "AAAAA0000001"),  # isrc
            track("Song", "Artist", 200_000),                  # perfect weighted
            track("Totally Different", "Nobody", 999_000),     # hard reject
            track("Song", "Artist", 207_000),                  # mid-curve
        ):
            assert 0.0 <= verify_match(s, c) <= 1.0

    def test_accepted_flag_tracks_threshold(self) -> None:
        r = score_match(seed("Song", "Artist", 200_000), track("Song", "Artist", 200_000))
        assert r.accepted is (r.confidence >= MATCH_ACCEPT_THRESHOLD)

    def test_isrc_reason_only_on_real_match(self) -> None:
        s = seed("Song", "Artist", 200_000, {"AAAAA0000001"})
        assert score_match(s, track("Song", "Artist", 200_000, "AAAAA0000001")).reason is MatchReason.ISRC
        assert score_match(s, track("Song", "Artist", 200_000, "BBBBB0000002")).reason is MatchReason.WEIGHTED


# --------------------------------------------------------------------------- #
# Robustness — degenerate inputs must not crash
# --------------------------------------------------------------------------- #

class TestRobustness:
    def test_empty_candidate_title_does_not_crash(self) -> None:
        r = score_match(seed("Blinding Lights", "The Weeknd", 200_000), track("", "The Weeknd", 200_000))
        assert not r.accepted  # title contributes ~0

    def test_empty_artist_strings_stay_in_range(self) -> None:
        r = score_match(seed("Blinding Lights", "", 200_000), track("Blinding Lights", "", 200_000))
        assert 0.0 <= r.confidence <= 1.0

    def test_blank_isrc_is_ignored(self) -> None:
        # A whitespace-only / punctuation-only ISRC normalizes to nothing and must
        # not be treated as a match.
        s = seed("Song", "Artist", 200_000, {"   "})
        c = track("Song", "Artist", 200_000, "-")
        assert score_match(s, c).reason is not MatchReason.ISRC
