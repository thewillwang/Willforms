"""Body API: the tools the LLM can call. Phase 0 set (docs/02-architecture.md §2).

These are plain Claude tool definitions (JSON schema). The cloud brain passes
them to the model; the device receives `Tool` frames with the same names/args.
Tools are *intents*, never motor commands.
"""
from __future__ import annotations

EMOTIONS = ["neutral", "happy", "curious", "sleepy", "surprised", "sad", "annoyed"]
GESTURES = ["nod", "shake", "wiggle", "look_up", "look_down", "flap", "idle"]
LOOK_DIRECTIONS = ["left", "right", "center", "user"]

PHASE0_TOOLS: list[dict] = [
    {
        "name": "set_emotion",
        "description": (
            "Set the duck's visible mood: eye colour and breathing rhythm, posture. "
            "Call this BEFORE speaking so the body reacts first. Returns immediately."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "emotion": {"type": "string", "enum": EMOTIONS},
                "intensity": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.7},
            },
            "required": ["emotion"],
            "additionalProperties": False,
        },
    },
    {
        "name": "gesture",
        "description": (
            "Play a short body animation (head/wing servos). Non-blocking: returns as soon "
            "as the animation starts. Use alongside speech, e.g. nod while agreeing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "enum": GESTURES}},
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "look_at",
        "description": "Turn the head towards a direction. 'user' means towards the last sound source.",
        "input_schema": {
            "type": "object",
            "properties": {"direction": {"type": "string", "enum": LOOK_DIRECTIONS}},
            "required": ["direction"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_state",
        "description": (
            "Read the body's sensors: touch, pose (upright/picked_up/tilted), battery, "
            "network quality, current emotion. Use when you need to know what is physically happening."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "sleep",
        "description": "Go to low-power standby: eyes dim, servos relax. Wake on touch or voice.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]

# `say` is NOT a tool: the model's streamed text *is* the speech. The brain
# chunks it into sentences and sends `Say` / TTS audio. This keeps text
# streaming and avoids a tool round-trip per sentence.


def tool_names(tools: list[dict] = PHASE0_TOOLS) -> set[str]:
    return {t["name"] for t in tools}
