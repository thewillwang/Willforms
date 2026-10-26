from __future__ import annotations

import contextlib
import json
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from embody.cloud.config import Settings
from embody.cloud.gateway import create_app
from embody.cloud.ports import ASR, Brain, ToolCall
from embody.proto import BinaryType, pack_binary, unpack_binary


class FakeBrain(Brain):
    """Echoes everything back through `say` so tests can assert from the client side."""

    def __init__(self, body) -> None:
        self.body = body
        self.closed = False
        self.interrupts = 0

    async def on_user_text(self, text: str) -> None:
        if text == "nod":
            out = await self.body.call_tool(ToolCall("c1", "gesture", {"name": "nod"}))
            await self.body.say("好", "u1")
            await self.body.say(f"ok={out.ok} err={out.error} res={out.result}", "u1", True)
        elif text == "slow":
            out = await self.body.call_tool(ToolCall("c2", "gesture", {"name": "nod"}), timeout_s=0.1)
            await self.body.say(f"ok={out.ok} err={out.error}", "u2", True)
        elif text == "state":
            st = self.body.last_state
            await self.body.say(f"pose={st.pose if st else None}", "u3", True)
        elif text == "audio":
            await self.body.send_audio(b"\x01\x02")
            await self.body.tts_state("start", "u4")
            await self.body.say("done", "u4", True)
        else:
            await self.body.say(f"got:{text}", "u0", True)

    async def on_event(self, name, where, data) -> None:
        await self.body.say(f"event:{name}:{where}:{data}", "e", True)

    async def interrupt(self) -> None:
        self.interrupts += 1
        await self.body.say("interrupted", "i", True)

    async def close(self) -> None:
        self.closed = True


class FakeASR(ASR):
    def __init__(self) -> None:
        self.buf: list[bytes] = []

    async def feed(self, opus_frame: bytes) -> None:
        self.buf.append(opus_frame)

    async def finish(self) -> str:
        return b"".join(self.buf).decode()

    async def reset(self) -> None:
        self.buf.clear()


HELLO = {"t": "hello", "dev": "duck-test", "fw": "0.0", "caps": ["text_in", "audio_out"]}


def make_client(token: str = "", **kw) -> tuple[TestClient, list[FakeBrain]]:
    brains: list[FakeBrain] = []

    def factory(body):
        b = FakeBrain(body)
        brains.append(b)
        return b

    settings = Settings(device_token=token, ping_interval_s=kw.pop("ping_interval_s", 1000.0), **kw)
    app = create_app(settings, factory)
    return TestClient(app), brains


@contextlib.contextmanager
def ws_session(client: TestClient):
    """websocket_connect, but let the server finish its cleanup before the TestClient
    cancels the app task on exit (otherwise teardown races and raises CancelledError)."""
    with client.websocket_connect("/ws") as ws:
        try:
            yield ws
        finally:
            with contextlib.suppress(Exception):
                ws.close()
            time.sleep(0.1)


def connect(ws, hello=HELLO):
    ws.send_text(json.dumps(hello))
    w = ws.receive_json()
    assert w["t"] == "welcome"
    return w


def test_handshake_welcome_and_healthz():
    client, brains = make_client()
    with ws_session(client) as ws:
        w = connect(ws)
        assert len(w["session"]) == 32
        assert client.get("/healthz").json() == {"ok": True, "devices": 1}
        assert len(brains) == 1
    # session is removed after disconnect
    for _ in range(50):
        if client.get("/healthz").json()["devices"] == 0:
            break
        time.sleep(0.02)
    assert client.get("/healthz").json() == {"ok": True, "devices": 0}
    assert brains[0].closed


def test_bad_first_frame_closes_4000():
    client, brains = make_client()
    with ws_session(client) as ws:
        ws.send_text(json.dumps({"t": "text", "text": "hi"}))
        assert ws.receive_json()["t"] == "error"
        with pytest.raises(WebSocketDisconnect) as ei:
            ws.receive_json()
        assert ei.value.code == 4000
    assert brains == []


def test_wrong_token_closes_4001():
    client, brains = make_client(token="secret")
    with ws_session(client) as ws:
        ws.send_text(json.dumps({**HELLO, "token": "nope"}))
        err = ws.receive_json()
        assert err["t"] == "error" and err["code"] == "auth"
        with pytest.raises(WebSocketDisconnect) as ei:
            ws.receive_json()
        assert ei.value.code == 4001
    assert brains == []
    # correct token works
    with ws_session(client) as ws:
        connect(ws, {**HELLO, "token": "secret"})


def test_text_reaches_brain():
    client, _ = make_client()
    with ws_session(client) as ws:
        connect(ws)
        ws.send_json({"t": "text", "text": "hello duck"})
        m = ws.receive_json()
        assert m == {"t": "say", "text": "got:hello duck", "utterance_id": "u0", "final": True}


def test_tool_round_trip():
    client, _ = make_client()
    with ws_session(client) as ws:
        connect(ws)
        ws.send_json({"t": "text", "text": "nod"})
        tool = ws.receive_json()
        assert tool == {"t": "tool", "id": "c1", "name": "gesture", "args": {"name": "nod"}}
        ws.send_json({"t": "tool_result", "id": "c1", "ok": True, "result": {"done": 1}})
        say = ws.receive_json()
        assert say["t"] == "say" and say["text"] == "好" and say["utterance_id"] == "u1"
        res = ws.receive_json()
        assert res["text"] == "ok=True err=None res={'done': 1}"


def test_tool_device_error_returns_not_ok():
    client, _ = make_client()
    with ws_session(client) as ws:
        connect(ws)
        ws.send_json({"t": "text", "text": "nod"})
        ws.receive_json()
        ws.send_json({"t": "tool_result", "id": "c1", "ok": False, "error": "servo_stall"})
        ws.receive_json()
        assert "ok=False err=servo_stall" in ws.receive_json()["text"]


def test_tool_timeout_returns_not_ok():
    client, _ = make_client()
    with ws_session(client) as ws:
        connect(ws)
        ws.send_json({"t": "text", "text": "slow"})
        assert ws.receive_json()["t"] == "tool"
        assert ws.receive_json()["text"] == "ok=False err=timeout"


def test_malformed_json_gives_error_and_session_survives():
    client, _ = make_client()
    with ws_session(client) as ws:
        connect(ws)
        ws.send_text("{not json")
        err = ws.receive_json()
        assert err["t"] == "error" and err["code"] == "bad_frame"
        ws.send_text(json.dumps({"t": "nonsense"}))
        assert ws.receive_json()["code"] == "bad_frame"
        ws.send_bytes(b"\x01")  # too short: ignored
        ws.send_json({"t": "text", "text": "still alive"})
        assert ws.receive_json()["text"] == "got:still alive"


def test_ping_gets_pong():
    client, _ = make_client()
    with ws_session(client) as ws:
        connect(ws)
        ws.send_json({"t": "ping", "ts": 42})
        assert ws.receive_json() == {"t": "pong", "ts": 42}


def test_event_reaches_brain():
    client, _ = make_client()
    with ws_session(client) as ws:
        connect(ws)
        ws.send_json({"t": "event", "name": "touch", "where": "head", "data": {"k": 1}})
        assert ws.receive_json()["text"] == "event:touch:head:{'k': 1}"


def test_state_is_stored():
    client, _ = make_client()
    with ws_session(client) as ws:
        connect(ws)
        ws.send_json({"t": "state", "batt": 80, "pose": "tilted"})
        ws.send_json({"t": "text", "text": "state"})
        assert ws.receive_json()["text"] == "pose=tilted"


def test_audio_down_only_with_audio_out_cap():
    client, _ = make_client()
    with ws_session(client) as ws:
        connect(ws)  # caps include audio_out
        ws.send_json({"t": "text", "text": "audio"})
        f = unpack_binary(ws.receive_bytes())
        assert f.type == BinaryType.AUDIO_DOWN and f.seq == 0 and f.payload == b"\x01\x02"
        assert ws.receive_json()["t"] == "tts"
        assert ws.receive_json()["text"] == "done"
    with ws_session(client) as ws:
        connect(ws, {**HELLO, "caps": []})
        ws.send_json({"t": "text", "text": "audio"})
        assert ws.receive_json()["t"] == "tts"  # no binary frame first


def test_vad_barge_in_and_asr():
    brains: list[FakeBrain] = []

    def factory(body):
        brains.append(FakeBrain(body))
        return brains[-1]

    app = create_app(Settings(ping_interval_s=1000.0), factory, asr_factory=FakeASR)
    client = TestClient(app)
    with ws_session(client) as ws:
        connect(ws)
        ws.send_json({"t": "vad", "on": True})
        assert ws.receive_json()["text"] == "interrupted"
        ws.send_bytes(pack_binary(BinaryType.AUDIO_UP, 0, b"hel"))
        ws.send_bytes(pack_binary(BinaryType.AUDIO_UP, 1, b"lo"))
        ws.send_json({"t": "vad", "on": False})
        assert ws.receive_json()["text"] == "got:hello"


def test_vad_without_asr_still_interrupts():
    client, _ = make_client()
    with ws_session(client) as ws:
        connect(ws)
        ws.send_json({"t": "vad", "on": True})
        assert ws.receive_json()["text"] == "interrupted"
        ws.send_json({"t": "vad", "on": False})
        ws.send_json({"t": "ping"})
        assert ws.receive_json()["t"] == "pong"


def test_heartbeat_misses_close_4002():
    client, _ = make_client(ping_interval_s=0.05, ping_misses=2)
    with ws_session(client) as ws:
        connect(ws)
        got_ping = False
        with pytest.raises(WebSocketDisconnect) as ei:
            for _ in range(20):
                if ws.receive_json()["t"] == "ping":
                    got_ping = True
        assert got_ping
        assert ei.value.code == 4002


def test_heartbeat_answered_keeps_alive():
    client, _ = make_client(ping_interval_s=0.05, ping_misses=2)
    with ws_session(client) as ws:
        connect(ws)
        for _ in range(8):
            m = ws.receive_json()
            assert m["t"] == "ping"
            ws.send_json({"t": "pong", "ts": m["ts"]})
