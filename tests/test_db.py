"""Offline db-layer tests — no Postgres required (these run on the CI merge gate).

Covers the migration runner's pure decision core (discovery, ordering, checksum drift), the
re-embedding threshold, and the resolver→rows persistence *mapping* via a recording fake
connection. The live round-trips against real Postgres live in ``test_db_integration.py``.
"""
from __future__ import annotations

import uuid

import pytest

from doppel.aggregation.candidates import normalize_text
from doppel.config import RESOLVER_VERSION
from doppel.db import migrate, repository as repo
from doppel.matching.resolver import ResolvedMatch, ResolveStatus
from doppel.matching.verify import MatchReason, MatchScore, ProviderTrack, SeedRecording


# --- migration runner (pure pieces) ------------------------------------------ #


def test_discover_returns_initial_migration():
    discovered = migrate._discover()
    versions = [v for v, _, _ in discovered]
    assert versions == sorted(versions)          # filename order
    assert "0001_initial_schema" in versions
    sql = next(s for v, s, _ in discovered if v == "0001_initial_schema")
    assert "CREATE TABLE tracks" in sql and "vector(512)" in sql


def test_plan_applies_all_when_none_applied():
    discovered = [("0001_a", "sql-a", "sum-a"), ("0002_b", "sql-b", "sum-b")]
    assert migrate._plan({}, discovered) == discovered


def test_plan_skips_already_applied_with_matching_checksum():
    discovered = [("0001_a", "sql-a", "sum-a"), ("0002_b", "sql-b", "sum-b")]
    pending = migrate._plan({"0001_a": "sum-a"}, discovered)
    assert pending == [("0002_b", "sql-b", "sum-b")]


def test_plan_raises_on_checksum_drift():
    discovered = [("0001_a", "sql-a-EDITED", "sum-NEW")]
    with pytest.raises(migrate.MigrationError, match="modified after being applied"):
        migrate._plan({"0001_a": "sum-OLD"}, discovered)


def test_plan_raises_when_applied_migration_missing_from_disk():
    # symmetric to the checksum guard: an applied version absent from disk is undetected drift
    discovered = [("0001_a", "sql-a", "sum-a")]
    with pytest.raises(migrate.MigrationError, match="missing from"):
        migrate._plan({"0001_a": "sum-a", "0002_gone": "sum-gone"}, discovered)


# --- re-embedding threshold -------------------------------------------------- #


@pytest.mark.parametrize(
    "existing, new, expected",
    [
        (0.5, 0.65, True),    # exactly the 0.15 delta
        (0.5, 0.649, False),  # just under
        (0.5, 0.9, True),
        (1.0, 1.0, False),    # equal — no refresh
        (0.8, 0.7, False),    # worse — never refresh
    ],
)
def test_needs_reembed(existing, new, expected):
    assert repo.needs_reembed(existing, new) is expected


# --- persist_resolved_match mapping (recording fake connection) -------------- #


class _FakeTx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeConn:
    """Records issued statements so we can assert which tables a persist writes to."""

    def __init__(self):
        self.calls: list[tuple[str, str, tuple]] = []

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        return {"id": 7}  # audio_assets RETURNING id

    def transaction(self):
        return _FakeTx()

    def tables_written(self) -> set[str]:
        return {
            t
            for _, sql, _ in self.calls
            for t in ("tracks", "audio_assets", "canonical_lookups")
            if f"INTO {t}" in sql
        }


def _seed():
    return SeedRecording("HUMBLE.", "Kendrick Lamar", duration_ms=177000,
                         isrcs=frozenset({"USUM71703086"}), mbid=str(uuid.uuid4()))


def _candidate():
    return ProviderTrack("HUMBLE.", "Kendrick Lamar", provider_track_duration_ms=177000,
                         isrc="USUM71703086", preview_url="https://cdnt-preview.dzcdn.net/x.mp3",
                         provider_track_id=123456)


async def test_persist_found_writes_all_three_tables():
    conn = FakeConn()
    match = MatchScore(1.0, True, MatchReason.ISRC, 1.0, 1.0, None, 0, isrc_match=True)
    resolved = ResolvedMatch(ResolveStatus.FOUND, _seed(), _candidate(), match)
    asset_id = await repo.persist_resolved_match(conn, "humble", "kendrick lamar", resolved)
    assert asset_id == 7
    assert conn.tables_written() == {"tracks", "audio_assets", "canonical_lookups"}


async def test_persist_rejected_writes_all_three_tables_but_withholds_asset_id():
    conn = FakeConn()
    seed = _seed()
    match = MatchScore(0.40, False, MatchReason.WEIGHTED, 0.5, 0.3, 0.5, 9000, isrc_match=False)
    resolved = ResolvedMatch(ResolveStatus.REJECTED, seed, _candidate(), match)
    asset_id = await repo.persist_resolved_match(conn, "humble", "kendrick lamar", resolved)
    assert asset_id is None  # REJECTED asset is persisted as evidence, but not returned as embeddable
    assert conn.tables_written() == {"tracks", "audio_assets", "canonical_lookups"}
    # the lookup still carries the canonicalized mbid even though verification failed
    lookup_call = next(c for c in conn.calls if "INTO canonical_lookups" in c[1])
    assert uuid.UUID(seed.mbid) in lookup_call[2]


async def test_persist_not_found_writes_only_the_lookup():
    conn = FakeConn()
    resolved = ResolvedMatch(ResolveStatus.NOT_FOUND, None, None, None,
                             "no relevant provider track with a preview")
    asset_id = await repo.persist_resolved_match(conn, "obscure title", "obscure artist", resolved)
    assert asset_id is None
    assert conn.tables_written() == {"canonical_lookups"}


async def test_upsert_canonical_lookup_uses_shared_normalization():
    conn = FakeConn()
    await repo.upsert_canonical_lookup(
        conn, query_title="HUMBLE.", query_artist="Kendrick Lamar",
        status=ResolveStatus.NOT_FOUND, mbid=None, match_confidence=None,
    )
    _, _, args = conn.calls[0]
    # first two args are normalized via the SAME function the aggregator dedupes by
    assert args[0] == normalize_text("HUMBLE.") and args[1] == normalize_text("Kendrick Lamar")
    assert RESOLVER_VERSION in args  # the row is version-stamped
