"""One connected device = one `DeviceSession` (implements `BodyPort`, owns one `Brain`)."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from typing import Any, Callable, Coroutine

from pydantic import BaseModel, ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect

from embody.cloud.config import Settings
from embody.cloud.ports import ASR, BodyPort, Brain, ToolCall, ToolOutcome
from embody.proto import (
    BinaryType,
    Error,
    Event,
    Hello,
    Ping,
    Pong,
    Say,
    State,
    Text,
    Tool,
    ToolResult,
    Tts,
    Vad,
    Welcome,
    dump,
    pack_binary,
    parse_up,
    unpack_binary,
)

log = logging.getLogger("embody.gateway")

CLOSE_HANDSHAKE = 4000
CLOSE_AUTH = 4001
CLOSE_HEARTBEAT = 4002


class DeviceSession(BodyPort):
    def __init__(
        self,
        ws: WebSocket,
        settings: Settings,
        brain_factory: Callable[[BodyPort], Brain],
        asr: ASR | None = None,
        handshake_timeout_s: float = 5.0,
    ) -> None:
        self._ws = ws
        self._settings = settings
        self._brain_factory = brain_factory
        self._asr = asr
        self._handshake_timeout_s = handshake_timeout_s

        self.session_id: str = ""
        self._hello: Hello | None = None
        self._last_state: State | None = None
        self.brain: Brain | None = None

        self._pending: dict[str, asyncio.Future[ToolResult]] = {}
        self._tasks: set[asyncio.Task[Any]] = set()
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._dead = asyncio.Event()  # set when the heartbeat gives up
        self._rx_since_ping = False
        self._audio_seq = 0
        self._closed = False  # socket no longer usable
        self._cleaned = False
        self.last_pong: float = time.monotonic()
        self.close_reason: str = "disconnect"

    # ───────────────────────── BodyPort ─────────────────────────

    @property
    def hello(self) -> Hello:
        if self._hello is None:
            raise RuntimeError("handshake not completed")
        return self._hello

    @property
    def last_state(self) -> State | None:
        return self._last_state

    @property
    def device_id(self) -> str:
        return self._hello.dev if self._hello else "?"

    async def call_tool(self, call: ToolCall, timeout_s: float = 2.0) -> ToolOutcome:
        if self._closed:
            raise ConnectionError("device connection closed")
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[ToolResult] = loop.create_future()
        self._pending[call.id] = fut
        try:
            sent = await self._send_json(Tool(id=call.id, name=call.name, args=call.args))
            if not sent:
                raise ConnectionError("device connection closed")
            try:
                res = await asyncio.wait_for(fut, timeout_s)
            except asyncio.TimeoutError:
                log.warning("tool %s (%s) timed out on %s", call.name, call.id, self.device_id)
                return ToolOutcome(ok=False, error="timeout")
            if not res.ok:
                return ToolOutcome(ok=False, result=res.result, error=res.error or "device_error")
            return ToolOutcome(ok=True, result=res.result)
        finally:
            self._pending.pop(call.id, None)

    async def say(self, text: str, utterance_id: str, final: bool = False) -> None:
        await self._send_json(Say(text=text, utterance_id=utterance_id, final=final))

    async def send_audio(self, opus_frame: bytes) -> None:
        if "audio_out" not in self.hello.caps:
            return
        seq = self._audio_seq
        self._audio_seq = (self._audio_seq + 1) & 0xFFFF
        await self._send_bytes(pack_binary(BinaryType.AUDIO_DOWN, seq, opus_frame))

    async def tts_state(self, state: str, utterance_id: str) -> None:
        if state not in ("start", "end"):
            raise ValueError(f"bad tts state: {state!r}")
        await self._send_json(Tts(state=state, utterance_id=utterance_id))  # type: ignore[arg-type]

    # ───────────────────────── sending ─────────────────────────

    async def _send_json(self, frame: BaseModel) -> bool:
        if self._closed:
            return False
        try:
            await self._ws.send_text(dump(frame))
            return True
        except (WebSocketDisconnect, RuntimeError) as e:
            self._closed = True
            log.debug("send on closed socket (%s): %r", self.device_id, e)
            return False

    async def _send_bytes(self, data: bytes) -> bool:
        if self._closed:
            return False
        try:
            await self._ws.send_bytes(data)
            return True
        except (WebSocketDisconnect, RuntimeError) as e:
            self._closed = True
            log.debug("send on closed socket (%s): %r", self.device_id, e)
            return False

    async def _close_socket(self, code: int, reason: str = "") -> None:
        self.close_reason = f"{code} {reason}".strip()
        was_closed = self._closed
        self._closed = True
        if was_closed:
            return
        with contextlib.suppress(WebSocketDisconnect, RuntimeError):
            await self._ws.close(code=code, reason=reason)

    # ───────────────────────── lifecycle ─────────────────────────

    async def run(self) -> None:
        """Handshake then serve until disconnect. Caller must still call `close()`."""
        if await self.handshake():
            await self.serve()

    async def handshake(self) -> bool:
        try:
            msg = await asyncio.wait_for(self._ws.receive(), self._handshake_timeout_s)
        except asyncio.TimeoutError:
            await self._close_socket(CLOSE_HANDSHAKE, "hello timeout")
            return False
        except (WebSocketDisconnect, RuntimeError):
            self._closed = True
            self.close_reason = "disconnect before hello"
            return False
        if msg["type"] == "websocket.disconnect":
            self._closed = True
            self.close_reason = "disconnect before hello"
            return False
        raw = msg.get("text")
        hello: Any = None
        if raw is not None:
            try:
                hello = parse_up(raw)
            except (ValidationError, ValueError):
                hello = None
        if not isinstance(hello, Hello):
            await self._send_json(Error(code="bad_frame", msg="first frame must be hello"))
            await self._close_socket(CLOSE_HANDSHAKE, "expected hello")
            return False
        token = self._settings.device_token
        if token and hello.token != token:
            await self._send_json(Error(code="auth", msg="bad token"))
            await self._close_socket(CLOSE_AUTH, "auth")
            return False

        self._hello = hello
        self.session_id = uuid.uuid4().hex
        await self._send_json(Welcome(session=self.session_id))
        self.brain = self._brain_factory(self)
        log.info("device %s connected (session=%s fw=%s caps=%s)",
                 hello.dev, self.session_id, hello.fw, ",".join(hello.caps))
        return True

    async def serve(self) -> None:
        self._heartbeat_task = asyncio.create_task(self._heartbeat(), name="heartbeat")
        recv = asyncio.create_task(self._receive_loop(), name="receive")
        dead = asyncio.create_task(self._dead.wait(), name="dead")
        try:
            await asyncio.wait({recv, dead}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in (recv, dead):
                if not t.done():
                    t.cancel()
            await asyncio.gather(recv, dead, return_exceptions=True)
        if recv.done() and not recv.cancelled() and recv.exception():
            raise recv.exception()  # type: ignore[misc]

    async def close(self) -> None:
        if self._cleaned:
            return
        self._cleaned = True
        self._closed = True
        current = asyncio.current_task()
        to_cancel = [t for t in self._tasks if t is not current]
        if self._heartbeat_task is not None and self._heartbeat_task is not current:
            to_cancel.append(self._heartbeat_task)
        for t in to_cancel:
            t.cancel()
        if to_cancel:
            await asyncio.gather(*to_cancel, return_exceptions=True)
        self._tasks.clear()
        if self.brain is not None:
            try:
                await self.brain.close()
            except Exception:
                log.exception("brain.close failed for %s", self.device_id)
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_exception(ConnectionError("device connection closed"))
        self._pending.clear()

    # ───────────────────────── receive ─────────────────────────

    async def _receive_loop(self) -> None:
        while True:
            try:
                msg = await self._ws.receive()
            except (WebSocketDisconnect, RuntimeError):
                break
            if msg["type"] == "websocket.disconnect":
                self.close_reason = f"disconnect {msg.get('code', '')}".strip()
                break
            self._rx_since_ping = True
            try:
                if msg.get("text") is not None:
                    await self._on_text(msg["text"])
                elif msg.get("bytes") is not None:
                    await self._on_binary(msg["bytes"])
            except Exception:
                log.exception("error handling frame from %s", self.device_id)
        self._closed = True

    async def _on_text(self, raw: str) -> None:
        try:
            frame = parse_up(raw)
        except (ValidationError, ValueError) as e:
            log.debug("bad frame from %s: %s", self.device_id, e)
            await self._send_json(Error(code="bad_frame", msg=_short_err(e)))
            return
        brain = self.brain
        assert brain is not None
        if isinstance(frame, Text):
            self._spawn(brain.on_user_text(frame.text), "user_text")
        elif isinstance(frame, Event):
            self._spawn(brain.on_event(frame.name, frame.where, frame.data), "event")
        elif isinstance(frame, State):
            self._last_state = frame
        elif isinstance(frame, Vad):
            await self._on_vad(frame.on)
        elif isinstance(frame, ToolResult):
            fut = self._pending.get(frame.id)
            if fut is not None and not fut.done():
                fut.set_result(frame)
            else:
                log.debug("tool_result for unknown id %s", frame.id)
        elif isinstance(frame, Ping):
            await self._send_json(Pong(ts=frame.ts))
        elif isinstance(frame, Pong):
            self.last_pong = time.monotonic()
        elif isinstance(frame, Hello):
            log.debug("ignoring duplicate hello from %s", self.device_id)

    async def _on_vad(self, on: bool) -> None:
        brain = self.brain
        assert brain is not None
        if on:
            await brain.interrupt()
            if self._asr is not None:
                await self._asr.reset()
        elif self._asr is not None:
            self._spawn(self._finish_utterance(), "asr_finish")

    async def _finish_utterance(self) -> None:
        assert self._asr is not None and self.brain is not None
        text = (await self._asr.finish()).strip()
        if text:
            await self.brain.on_user_text(text)

    async def _on_binary(self, data: bytes) -> None:
        try:
            frame = unpack_binary(data)
        except ValueError as e:
            log.debug("bad binary frame from %s: %s", self.device_id, e)
            return
        if frame.type == BinaryType.AUDIO_UP and self._asr is not None:
            await self._asr.feed(frame.payload)

    def _spawn(self, coro: Coroutine[Any, Any, Any], name: str) -> asyncio.Task[Any]:
        task = asyncio.create_task(coro, name=f"{name}:{self.device_id}")
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            log.error("task %s failed: %r", task.get_name(), exc, exc_info=exc)

    # ───────────────────────── heartbeat ─────────────────────────

    async def _heartbeat(self) -> None:
        interval = self._settings.ping_interval_s
        limit = self._settings.ping_misses
        misses = 0
        sent_any = False
        while True:
            await asyncio.sleep(interval)
            if sent_any:
                misses = 0 if self._rx_since_ping else misses + 1
                if misses >= limit:
                    log.warning("device %s missed %d pings, closing", self.device_id, misses)
                    await self._close_socket(CLOSE_HEARTBEAT, "heartbeat")
                    self._dead.set()
                    return
            self._rx_since_ping = False
            sent_any = True
            await self._send_json(Ping(ts=int(time.time() * 1000)))


def _short_err(e: Exception) -> str:
    if isinstance(e, ValidationError):
        errs = e.errors(include_url=False, include_context=False, include_input=False)
        if errs:
            first = errs[0]
            loc = ".".join(str(x) for x in first.get("loc", ()))
            return f"{loc}: {first.get('msg', '')}"[:200]
    return str(e)[:200]
