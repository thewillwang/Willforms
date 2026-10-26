"""End-to-end: real gateway + real ClaudeBrain (scripted fake Claude client)
+ real SqliteMemory + real LatencyTelemetry + real software duck over a real
TCP WebSocket. The only fake is the model.
"""
from __future__ import annotations

import asyncio
import socket

import pytest
import uvicorn

from embody.cloud.brain import ClaudeBrain
from embody.cloud.config import Settings
from embody.cloud.gateway import create_app
from embody.cloud.memory import SqliteMemory
from embody.cloud.telemetry import LatencyTelemetry
from embody.sim import DuckBody, DuckClient
from tests.test_brain_agent import FakeClient, Script


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_for(pred, timeout=5.0, step=0.02):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        if pred():
            return True
        await asyncio.sleep(step)
    return False


@pytest.fixture
async def stack():
    port = _free_port()
    settings = Settings(host="127.0.0.1", port=port, device_token="", fallbacks=True, ping_interval_s=30)
    memory = SqliteMemory(":memory:")
    telemetry = LatencyTelemetry()

    # Model script for turn 1: round 1 -> set_emotion + gesture (stop tool_use),
    # round 2 (after tool_results) -> the spoken text. Turn 2 (touch event) -> text.
    round1 = (
        Script(stop_reason="tool_use")
        .tool("t1", "set_emotion", {"emotion": "happy", "intensity": 0.8})
        .tool("t2", "gesture", {"name": "nod"})
    )
    round2 = Script().text("你好呀！", "今天过得怎么样？")
    event_turn = Script().text("嘎，", "我在这儿呢。")
    fake = FakeClient(round1, round2, event_turn)
    brains: list[ClaudeBrain] = []

    def brain_factory(body):
        b = ClaudeBrain(body, memory, telemetry, settings, tts=None, client=fake)
        brains.append(b)
        return b

    app = create_app(settings, brain_factory)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    assert await _wait_for(lambda: server.started, timeout=5), "uvicorn did not start"

    out: list[str] = []
    body = DuckBody()
    duck = DuckClient(f"ws://127.0.0.1:{port}/ws", "sim-e2e", None, body, out.append, quiet=False)
    duck_task = asyncio.create_task(duck.run())
    assert await _wait_for(lambda: body.online, timeout=5), f"duck never connected: {out}"

    yield {"duck": duck, "body": body, "out": out, "memory": memory, "telemetry": telemetry, "fake": fake}

    await duck.stop()
    duck_task.cancel()
    server.should_exit = True
    await asyncio.wait_for(server_task, timeout=5)
    await memory.close()


async def test_text_turn_moves_body_before_speech(stack):
    duck, body, out = stack["duck"], stack["body"], stack["out"]
    assert await duck.send_text("你好")

    ok = await _wait_for(lambda: any("今天过得怎么样" in line for line in out), timeout=5)
    assert ok, f"no speech line; output was: {out}"

    # Body state changed by the tool calls
    assert body.emotion == "happy"

    # Tool outcome lines are printed before the duck line
    tool_idx = next(i for i, l in enumerate(out) if "tool set_emotion" in l)
    say_idx = next(i for i, l in enumerate(out) if l.startswith("🦆"))
    assert tool_idx < say_idx

    # Stored history: user, assistant(tool_use), user(tool_result), assistant(text)
    hist = await stack["memory"].history("sim-e2e", 20)
    roles = [h["role"] for h in hist]
    assert roles[0] == "user" and roles[-1] == "assistant"
    assert any(isinstance(h["content"], list) and any(b.get("type") == "tool_result" for b in h["content"]) for h in hist)

    # Telemetry recorded the turn
    assert await _wait_for(lambda: len(stack["telemetry"].recent) >= 1, timeout=2)
    marks = stack["telemetry"].recent[-1]
    assert "first_say" in marks and "total" in marks

    # Request shape: no thinking / temperature / tool_choice, fallback beta on
    path, kw = stack["fake"].requests[0]
    assert path == "beta"
    for forbidden in ("thinking", "temperature", "tool_choice"):
        assert forbidden not in kw
    assert kw["output_config"] == {"effort": "low"}


async def test_second_turn_and_touch_event(stack):
    duck, body, out = stack["duck"], stack["body"], stack["out"]
    await duck.send_text("你好")
    assert await _wait_for(lambda: any("今天过得怎么样" in l for l in out), timeout=5)
    await duck.send_event("touch", "head")
    assert await _wait_for(lambda: any("我在这儿呢" in l for l in out), timeout=5), out
    hist = await stack["memory"].history("sim-e2e", 20)
    assert any("[身体事件]" in str(h["content"]) for h in hist)
