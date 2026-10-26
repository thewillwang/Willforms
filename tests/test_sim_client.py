import asyncio
import json
from contextlib import suppress

import pytest
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

import embody
from embody.proto import parse_up
from embody.sim import DuckBody, DuckClient

T = 5.0  # generic timeout


class FakeGateway:
    """Tiny stand-in for the cloud gateway; records frames, lets tests push frames."""

    def __init__(self):
        self.server = None
        self.port = 0
        self.conns = []
        self.frames: asyncio.Queue = asyncio.Queue()  # (conn_index, parsed-or-raw frame)
        self.hellos = 0

    async def _handler(self, ws):
        self.conns.append(ws)
        raw = await ws.recv()
        hello = parse_up(raw)
        assert hello.t == "hello"
        self.hellos += 1
        await self.frames.put(hello)
        await ws.send(json.dumps({"t": "welcome", "session": f"s{self.hellos}"}))
        try:
            async for raw in ws:
                await self.frames.put(parse_up(raw))
        except ConnectionClosed:
            pass

    async def start(self, port=0):
        self.server = await serve(self._handler, "127.0.0.1", port)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    @property
    def url(self):
        return f"ws://127.0.0.1:{self.port}/ws"

    async def next(self, t=None):
        while True:
            f = await asyncio.wait_for(self.frames.get(), T)
            if t is None or f.t == t:
                return f

    async def send(self, obj):
        await self.conns[-1].send(json.dumps(obj))

    async def stop(self):
        self.server.close()
        for c in self.conns:
            with suppress(Exception):
                await c.close()
        await asyncio.wait_for(self.server.wait_closed(), T)


async def wait_for(pred, timeout=T):
    async def poll():
        while not pred():
            await asyncio.sleep(0.01)
    await asyncio.wait_for(poll(), timeout)


@pytest.fixture
async def gw():
    g = await FakeGateway().start()
    yield g
    with suppress(Exception):
        await g.stop()


def make_client(gw, out, body=None, **kw):
    kw.setdefault("backoff_base", 0.05)
    kw.setdefault("offline_interval", 0.01)
    body = body or DuckBody()
    return DuckClient(gw.url, "sim-test", "tok123", body, out.append, **kw), body


async def start(client):
    task = asyncio.create_task(client.run())
    return task


async def shutdown(client, task):
    await client.stop()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_hello_welcome_tool_say_ping(gw):
    out = []
    client, body = make_client(gw, out)
    task = await start(client)
    try:
        hello = await gw.next("hello")
        assert hello.dev == "sim-test" and hello.token == "tok123"
        assert hello.fw == embody.__version__
        assert set(hello.caps) == {"text_in", "text_out", "servo_head", "servo_wing", "led_eyes", "touch", "imu"}
        await wait_for(lambda: body.online)

        await gw.send({"t": "tool", "id": "c1", "name": "set_emotion", "args": {"emotion": "happy"}})
        res = await gw.next("tool_result")
        assert res.id == "c1" and res.ok and res.error is None
        assert body.emotion == "happy"
        assert any("warm-yellow" in line for line in out)  # render reprinted

        await gw.send({"t": "tool", "id": "c2", "name": "get_state", "args": {}})
        res = await gw.next("tool_result")
        assert res.ok and res.result["emotion"] == "happy" and res.result["batt"] == 100

        await gw.send({"t": "tool", "id": "c3", "name": "set_emotion", "args": {"emotion": "bogus"}})
        res = await gw.next("tool_result")
        assert res.id == "c3" and not res.ok and res.error

        await gw.send({"t": "tool", "id": "c4", "name": "teleport", "args": {}})
        res = await gw.next("tool_result")
        assert not res.ok and "teleport" in res.error

        await gw.send({"t": "tts", "state": "start", "utterance_id": "u1"})
        await wait_for(lambda: body.speaking)
        await gw.send({"t": "say", "text": "Hello there.", "utterance_id": "u1"})
        await gw.send({"t": "say", "text": "How are you?", "utterance_id": "u1", "final": True})
        await gw.send({"t": "tts", "state": "end", "utterance_id": "u1"})
        await wait_for(lambda: not body.speaking)
        await wait_for(lambda: "🦆 Hello there. How are you?" in out)

        await gw.send({"t": "ping", "ts": 42})
        pong = await gw.next("pong")
        assert pong.ts == 42
    finally:
        await shutdown(client, task)


async def test_say_other_utterances_and_misc_frames(gw):
    out = []
    client, body = make_client(gw, out, say_flush_delay=0.05)
    task = await start(client)
    try:
        await gw.next("hello")
        await wait_for(lambda: body.online)
        await gw.send({"t": "say", "text": "one", "utterance_id": "a"})
        await gw.send({"t": "say", "text": "two", "utterance_id": "b", "final": True})
        await wait_for(lambda: "🦆 two" in out)
        assert "🦆 one" in out
        # no final: flushed by timer
        await gw.send({"t": "say", "text": "lonely", "utterance_id": "c"})
        await wait_for(lambda: "🦆 lonely" in out)
        # misc frames
        await gw.send({"t": "pong"})
        await gw.send({"t": "error", "code": "rate", "msg": "slow down"})
        await gw.send({"t": "ota", "url": "http://x", "sha256": "0" * 64, "ver": "9.9.9"})
        await wait_for(lambda: any("OTA requested v9.9.9 (sim ignores)" in line for line in out))
        assert any("rate" in line and "slow down" in line for line in out)
        # binary + garbage are survived
        await gw.conns[-1].send(b"\x02\x00\x01abc")
        await gw.conns[-1].send("not json at all")
        await gw.conns[-1].send(json.dumps({"t": "nonsense"}))
        await wait_for(lambda: client.binary_frames == 1)
        await wait_for(lambda: sum("warning" in line for line in out) >= 2)
        await gw.send({"t": "ping"})
        await gw.next("pong")  # still alive
    finally:
        await shutdown(client, task)


async def test_client_sends(gw):
    out = []
    client, body = make_client(gw, out)
    task = await start(client)
    try:
        await gw.next("hello")
        await wait_for(lambda: body.online)
        assert await client.send_text("你好, duck")
        f = await gw.next("text")
        assert f.text == "你好, duck"
        await client.send_event("touch", where="head")
        f = await gw.next("event")
        assert (f.name, f.where) == ("touch", "head")
        await client.send_event("custom", data={"k": 1})
        f = await gw.next("event")
        assert f.name == "custom" and f.where is None and f.data == {"k": 1}
        await client.send_vad(True)
        assert (await gw.next("vad")).on is True
        await client.send_vad(False)
        assert (await gw.next("vad")).on is False
        body.pose = "picked_up"
        await client.send_state()
        s = await gw.next("state")
        assert s.pose == "picked_up" and s.batt == 100 and s.rssi == -50 and s.emotion == "neutral"
    finally:
        await shutdown(client, task)


async def test_periodic_state(gw):
    out = []
    client, body = make_client(gw, out, state_interval=0.05)
    task = await start(client)
    try:
        await gw.next("hello")
        a = await gw.next("state")
        b = await gw.next("state")
        assert a.t == b.t == "state"
    finally:
        await shutdown(client, task)


async def test_offline_send_text_dropped():
    out = []
    client = DuckClient("ws://127.0.0.1:1/ws", "x", None, DuckBody(), out.append)
    assert await client.send_text("hi") is False
    assert await client.send_event("touch") is False
    assert await client.send_state() is False
    assert any("offline" in line for line in out)


async def test_offline_then_reconnect(gw):
    out = []
    client, body = make_client(gw, out)
    port = gw.port
    task = await start(client)
    try:
        await gw.next("hello")
        await wait_for(lambda: body.online)
        n = len(out)

        await gw.stop()
        await wait_for(lambda: not body.online)
        assert not client.connected
        # offline persona shows up
        await wait_for(lambda: any("OFFLINE" in line for line in out[n:]))
        await wait_for(lambda: any("嘎" in line for line in out[n:]))

        # gateway returns on the same port -> client reconnects and re-hellos
        gw2 = FakeGateway()
        await gw2.start(port)
        try:
            hello = await gw2.next("hello")
            assert hello.dev == "sim-test"
            await wait_for(lambda: body.online)
            await client.send_text("back again")
            assert (await gw2.next("text")).text == "back again"
        finally:
            await gw2.stop()
    finally:
        await shutdown(client, task)
    assert not body.online


async def test_rejected_by_gateway_retries_with_backoff():
    """Gateway answers hello with an error frame and closes: client must not go online."""
    attempts = []

    async def handler(ws):
        await ws.recv()
        attempts.append(1)
        await ws.send(json.dumps({"t": "error", "code": "auth", "msg": "bad token"}))
        await ws.close()

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        out = []
        body = DuckBody()
        client = DuckClient(f"ws://127.0.0.1:{port}/ws", "x", "bad", body, out.append,
                            backoff_base=0.02, offline_interval=0.005)
        task = asyncio.create_task(client.run())
        try:
            await wait_for(lambda: len(attempts) >= 3)
            assert not body.online
            assert any("bad token" in line for line in out)
        finally:
            await shutdown(client, task)


async def test_quiet_suppresses_renders_but_not_speech(gw):
    out = []
    client, body = make_client(gw, out, quiet=True, say_flush_delay=0.02)
    task = await start(client)
    try:
        await gw.next("hello")
        await wait_for(lambda: body.online)
        await gw.send({"t": "tool", "id": "q", "name": "set_emotion", "args": {"emotion": "sad"}})
        await gw.next("tool_result")
        await gw.send({"t": "say", "text": "hi", "utterance_id": "u", "final": True})
        await wait_for(lambda: "🦆 hi" in out)
        assert out == ["🦆 hi"]
    finally:
        await shutdown(client, task)


async def test_speak_pipes_text_to_tts(gw, tmp_path):
    script = tmp_path / "fake_tts.sh"
    log = tmp_path / "spoken.txt"
    script.write_text(f"#!/bin/sh\ncat >> {log}\necho >> {log}\n")
    script.chmod(0o755)
    out = []
    client, body = make_client(gw, out, speak=True)
    client.tts_cmd = [str(script)]
    task = await start(client)
    try:
        await gw.next("hello")
        await wait_for(lambda: body.online)
        await gw.send({"t": "say", "text": "first.", "utterance_id": "u"})
        await gw.send({"t": "say", "text": "second.", "utterance_id": "u", "final": True})
        await wait_for(lambda: log.exists() and log.read_text().count("\n") >= 2)
        assert log.read_text().split("\n")[:2] == ["first.", "second."]
    finally:
        await shutdown(client, task)


async def test_speak_without_tts_binary_is_harmless(gw):
    out = []
    client, body = make_client(gw, out, speak=True)
    client.tts_cmd = ["/nonexistent/tts-binary"]
    task = await start(client)
    try:
        await gw.next("hello")
        await wait_for(lambda: body.online)
        await gw.send({"t": "say", "text": "hello", "utterance_id": "u", "final": True})
        await wait_for(lambda: "🦆 hello" in out)
        await asyncio.sleep(0.05)
        await gw.send({"t": "ping"})
        await gw.next("pong")
    finally:
        await shutdown(client, task)
