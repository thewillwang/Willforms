"""ClaudeBrain: one agent turn per user utterance (docs/02-architecture.md §5).

Per turn:
  1. assemble messages (recent history + this utterance) and the system prompt
  2. stream Claude; every tool_use block is dispatched to the body the moment
     its content block closes (not when the whole message is done)
  3. text deltas are chunked into sentences and spoken in order by a speech
     worker, so TTS never blocks reading the stream or dispatching tools
  4. tool results go back to the model (up to MAX_TOOL_ROUNDS), then the turn
     is written to memory and its latency recorded

History stored in Memory is always valid to replay: every assistant tool_use
is followed by a user message holding its tool_result. Thinking blocks are
replayed within a turn's tool loop but not stored across turns (see
``_history_content``).
"""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import anthropic

from embody.cloud.config import Settings
from embody.cloud.ports import TTS, BodyPort, Brain, Memory, Telemetry, ToolCall, ToolOutcome, TurnTimer
from embody.proto.tools import PHASE0_TOOLS, tool_names

from .chunker import SentenceChunker
from .persona import build_system_prompt

log = logging.getLogger("embody.brain")

FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOOL_ROUNDS = 4

APOLOGY = "嘎……我脑子有点卡，再说一遍？"
REFUSAL_DEFLECTION = "这个我不太方便说呢。"
EVENT_PREFIX = "[身体事件]"

_TOOLS_BY_NAME: dict[str, dict] = {t["name"]: t for t in PHASE0_TOOLS}
_STRIP_FROM_HISTORY = {"thinking", "redacted_thinking", "fallback"}


# ───────────────────────── helpers ─────────────────────────

def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _block_param(block: Any) -> dict[str, Any]:
    """Response content block → request content block param (only fields the API accepts back)."""
    btype = _get(block, "type")
    if btype == "text":
        return {"type": "text", "text": _get(block, "text", "")}
    if btype == "tool_use":
        return {"type": "tool_use", "id": _get(block, "id"), "name": _get(block, "name"), "input": _get(block, "input") or {}}
    if btype == "thinking":
        return {"type": "thinking", "thinking": _get(block, "thinking", ""), "signature": _get(block, "signature", "")}
    if btype == "redacted_thinking":
        return {"type": "redacted_thinking", "data": _get(block, "data", "")}
    if isinstance(block, dict):
        return dict(block)
    if hasattr(block, "model_dump"):
        return block.model_dump(mode="json", exclude_none=True)
    return {k: v for k, v in vars(block).items() if v is not None}


def _echo_content(content: list[Any]) -> list[dict[str, Any]]:
    """Assistant content to send back within the turn.

    After a mid-output server-side fallback, model-internal blocks (thinking,
    tool_use) that precede the last ``fallback`` marker belong to the declined
    attempt and must not be echoed. Empty text blocks are rejected by the API.
    """
    params = [_block_param(b) for b in content]
    last_fb = max((i for i, b in enumerate(params) if b.get("type") == "fallback"), default=-1)
    out: list[dict[str, Any]] = []
    for i, b in enumerate(params):
        t = b.get("type")
        if i < last_fb and t in ("thinking", "redacted_thinking", "tool_use"):
            continue
        if t == "text" and not (b.get("text") or "").strip():
            continue
        out.append(b)
    return out


def _history_content(echo: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assistant content as stored in Memory.

    Thinking blocks are bound to the exact conversation prefix that produced
    them; the history window slides and the volatile system block changes,
    so replaying them on later turns would be rejected. Store text/tool_use only.
    """
    return [b for b in echo if b.get("type") not in _STRIP_FROM_HISTORY]


def _tool_use_ids(content: Any) -> list[str]:
    if not isinstance(content, list):
        return []
    return [b["id"] for b in content if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id")]


def _tool_result_ids(content: Any) -> list[str]:
    if not isinstance(content, list):
        return []
    return [b.get("tool_use_id") for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]


def sanitize_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Make a stored history window safe to send.

    - starts with a plain user message (a window cut can leave a leading
      assistant turn or an orphan tool_result message)
    - every assistant tool_use is answered by the next user message; unanswered
      tool_use blocks are dropped, orphan tool_result blocks are dropped.
    """
    msgs = [m for m in history if isinstance(m, dict) and m.get("role") in ("user", "assistant")]
    out: list[dict[str, Any]] = []
    for idx, m in enumerate(msgs):
        role, content = m["role"], m.get("content")
        if role == "assistant":
            ids = _tool_use_ids(content)
            if ids:
                nxt = msgs[idx + 1] if idx + 1 < len(msgs) else None
                answered = set(_tool_result_ids(nxt.get("content"))) if nxt and nxt.get("role") == "user" else set()
                if not set(ids) <= answered:
                    content = [b for b in content if not (isinstance(b, dict) and b.get("type") == "tool_use")]
            if isinstance(content, list) and not content:
                continue
            if not out:
                continue  # history must start with a user turn
            out.append({"role": "assistant", "content": content})
        else:
            if isinstance(content, list) and _tool_result_ids(content):
                prev_ids = set(_tool_use_ids(out[-1]["content"])) if out and out[-1]["role"] == "assistant" else set()
                content = [
                    b for b in content
                    if not (isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") not in prev_ids)
                ]
                if not content:
                    continue
            if not out and isinstance(content, list) and _tool_result_ids(content):
                continue
            out.append({"role": "user", "content": content})
    return out


def validate_tool_input(name: str, args: Any) -> str | None:
    """Return an error string if ``args`` does not fit the tool's schema (shallow check)."""
    tool = _TOOLS_BY_NAME.get(name)
    if tool is None:
        return f"unknown tool {name!r}"
    if not isinstance(args, dict):
        return "tool input must be a JSON object"
    schema = tool.get("input_schema", {})
    props: dict[str, Any] = schema.get("properties", {})
    for key in schema.get("required", []):
        if key not in args:
            return f"missing required argument {key!r}"
    for key, value in args.items():
        spec = props.get(key)
        if spec is None:
            if schema.get("additionalProperties") is False:
                return f"unexpected argument {key!r}"
            continue
        enum = spec.get("enum")
        if enum is not None and value not in enum:
            return f"{key!r} must be one of {enum}"
        if spec.get("type") == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return f"{key!r} must be a number"
            if "minimum" in spec and value < spec["minimum"]:
                return f"{key!r} must be >= {spec['minimum']}"
            if "maximum" in spec and value > spec["maximum"]:
                return f"{key!r} must be <= {spec['maximum']}"
        if spec.get("type") == "string" and not isinstance(value, str):
            return f"{key!r} must be a string"
    return None


@dataclass
class _PendingTool:
    id: str
    name: str
    task: asyncio.Task | None = None
    outcome: ToolOutcome | None = None  # set immediately when rejected


@dataclass
class _Turn:
    uid: str
    timer: TurnTimer
    chunker: SentenceChunker = field(default_factory=SentenceChunker)
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    marks: set[str] = field(default_factory=set)
    unpersisted_speech: list[str] = field(default_factory=list)
    tools: list[_PendingTool] = field(default_factory=list)

    def mark_once(self, key: str) -> None:
        if key not in self.marks:
            self.marks.add(key)
            self.timer.mark(key)

    def speak(self, sentence: str) -> None:
        if sentence:
            self.unpersisted_speech.append(sentence)
            self.queue.put_nowait(sentence)


# ───────────────────────── the brain ─────────────────────────

class ClaudeBrain(Brain):
    def __init__(
        self,
        body: BodyPort,
        memory: Memory,
        telemetry: Telemetry,
        settings: Settings,
        tts: TTS | None = None,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        self.body = body
        self.memory = memory
        self.telemetry = telemetry
        self.settings = settings
        self.tts = tts
        self._client = client
        self._owns_client = client is None
        self._turn: asyncio.Task | None = None
        self._cur: _Turn | None = None
        self._tts_open: str | None = None  # utterance id with a "start" but no "end" yet
        self._seq = itertools.count(1)

    # ── public API ──

    @property
    def device_id(self) -> str:
        return self.body.hello.dev

    @property
    def client(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            self._client = anthropic.AsyncAnthropic()
        return self._client

    async def on_user_text(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        if self._turn is not None and not self._turn.done():
            await self.interrupt()
        task = asyncio.create_task(self._run_turn(text), name=f"brain-turn-{self.device_id}")
        self._turn = task
        try:
            await asyncio.wait({task})
        except asyncio.CancelledError:
            task.cancel()
            raise
        if not task.cancelled():
            task.result()  # propagate unexpected errors (e.g. dead connection)

    async def on_event(self, name: str, where: str | None, data: dict[str, Any]) -> None:
        if name == "touch":
            text = f"{EVENT_PREFIX} 有人摸了你的{where or '头'}"
        elif name == "picked_up":
            text = f"{EVENT_PREFIX} 你被拿起来了"
        else:
            detail = json.dumps(data or {}, ensure_ascii=False, sort_keys=True)
            text = f"{EVENT_PREFIX} {name} {detail}" if not where else f"{EVENT_PREFIX} {name} {where} {detail}"
        await self.on_user_text(text)

    async def interrupt(self) -> None:
        task = self._turn
        if task is not None and not task.done():
            task.cancel()
            await asyncio.wait({task})
        await self._end_tts()

    async def close(self) -> None:
        await self.interrupt()
        if self._owns_client and self._client is not None:
            try:
                await self._client.close()
            except Exception:  # pragma: no cover - best effort
                log.debug("client close failed", exc_info=True)
            self._client = None

    # ── speech ──

    async def _speak(self, text: str, utterance_id: str) -> None:
        if self._tts_open != utterance_id:
            await self.body.tts_state("start", utterance_id)
            self._tts_open = utterance_id
        await self.body.say(text, utterance_id)
        cur = self._cur
        if cur is not None and cur.uid == utterance_id:
            cur.mark_once("first_say")
        if self.tts is not None:
            async for frame in self.tts.synthesize(text):
                await self.body.send_audio(frame)
                if cur is not None and cur.uid == utterance_id:
                    cur.mark_once("tts_first_audio")

    async def _end_tts(self) -> None:
        uid = self._tts_open
        if uid is not None:
            self._tts_open = None
            try:
                await self.body.tts_state("end", uid)
            except Exception:
                log.warning("could not send tts end for %s", uid, exc_info=True)

    async def _speech_worker(self, cur: _Turn) -> None:
        while True:
            sentence = await cur.queue.get()
            if sentence is None:
                return
            await self._speak(sentence, cur.uid)

    # ── the turn ──

    async def _run_turn(self, text: str) -> None:
        dev = self.device_id
        uid = f"{dev}-{next(self._seq)}"
        timer = self.telemetry.turn_start(dev)
        cur = _Turn(uid=uid, timer=timer)
        self._cur = cur
        worker = asyncio.create_task(self._speech_worker(cur), name=f"brain-speech-{uid}")
        finished = False
        try:
            history = sanitize_history(await self.memory.history(dev, self.settings.history_turns))
            await self.memory.append_turn(dev, "user", text)
            messages: list[dict[str, Any]] = history + [{"role": "user", "content": text}]
            memories = await self.memory.recall(dev)
            system = build_system_prompt(self.settings.persona, list(self.body.hello.caps), memories)
            try:
                await self._agent_loop(messages, system, cur)
            except anthropic.RateLimitError as e:
                log.warning("rate limited (%s): %s", getattr(e, "request_id", None), e)
                cur.speak(APOLOGY)
            except anthropic.APIStatusError as e:
                log.error("API error %s (%s): %s", e.status_code, getattr(e, "request_id", None), e)
                cur.speak(APOLOGY)
            except anthropic.APIConnectionError as e:
                log.error("API connection error: %s", e)
                cur.speak(APOLOGY)
            except ValueError:
                log.exception("unparseable model output after retry")
                cur.speak(APOLOGY)
            cur.queue.put_nowait(None)
            await worker
            finished = True
        except asyncio.CancelledError:
            log.info("turn %s interrupted", uid)
            await asyncio.shield(self._persist_interrupted(cur))
            raise
        finally:
            for p in cur.tools:
                if p.task is not None and not p.task.done():
                    p.task.cancel()
            if not worker.done():
                worker.cancel()
                await asyncio.wait({worker})
            if finished:
                await self._end_tts()
            else:
                await asyncio.shield(self._end_tts())
            timer.mark("turn_end")
            timer.finish()
            if self._cur is cur:
                self._cur = None

    async def _persist_interrupted(self, cur: _Turn) -> None:
        """Keep what was already said, so the model knows it got cut off."""
        if not cur.unpersisted_speech:
            return
        said = "".join(cur.unpersisted_speech) + "……"
        cur.unpersisted_speech.clear()
        try:
            await self.memory.append_turn(self.device_id, "assistant", [{"type": "text", "text": said}])
        except Exception:
            log.warning("could not persist interrupted speech", exc_info=True)

    async def _persist(self, cur: _Turn, *turns: tuple[str, Any]) -> None:
        for role, content in turns:
            await self.memory.append_turn(self.device_id, role, content)
        cur.unpersisted_speech.clear()

    def _open_stream(self, messages: list[dict[str, Any]], system: list[dict]):
        s = self.settings
        kw: dict[str, Any] = dict(
            model=s.model,
            max_tokens=s.max_tokens,
            system=system,
            tools=PHASE0_TOOLS,
            messages=list(messages),
            output_config={"effort": s.effort},
        )
        if s.fallbacks:
            return self.client.beta.messages.stream(betas=[FALLBACK_BETA], fallbacks="default", **kw)
        return self.client.messages.stream(**kw)

    async def _agent_loop(self, messages: list[dict[str, Any]], system: list[dict], cur: _Turn) -> None:
        for round_no in range(MAX_TOOL_ROUNDS + 1):
            final = await self._round_with_retry(messages, system, cur)
            rest = cur.chunker.flush()
            if rest:
                cur.speak(rest)
            stop = _get(final, "stop_reason")
            echo = _echo_content(list(_get(final, "content") or []))
            tool_blocks = [b for b in echo if b.get("type") == "tool_use"]

            if stop == "refusal":
                details = _get(final, "stop_details")
                log.warning("refusal (category=%s)", _get(details, "category"))
                self._cancel_tools(cur)
                cur.speak(REFUSAL_DEFLECTION)
                await self._persist(cur, ("assistant", [{"type": "text", "text": REFUSAL_DEFLECTION}]))
                return

            if stop == "max_tokens" and tool_blocks:
                log.warning("max_tokens with %d pending tool_use block(s); not running them", len(tool_blocks))
                self._cancel_tools(cur)
                content = [b for b in _history_content(echo) if b.get("type") != "tool_use"]
                if content:
                    await self._persist(cur, ("assistant", content))
                return

            if not tool_blocks:
                content = _history_content(echo)
                if content:
                    await self._persist(cur, ("assistant", content))
                return

            results = await self._collect_results(cur, tool_blocks)
            messages.append({"role": "assistant", "content": echo})
            messages.append({"role": "user", "content": results})
            await asyncio.shield(self._persist(cur, ("assistant", _history_content(echo)), ("user", results)))
            cur.tools.clear()
            if round_no == MAX_TOOL_ROUNDS:
                log.warning("tool round limit (%d) reached; ending turn", MAX_TOOL_ROUNDS)
                return

    async def _round_with_retry(self, messages: list[dict[str, Any]], system: list[dict], cur: _Turn) -> Any:
        for attempt in (0, 1):
            try:
                return await self._stream_round(messages, system, cur)
            except ValueError:
                if attempt:
                    raise
                log.warning("unparseable tool input from stream; retrying round once", exc_info=True)
                self._cancel_tools(cur)
                cur.tools.clear()
                cur.chunker.flush()
        raise AssertionError("unreachable")

    async def _stream_round(self, messages: list[dict[str, Any]], system: list[dict], cur: _Turn) -> Any:
        async with self._open_stream(messages, system) as stream:
            async for event in stream:
                etype = _get(event, "type")
                if etype == "content_block_delta":
                    delta = _get(event, "delta")
                    if _get(delta, "type") == "text_delta":
                        cur.mark_once("llm_first_token")
                        for sentence in cur.chunker.feed(_get(delta, "text") or ""):
                            cur.speak(sentence)
                elif etype == "content_block_stop":
                    block = stream.current_message_snapshot.content[event.index]
                    btype = _get(block, "type")
                    if btype == "text":
                        rest = cur.chunker.flush()
                        if rest:
                            cur.speak(rest)
                    elif btype == "tool_use":
                        cur.mark_once("llm_first_tool")
                        self._dispatch(cur, block)
                        await asyncio.sleep(0)  # let the tool frame go out before more speech
            return await stream.get_final_message()

    # ── tools ──

    def _dispatch(self, cur: _Turn, block: Any) -> None:
        tid, name, args = _get(block, "id"), _get(block, "name"), _get(block, "input")
        if any(p.id == tid for p in cur.tools):
            return
        pending = _PendingTool(id=tid, name=name)
        error = None if name in tool_names() else f"unknown tool {name!r}"
        error = error or validate_tool_input(name, args)
        if error:
            log.warning("rejected tool call %s %s: %s", name, args, error)
            pending.outcome = ToolOutcome(ok=False, error=error)
        else:
            log.debug("dispatch %s %s", name, args)
            pending.task = asyncio.create_task(self.body.call_tool(ToolCall(tid, name, dict(args))))
        cur.tools.append(pending)

    def _cancel_tools(self, cur: _Turn) -> None:
        for p in cur.tools:
            if p.task is not None and not p.task.done():
                p.task.cancel()

    async def _collect_results(self, cur: _Turn, tool_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        known = {p.id for p in cur.tools}
        for b in tool_blocks:  # anything the stream did not close for us
            if b["id"] not in known:
                self._dispatch(cur, b)
        by_id = {p.id: p for p in cur.tools}
        results: list[dict[str, Any]] = []
        for b in tool_blocks:
            p = by_id[b["id"]]
            outcome = p.outcome
            if outcome is None:
                assert p.task is not None
                try:
                    outcome = await p.task
                except asyncio.CancelledError:
                    if asyncio.current_task().cancelling():
                        raise
                    outcome = ToolOutcome(ok=False, error="cancelled")
                except Exception as e:
                    log.warning("tool %s failed: %s", p.name, e)
                    outcome = ToolOutcome(ok=False, error=str(e) or type(e).__name__)
            if p.name == "get_state" and not outcome.ok and self.body.last_state is not None:
                state = self.body.last_state.model_dump(exclude_none=True)
                state.pop("t", None)
                outcome = ToolOutcome(ok=True, result={**state, "stale": True})
            if outcome.ok:
                payload: dict[str, Any] = outcome.result or {"ok": True}
            else:
                payload = {"error": outcome.error or "failed", **(outcome.result or {})}
            results.append({
                "type": "tool_result",
                "tool_use_id": p.id,
                "content": json.dumps(payload, ensure_ascii=False),
                "is_error": not outcome.ok,
            })
        return results


__all__ = ["ClaudeBrain", "sanitize_history", "validate_tool_input", "APOLOGY", "REFUSAL_DEFLECTION", "FALLBACK_BETA"]
