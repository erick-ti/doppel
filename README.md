# Doppel

A song recommendation engine that matches the *vibe* of a seed track — mood,
texture, production aesthetic, scene feel — by combining cultural retrieval with
audio-embedding scoring and LLM-generated rationales. API-first.

## Local development

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), and Docker (the database runs in a
container).

```bash
uv sync                # core deps (add --group clap for the heavy CLAP audio stack)
cp .env.example .env   # then fill in LASTFM_API_KEY (optional — the aggregator degrades without it)
```

### Database (Postgres 16 + pgvector)

```bash
docker compose up -d                      # Postgres on localhost:5432 (run `orb start` first if needed)
uv run python -m doppel.db.migrate up     # apply the schema  (`… status` lists applied/pending)
```

Migrations are forward-only and run as an explicit step (never on app startup). Already running
Postgres on 5432? Start the container on another port and point `DATABASE_URL` at it:

```bash
DOPPEL_DB_PORT=5433 docker compose up -d
export DATABASE_URL=postgresql://doppel:doppel@localhost:5433/doppel
```

### Tests

```bash
uv run --group dev pytest                    # offline suite (fast, hermetic)
uv run --group dev pytest --run-db           # + tests against the running Postgres
uv run --group dev pytest --run-integration  # + live Deezer / MusicBrainz / ListenBrainz / Last.fm
```
