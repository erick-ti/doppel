"""LLM vibe→acoustic-terms translator — the v2 "deepen the engine" flagship.

The Day-7 eval proved CLAP's *text* encoder is weak on cultural/emotional language: a vibe like
"sad late-night driving" lands at ~0.15–0.37 cosine and ranks inconsistently. CLAP was trained on
literal audio captions ("slow tempo, minor key, reverb-heavy synth pads"), so this rewrites the
listener's natural-language vibe into that vocabulary *before* :meth:`ClapEmbedder.embed_text`
encodes it — giving the encoder text it can actually place in the audio space.

Mirrors :class:`~doppel.explanation.explainer.ClaudeExplainer`'s discipline exactly, because the
flagship's whole safety argument rests on it: one prompt-cached Anthropic call, a tight timeout, a
single retry, and **degrade-to-raw on any failure** (missing ``ANTHROPIC_API_KEY``, API error,
timeout, or empty output all return the original vibe unchanged). The raw-vibe path is the
eval-validated floor, so translation can only help or no-op — never sink or regress a request.

Cheap/fast by default (``VIBE_TRANSLATION_MODEL``, a Haiku-class model — this is a short str→str
rewrite, not reasoning). The Anthropic client loads lazily on first use, so importing this is free on
the API-only path; satisfies the pipeline's ``VibeTranslator`` protocol.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from doppel.config import (
    ANTHROPIC_API_KEY,
    VIBE_TRANSLATION_MAX_TOKENS,
    VIBE_TRANSLATION_MODEL,
    VIBE_TRANSLATION_TIMEOUT_S,
)

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic


_SYSTEM_PROMPT = """\
You translate a listener's natural-language "vibe" for a song into the literal acoustic vocabulary an \
audio model was trained on. The downstream model (CLAP) understands concrete sonic descriptors — \
tempo, key/mode, instrumentation, production texture, energy — but NOT cultural or emotional phrasing \
("late-night", "main-character energy", "nostalgic"). Your job is to rewrite the vibe into those \
concrete terms while staying faithful to what the listener is asking for.

Draw from these families (pick only what the vibe implies; do not force every family):
- tempo: slow / downtempo / mid-tempo / driving / uptempo / fast
- key & mode: minor key / major key / modal / dissonant / consonant
- instrumentation: acoustic guitar / electric guitar / piano / synth pads / synth bass / 808s / \
brushed drums / live drums / strings / horns / vocal-led / instrumental
- production & texture: reverb-drenched / dry / lo-fi / hi-fi / warm / bright / sparse / dense / \
distorted / clean / atmospheric / compressed
- energy & feel: calm / intimate / restrained / tense / aggressive / euphoric / melancholic / hypnotic

Rules:
- Output ONLY a single fluent audio caption — one natural descriptive phrase of 8–18 words describing \
how the music SOUNDS, as if captioning an audio clip — NOT a comma-separated tag list (CLAP was trained \
on captions, so prose embeds better than labels). Example: "a slow, reverb-drenched melancholic \
electronic track with sparse instrumentation and an intimate, late-night feel".
- Weave the concrete acoustic qualities (tempo, key/mode, instrumentation, texture, energy) from the \
families above into the phrase as flowing prose, not as a list of labels.
- Translate the listener's INTENT, including when it asks to depart from the seed (e.g. "stripped back" \
for a dense track → "a sparse, intimate acoustic arrangement with minimal percussion and a dry, close sound").
- No preamble, explanation, or quotes. Never invent a specific named genre, artist, era, or lyric — only \
sonic qualities."""


class ClaudeVibeTranslator:
    """Anthropic-backed vibe→acoustic-terms rewriter; satisfies the pipeline's ``VibeTranslator`` protocol.

    Instantiate once and reuse (caches an ``AsyncAnthropic`` client). Safe to construct without an API
    key — :meth:`translate` then returns the vibe unchanged. Call :meth:`aclose` on shutdown.
    """

    def __init__(
        self, *, api_key: str | None = ANTHROPIC_API_KEY, model: str = VIBE_TRANSLATION_MODEL,
        max_tokens: int = VIBE_TRANSLATION_MAX_TOKENS, timeout_s: float = VIBE_TRANSLATION_TIMEOUT_S,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._max_tokens = max_tokens
        self._timeout_s = timeout_s
        self._client: AsyncAnthropic | None = None

    def _ensure_client(self) -> AsyncAnthropic:
        if self._client is None:
            from anthropic import AsyncAnthropic

            # Tight timeout + single retry: translation is a hot-path nicety and /recommend must never
            # block on it — any slowness degrades to the raw vibe (the eval-validated floor).
            self._client = AsyncAnthropic(
                api_key=self._api_key, timeout=self._timeout_s, max_retries=1
            )
        return self._client

    async def translate(self, vibe: str) -> str:
        """Rewrite ``vibe`` into literal acoustic terms, or return it **unchanged** on any problem.

        Degradation is the contract: no key, an empty/whitespace vibe, an API error/timeout, or empty
        model output all return the original ``vibe`` so the raw-vibe scoring path is the floor.
        """
        if not self._api_key or not vibe or not vibe.strip():
            return vibe
        try:
            response = await self._ensure_client().messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=[{"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": vibe}],
                thinking={"type": "disabled"},
            )
            text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), None)
            translated = text.strip() if text else ""
            return translated or vibe  # empty output ⇒ fall back to the raw vibe
        except Exception:
            return vibe  # missing/invalid key, API error, timeout — degrade to the raw vibe

    async def aclose(self) -> None:
        """Close the underlying HTTP client (call from the app/worker shutdown hook)."""
        if self._client is not None:
            await self._client.close()
            self._client = None
