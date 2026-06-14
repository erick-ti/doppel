# Doppel

A song recommendation engine that matches the *vibe* of a seed track — mood,
texture, production aesthetic, scene feel — by combining cultural retrieval with
audio-embedding scoring and LLM-generated rationales. API-first.

## Live showcase

[![Doppel — the hero thesis, proof-stat ribbon, and seed gallery](docs/showcase.png)](https://doppel.erickti.com)

A fully static web showcase is live at **https://doppel.erickti.com** — a curated gallery of seed
tracks across eight genres, each rendering its real top-10: ranked neighbors, the four-axis score
breakdown (raw CLAP audio cosine, vibe-text cosine, within-batch fused rerank, and unbounded RRF
cultural consensus), source overlap, and the LLM rationale.

Every number is a serialization of **real** pipeline output. The committed `web/public/seeds/*.json`
hold derived CLAP scores, Deezer track-*page* links, and rationale text only — **no audio is persisted
or served**, and the live embedding pipeline is never invoked publicly. The site is a Next.js app built
with `output: "export"` (no backend, no request-time inference); the source lives in [`web/`](web/).

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

## Production deploy

Single-user VPS deploy (Docker Compose, SSH-tunnel access, no public ports) — see
[DEPLOY.md](DEPLOY.md) for the full runbook.
