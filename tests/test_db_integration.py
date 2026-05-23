"""Live db tests against real Postgres + pgvector (gated by ``--run-db``).

Each test runs inside a transaction that is rolled back, on freshly truncated tables, so they
neither pollute each other nor depend on the surrounding database state. Bring up the DB with
``docker compose up -d`` (or point ``DATABASE_URL`` at any Postgres with the pgvector extension).
"""
from __future__ import annotations

import uuid

import asyncpg
import numpy as np
import pytest

from doppel.config import CLAP_MODEL_VERSION, DATABASE_URL, RESOLVER_VERSION
from doppel.db import migrate, repository as repo
from doppel.db.pool import create_pool
from doppel.matching.resolver import ResolvedMatch, ResolveStatus
from doppel.matching.verify import MatchReason, MatchScore, ProviderTrack, SeedRecording

pytestmark = pytest.mark.db

_DATA_TABLES = "tracks, audio_assets, canonical_lookups, embeddings, query_logs"


@pytest.fixture
async def conn():
    """A migrated connection inside a rolled-back transaction over freshly truncated tables."""
    # Migrate via a RAW connection FIRST: create_pool registers the pgvector codec, which raises
    # `unknown type: public.vector` on a fresh DB where the extension hasn't been created yet. The
    # migration (raw asyncpg, no codec) creates it, so the pool can then register the type. Mirrors
    # the deploy ordering — migrate as an explicit step before anything opens the app pool.
    raw = await asyncpg.connect(DATABASE_URL)
    try:
        await migrate.up(raw)
    finally:
        await raw.close()
    pool = await create_pool(DATABASE_URL)
    try:
        async with pool.acquire() as c:
            tx = c.transaction()
            await tx.start()
            try:
                await c.execute(f"TRUNCATE {_DATA_TABLES} RESTART IDENTITY CASCADE")
                yield c
            finally:
                await tx.rollback()
    finally:
        await pool.close()


@pytest.fixture
async def fresh_db_dsn():
    """A throwaway database with no extension/schema, for cold-start ordering tests; dropped after."""
    name = f"doppel_coldstart_{uuid.uuid4().hex[:8]}"
    admin = await asyncpg.connect(DATABASE_URL)
    await admin.execute(f'CREATE DATABASE "{name}"')
    await admin.close()
    base = DATABASE_URL.rpartition("/")[0]
    try:
        yield f"{base}/{name}"
    finally:
        admin = await asyncpg.connect(DATABASE_URL)
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()


def _found(mbid: str) -> ResolvedMatch:
    seed = SeedRecording("HUMBLE.", "Kendrick Lamar", 177000, frozenset({"USUM71703086"}), mbid)
    cand = ProviderTrack("HUMBLE.", "Kendrick Lamar", 177000, "USUM71703086",
                         "https://cdnt-preview.dzcdn.net/x.mp3", 123456)
    match = MatchScore(1.0, True, MatchReason.ISRC, 1.0, 1.0, None, 0, isrc_match=True)
    return ResolvedMatch(ResolveStatus.FOUND, seed, cand, match)


async def _insert_track(conn) -> uuid.UUID:
    mbid = uuid.uuid4()
    await conn.execute("INSERT INTO tracks (mbid, title, artist) VALUES ($1, 'T', 'A')", mbid)
    return mbid


async def test_persist_found_round_trip(conn):
    mbid = str(uuid.uuid4())
    asset_id = await repo.persist_resolved_match(conn, "humble", "kendrick lamar", _found(mbid))
    assert asset_id is not None
    track = await conn.fetchrow("SELECT * FROM tracks WHERE mbid = $1", uuid.UUID(mbid))
    assert track["title"] == "HUMBLE." and track["isrcs"] == ["USUM71703086"]
    asset = await conn.fetchrow("SELECT * FROM audio_assets WHERE id = $1", asset_id)
    assert asset["asset_status"] == "found" and asset["preview_url"]
    look = await repo.get_canonical_lookup(conn, "HUMBLE.", "Kendrick Lamar")
    assert look["status"] == "found" and str(look["mbid"]) == mbid


async def test_persist_rejected_keeps_mbid(conn):
    mbid = str(uuid.uuid4())
    seed = SeedRecording("Song", "Artist", 200000, frozenset(), mbid)
    cand = ProviderTrack("Song", "Artist", 240000, None, "https://cdnt-preview.dzcdn.net/y.mp3", 999)
    match = MatchScore(0.40, False, MatchReason.WEIGHTED, 0.5, 0.3, 0.0, 40000, isrc_match=False)
    resolved = ResolvedMatch(ResolveStatus.REJECTED, seed, cand, match)
    asset_id = await repo.persist_resolved_match(conn, "song", "artist", resolved)
    assert asset_id is None  # rejected asset is evidence, not embeddable
    asset = await conn.fetchrow("SELECT * FROM audio_assets WHERE mbid = $1", uuid.UUID(mbid))
    assert asset["asset_status"] == "rejected"
    look = await repo.get_canonical_lookup(conn, "Song", "Artist")
    assert look["status"] == "rejected" and str(look["mbid"]) == mbid  # REJECTED carries an mbid


async def test_persist_not_found_writes_only_lookup(conn):
    resolved = ResolvedMatch(ResolveStatus.NOT_FOUND, None, None, None, "no track")
    asset_id = await repo.persist_resolved_match(conn, "ghost title", "nobody", resolved)
    assert asset_id is None
    look = await repo.get_canonical_lookup(conn, "ghost title", "nobody")
    assert look["status"] == "not_found" and look["mbid"] is None
    assert await conn.fetchval("SELECT count(*) FROM tracks") == 0
    assert await conn.fetchval("SELECT count(*) FROM audio_assets") == 0


async def test_get_canonical_lookup_misses_on_stale_resolver_version(conn):
    # a row written by an OLD resolver version reads as a MISS (so the candidate re-resolves), and a
    # fresh resolve overwrites it on the unique key — self-healing with no caller-side version check.
    await conn.execute(
        "INSERT INTO canonical_lookups "
        "(norm_title, norm_artist, query_title, query_artist, status, mbid, resolver_version) "
        "VALUES ('humble', 'kendrick lamar', 'HUMBLE.', 'Kendrick Lamar', 'not_found', NULL, 'v0-OLD')"
    )
    assert await repo.get_canonical_lookup(conn, "HUMBLE.", "Kendrick Lamar") is None
    await repo.upsert_canonical_lookup(conn, query_title="HUMBLE.", query_artist="Kendrick Lamar",
                                       status=ResolveStatus.NOT_FOUND, mbid=None, match_confidence=None)
    row = await repo.get_canonical_lookup(conn, "HUMBLE.", "Kendrick Lamar")
    assert row is not None and row["resolver_version"] == RESOLVER_VERSION


async def test_embedding_round_trip_and_knn(conn):
    mbid = str(uuid.uuid4())
    asset_id = await repo.persist_resolved_match(conn, "humble", "kendrick lamar", _found(mbid))
    vec = np.random.default_rng(0).random(512).astype("float32")
    vec /= np.linalg.norm(vec)
    await repo.upsert_embedding(conn, mbid=mbid, model_version=CLAP_MODEL_VERSION,
                                embedding=vec, source_confidence=1.0, asset_id=asset_id)
    emb = await repo.get_embedding(conn, mbid, CLAP_MODEL_VERSION)
    assert len(emb["embedding"]) == 512
    fetched = await repo.fetch_embeddings(conn, [mbid], CLAP_MODEL_VERSION)
    assert len(fetched) == 1 and str(fetched[0]["mbid"]) == mbid
    nearest = await repo.knn(conn, vec, 5, model_version=CLAP_MODEL_VERSION)
    assert str(nearest[0]["mbid"]) == mbid
    assert float(nearest[0]["distance"]) == pytest.approx(0.0, abs=1e-6)  # cosine to self


async def test_reembed_refresh_updates_in_place(conn):
    mbid = str(uuid.uuid4())
    asset_id = await repo.persist_resolved_match(conn, "humble", "kendrick lamar", _found(mbid))
    v1 = np.zeros(512, dtype="float32"); v1[0] = 1.0
    v2 = np.zeros(512, dtype="float32"); v2[1] = 1.0
    await repo.upsert_embedding(conn, mbid=mbid, model_version=CLAP_MODEL_VERSION,
                                embedding=v1, source_confidence=0.80, asset_id=asset_id)
    await repo.upsert_embedding(conn, mbid=mbid, model_version=CLAP_MODEL_VERSION,
                                embedding=v2, source_confidence=0.97, asset_id=asset_id)
    rows = await conn.fetch("SELECT * FROM embeddings WHERE mbid = $1", uuid.UUID(mbid))
    assert len(rows) == 1  # refreshed in place (re-embed path), not duplicated
    assert rows[0]["source_confidence"] == pytest.approx(0.97)
    assert float(rows[0]["embedding"][1]) == pytest.approx(1.0)  # the v2 vector is stored


async def test_composite_fk_blocks_cross_mbid_embedding(conn):
    # Schema-level backstop (independent of the repository's found-only guard): an embedding row
    # may not reference an asset belonging to a different MBID. Insert raw to exercise the FK.
    mbid_a, mbid_b = str(uuid.uuid4()), str(uuid.uuid4())
    asset_id = await repo.persist_resolved_match(conn, "a", "a", _found(mbid_a))
    await conn.execute("INSERT INTO tracks (mbid, title, artist) VALUES ($1, 'B', 'B')", uuid.UUID(mbid_b))
    vec = np.zeros(512, dtype="float32"); vec[0] = 1.0
    with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
        await conn.execute(
            "INSERT INTO embeddings (mbid, model_version, embedding, source_confidence, asset_id) "
            "VALUES ($1, $2, $3, $4, $5)",
            uuid.UUID(mbid_b), CLAP_MODEL_VERSION, vec, 0.9, asset_id,
        )


async def test_upsert_embedding_refuses_non_found_asset(conn):
    # found-only guard: a REJECTED asset's preview must never be embedded under the canonical MBID
    mbid = str(uuid.uuid4())
    seed = SeedRecording("Song", "Artist", 200000, frozenset(), mbid)
    cand = ProviderTrack("Song", "Artist", 240000, None, "https://cdnt-preview.dzcdn.net/z.mp3", 7)
    match = MatchScore(0.40, False, MatchReason.WEIGHTED, 0.5, 0.3, 0.0, 40000, isrc_match=False)
    await repo.persist_resolved_match(conn, "song", "artist",
                                      ResolvedMatch(ResolveStatus.REJECTED, seed, cand, match))
    rejected_id = await conn.fetchval(
        "SELECT id FROM audio_assets WHERE mbid = $1 AND asset_status = 'rejected'", uuid.UUID(mbid)
    )
    vec = np.zeros(512, dtype="float32"); vec[0] = 1.0
    with pytest.raises(ValueError, match="found"):
        await repo.upsert_embedding(conn, mbid=mbid, model_version=CLAP_MODEL_VERSION,
                                    embedding=vec, source_confidence=0.9, asset_id=rejected_id)


async def test_upsert_embedding_refuses_downgrade(conn):
    # no-downgrade guard: a late lower-confidence write must not overwrite a better cached vector
    mbid = str(uuid.uuid4())
    asset_id = await repo.persist_resolved_match(conn, "humble", "kendrick lamar", _found(mbid))
    hi = np.zeros(512, dtype="float32"); hi[0] = 1.0
    lo = np.zeros(512, dtype="float32"); lo[1] = 1.0
    assert await repo.upsert_embedding(conn, mbid=mbid, model_version=CLAP_MODEL_VERSION,
                                       embedding=hi, source_confidence=0.95, asset_id=asset_id) is True
    assert await repo.upsert_embedding(conn, mbid=mbid, model_version=CLAP_MODEL_VERSION,
                                       embedding=lo, source_confidence=0.80, asset_id=asset_id) is False
    row = await conn.fetchrow("SELECT * FROM embeddings WHERE mbid = $1", uuid.UUID(mbid))
    assert row["source_confidence"] == pytest.approx(0.95)   # the better vector was kept
    assert float(row["embedding"][0]) == pytest.approx(1.0)
    # an equal-or-higher write still goes through (idempotent rewrite / genuine upgrade)
    assert await repo.upsert_embedding(conn, mbid=mbid, model_version=CLAP_MODEL_VERSION,
                                       embedding=lo, source_confidence=0.95, asset_id=asset_id) is True


async def test_embedding_purged_when_asset_reclassified_rejected(conn):
    # write-side: a re-resolve that flips a previously-FOUND+embedded asset to REJECTED must purge
    # the now-untrusted vector in the same transaction (the same provider asset is re-persisted).
    mbid = str(uuid.uuid4())
    seed = SeedRecording("HUMBLE.", "Kendrick Lamar", 177000, frozenset({"USUM71703086"}), mbid)
    cand = ProviderTrack("HUMBLE.", "Kendrick Lamar", 177000, "USUM71703086",
                         "https://cdnt-preview.dzcdn.net/x.mp3", 555001)
    found = MatchScore(1.0, True, MatchReason.ISRC, 1.0, 1.0, None, 0, isrc_match=True)
    asset_id = await repo.persist_resolved_match(
        conn, "humble", "kendrick", ResolvedMatch(ResolveStatus.FOUND, seed, cand, found)
    )
    vec = np.zeros(512, dtype="float32"); vec[0] = 1.0
    await repo.upsert_embedding(conn, mbid=mbid, model_version=CLAP_MODEL_VERSION,
                                embedding=vec, source_confidence=1.0, asset_id=asset_id)
    assert len(await repo.fetch_embeddings(conn, [mbid], CLAP_MODEL_VERSION)) == 1
    rej = MatchScore(0.40, False, MatchReason.WEIGHTED, 0.5, 0.3, 0.5, 9000, isrc_match=False)
    await repo.persist_resolved_match(conn, "humble", "kendrick",
                                      ResolvedMatch(ResolveStatus.REJECTED, seed, cand, rej))
    assert await conn.fetchval("SELECT count(*) FROM embeddings WHERE mbid = $1", uuid.UUID(mbid)) == 0
    assert await repo.fetch_embeddings(conn, [mbid], CLAP_MODEL_VERSION) == []


async def test_fetch_embeddings_excludes_non_found_source_assets(conn):
    # read-side backstop: even a stale embedding (asset flipped outside the purge path) is hidden
    # once its source asset is no longer 'found'.
    mbid = str(uuid.uuid4())
    asset_id = await repo.persist_resolved_match(conn, "humble", "kendrick lamar", _found(mbid))
    vec = np.zeros(512, dtype="float32"); vec[0] = 1.0
    await repo.upsert_embedding(conn, mbid=mbid, model_version=CLAP_MODEL_VERSION,
                                embedding=vec, source_confidence=1.0, asset_id=asset_id)
    assert len(await repo.fetch_embeddings(conn, [mbid], CLAP_MODEL_VERSION)) == 1
    await conn.execute("UPDATE audio_assets SET asset_status = 'rejected' WHERE id = $1", asset_id)
    assert await repo.fetch_embeddings(conn, [mbid], CLAP_MODEL_VERSION) == []


async def test_get_embedding_excludes_non_found_source_asset(conn):
    # the single-row read path shares the found-only view: a rejected-source row reads as a miss
    mbid = str(uuid.uuid4())
    asset_id = await repo.persist_resolved_match(conn, "humble", "kendrick lamar", _found(mbid))
    vec = np.zeros(512, dtype="float32"); vec[0] = 1.0
    await repo.upsert_embedding(conn, mbid=mbid, model_version=CLAP_MODEL_VERSION,
                                embedding=vec, source_confidence=1.0, asset_id=asset_id)
    assert await repo.get_embedding(conn, mbid, CLAP_MODEL_VERSION) is not None
    await conn.execute("UPDATE audio_assets SET asset_status = 'rejected' WHERE id = $1", asset_id)
    assert await repo.get_embedding(conn, mbid, CLAP_MODEL_VERSION) is None


async def test_deleting_track_cascades_lookup_asset_embedding(conn):
    # deleting a recording must cascade cleanly to its assets, embeddings, AND cache lookups
    # (SET NULL on canonical_lookups.mbid used to violate the found/not_found CHECK and block this).
    mbid = str(uuid.uuid4())
    asset_id = await repo.persist_resolved_match(conn, "humble", "kendrick lamar", _found(mbid))
    vec = np.zeros(512, dtype="float32"); vec[0] = 1.0
    await repo.upsert_embedding(conn, mbid=mbid, model_version=CLAP_MODEL_VERSION,
                                embedding=vec, source_confidence=1.0, asset_id=asset_id)
    await conn.execute("DELETE FROM tracks WHERE mbid = $1", uuid.UUID(mbid))
    u = uuid.UUID(mbid)
    assert await conn.fetchval("SELECT count(*) FROM audio_assets WHERE mbid = $1", u) == 0
    assert await conn.fetchval("SELECT count(*) FROM embeddings WHERE mbid = $1", u) == 0
    assert await conn.fetchval("SELECT count(*) FROM canonical_lookups WHERE mbid = $1", u) == 0


async def test_check_constraints_reject_bad_rows(conn):
    mbid = await _insert_track(conn)  # valid FK target; each violation in its own savepoint
    # not_found must not carry an mbid (canonical_lookups biconditional CHECK)
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO canonical_lookups "
                "(norm_title, norm_artist, query_title, query_artist, status, mbid, resolver_version) "
                "VALUES ('t', 'a', 'T', 'A', 'not_found', $1, '1')",
                mbid,
            )
    # match_confidence must be in [0, 1]
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO audio_assets (mbid, preview_url, asset_status, match_confidence, match_reason) "
                "VALUES ($1, 'https://x', 'found', 1.5, 'isrc')",
                mbid,
            )
    # a found asset must have a preview_url
    with pytest.raises(asyncpg.exceptions.NotNullViolationError):
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO audio_assets (mbid, preview_url, asset_status, match_confidence, match_reason) "
                "VALUES ($1, NULL, 'found', 0.9, 'isrc')",
                mbid,
            )


async def test_nulls_not_distinct_dedupes_missing_provider_id(conn):
    mbid = await _insert_track(conn)

    async def upsert_no_id() -> int:
        return await conn.fetchval(
            "INSERT INTO audio_assets "
            "(mbid, provider, provider_track_id, preview_url, asset_status, match_confidence, match_reason) "
            "VALUES ($1, 'deezer', NULL, 'https://x', 'found', 0.9, 'isrc') "
            "ON CONFLICT (mbid, provider, provider_track_id) "
            "DO UPDATE SET match_confidence = EXCLUDED.match_confidence RETURNING id",
            mbid,
        )

    first, second = await upsert_no_id(), await upsert_no_id()
    assert first == second  # NULLS NOT DISTINCT: the second hits the same row, not a duplicate
    assert await conn.fetchval("SELECT count(*) FROM audio_assets WHERE mbid = $1", mbid) == 1


async def test_migrate_is_idempotent(conn):
    assert await migrate.up(conn) == []  # the fixture already applied everything


async def test_migrate_detects_checksum_drift(conn):
    await conn.execute(
        "UPDATE schema_migrations SET checksum = 'deadbeef' WHERE version = '0001_initial_schema'"
    )
    with pytest.raises(migrate.MigrationError):
        await migrate.up(conn)


async def test_pool_requires_extension_so_migrations_run_first(fresh_db_dsn):
    # Cold start: create_pool registers the pgvector codec, so it cannot be created before
    # `CREATE EXTENSION vector` exists — proving why migrations must run first (raw, no codec).
    with pytest.raises(ValueError, match="vector"):
        await create_pool(fresh_db_dsn)
    # Migrate via a raw connection (no codec), then the pool can register the vector type and work.
    # This is the ordering the conn fixture and the CI db-tests job depend on.
    raw = await asyncpg.connect(fresh_db_dsn)
    try:
        await migrate.up(raw)
    finally:
        await raw.close()
    pool = await create_pool(fresh_db_dsn)
    try:
        async with pool.acquire() as c:
            assert await c.fetchval("SELECT count(*) FROM tracks") == 0
    finally:
        await pool.close()
