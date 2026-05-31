"""Offline tests for the vibe→acoustic-terms translator — fakes the Anthropic client (no network/key).

The whole safety argument for the v2 flagship is the degradation contract: every failure path
(no key, empty vibe, API error, empty output) returns the RAW vibe unchanged, so the eval-validated
raw-vibe scoring path is always the floor. These tests pin that contract.
"""
from __future__ import annotations

from doppel.translation.translator import ClaudeVibeTranslator

_ACOUSTIC = "slow tempo, minor key, reverb-drenched synth pads, downtempo, melancholic"


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


def _translator_with(client: _FakeClient) -> ClaudeVibeTranslator:
    t = ClaudeVibeTranslator(api_key="test-key")
    t._client = client  # inject the fake; _ensure_client returns it as-is
    return t


async def test_translates_to_acoustic_terms():
    t = _translator_with(_FakeClient(_Response(f"  {_ACOUSTIC}  ")))
    out = await t.translate("melancholic, late-night driving")
    assert out == _ACOUSTIC  # stripped


async def test_no_api_key_returns_raw_without_calling_client():
    t = ClaudeVibeTranslator(api_key=None)
    fake = _FakeClient(_Response(_ACOUSTIC))
    t._client = fake
    out = await t.translate("late night")
    assert out == "late night"
    assert fake.messages.calls == []  # never reached the client


async def test_blank_vibe_passes_through_without_calling_client():
    fake = _FakeClient(_Response(_ACOUSTIC))
    t = _translator_with(fake)
    assert await t.translate("   ") == "   "
    assert fake.messages.calls == []


async def test_api_error_degrades_to_raw():
    t = _translator_with(_FakeClient(exc=RuntimeError("boom")))
    out = await t.translate("dreamy and nostalgic")
    assert out == "dreamy and nostalgic"


async def test_empty_model_output_degrades_to_raw():
    t = _translator_with(_FakeClient(_Response("   ")))  # whitespace-only completion
    out = await t.translate("warm and intimate")
    assert out == "warm and intimate"


async def test_call_shape_is_cacheable_and_thinking_disabled():
    fake = _FakeClient(_Response(_ACOUSTIC))
    t = _translator_with(fake)
    await t.translate("epic and cinematic")
    call = fake.messages.calls[0]
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert call["thinking"] == {"type": "disabled"}
    assert call["messages"][0]["content"] == "epic and cinematic"  # raw vibe is the user turn


async def test_aclose_closes_client():
    fake = _FakeClient(_Response(_ACOUSTIC))
    t = _translator_with(fake)
    await t.aclose()
    assert fake.closed is True
