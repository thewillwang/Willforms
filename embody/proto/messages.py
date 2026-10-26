"""JSON text frames. Every frame has a short type tag ``t``.

Direction legend:  ↑ device → cloud   ↓ cloud → device   ↔ both.

The same frames are spoken by the ESP32 firmware (phase 0), the software duck
(sim) and the edge board (phase 2+). Keep them small: the MCU parses them with
a few KB of RAM.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter

PROTOCOL_VERSION = 1


class _Frame(BaseModel):
    model_config = {"extra": "ignore"}


# ───────────────────────── device → cloud ─────────────────────────

class Hello(_Frame):
    """↑ First frame after connect."""
    t: Literal["hello"] = "hello"
    dev: str = Field(description="device id, e.g. duck-01 or sim-<host>")
    fw: str = Field(description="firmware / software version")
    caps: list[str] = Field(default_factory=list, description="capabilities: audio_in, audio_out, text_in, servo_head, servo_wing, led_eyes, touch, imu, wheels, camera")
    proto: int = PROTOCOL_VERSION
    token: str | None = Field(default=None, description="pre-shared device token (phase 0 auth)")


class Event(_Frame):
    """↑ Something happened on the body (touch, pickup, button...)."""
    t: Literal["event"] = "event"
    name: str
    where: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class State(_Frame):
    """↑ Periodic / on-demand body state snapshot."""
    t: Literal["state"] = "state"
    batt: int | None = Field(default=None, ge=0, le=100)
    rssi: int | None = None
    pose: str | None = Field(default=None, description="upright | tilted | picked_up | upside_down")
    emotion: str | None = None
    busy: bool = False
    extra: dict[str, Any] = Field(default_factory=dict)


class Vad(_Frame):
    """↑ Device-side voice activity: user started / stopped speaking."""
    t: Literal["vad"] = "vad"
    on: bool


class Text(_Frame):
    """↑ Typed user utterance. Used by the software duck in text mode and by
    devices that do ASR locally (phase 2 edge). Replaces the audio path."""
    t: Literal["text"] = "text"
    text: str


class ToolResult(_Frame):
    """↑ Reply to a `tool` frame."""
    t: Literal["tool_result"] = "tool_result"
    id: str
    ok: bool = True
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


# ───────────────────────── cloud → device ─────────────────────────

class Tool(_Frame):
    """↓ The brain calls a Body API tool on the device."""
    t: Literal["tool"] = "tool"
    id: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class Tts(_Frame):
    """↓ TTS stream boundaries, so the body can animate the beak / pause VAD."""
    t: Literal["tts"] = "tts"
    state: Literal["start", "end"]
    utterance_id: str | None = None


class Say(_Frame):
    """↓ Text the body should speak. Sent when the device has `text_out`
    capability (software duck prints it / uses local TTS) or alongside audio
    for subtitles. Sentence-sized chunks, in order."""
    t: Literal["say"] = "say"
    text: str
    utterance_id: str | None = None
    final: bool = False


class Ota(_Frame):
    """↓ Firmware update request."""
    t: Literal["ota"] = "ota"
    url: str
    sha256: str
    ver: str


class Error(_Frame):
    """↓ Cloud-side error the device may want to show / log."""
    t: Literal["error"] = "error"
    code: str
    msg: str = ""


class Welcome(_Frame):
    """↓ Reply to hello."""
    t: Literal["welcome"] = "welcome"
    session: str
    server: str = "embody-cloud"
    proto: int = PROTOCOL_VERSION


# ───────────────────────── both ─────────────────────────

class Ping(_Frame):
    t: Literal["ping"] = "ping"
    ts: int | None = None


class Pong(_Frame):
    t: Literal["pong"] = "pong"
    ts: int | None = None


UpFrame = Annotated[Union[Hello, Event, State, Vad, Text, ToolResult, Ping, Pong], Field(discriminator="t")]
DownFrame = Annotated[Union[Tool, Tts, Say, Ota, Error, Welcome, Ping, Pong], Field(discriminator="t")]
AnyFrame = Annotated[
    Union[Hello, Event, State, Vad, Text, ToolResult, Tool, Tts, Say, Ota, Error, Welcome, Ping, Pong],
    Field(discriminator="t"),
]

_up = TypeAdapter(UpFrame)
_down = TypeAdapter(DownFrame)
_any = TypeAdapter(AnyFrame)


def parse_up(raw: str | bytes) -> Hello | Event | State | Vad | Text | ToolResult | Ping | Pong:
    """Parse a frame sent by a device. Raises pydantic.ValidationError."""
    return _up.validate_json(raw)


def parse_down(raw: str | bytes) -> Tool | Tts | Say | Ota | Error | Welcome | Ping | Pong:
    """Parse a frame sent by the cloud."""
    return _down.validate_json(raw)


def parse_any(raw: str | bytes):
    return _any.validate_json(raw)


def dump(frame: BaseModel) -> str:
    """Serialize a frame compactly (no spaces, drop None) for the wire."""
    return frame.model_dump_json(exclude_none=True)


__all__ = [
    "PROTOCOL_VERSION",
    "Hello", "Event", "State", "Vad", "Text", "ToolResult",
    "Tool", "Tts", "Say", "Ota", "Error", "Welcome",
    "Ping", "Pong",
    "UpFrame", "DownFrame", "AnyFrame",
    "parse_up", "parse_down", "parse_any", "dump",
]
