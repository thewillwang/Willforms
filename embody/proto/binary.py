"""Binary frames: ``[1B type][2B seq big-endian][payload]``.

Used for audio (Opus) and image keyframes. Text/control goes in JSON frames.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum

_HDR = struct.Struct("!BH")  # type u8, seq u16
HEADER_SIZE = _HDR.size


class BinaryType(IntEnum):
    AUDIO_UP = 0x01    # device → cloud, Opus 16 kHz mono, 20 ms frames
    AUDIO_DOWN = 0x02  # cloud → device, Opus TTS
    IMAGE_UP = 0x03    # device → cloud, JPEG keyframe (phase 1+)


@dataclass(frozen=True, slots=True)
class BinaryFrame:
    type: BinaryType
    seq: int
    payload: bytes


def pack_binary(type_: BinaryType, seq: int, payload: bytes) -> bytes:
    return _HDR.pack(int(type_), seq & 0xFFFF) + payload


def unpack_binary(data: bytes) -> BinaryFrame:
    if len(data) < HEADER_SIZE:
        raise ValueError(f"binary frame too short: {len(data)} bytes")
    type_, seq = _HDR.unpack_from(data)
    return BinaryFrame(BinaryType(type_), seq, bytes(data[HEADER_SIZE:]))
