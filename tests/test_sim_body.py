import pytest

from embody.proto import EMOTIONS, GESTURES, LOOK_DIRECTIONS
from embody.sim import DuckBody
from embody.sim.body import EYE_COLOURS


def test_defaults():
    b = DuckBody()
    assert b.emotion == "neutral" and b.pose == "upright"
    assert not b.asleep and not b.online and not b.speaking and not b.touched
    assert b.wing == 0 and b.head == 0


@pytest.mark.parametrize("emotion", EMOTIONS)
def test_set_emotion_all(emotion):
    b = DuckBody()
    ok, result, err = b.apply_tool("set_emotion", {"emotion": emotion, "intensity": 0.3})
    assert ok and err is None
    assert result["emotion"] == emotion
    assert b.emotion == emotion and b.intensity == 0.3
    assert b.eyes_rgb == EYE_COLOURS[emotion][1]
    assert emotion in b.render() and b.eyes_name in b.render()


def test_emotion_colours_distinct_and_named():
    assert EYE_COLOURS["happy"][0] == "warm-yellow"
    assert EYE_COLOURS["curious"][0] == "cyan"
    assert EYE_COLOURS["annoyed"][0] == "red"
    assert len({v[1] for v in EYE_COLOURS.values()}) == len(EYE_COLOURS)


def test_set_emotion_default_intensity():
    b = DuckBody()
    ok, result, _ = b.apply_tool("set_emotion", {"emotion": "happy"})
    assert ok and result["intensity"] == 0.7


@pytest.mark.parametrize("args", [
    {}, {"emotion": "furious"}, {"emotion": 3}, {"emotion": "happy", "intensity": 1.5},
    {"emotion": "happy", "intensity": -0.1}, {"emotion": "happy", "intensity": "high"},
    {"emotion": "happy", "intensity": True}, {"emotion": "happy", "bogus": 1},
])
def test_set_emotion_invalid(args):
    b = DuckBody()
    ok, result, err = b.apply_tool("set_emotion", args)
    assert not ok and result == {} and isinstance(err, str) and err
    assert b.emotion == "neutral"


@pytest.mark.parametrize("name", GESTURES)
def test_gesture_all(name):
    b = DuckBody()
    ok, result, err = b.apply_tool("gesture", {"name": name})
    assert ok and err is None and result == {"started": name}
    if name in ("wiggle", "flap"):
        assert b.wing == 1.0
    else:
        assert b.wing == 0.0


def test_gesture_idle_resets():
    b = DuckBody()
    b.apply_tool("gesture", {"name": "flap"})
    b.apply_tool("look_at", {"direction": "left"})
    b.apply_tool("gesture", {"name": "idle"})
    assert b.wing == 0 and b.head == 0 and b.gesture is None


@pytest.mark.parametrize("args", [{}, {"name": "dance"}, {"name": 1}, {"name": "nod", "x": 1}])
def test_gesture_invalid(args):
    ok, result, err = DuckBody().apply_tool("gesture", args)
    assert not ok and result == {} and err


@pytest.mark.parametrize("direction", LOOK_DIRECTIONS)
def test_look_at_all(direction):
    b = DuckBody()
    ok, result, err = b.apply_tool("look_at", {"direction": direction})
    assert ok and err is None and result["direction"] == direction
    assert -30 <= b.head <= 30
    assert b.head == {"left": -30, "right": 30, "center": 0, "user": 0}[direction]


@pytest.mark.parametrize("args", [{}, {"direction": "up"}, {"direction": None}])
def test_look_at_invalid(args):
    ok, result, err = DuckBody().apply_tool("look_at", args)
    assert not ok and result == {} and err


def test_get_state():
    b = DuckBody()
    b.pose, b.touched = "tilted", True
    b.apply_tool("set_emotion", {"emotion": "sad"})
    ok, result, err = b.apply_tool("get_state", {})
    assert ok and err is None
    assert result == {"touched": True, "pose": "tilted", "batt": 100, "rssi": -50,
                      "emotion": "sad", "asleep": False}
    assert b.apply_tool("get_state", {"x": 1})[0] is False
    assert b.apply_tool("get_state")[0] is True  # args default


def test_sleep_and_wake_on_tool():
    b = DuckBody()
    ok, result, err = b.apply_tool("sleep", {})
    assert ok and b.asleep and result == {"asleep": True}
    dark = b.eyes_rgb
    assert "zZz" in b.render()
    ok, result, _ = b.apply_tool("get_state", {})
    assert ok and not b.asleep and result["asleep"] is False
    assert b.eyes_rgb != dark
    # every tool wakes it
    for name, args in [("set_emotion", {"emotion": "happy"}), ("gesture", {"name": "nod"}),
                       ("look_at", {"direction": "left"})]:
        b.apply_tool("sleep", {})
        assert b.asleep
        b.apply_tool(name, args)
        assert not b.asleep


def test_sleep_when_asleep_stays_asleep():
    b = DuckBody()
    b.apply_tool("sleep", {})
    b.apply_tool("sleep", {})
    assert b.asleep


def test_unknown_tool_and_bad_args_type():
    b = DuckBody()
    b.apply_tool("sleep", {})
    ok, result, err = b.apply_tool("fly", {})
    assert not ok and result == {} and "fly" in err
    assert b.asleep  # unknown tool does not wake
    ok, _, err = b.apply_tool("gesture", "nod")  # type: ignore[arg-type]
    assert not ok and err


def test_render_shape_and_content():
    b = DuckBody()
    r = b.render()
    assert 1 <= len(r.splitlines()) <= 3
    assert "OFFLINE" in r and "neutral" in r and "soft-white" in r
    b.online = True
    b.speaking = True
    b.apply_tool("look_at", {"direction": "left"})
    b.apply_tool("gesture", {"name": "flap"})
    r = b.render()
    assert len(r.splitlines()) <= 3
    assert "online" in r and "speaking" in r and "head=left" in r and "wing=up" in r


def test_render_changes_with_state():
    b = DuckBody()
    seen = set()
    for e in EMOTIONS:
        b.apply_tool("set_emotion", {"emotion": e})
        seen.add(b.render())
    assert len(seen) == len(EMOTIONS)


def test_offline_tick_cycles():
    b = DuckBody()
    frames = [b.offline_tick() for _ in range(22)]
    assert all(f is not None for f in frames)  # every step is visible
    assert any("嘎" in f for f in frames)
    assert any("head=left" in f for f in frames)
    assert any("head=right" in f for f in frames)
    assert any("( - -)" in f for f in frames)  # blink
    assert frames[:11] == frames[11:]  # periodic
    assert b.head == 0 and not b.blink  # script ends at rest


def test_offline_tick_noop_when_online_or_asleep():
    b = DuckBody()
    b.online = True
    assert b.offline_tick() is None
    b.online = False
    b.apply_tool("sleep", {})
    assert b.offline_tick() is None
