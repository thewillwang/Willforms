"""SqliteMemory: facts, turn history, JSON round-trip and orphan tool_result trimming."""
from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from pydantic import BaseModel

from embody.cloud.memory import SqliteMemory


@pytest_asyncio.fixture
async def mem():
    m = SqliteMemory(":memory:")
    yield m
    await m.close()


# ───────────────────────── facts ─────────────────────────

async def test_memory_path_works_and_starts_empty(mem):
    assert await mem.recall("duck-01") == {}
    assert await mem.recall("duck-01", "name") == {}


async def test_remember_then_recall_by_key(mem):
    await mem.remember("duck-01", "name", "Ada")
    assert await mem.recall("duck-01", "name") == {"name": "Ada"}


async def test_remember_upserts(mem):
    await mem.remember("duck-01", "name", "Ada")
    await mem.remember("duck-01", "name", "Grace")
    assert await mem.recall("duck-01", "name") == {"name": "Grace"}
    assert await mem.recall("duck-01") == {"name": "Grace"}


async def test_recall_all_keys(mem):
    await mem.remember("duck-01", "name", "Ada")
    await mem.remember("duck-01", "likes", "rain")
    await mem.remember("duck-01", "bedtime", "21:00")
    assert await mem.recall("duck-01") == {
        "name": "Ada",
        "likes": "rain",
        "bedtime": "21:00",
    }


async def test_missing_key_returns_empty_dict(mem):
    await mem.remember("duck-01", "name", "Ada")
    assert await mem.recall("duck-01", "nope") == {}


async def test_facts_are_isolated_per_device(mem):
    await mem.remember("duck-01", "name", "Ada")
    await mem.remember("duck-02", "name", "Grace")
    await mem.remember("duck-02", "mood", "sleepy")
    assert await mem.recall("duck-01") == {"name": "Ada"}
    assert await mem.recall("duck-02", "name") == {"name": "Grace"}
    assert await mem.recall("duck-02") == {"name": "Grace", "mood": "sleepy"}
    assert await mem.recall("duck-03") == {}


async def test_facts_persist_across_reopen(tmp_path):
    path = str(tmp_path / "embody.sqlite3")
    first = SqliteMemory(path)
    await first.remember("duck-01", "name", "Ada")
    await first.append_turn("duck-01", "user", "hi")
    await first.close()

    second = SqliteMemory(path)
    try:
        assert await second.recall("duck-01") == {"name": "Ada"}
        assert await second.history("duck-01", 10) == [{"role": "user", "content": "hi"}]
    finally:
        await second.close()


# ───────────────────────── turns ─────────────────────────

async def test_history_is_oldest_first_and_limited(mem):
    for i in range(5):
        role = "user" if i % 2 == 0 else "assistant"
        await mem.append_turn("duck-01", role, f"msg {i}")

    assert await mem.history("duck-01", 3) == [
        {"role": "user", "content": "msg 2"},
        {"role": "assistant", "content": "msg 3"},
        {"role": "user", "content": "msg 4"},
    ]
    everything = await mem.history("duck-01", 100)
    assert [m["content"] for m in everything] == [f"msg {i}" for i in range(5)]


async def test_history_limit_zero_is_empty(mem):
    await mem.append_turn("duck-01", "user", "hi")
    assert await mem.history("duck-01", 0) == []


async def test_history_is_isolated_per_device(mem):
    await mem.append_turn("duck-01", "user", "for one")
    await mem.append_turn("duck-02", "user", "for two")
    assert await mem.history("duck-01", 10) == [{"role": "user", "content": "for one"}]
    assert await mem.history("duck-02", 10) == [{"role": "user", "content": "for two"}]
    assert await mem.history("duck-03", 10) == []


async def test_list_content_round_trips_as_json(mem):
    blocks = [
        {"type": "text", "text": "look at this"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "AAA="}},
    ]
    await mem.append_turn("duck-01", "user", blocks)
    await mem.append_turn("duck-01", "assistant", [{"type": "text", "text": "nice duck"}])
    history = await mem.history("duck-01", 10)
    assert history[0] == {"role": "user", "content": blocks}
    assert history[1]["content"] == [{"type": "text", "text": "nice duck"}]


async def test_non_ascii_text_round_trips(mem):
    await mem.append_turn("duck-01", "user", "嘎嘎，你好")
    assert await mem.history("duck-01", 1) == [{"role": "user", "content": "嘎嘎，你好"}]


class _Block(BaseModel):
    type: str = "text"
    text: str
    citations: list[str] | None = None


async def test_pydantic_blocks_are_dumped_without_nulls(mem):
    # The SDK hands back pydantic objects; they must be stored as plain JSON.
    await mem.append_turn("duck-01", "user", "say something")
    await mem.append_turn("duck-01", "assistant", [_Block(text="quack")])
    history = await mem.history("duck-01", 2)
    assert history == [
        {"role": "user", "content": "say something"},
        {"role": "assistant", "content": [{"type": "text", "text": "quack"}]},
    ]


async def test_concurrent_appends_are_all_stored(mem):
    await asyncio.gather(
        *(mem.append_turn("duck-01", "user", f"n{i}") for i in range(50))
    )
    history = await mem.history("duck-01", 100)
    assert len(history) == 50
    assert {m["content"] for m in history} == {f"n{i}" for i in range(50)}


# ───────────────────────── orphan tool_result trimming ─────────────────────────

async def _tool_exchange_conversation(mem):
    """u q1 | a tool_use | u tool_result | a 'done' | u q2 | a ans2"""
    await mem.append_turn("duck-01", "user", "q1")
    await mem.append_turn("duck-01", "assistant", [
        {"type": "tool_use", "id": "t1", "name": "set_emotion", "input": {"emotion": "happy"}},
    ])
    await mem.append_turn("duck-01", "user", [
        {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
    ])
    await mem.append_turn("duck-01", "assistant", [{"type": "text", "text": "done"}])
    await mem.append_turn("duck-01", "user", "q2")
    await mem.append_turn("duck-01", "assistant", "ans2")


async def test_window_starting_at_orphan_tool_result_is_trimmed(mem):
    await _tool_exchange_conversation(mem)
    # Last 4 turns open with the orphan tool_result, last 3 with an assistant turn.
    expected = [{"role": "user", "content": "q2"}, {"role": "assistant", "content": "ans2"}]
    assert await mem.history("duck-01", 4) == expected
    assert await mem.history("duck-01", 3) == expected


async def test_window_starting_at_assistant_is_trimmed(mem):
    await _tool_exchange_conversation(mem)
    # Last 5 turns open with the tool_use assistant turn, then the orphan result.
    expected = [{"role": "user", "content": "q2"}, {"role": "assistant", "content": "ans2"}]
    assert await mem.history("duck-01", 5) == expected


async def test_full_history_with_tool_exchange_is_untouched(mem):
    await _tool_exchange_conversation(mem)
    history = await mem.history("duck-01", 6)
    assert len(history) == 6
    assert history[0] == {"role": "user", "content": "q1"}
    assert history[2]["content"][0]["type"] == "tool_result"


async def test_window_without_tool_results_is_untouched(mem):
    await mem.append_turn("duck-01", "user", "a")
    await mem.append_turn("duck-01", "assistant", "b")
    await mem.append_turn("duck-01", "user", [{"type": "text", "text": "c"}])
    assert [m["content"] for m in await mem.history("duck-01", 3)] == [
        "a",
        "b",
        [{"type": "text", "text": "c"}],
    ]


async def test_history_with_only_tool_results_is_empty(mem):
    await mem.append_turn("duck-01", "assistant", [{"type": "tool_use", "id": "t", "name": "x", "input": {}}])
    await mem.append_turn("duck-01", "user", [{"type": "tool_result", "tool_use_id": "t", "content": "ok"}])
    assert await mem.history("duck-01", 2) == []


# ───────────────────────── lifecycle ─────────────────────────

async def test_close_is_idempotent(tmp_path):
    m = SqliteMemory(str(tmp_path / "x.sqlite3"))
    await m.close()
    await m.close()
