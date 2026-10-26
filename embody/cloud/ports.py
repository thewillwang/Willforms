"""Interfaces between cloud modules. Each module depends on these, not on each other.

    gateway  ──calls──▶  Brain            (one Brain per connected device session)
    Brain    ──calls──▶  BodyPort         (implemented by the gateway session)
    Brain    ──calls──▶  Memory, Telemetry, TTS
    gateway  ──calls──▶  ASR              (audio frames in → text out)

Everything is asyncio. Nothing here touches the network or the Anthropic SDK.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol

from embody.proto import Hello, State


# ───────────────────────── Brain → body ─────────────────────────

@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass(slots=True)
class ToolOutcome:
    ok: bool
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class BodyPort(abc.ABC):
    """What the brain can do to the body. Implemented by the gateway session."""

    @property
    @abc.abstractmethod
    def hello(self) -> Hello: ...

    @property
    @abc.abstractmethod
    def last_state(self) -> State | None: ...

    @abc.abstractmethod
    async def call_tool(self, call: ToolCall, timeout_s: float = 2.0) -> ToolOutcome:
        """Send a `Tool` frame and await its `ToolResult`. Must never raise on
        device errors: return ToolOutcome(ok=False, error=...). Raise only on
        a dead connection."""

    @abc.abstractmethod
    async def say(self, text: str, utterance_id: str, final: bool = False) -> None:
        """Send one sentence of speech text (`Say` frame)."""

    @abc.abstractmethod
    async def send_audio(self, opus_frame: bytes) -> None:
        """Send one Opus TTS frame (binary AUDIO_DOWN). No-op if device lacks audio_out."""

    @abc.abstractmethod
    async def tts_state(self, state: str, utterance_id: str) -> None:
        """'start' | 'end' boundary frames."""


# ───────────────────────── gateway → brain ─────────────────────────

class Brain(abc.ABC):
    """One per device session. The gateway feeds it user input and body events;
    it drives the body through its BodyPort."""

    @abc.abstractmethod
    async def on_user_text(self, text: str) -> None:
        """Final ASR text or typed text. Runs one agent turn: stream the model,
        dispatch tool calls to the body as soon as they are complete, chunk
        text into sentences and speak them. Must be cancellable (barge-in)."""

    @abc.abstractmethod
    async def on_event(self, name: str, where: str | None, data: dict[str, Any]) -> None:
        """Body event (touch, picked_up...). The brain may react with a short turn."""

    @abc.abstractmethod
    async def interrupt(self) -> None:
        """User started talking while we speak: stop the current turn and TTS."""

    @abc.abstractmethod
    async def close(self) -> None: ...


# ───────────────────────── voice adapters ─────────────────────────

class ASR(abc.ABC):
    """Streaming speech → text for one utterance."""

    @abc.abstractmethod
    async def feed(self, opus_frame: bytes) -> None: ...

    @abc.abstractmethod
    async def finish(self) -> str:
        """Called when VAD says the user stopped. Returns final transcript."""

    @abc.abstractmethod
    async def reset(self) -> None: ...


class TTS(abc.ABC):
    """Text → Opus frames. Implementations may be `NullTTS` (text only)."""

    @abc.abstractmethod
    def synthesize(self, text: str) -> AsyncIterator[bytes]:
        """Yield Opus frames (20 ms each) as they are produced."""


# ───────────────────────── memory & telemetry ─────────────────────────

class Memory(abc.ABC):
    @abc.abstractmethod
    async def remember(self, device: str, key: str, value: str) -> None: ...

    @abc.abstractmethod
    async def recall(self, device: str, key: str | None = None) -> dict[str, str]: ...

    @abc.abstractmethod
    async def append_turn(self, device: str, role: str, content: Any) -> None: ...

    @abc.abstractmethod
    async def history(self, device: str, limit: int) -> list[dict[str, Any]]:
        """Last `limit` turns as Anthropic `messages` entries ({"role","content"})."""

    @abc.abstractmethod
    async def close(self) -> None: ...


class Telemetry(Protocol):
    """Latency breakdown per turn. Keys: utterance_end, asr_done, llm_first_token,
    llm_first_tool, first_say, tts_first_audio, turn_end (monotonic seconds)."""

    def turn_start(self, device: str) -> "TurnTimer": ...


class TurnTimer(Protocol):
    def mark(self, key: str) -> None: ...
    def finish(self) -> dict[str, float]: ...
