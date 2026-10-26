"""WebSocket client that makes the software duck speak the Embody device protocol."""
from __future__ import annotations

import asyncio
import contextlib
import shutil
from typing import Any, Callable

from websockets.asyncio.client import connect

import embody
from embody.proto import (
    Error, Event, Hello, Ota, Ping, Pong, Say, State, Text, Tool, ToolResult, Tts, Vad, Welcome,
    dump, parse_down,
)

from .body import DuckBody

CAPS = ["text_in", "text_out", "servo_head", "servo_wing", "led_eyes", "touch", "imu"]


def _find_tts() -> list[str] | None:
    for cmd in ("say", "espeak-ng", "espeak"):
        if shutil.which(cmd):
            return [cmd]
    return None


def _join(prev: str, nxt: str) -> str:
    if prev and nxt and prev[-1].isascii() and nxt[0].isascii():
        return f"{prev} {nxt}"
    return prev + nxt


class DuckClient:
    def __init__(
        self,
        url: str,
        device_id: str,
        token: str | None,
        body: DuckBody,
        out: Callable[[str], None] = print,
        *,
        speak: bool = False,
        quiet: bool = False,
        backoff_base: float = 1.0,
        backoff_max: float = 30.0,
        offline_interval: float = 2.0,
        state_interval: float = 10.0,
        say_flush_delay: float = 0.5,
        welcome_timeout: float = 10.0,
    ) -> None:
        self.url = url
        self.device_id = device_id
        self.token = token
        self.body = body
        self.out = out
        self.speak = speak
        self.quiet = quiet
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self.offline_interval = offline_interval
        self.state_interval = state_interval
        self.say_flush_delay = say_flush_delay
        self.welcome_timeout = welcome_timeout

        self.binary_frames = 0
        self.session_id: str | None = None
        self.tts_cmd: list[str] | None = _find_tts() if speak else None

        self._ws: Any = None
        self._stop = asyncio.Event()
        self._text_q: asyncio.Queue[str] = asyncio.Queue()
        self._say_id: str | None = None
        self._say_text = ""
        self._say_timer: asyncio.TimerHandle | None = None
        self._speak_lock = asyncio.Lock()
        self._bg: set[asyncio.Task] = set()

    # ───────────────────────── output helpers ─────────────────────────

    def _info(self, msg: str) -> None:
        if not self.quiet:
            self.out(msg)

    def _show(self) -> None:
        if not self.quiet:
            self.out(self.body.render())

    # ───────────────────────── public send API ─────────────────────────

    @property
    def connected(self) -> bool:
        return self._ws is not None

    async def _send(self, frame) -> bool:
        ws = self._ws
        if ws is None:
            return False
        try:
            await ws.send(dump(frame))
        except Exception as e:  # connection closing; run() will notice
            self._info(f"(send failed: {e})")
            return False
        return True

    async def send_text(self, text: str) -> bool:
        """Queue a typed utterance. Returns False (and drops it) when offline."""
        if not self.connected:
            self.out("(offline: message not sent)")
            return False
        await self._text_q.put(text)
        return True

    async def send_event(self, name: str, where: str | None = None, data: dict | None = None) -> bool:
        return await self._send(Event(name=name, where=where, data=data or {}))

    async def send_vad(self, on: bool) -> bool:
        return await self._send(Vad(on=on))

    def _state_frame(self) -> State:
        b = self.body
        return State(
            batt=100, rssi=-50, pose=b.pose, emotion=b.emotion, busy=b.speaking,
            extra={"touched": b.touched, "asleep": b.asleep},
        )

    async def send_state(self) -> bool:
        return await self._send(self._state_frame())

    async def stop(self) -> None:
        self._stop.set()
        self._flush_say()
        ws = self._ws
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()

    # ───────────────────────── connection loop ─────────────────────────

    async def run(self) -> None:
        delay = self.backoff_base
        while not self._stop.is_set():
            connected_ok = False
            try:
                async with connect(self.url, max_size=None) as ws:
                    await self._handshake(ws)
                    connected_ok = True
                    delay = self.backoff_base
                    await self._session(ws)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if not self._stop.is_set():
                    what = "disconnected" if connected_ok else f"cannot connect to {self.url}"
                    self._info(f"({what}: {type(e).__name__}: {e})")
            finally:
                self._ws = None
                self.body.online = False
                self.body.speaking = False
                self._flush_say()
            if self._stop.is_set():
                break
            self._show()
            await self._offline_wait(delay)
            delay = min(delay * 2, self.backoff_max)

    async def _offline_wait(self, delay: float) -> None:
        loop = asyncio.get_running_loop()
        end = loop.time() + delay
        while not self._stop.is_set():
            remaining = end - loop.time()
            if remaining <= 0:
                return
            step = min(self.offline_interval, remaining)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=step)
                return
            except TimeoutError:
                pass
            if step >= self.offline_interval:
                frame = self.body.offline_tick()
                if frame is not None and not self.quiet:
                    self.out(frame)

    async def _handshake(self, ws) -> None:
        hello = Hello(dev=self.device_id, fw=embody.__version__, caps=CAPS, token=self.token)
        await ws.send(dump(hello))
        raw = await asyncio.wait_for(ws.recv(), timeout=self.welcome_timeout)
        if isinstance(raw, bytes):
            raise ConnectionError("binary frame before welcome")
        frame = parse_down(raw)
        if isinstance(frame, Error):
            raise ConnectionError(f"rejected by gateway: {frame.code} {frame.msg}")
        if not isinstance(frame, Welcome):
            raise ConnectionError(f"expected welcome, got {frame.t}")
        self._ws = ws
        self.session_id = frame.session
        self.body.online = True
        self._info(f"(connected to {self.url} as {self.device_id}, session {frame.session})")
        self._show()

    async def _session(self, ws) -> None:
        tasks = [
            asyncio.create_task(self._recv_loop(ws)),
            asyncio.create_task(self._text_loop()),
            asyncio.create_task(self._state_loop()),
        ]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                t.result()  # re-raise ConnectionClosed etc.
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _text_loop(self) -> None:
        while True:
            text = await self._text_q.get()
            await self._send(Text(text=text))

    async def _state_loop(self) -> None:
        while True:
            await asyncio.sleep(self.state_interval)
            await self.send_state()

    async def _recv_loop(self, ws) -> None:
        async for raw in ws:
            if isinstance(raw, (bytes, bytearray)):
                self.binary_frames += 1
                continue
            try:
                frame = parse_down(raw)
            except Exception as e:
                self.out(f"(warning: bad frame ignored: {str(e).splitlines()[0] if str(e) else type(e).__name__})")
                continue
            await self._handle(frame)

    # ───────────────────────── frame handling ─────────────────────────

    async def _handle(self, frame) -> None:
        if isinstance(frame, Tool):
            ok, result, error = self.body.apply_tool(frame.name, frame.args)
            await self._send(ToolResult(id=frame.id, ok=ok, result=result, error=error))
            if not self.quiet:
                self.out(f"(tool {frame.name} {frame.args} -> {'ok' if ok else 'ERROR ' + str(error)})")
            self._show()
        elif isinstance(frame, Say):
            self._on_say(frame)
        elif isinstance(frame, Tts):
            self.body.speaking = frame.state == "start"
            if frame.state == "end":
                self._flush_say()
        elif isinstance(frame, Ping):
            await self._send(Pong(ts=frame.ts))
        elif isinstance(frame, Pong):
            pass
        elif isinstance(frame, Error):
            self.out(f"(cloud error {frame.code}: {frame.msg})")
        elif isinstance(frame, Ota):
            self.out(f"(OTA requested v{frame.ver} (sim ignores))")
        # Welcome mid-session: ignore

    # ───────────────────────── say / speak ─────────────────────────

    def _on_say(self, frame: Say) -> None:
        if self._say_id != frame.utterance_id or frame.utterance_id is None:
            self._flush_say()
        self._say_id = frame.utterance_id
        self._say_text = _join(self._say_text, frame.text.strip()) if self._say_text else frame.text.strip()
        if self.speak:
            self._spawn(self._speak(frame.text))
        if self._say_timer is not None:
            self._say_timer.cancel()
            self._say_timer = None
        if frame.final or frame.utterance_id is None:
            self._flush_say()
        else:
            self._say_timer = asyncio.get_running_loop().call_later(self.say_flush_delay, self._flush_say)

    def _flush_say(self) -> None:
        if self._say_timer is not None:
            self._say_timer.cancel()
            self._say_timer = None
        text, self._say_text, self._say_id = self._say_text, "", None
        if text:
            self.out(f"🦆 {text}")

    def _spawn(self, coro) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    async def _speak(self, text: str) -> None:
        if not self.tts_cmd or not text.strip():
            return
        async with self._speak_lock:  # keep sentences in order
            try:
                proc = await asyncio.create_subprocess_exec(
                    *self.tts_cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                assert proc.stdin is not None
                proc.stdin.write(text.encode())
                await proc.stdin.drain()
                proc.stdin.close()
                await proc.wait()
            except asyncio.CancelledError:
                raise
            except Exception:
                pass  # TTS is best-effort
