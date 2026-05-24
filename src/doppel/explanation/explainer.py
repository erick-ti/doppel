"""LLM explainer — Claude writes a concise rationale per recommended track. Explanation, not ranking.

One batched Anthropic Messages call turns the seed + the scored top-N results (their audio / vibe
cosines and cultural-source overlap) into a short, grounded rationale for each. The model is told to
ground strictly in the evidence it is given and stay restrained when that evidence is thin — never to
invent musicological connections, and never to re-order the results (CLAP owns ranking; BRAINDUMP
"the LLM explains, it does not rank").

Fully degradable: no ``ANTHROPIC_API_KEY``, an API error, or a timeout all yield an empty rationale
map, and the pipeline returns the recommendations without rationales (``rationales_available=False``).
The explanation layer can never sink a recommendation.

Output is keyed by result *position* (a JSON array of ``{position, rationale}``), so a partial
response degrades per-row — a missing position just gets no rationale — and a cultural-backfill row
that has no MBID is still addressable (a mbid key couldn't address it). Prompt caching marks the
static instructions cacheable; note that only *actually* caches once that prefix clears the model's
minimum cacheable size (2048 tokens for Sonnet 4.6), which a concise instruction block may not reach —
it is the correct pattern and future-proofs a longer prompt, not a guaranteed hit today.

Model is ``LLM_MODEL`` (Claude Sonnet 4.6 by default — the project's chosen explainer model).
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from doppel.config import ANTHROPIC_API_KEY, LLM_MAX_TOKENS, LLM_MODEL, LLM_TIMEOUT_S

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic

    from doppel.pipeline.recommend import RecommendationResult


_SYSTEM_PROMPT = """\
You explain why each recommended song was suggested for a seed track. You do NOT rank or re-order \
them — the ranking is already decided by audio-embedding similarity. Your only job is a short rationale.

You receive a seed track (title, artist, and an optional natural-language "vibe" the listener asked \
for) and a list of recommended candidates. Each candidate carries the evidence behind it:
- "audio_scored": true means an audio-embedding (CLAP) similarity to the seed was computed; false \
means it is a cultural-only suggestion (no preview was available to compare sonically).
- "audio_similarity": cosine similarity of the candidate's audio to the seed's, in [-1, 1] (higher = \
more sonically alike). Present only when audio_scored is true.
- "vibe_text_similarity": cosine of the candidate's audio against the listener's vibe text, in \
[-1, 1]. Present only when a vibe was given and the candidate was audio-scored.
- "shared_sources": which cultural sources (e.g. lastfm, listenbrainz) surfaced this track as \
similar to the seed.

Write ONE rationale per candidate, one or two sentences, grounded ONLY in that evidence and the \
seed/candidate metadata. Rules:
- Ground every claim in the provided evidence. Do NOT invent acoustic details, genres, instruments, \
moods, lyrics, or history you were not given — you have not heard either track.
- When the evidence is thin (cultural-only, low similarity, no shared sources), say something \
restrained and honest (e.g. "surfaced by listener-taste data; no audio comparison was available") \
rather than inventing a sonic connection.
- A high audio_similarity supports a sonic-likeness claim; agreement across multiple shared_sources \
supports a cultural-relevance claim; vibe_text_similarity supports a fits-the-requested-vibe claim. \
Use whichever signal is actually strong for that candidate.
- Be specific to this seed/candidate pair; avoid generic filler that would fit any pair.

Return JSON only, matching the schema: an object with a "rationales" array of \
{"position": <int>, "rationale": <string>} — one entry per candidate, reusing each candidate's \
given "position"."""

# Structured-output schema: an array keyed by the result's position (not a dict — JSON Schema can't
# key on arbitrary integers, and additionalProperties must be false). Position-keyed so a partial
# response degrades per-row. No string-length constraints (structured outputs don't support them);
# the "one or two sentences" cap is instructed in the system prompt instead.
_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "rationales": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "position": {"type": "integer"},
                    "rationale": {"type": "string"},
                },
                "required": ["position", "rationale"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["rationales"],
    "additionalProperties": False,
}


class ClaudeExplainer:
    """Anthropic-backed rationale generator; satisfies the pipeline's ``Explainer`` protocol.

    Instantiate once and reuse — it caches an ``AsyncAnthropic`` client. Safe to construct without an
    API key (it simply returns no rationales). Call :meth:`aclose` on shutdown to close the client.
    """

    def __init__(
        self, *, api_key: str | None = ANTHROPIC_API_KEY, model: str = LLM_MODEL,
        max_tokens: int = LLM_MAX_TOKENS, timeout_s: float = LLM_TIMEOUT_S,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._max_tokens = max_tokens
        self._timeout_s = timeout_s
        self._client: AsyncAnthropic | None = None

    def _ensure_client(self) -> AsyncAnthropic:
        if self._client is None:
            from anthropic import AsyncAnthropic

            # Fail fast and degrade: a tight timeout + a single retry, since rationales are optional
            # and /recommend must not block on the LLM.
            self._client = AsyncAnthropic(
                api_key=self._api_key, timeout=self._timeout_s, max_retries=1
            )
        return self._client

    async def explain(
        self, *, seed_title: str, seed_artist: str, vibe: str | None,
        results: Sequence[RecommendationResult],
    ) -> Mapping[int, str]:
        """Return ``{position: rationale}`` for the given results, or ``{}`` (degraded) on any problem."""
        if not self._api_key or not results:
            return {}
        try:
            response = await self._ensure_client().messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=[{"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": _user_payload(seed_title, seed_artist, vibe, results)}],
                thinking={"type": "disabled"},
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": _RESULT_SCHEMA}},
            )
            return _parse(response)
        except Exception:
            return {}  # missing/invalid key, API error, timeout, or malformed output — degrade silently

    async def aclose(self) -> None:
        """Close the underlying HTTP client (call from the app/worker shutdown hook)."""
        if self._client is not None:
            await self._client.close()
            self._client = None


def _user_payload(
    seed_title: str, seed_artist: str, vibe: str | None, results: Sequence[RecommendationResult]
) -> str:
    """Compact JSON evidence for the prompt: the seed + each result's scores and source overlap."""
    seed: dict = {"title": seed_title, "artist": seed_artist}
    if vibe and vibe.strip():
        seed["vibe_description"] = vibe
    candidates = []
    for r in results:
        item: dict = {
            "position": r.position, "title": r.title, "artist": r.artist,
            "audio_scored": r.was_audio_scored, "shared_sources": list(r.sources),
        }
        if r.audio_score is not None:
            item["audio_similarity"] = round(r.audio_score, 3)
        if r.vibe_text_score is not None:
            item["vibe_text_similarity"] = round(r.vibe_text_score, 3)
        candidates.append(item)
    return json.dumps({"seed": seed, "candidates": candidates}, ensure_ascii=False)


def _parse(response) -> dict[int, str]:
    """Defensively map the structured response to ``{position: rationale}`` (ignore malformed rows)."""
    text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), None)
    if not text:
        return {}
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return {}
    rationales: dict[int, str] = {}
    for item in data.get("rationales", []) if isinstance(data, dict) else []:
        if not isinstance(item, dict):
            continue
        try:
            position = int(item["position"])
        except (KeyError, TypeError, ValueError):
            continue
        rationale = str(item.get("rationale", "")).strip()
        if rationale:
            rationales[position] = rationale
    return rationales
