"""M0 default voice adapters: text only, no audio."""
from __future__ import annotations

from typing import AsyncIterator

from embody.cloud.ports import ASR, TTS


class NullTTS(TTS):
    """Yields no audio frames: the body only receives `say` text."""

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:  # type: ignore[override]
        return
        yield b""  # pragma: no cover - makes this an async generator


class NullASR(ASR):
    """Ignores audio; `finish()` always returns an empty transcript."""

    async def feed(self, opus_frame: bytes) -> None:
        return None

    async def finish(self) -> str:
        return ""

    async def reset(self) -> None:
        return None
