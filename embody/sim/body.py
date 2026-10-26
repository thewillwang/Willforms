"""Pure state machine for the software duck. No I/O, no clocks, no randomness."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from embody.proto import EMOTIONS, GESTURES, LOOK_DIRECTIONS

POSES = ("upright", "picked_up", "tilted")

# emotion -> (colour name, rgb)
EYE_COLOURS: dict[str, tuple[str, tuple[int, int, int]]] = {
    "neutral": ("soft-white", (230, 230, 220)),
    "happy": ("warm-yellow", (255, 200, 60)),
    "curious": ("cyan", (0, 220, 230)),
    "sleepy": ("dim-blue", (20, 30, 90)),
    "surprised": ("white", (255, 255, 255)),
    "sad": ("blue", (30, 60, 220)),
    "annoyed": ("red", (230, 30, 30)),
}
_ASLEEP_EYES = ("off", (4, 6, 18))

_EYE_GLYPH = {
    "neutral": ("o", "o"),
    "happy": ("^", "^"),
    "curious": ("O", "o"),
    "sleepy": ("-", "-"),
    "surprised": ("O", "O"),
    "sad": ("T", "T"),
    "annoyed": (">", "<"),
}

_LOOK_ANGLE = {"left": -30.0, "right": 30.0, "center": 0.0, "user": 0.0}

# One full cycle of the offline persona (docs/02-architecture.md §6).
_OFFLINE_SCRIPT = (
    "blink", "open", "left", "center", "blink", "open",
    "right", "center", "quack", "blink", "open",
)

_TOOL_NAMES = ("set_emotion", "gesture", "look_at", "get_state", "sleep")


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


@dataclass
class DuckBody:
    emotion: str = "neutral"
    intensity: float = 0.7
    head: float = 0.0            # degrees, -30 (left) .. 30 (right)
    wing: float = 0.0            # 0 (down) .. 1 (up)
    eyes_rgb: tuple[int, int, int] = EYE_COLOURS["neutral"][1]
    touched: bool = False
    pose: str = "upright"
    asleep: bool = False
    speaking: bool = False
    online: bool = False
    gesture: str | None = None   # last gesture, shown until the next change
    look: str = "center"         # last look_at direction
    blink: bool = False
    quack: bool = False
    _offline_i: int = field(default=0, repr=False)

    # ───────────────────────── state helpers ─────────────────────────

    @property
    def eyes_name(self) -> str:
        if self.asleep:
            return _ASLEEP_EYES[0]
        return EYE_COLOURS[self.emotion][0]

    def _refresh_eyes(self) -> None:
        self.eyes_rgb = _ASLEEP_EYES[1] if self.asleep else EYE_COLOURS[self.emotion][1]

    def wake(self) -> None:
        if self.asleep:
            self.asleep = False
            self._refresh_eyes()

    # ───────────────────────── Body API ─────────────────────────

    def apply_tool(self, name: str, args: dict[str, Any] | None = None) -> tuple[bool, dict, str | None]:
        """Execute a Body API tool. Returns ``(ok, result, error)``."""
        if name not in _TOOL_NAMES:
            return False, {}, f"unknown tool: {name!r}"
        if args is None:
            args = {}
        if not isinstance(args, dict):
            return False, {}, "args must be an object"
        handler = getattr(self, f"_tool_{name}")
        self.wake()  # any (known) tool call wakes the duck; `sleep` re-sleeps below
        return handler(args)

    @staticmethod
    def _check_keys(args: dict, allowed: set[str]) -> str | None:
        extra = set(args) - allowed
        if extra:
            return f"unexpected argument(s): {', '.join(sorted(extra))}"
        return None

    def _tool_set_emotion(self, args: dict) -> tuple[bool, dict, str | None]:
        if (err := self._check_keys(args, {"emotion", "intensity"})):
            return False, {}, err
        emotion = args.get("emotion")
        if emotion not in EMOTIONS:
            return False, {}, f"emotion must be one of {EMOTIONS}, got {emotion!r}"
        intensity = args.get("intensity", 0.7)
        if not _is_number(intensity) or not 0 <= intensity <= 1:
            return False, {}, f"intensity must be a number in [0, 1], got {intensity!r}"
        self.emotion = emotion
        self.intensity = float(intensity)
        self.gesture = None
        self._refresh_eyes()
        return True, {"emotion": emotion, "intensity": self.intensity}, None

    def _tool_gesture(self, args: dict) -> tuple[bool, dict, str | None]:
        if (err := self._check_keys(args, {"name"})):
            return False, {}, err
        name = args.get("name")
        if name not in GESTURES:
            return False, {}, f"name must be one of {GESTURES}, got {name!r}"
        self.gesture = None if name == "idle" else name
        if name == "idle":
            self.head, self.look = 0.0, "center"
        # nod/shake/look_* are transient head animations: head rests at centre.
        elif name in ("nod", "shake", "look_up", "look_down"):
            self.head = 0.0
        self.wing = 1.0 if name in ("wiggle", "flap") else 0.0
        return True, {"started": name}, None

    def _tool_look_at(self, args: dict) -> tuple[bool, dict, str | None]:
        if (err := self._check_keys(args, {"direction"})):
            return False, {}, err
        direction = args.get("direction")
        if direction not in LOOK_DIRECTIONS:
            return False, {}, f"direction must be one of {LOOK_DIRECTIONS}, got {direction!r}"
        self.head = _LOOK_ANGLE[direction]
        self.look = direction
        self.gesture = None
        return True, {"direction": direction, "angle": self.head}, None

    def _tool_get_state(self, args: dict) -> tuple[bool, dict, str | None]:
        if (err := self._check_keys(args, set())):
            return False, {}, err
        return True, self.snapshot(), None

    def _tool_sleep(self, args: dict) -> tuple[bool, dict, str | None]:
        if (err := self._check_keys(args, set())):
            return False, {}, err
        self.asleep = True
        self.speaking = False
        self.gesture = None
        self.head, self.wing, self.look = 0.0, 0.0, "center"
        self._refresh_eyes()
        return True, {"asleep": True}, None

    def snapshot(self) -> dict[str, Any]:
        return {
            "touched": self.touched,
            "pose": self.pose,
            "batt": 100,
            "rssi": -50,
            "emotion": self.emotion,
            "asleep": self.asleep,
        }

    # ───────────────────────── rendering ─────────────────────────

    def render(self) -> str:
        if self.asleep or self.blink:
            left = right = "-"
        else:
            left, right = _EYE_GLYPH[self.emotion]
        if self.head < -5:
            beak = "<"
        elif self.head > 5:
            beak = ">"
        else:
            beak = "v"
        pad = " " * (2 + round(self.head / 15))
        wing = "~" if self.wing > 0.5 else "_"
        status = "online" if self.online else "OFFLINE"
        flags = []
        if self.asleep:
            flags.append("zZz")
        if self.speaking:
            flags.append("speaking")
        if self.touched:
            flags.append("touched")
        if self.pose != "upright":
            flags.append(self.pose)
        if self.quack:
            flags.append("嘎!")
        if self.gesture:
            flags.append(f"<{self.gesture}>")
        info1 = f"[{status}] {self.emotion}({self.intensity:.1f})"
        info2 = f"eyes={self.eyes_name} head={self.head_label()} wing={'up' if self.wing > 0.5 else 'down'}"
        info3 = " ".join(flags)
        lines = [
            f"{pad} ,--.     {info1}",
            f"{pad}( {left} {right}){beak}   {info2}",
            f"{pad} \\_{wing}_/     {info3}".rstrip(),
        ]
        return "\n".join(lines)

    def head_label(self) -> str:
        if self.head < -5:
            return "left"
        if self.head > 5:
            return "right"
        return "user" if self.look == "user" else "center"

    # ───────────────────────── offline persona ─────────────────────────

    def offline_tick(self) -> str | None:
        """Advance the offline persona one step (call every ~2 s while disconnected).

        Returns the new render if something visible changed, else None.
        """
        if self.online or self.asleep:
            return None
        before = self.render()
        step = _OFFLINE_SCRIPT[self._offline_i % len(_OFFLINE_SCRIPT)]
        self._offline_i += 1
        self.quack = False
        if step == "blink":
            self.blink = True
        elif step == "open":
            self.blink = False
        elif step == "left":
            self.head, self.look = -20.0, "left"
        elif step == "right":
            self.head, self.look = 20.0, "right"
        elif step == "center":
            self.head, self.look = 0.0, "center"
        elif step == "quack":
            self.quack = True
        after = self.render()
        return after if after != before else None
