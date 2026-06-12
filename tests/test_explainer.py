"""Offline tests for the LLM explainer — fakes the Anthropic client (no network, no key needed).

Covers the contract the pipeline relies on: rationales keyed by result position, robustness to a
partial / malformed model response, and the three degradation paths (no API key, API error, bad JSON)
all returning an empty map so the pipeline degrades to no-rationales.
"""
from __future__ import annotations

import json

import pytest

from doppel.explanation.explainer import ClaudeExplainer
from doppel.pipeline.recommend import RecommendationResult


class _TextBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _Response:
    def __init__(self, text: str) -> None:
        self.content = [_TextBlock(text)]


class _FakeMessages:
    def __init__(self, response=None, exc: Exception | None = None) -> None:
        self._response = response
        self._exc = exc
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._exc is not None:
            raise self._exc
        return self._response


class _FakeClient:
    def __init__(self, response=None, exc: Exception | None = None) -> None:
        self.messages = _FakeMessages(response, exc)
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def _result(position: int, title: str, *, audio=True, audio_score=None, sources=("lastfm",)) -> RecommendationResult:
    return RecommendationResult(
        position=position, title=title, artist=f"Artist {title}", cultural_score=0.03,
        was_audio_scored=audio, sources=tuple(sources), audio_score=audio_score,
        combined_score=(0.9 if audio else None),
    )


def _explainer_with(client: _FakeClient) -> ClaudeExplainer:
    explainer = ClaudeExplainer(api_key="test-key")
    explainer._client = client  # inject the fake; _ensure_client returns it as-is
    return explainer


async def test_returns_rationales_keyed_by_position():
    body = json.dumps({"rationales": [
        {"position": 1, "rationale": "Strong sonic match."},
        {"position": 2, "rationale": "Surfaced by listener-taste data."},
    ]})
    explainer = _explainer_with(_FakeClient(_Response(body)))
    out = await explainer.explain(
        seed_title="Seed", seed_artist="Artist", vibe="late night",
        results=[_result(1, "A", audio_score=0.82), _result(2, "B", audio=False)],
    )
    assert out == {1: "Strong sonic match.", 2: "Surfaced by listener-taste data."}


async def test_partial_response_degrades_per_row():
    # Model returned a rationale for position 1 only — position 2 simply gets none, no crash.
    body = json.dumps({"rationales": [{"position": 1, "rationale": "Only this one."}]})
    explainer = _explainer_with(_FakeClient(_Response(body)))
    out = await explainer.explain(
        seed_title="S", seed_artist="A", vibe=None,
        results=[_result(1, "A", audio_score=0.7), _result(2, "B", audio_score=0.6)],
    )
    assert out == {1: "Only this one."}


async def test_malformed_rows_are_skipped():
    body = json.dumps({"rationales": [
        {"position": "oops", "rationale": "bad position"},   # non-int position → skipped
        {"position": 2},                                       # missing rationale → skipped
        {"position": 3, "rationale": "   "},                  # blank → skipped
        {"position": 4, "rationale": "kept"},
    ]})
    explainer = _explainer_with(_FakeClient(_Response(body)))
    out = await explainer.explain(seed_title="S", seed_artist="A", vibe=None, results=[_result(4, "D")])
    assert out == {4: "kept"}


async def test_invalid_json_degrades_to_empty():
    explainer = _explainer_with(_FakeClient(_Response("not json at all {")))
    out = await explainer.explain(seed_title="S", seed_artist="A", vibe=None, results=[_result(1, "A")])
    assert out == {}


async def test_api_error_degrades_to_empty():
    explainer = _explainer_with(_FakeClient(exc=RuntimeError("boom")))
    out = await explainer.explain(seed_title="S", seed_artist="A", vibe=None, results=[_result(1, "A")])
    assert out == {}


async def test_no_api_key_returns_empty_without_calling_client():
    explainer = ClaudeExplainer(api_key=None)
    fake = _FakeClient(_Response(json.dumps({"rationales": [{"position": 1, "rationale": "x"}]})))
    explainer._client = fake
    out = await explainer.explain(seed_title="S", seed_artist="A", vibe=None, results=[_result(1, "A")])
    assert out == {}
    assert fake.messages.calls == []  # never reached the client


async def test_empty_results_returns_empty():
    fake = _FakeClient(_Response(json.dumps({"rationales": []})))
    explainer = _explainer_with(fake)
    out = await explainer.explain(seed_title="S", seed_artist="A", vibe=None, results=[])
    assert out == {} and fake.messages.calls == []


async def test_payload_includes_evidence_and_schema_request():
    fake = _FakeClient(_Response(json.dumps({"rationales": []})))
    explainer = _explainer_with(fake)
    await explainer.explain(
        seed_title="Seed", seed_artist="Artist", vibe="dreamy",
        results=[_result(1, "A", audio_score=0.82, sources=("lastfm", "listenbrainz"))],
    )
    call = fake.messages.calls[0]
    # structured-output format + the static system prompt is marked cacheable
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    payload = json.loads(call["messages"][0]["content"])
    assert payload["seed"] == {"title": "Seed", "artist": "Artist", "vibe_description": "dreamy"}
    cand = payload["candidates"][0]
    assert cand["audio_similarity"] == 0.82 and cand["shared_sources"] == ["lastfm", "listenbrainz"]
    assert "retrieved_by" not in cand  # a cultural result is not marked as vibe-retrieved


async def test_hnsw_only_result_marked_as_vibe_retrieved():
    # An HNSW-lane result (sources == ("hnsw",)) carries no cultural provenance: shared_sources is
    # emptied and a "retrieved_by" marker tells the model it was surfaced by vibe/acoustic similarity,
    # so the prompt doesn't read "hnsw" as a cultural co-listening source and fabricate a scene link.
    fake = _FakeClient(_Response(json.dumps({"rationales": []})))
    explainer = _explainer_with(fake)
    await explainer.explain(
        seed_title="Seed", seed_artist="Artist", vibe="sparse acoustic guitar",
        results=[_result(1, "A", audio_score=0.41, sources=("hnsw",))],
    )
    cand = json.loads(fake.messages.calls[0]["messages"][0]["content"])["candidates"][0]
    assert cand["shared_sources"] == []
    assert cand["retrieved_by"] == "global vibe/acoustic similarity"
