"""Wire protocol: frame round-trips, direction rules, binary packing, tool schemas."""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from embody.proto.binary import (
    HEADER_SIZE,
    BinaryType,
    pack_binary,
    unpack_binary,
)
from embody.proto.messages import (
    Error,
    Event,
    Hello,
    Ota,
    Ping,
    Pong,
    State,
    Say,
    Text,
    ToolResult,
    Tool,
    Tts,
    Vad,
    Welcome,
    dump,
    parse_any,
    parse_down,
    parse_up,
)
from embody.proto.tools import PHASE0_TOOLS, tool_names

UP_SAMPLES = [
    Hello(dev="duck-01", fw="0.0.1", caps=["audio_out", "text_in"], token="secret"),
    Event(name="touch", where="head", data={"force": 3}),
    State(batt=80, rssi=-55, pose="upright", emotion="happy", busy=False, extra={"temp": 31}),
    Vad(on=True),
    Text(text="hello duck"),
    ToolResult(id="t1", ok=False, result={}, error="servo stalled"),
]

DOWN_SAMPLES = [
    Tool(id="t1", name="set_emotion", args={"emotion": "curious", "intensity": 0.5}),
    Tts(state="start", utterance_id="u1"),
    Say(text="Quack.", utterance_id="u1", final=True),
    Ota(url="https://example.com/fw.bin", sha256="abc", ver="0.0.2"),
    Error(code="bad_frame", msg="oops"),
    Welcome(session="s1"),
]

BOTH_SAMPLES = [Ping(ts=1), Pong(ts=1)]


# ───────────────────────── round-trips ─────────────────────────

@pytest.mark.parametrize("frame", UP_SAMPLES + BOTH_SAMPLES, ids=lambda f: type(f).__name__)
def test_up_frames_round_trip(frame):
    parsed = parse_up(dump(frame))
    assert type(parsed) is type(frame)
    assert parsed == frame


@pytest.mark.parametrize("frame", DOWN_SAMPLES + BOTH_SAMPLES, ids=lambda f: type(f).__name__)
def test_down_frames_round_trip(frame):
    parsed = parse_down(dump(frame))
    assert type(parsed) is type(frame)
    assert parsed == frame


def test_every_frame_type_is_covered():
    seen = {type(f) for f in UP_SAMPLES + DOWN_SAMPLES + BOTH_SAMPLES}
    from embody.proto import messages

    frame_types = {
        getattr(messages, name)
        for name in messages.__all__
        if name not in {"PROTOCOL_VERSION", "UpFrame", "DownFrame", "AnyFrame",
                        "parse_up", "parse_down", "parse_any", "dump"}
    }
    assert frame_types == seen


# ───────────────────────── serialisation ─────────────────────────

def test_dump_drops_none_fields():
    raw = dump(Event(name="touch"))
    assert "where" not in raw
    assert json.loads(raw) == {"t": "event", "name": "touch", "data": {}}


def test_dump_is_compact():
    # Compact means: no separator whitespace. Samples may contain spaces inside
    # string values, so compare with a compact re-serialisation of the same JSON.
    for frame in UP_SAMPLES + DOWN_SAMPLES + BOTH_SAMPLES:
        raw = dump(frame)
        assert raw == json.dumps(json.loads(raw), separators=(",", ":"), ensure_ascii=False), type(frame).__name__


def test_dump_keeps_falsy_values():
    raw = json.loads(dump(Say(text="", final=False)))
    assert raw["text"] == ""
    assert raw["final"] is False


# ───────────────────────── parsing rules ─────────────────────────

def test_unknown_extra_keys_are_ignored():
    frame = parse_up('{"t":"vad","on":true,"future_field":42}')
    assert frame == Vad(on=True)


def test_tool_frame_is_rejected_by_parse_up():
    with pytest.raises(ValidationError):
        parse_up('{"t":"tool","id":"1","name":"get_state","args":{}}')


def test_text_frame_is_rejected_by_parse_down():
    with pytest.raises(ValidationError):
        parse_down('{"t":"text","text":"hi"}')


def test_parse_any_accepts_both_directions():
    assert parse_any(dump(Tool(id="1", name="sleep"))) == Tool(id="1", name="sleep")
    assert parse_any(dump(Text(text="hi"))) == Text(text="hi")
    assert parse_any(dump(Ping())) == Ping()


def test_parse_any_rejects_unknown_tag():
    with pytest.raises(ValidationError):
        parse_any('{"t":"nope"}')


def test_state_battery_out_of_range_is_rejected():
    with pytest.raises(ValidationError):
        parse_up('{"t":"state","batt":101}')


def test_parse_accepts_bytes():
    assert parse_up(b'{"t":"text","text":"hi"}') == Text(text="hi")


# ───────────────────────── binary frames ─────────────────────────

@pytest.mark.parametrize("kind", list(BinaryType))
def test_binary_round_trip(kind):
    payload = bytes(range(256))
    frame = unpack_binary(pack_binary(kind, 1234, payload))
    assert frame.type is kind
    assert frame.seq == 1234
    assert frame.payload == payload


def test_binary_header_layout():
    data = pack_binary(BinaryType.AUDIO_DOWN, 0x0102, b"\xaa")
    assert HEADER_SIZE == 3
    assert data == b"\x02\x01\x02\xaa"


def test_binary_seq_wraps_at_16_bits():
    assert unpack_binary(pack_binary(BinaryType.AUDIO_UP, 0xFFFF, b"")).seq == 0xFFFF
    assert unpack_binary(pack_binary(BinaryType.AUDIO_UP, 0x10000, b"")).seq == 0
    assert unpack_binary(pack_binary(BinaryType.AUDIO_UP, 0x10001, b"x")).seq == 1


def test_binary_empty_payload_is_allowed():
    frame = unpack_binary(pack_binary(BinaryType.IMAGE_UP, 7, b""))
    assert frame.payload == b""


@pytest.mark.parametrize("data", [b"", b"\x01", b"\x01\x00"])
def test_binary_too_short_raises(data):
    with pytest.raises(ValueError, match="too short"):
        unpack_binary(data)


# ───────────────────────── tool definitions ─────────────────────────

@pytest.mark.parametrize("tool", PHASE0_TOOLS, ids=lambda t: t["name"])
def test_tool_definition_shape(tool):
    assert isinstance(tool["name"], str) and tool["name"]
    assert isinstance(tool["description"], str) and tool["description"]
    schema = tool["input_schema"]
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False


def test_tool_names_are_unique_and_match_helper():
    names = [t["name"] for t in PHASE0_TOOLS]
    assert len(names) == len(set(names))
    assert tool_names() == set(names)
    assert tool_names() == {"set_emotion", "gesture", "look_at", "get_state", "sleep"}
