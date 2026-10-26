"""ClaudeBrain tests with a scripted fake Anthropic client. No network."""
from __future__ import annotations

import asyncio
import copy
import json
from types import SimpleNamespace as NS
from typing import Any

import anthropic
import httpx2
import pytest

from embody.cloud.brain import ClaudeBrain, build_system_prompt
from embody.cloud.brain.agent import APOLOGY, FALLBACK_BETA, REFUSAL_DEFLECTION, sanitize_history
from embody.cloud.config import Settings
from embody.cloud.ports import TTS, BodyPort, Memory, ToolCall, ToolOutcome
from embody.proto import Hello, State
from embody.proto.tools import PHASE0_TOOLS


# ───────────────────────── fakes: body / memory / telemetry / tts ─────────────────────────

class FakeBody(BodyPort):
    def __init__(self, tool_results: dict[str, ToolOutcome] | None = None, state: State | None = None):
        self._hello = Hello(dev="duck-test", fw="0.0.1", caps=["audio_out", "touch", "servo_head"])
        self._state = state
        self.log: list[tuple] = []
        self.calls: list[ToolCall] = []
        self.tool_results = tool_results or {}

    @property
    def hello(self) -> Hello:
        return self._hello

    @property
    def last_state(self) -> State | None:
        return self._state

    async def call_tool(self, call: ToolCall, timeout_s: float = 2.0) -> ToolOutcome:
        self.calls.append(call)
        self.log.append(("tool", call.name, call.args))
        return self.tool_results.get(call.name, ToolOutcome(ok=True))

    async def say(self, text: str, utterance_id: str, final: bool = False) -> None:
        self.log.append(("say", text, utterance_id))

    async def send_audio(self, opus_frame: bytes) -> None:
        self.log.append(("audio", opus_frame))

    async def tts_state(self, state: str, utterance_id: str) -> None:
        self.log.append(("tts", state, utterance_id))

    def said(self) -> list[str]:
        return [e[1] for e in self.log if e[0] == "say"]

    def kinds(self) -> list[str]:
        return [e[0] if e[0] != "tts" else f"tts_{e[1]}" for e in self.log]


class FakeMemory(Memory):
    def __init__(self, facts: dict[str, str] | None = None):
        self.turns: dict[str, list[dict[str, Any]]] = {}
        self.facts = facts or {}

    async def remember(self, device, key, value):
        self.facts[key] = value

    async def recall(self, device, key=None):
        return dict(self.facts) if key is None else {key: self.facts[key]} if key in self.facts else {}

    async def append_turn(self, device, role, content):
        self.turns.setdefault(device, []).append({"role": role, "content": copy.deepcopy(content)})

    async def history(self, device, limit):
        return copy.deepcopy(self.turns.get(device, [])[-limit:])

    async def close(self):
        pass


class FakeTimer:
    def __init__(self):
        self.marks: list[str] = []
        self.finished = False

    def mark(self, key: str) -> None:
        self.marks.append(key)

    def finish(self) -> dict[str, float]:
        self.finished = True
        return {k: 0.0 for k in self.marks}


class FakeTelemetry:
    def __init__(self):
        self.timers: list[FakeTimer] = []

    def turn_start(self, device: str) -> FakeTimer:
        t = FakeTimer()
        self.timers.append(t)
        return t


class FakeTTS(TTS):
    async def _gen(self, text: str):
        for i in range(2):
            yield f"{text}#{i}".encode()

    def synthesize(self, text: str):
        return self._gen(text)


# ───────────────────────── fake Anthropic client ─────────────────────────

class Script:
    """One model response: a list of stream events plus the final stop_reason."""

    def __init__(self, stop_reason: str = "end_turn"):
        self.items: list[Any] = []
        self.stop_reason = stop_reason
        self._index = 0

    def text(self, *deltas: str, hold: asyncio.Event | None = None) -> "Script":
        """A text block; with ``hold`` the stream blocks mid-block (before content_block_stop)."""
        i = self._index
        self._index += 1
        self.items.append(NS(type="content_block_start", index=i, content_block=NS(type="text", text="")))
        for d in deltas:
            self.items.append(NS(type="content_block_delta", index=i, delta=NS(type="text_delta", text=d)))
        if hold is not None:
            self.items.append(("wait", hold))
        self.items.append(NS(type="content_block_stop", index=i))
        return self

    def tool(self, tid: str, name: str, input: dict) -> "Script":
        i = self._index
        self._index += 1
        self.items.append(NS(type="content_block_start", index=i, content_block=NS(type="tool_use", id=tid, name=name, input={})))
        self.items.append(NS(type="content_block_delta", index=i, delta=NS(type="input_json_delta", partial_json=json.dumps(input))))
        self.items.append(("set_input", i, input))
        self.items.append(NS(type="content_block_stop", index=i))
        return self

    def thinking(self) -> "Script":
        i = self._index
        self._index += 1
        self.items.append(NS(type="content_block_start", index=i, content_block=NS(type="thinking", thinking="", signature="sig")))
        self.items.append(NS(type="content_block_stop", index=i))
        return self

    def wait(self, ev: asyncio.Event) -> "Script":
        self.items.append(("wait", ev))
        return self

    def fail(self, exc: BaseException) -> "Script":
        self.items.append(("raise", exc))
        return self


class FakeStream:
    def __init__(self, script: Script):
        self.script = script
        self.current_message_snapshot = NS(content=[])

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        return self._events()

    async def _events(self):
        snap = self.current_message_snapshot
        for item in self.script.items:
            if isinstance(item, tuple):
                if item[0] == "wait":
                    await item[1].wait()
                elif item[0] == "raise":
                    raise item[1]
                elif item[0] == "set_input":
                    snap.content[item[1]].input = item[2]
                continue
            if item.type == "content_block_start":
                snap.content.append(copy.copy(item.content_block))
            elif item.type == "content_block_delta" and item.delta.type == "text_delta":
                snap.content[item.index].text += item.delta.text
            await asyncio.sleep(0)
            yield item
        yield NS(type="message_delta", delta=NS(stop_reason=self.script.stop_reason))
        yield NS(type="message_stop")

    async def get_final_message(self):
        return NS(content=list(self.current_message_snapshot.content), stop_reason=self.script.stop_reason, stop_details=None)


class _Messages:
    def __init__(self, client: "FakeClient", path: str):
        self.client, self.path = client, path

    def stream(self, **kw):
        self.client.requests.append((self.path, copy.deepcopy(kw)))
        if not self.client.scripts:
            raise AssertionError("unexpected extra model call")
        nxt = self.client.scripts.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return FakeStream(nxt)


class FakeClient:
    def __init__(self, *scripts: Script | BaseException):
        self.scripts = list(scripts)
        self.requests: list[tuple[str, dict]] = []
        self.messages = _Messages(self, "messages")
        self.beta = NS(messages=_Messages(self, "beta"))


def make_brain(*scripts, fallbacks: bool = True, tts: TTS | None = None, body: FakeBody | None = None, memory: FakeMemory | None = None):
    body = body or FakeBody()
    memory = memory or FakeMemory()
    telemetry = FakeTelemetry()
    client = FakeClient(*scripts)
    settings = Settings(fallbacks=fallbacks, model="claude-opus-5-5", effort="low", max_tokens=2048, history_turns=20)
    brain = ClaudeBrain(body, memory, telemetry, settings, tts=tts, client=client)
    return brain, body, memory, telemetry, client


def history(memory: FakeMemory) -> list[dict]:
    return memory.turns["duck-test"]


# ───────────────────────── tests ─────────────────────────

async def test_text_only_reply_is_chunked_and_persisted():
    brain, body, memory, tel, client = make_brain(
        Script().text("你好", "呀！今天", "天气真好。我们", "去玩吧")
    )
    await brain.on_user_text("嗨")

    assert body.said() == ["你好呀！", "今天天气真好。", "我们去玩吧"]
    kinds = body.kinds()
    assert kinds[0] == "tts_start" and kinds[-1] == "tts_end"
    assert kinds.count("tts_start") == 1 and kinds.count("tts_end") == 1
    uids = {e[2] for e in body.log}
    assert len(uids) == 1

    assert history(memory) == [
        {"role": "user", "content": "嗨"},
        {"role": "assistant", "content": [{"type": "text", "text": "你好呀！今天天气真好。我们去玩吧"}]},
    ]
    timer = tel.timers[0]
    for key in ("llm_first_token", "first_say", "turn_end"):
        assert key in timer.marks
    assert "llm_first_tool" not in timer.marks
    assert timer.finished

    path, kw = client.requests[0]
    assert path == "beta"
    assert kw["betas"] == [FALLBACK_BETA] and kw["fallbacks"] == "default"
    assert kw["model"] == "claude-opus-5-5" and kw["max_tokens"] == 2048
    assert kw["output_config"] == {"effort": "low"}
    assert kw["tools"] == PHASE0_TOOLS
    assert all("eager_input_streaming" not in t for t in kw["tools"])
    for banned in ("thinking", "temperature", "tool_choice"):
        assert banned not in kw
    assert kw["messages"] == [{"role": "user", "content": "嗨"}]
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}


async def test_plain_endpoint_when_fallbacks_disabled():
    brain, body, memory, tel, client = make_brain(Script().text("好的。"), fallbacks=False)
    await brain.on_user_text("hi")
    path, kw = client.requests[0]
    assert path == "messages"
    assert "betas" not in kw and "fallbacks" not in kw


async def test_tool_dispatched_before_speech_and_history_is_valid():
    brain, body, memory, tel, client = make_brain(
        Script(stop_reason="tool_use").thinking().tool("tu_1", "set_emotion", {"emotion": "happy"}),
        Script().text("嘎！", "我好开心。"),
    )
    await brain.on_user_text("我给你买了面包")

    first_tool = body.kinds().index("tool")
    first_say = body.kinds().index("say")
    assert first_tool < first_say
    assert body.calls == [ToolCall("tu_1", "set_emotion", {"emotion": "happy"})]
    assert body.said() == ["嘎！", "我好开心。"]

    h = history(memory)
    assert [m["role"] for m in h] == ["user", "assistant", "user", "assistant"]
    assert h[1]["content"] == [{"type": "tool_use", "id": "tu_1", "name": "set_emotion", "input": {"emotion": "happy"}}]
    assert h[2]["content"] == [{"type": "tool_result", "tool_use_id": "tu_1", "content": json.dumps({"ok": True}), "is_error": False}]
    assert h[3]["content"] == [{"type": "text", "text": "嘎！我好开心。"}]

    # second request continues the same turn: thinking replayed within the turn, then tool_result
    _, kw2 = client.requests[1]
    msgs = kw2["messages"]
    assert msgs[-2]["role"] == "assistant"
    assert [b["type"] for b in msgs[-2]["content"]] == ["thinking", "tool_use"]
    assert msgs[-1]["content"][0]["tool_use_id"] == "tu_1"

    timer = tel.timers[0]
    assert timer.marks.index("llm_first_tool") < timer.marks.index("first_say")
    assert body.kinds().count("tts_end") == 1 and body.kinds()[-1] == "tts_end"


async def test_tool_call_mid_message_dispatched_before_message_ends():
    gate = asyncio.Event()
    brain, body, memory, tel, client = make_brain(
        Script(stop_reason="tool_use").tool("tu_1", "gesture", {"name": "nod"}).wait(gate).text("好呀。"),
        Script().text("走吧。"),
    )
    task = asyncio.create_task(brain.on_user_text("一起玩吗"))
    for _ in range(50):
        await asyncio.sleep(0)
        if body.calls:
            break
    assert body.calls and body.calls[0].name == "gesture"  # dispatched while stream still open
    gate.set()
    await task
    assert body.said() == ["好呀。", "走吧。"]


async def test_get_state_result_is_returned_to_model():
    state_result = ToolOutcome(ok=True, result={"pose": "picked_up", "batt": 80})
    body = FakeBody(tool_results={"get_state": state_result})
    brain, body, memory, tel, client = make_brain(
        Script(stop_reason="tool_use").tool("tu_s", "get_state", {}),
        Script().text("哇，我被举起来了！"),
        body=body,
    )
    await brain.on_user_text("你现在在哪")
    result = client.requests[1][1]["messages"][-1]["content"][0]
    assert json.loads(result["content"]) == {"pose": "picked_up", "batt": 80}
    assert result["is_error"] is False


async def test_get_state_falls_back_to_last_state_on_failure():
    body = FakeBody(tool_results={"get_state": ToolOutcome(ok=False, error="timeout")}, state=State(batt=55, pose="upright"))
    brain, body, memory, tel, client = make_brain(
        Script(stop_reason="tool_use").tool("tu_s", "get_state", {}),
        Script().text("还好。"),
        body=body,
    )
    await brain.on_user_text("电量多少")
    result = client.requests[1][1]["messages"][-1]["content"][0]
    payload = json.loads(result["content"])
    assert payload["batt"] == 55 and payload["stale"] is True and result["is_error"] is False


async def test_interrupt_mid_stream_cancels_and_ends_tts():
    never = asyncio.Event()
    brain, body, memory, tel, client = make_brain(
        Script().text("第一句。第二", "句还没说完", hold=never).text("不会出现。"),
    )
    task = asyncio.create_task(brain.on_user_text("讲个故事"))
    for _ in range(100):
        await asyncio.sleep(0)
        if body.said():
            break
    assert body.said() == ["第一句。"]

    await brain.interrupt()
    await asyncio.wait_for(task, 1)  # on_user_text returns normally after barge-in
    assert body.said() == ["第一句。"]  # the buffered remainder is never spoken

    assert body.kinds()[-1] == "tts_end"
    assert body.kinds().count("tts_end") == 1
    start_uid = next(e[2] for e in body.log if e[:2] == ("tts", "start"))
    assert body.log[-1] == ("tts", "end", start_uid)
    assert tel.timers[0].finished
    h = history(memory)
    assert h[0] == {"role": "user", "content": "讲个故事"}
    assert h[-1]["role"] == "assistant" and h[-1]["content"][0]["text"].startswith("第一句。")


async def test_new_utterance_interrupts_running_turn():
    never = asyncio.Event()
    brain, body, memory, tel, client = make_brain(
        Script().text("我在说话。很长", hold=never),
        Script().text("好的，听你的。"),
    )
    t1 = asyncio.create_task(brain.on_user_text("讲个故事"))
    for _ in range(100):
        await asyncio.sleep(0)
        if body.said():
            break
    await brain.on_user_text("停一下")
    await asyncio.wait_for(t1, 1)
    assert body.said() == ["我在说话。", "好的，听你的。"]
    # exactly one end per start
    assert body.kinds().count("tts_start") == body.kinds().count("tts_end") == 2


async def test_refusal_speaks_deflection():
    brain, body, memory, tel, client = make_brain(Script(stop_reason="refusal"))
    await brain.on_user_text("something disallowed")
    assert body.said() == [REFUSAL_DEFLECTION]
    assert len(client.requests) == 1
    assert body.kinds()[-1] == "tts_end"


async def test_unknown_tool_rejected_not_dispatched():
    brain, body, memory, tel, client = make_brain(
        Script(stop_reason="tool_use").tool("tu_x", "fly", {"height": 3}),
        Script().text("我飞不起来呢。"),
    )
    await brain.on_user_text("飞一个")
    assert body.calls == []
    result = client.requests[1][1]["messages"][-1]["content"][0]
    assert result["tool_use_id"] == "tu_x" and result["is_error"] is True
    assert "unknown tool" in json.loads(result["content"])["error"]
    assert body.said() == ["我飞不起来呢。"]


async def test_invalid_tool_args_rejected():
    brain, body, memory, tel, client = make_brain(
        Script(stop_reason="tool_use").tool("tu_e", "set_emotion", {"emotion": "furious"}),
        Script().text("哼。"),
    )
    await brain.on_user_text("生气一下")
    assert body.calls == []
    result = client.requests[1][1]["messages"][-1]["content"][0]
    assert result["is_error"] is True


async def test_max_tokens_with_tool_use_does_not_run_or_store_tool():
    brain, body, memory, tel, client = make_brain(
        Script(stop_reason="max_tokens").text("嗯。").tool("tu_t", "gesture", {"name": "nod"}),
    )
    await brain.on_user_text("hi")
    assert len(client.requests) == 1
    h = history(memory)
    assert h[-1] == {"role": "assistant", "content": [{"type": "text", "text": "嗯。"}]}
    assert all(b.get("type") != "tool_use" for m in h if isinstance(m["content"], list) for b in m["content"])


async def test_tool_round_limit():
    scripts = [Script(stop_reason="tool_use").tool(f"tu_{i}", "gesture", {"name": "nod"}) for i in range(10)]
    brain, body, memory, tel, client = make_brain(*scripts)
    await brain.on_user_text("一直点头")
    assert len(client.requests) == 5  # 1 initial + 4 tool rounds
    h = history(memory)
    assert h[-1]["role"] == "user" and h[-1]["content"][0]["type"] == "tool_result"
    assert sanitize_history(h) == h


@pytest.mark.parametrize("exc", [
    anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")),
    anthropic.RateLimitError("slow down", response=httpx2.Response(429, request=httpx2.Request("POST", "https://x")), body=None),
    anthropic.InternalServerError("boom", response=httpx2.Response(500, request=httpx2.Request("POST", "https://x")), body=None),
])
async def test_api_errors_speak_apology(exc):
    brain, body, memory, tel, client = make_brain(exc)
    await brain.on_user_text("hi")
    assert body.said() == [APOLOGY]
    assert body.kinds()[-1] == "tts_end"
    assert tel.timers[0].finished


async def test_value_error_from_stream_retries_once():
    brain, body, memory, tel, client = make_brain(
        Script().fail(ValueError("Unable to parse tool parameter JSON")),
        Script().text("再试一次成功啦。"),
    )
    await brain.on_user_text("hi")
    assert len(client.requests) == 2
    assert body.said() == ["再试一次成功啦。"]


async def test_value_error_twice_apologises():
    brain, body, memory, tel, client = make_brain(
        Script().fail(ValueError("bad json")),
        Script().fail(ValueError("bad json")),
    )
    await brain.on_user_text("hi")
    assert body.said() == [APOLOGY]


async def test_tts_frames_forwarded():
    brain, body, memory, tel, client = make_brain(Script().text("你好。再见。"), tts=FakeTTS())
    await brain.on_user_text("hi")
    assert [e[1] for e in body.log if e[0] == "audio"] == [b"\xe4\xbd\xa0\xe5\xa5\xbd\xe3\x80\x82#0", "你好。#1".encode(), "再见。#0".encode(), "再见。#1".encode()]
    kinds = body.kinds()
    assert kinds.index("say") < kinds.index("audio")
    assert "tts_first_audio" in tel.timers[0].marks


async def test_touch_event_runs_turn_with_prefixed_text():
    brain, body, memory, tel, client = make_brain(
        Script().text("嘿嘿，好痒。"),
        Script().text("放我下来！"),
    )
    await brain.on_event("touch", None, {})
    await brain.on_event("picked_up", None, {})
    users = [m["content"] for m in history(memory) if m["role"] == "user"]
    assert users == ["[身体事件] 有人摸了你的头", "[身体事件] 你被拿起来了"]
    # the second turn sees the first in history
    assert client.requests[1][1]["messages"][0]["content"] == "[身体事件] 有人摸了你的头"


async def test_history_is_reused_and_thinking_not_stored():
    memory = FakeMemory()
    brain, body, memory, tel, client = make_brain(
        Script().thinking().text("我叫小鸭。"),
        Script().text("记得呀。"),
        memory=memory,
    )
    await brain.on_user_text("你叫什么")
    await brain.on_user_text("还记得吗")
    msgs = client.requests[1][1]["messages"]
    assert msgs == [
        {"role": "user", "content": "你叫什么"},
        {"role": "assistant", "content": [{"type": "text", "text": "我叫小鸭。"}]},
        {"role": "user", "content": "还记得吗"},
    ]


def test_sanitize_history_drops_orphans():
    h = [
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "a", "content": "{}"}]},  # orphan from window cut
        {"role": "assistant", "content": [{"type": "text", "text": "x"}]},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [{"type": "text", "text": "hm"}, {"type": "tool_use", "id": "b", "name": "gesture", "input": {"name": "nod"}}]},
        {"role": "user", "content": "unrelated"},  # tool_use b never answered
    ]
    assert sanitize_history(h) == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [{"type": "text", "text": "hm"}]},
        {"role": "user", "content": "unrelated"},
    ]


def test_system_prompt_blocks():
    a = build_system_prompt("duck", ["touch", "audio_out"], {})
    b = build_system_prompt("duck", ["wheels"], {"name": "小明", "likes": "面包"})
    assert len(a) == 2 and a[0]["cache_control"] == {"type": "ephemeral"}
    assert a[0] == b[0]  # stable block independent of caps / memories
    assert "cache_control" not in a[1]
    assert "小明" in b[1]["text"] and "wheels" in b[1]["text"]
    stable = a[0]["text"]
    for needle in ("set_emotion", "gesture", "get_state", "Chinese", "markdown", "emoji"):
        assert needle in stable
    assert build_system_prompt("unknown-persona", [], {})[0] == a[0]
