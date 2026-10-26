"""LatencyTelemetry: offsets, first-mark-wins, bounded history, summary, log line."""
from __future__ import annotations

import logging

import pytest

from embody.cloud.telemetry import RECENT_LIMIT, LatencyTelemetry, Turn


class FakeClock:
    def __init__(self, start: float = 100.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance_ms(self, ms: float) -> None:
        self.now += ms / 1000.0


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def tel(clock) -> LatencyTelemetry:
    return LatencyTelemetry(clock=clock)


def test_offsets_are_ms_from_turn_start(tel, clock):
    turn = tel.turn_start("duck-01")
    clock.advance_ms(812)
    turn.mark("llm_first_token")
    clock.advance_ms(528)
    turn.mark("first_say")
    clock.advance_ms(270)

    result = turn.finish()
    assert result == pytest.approx(
        {"llm_first_token": 812.0, "first_say": 1340.0, "total": 1610.0}
    )


def test_total_is_present_even_without_marks(tel, clock):
    turn = tel.turn_start("duck-01")
    clock.advance_ms(250)
    assert turn.finish() == pytest.approx({"total": 250.0})


def test_first_mark_wins(tel, clock):
    turn = tel.turn_start("duck-01")
    clock.advance_ms(100)
    turn.mark("first_say")
    clock.advance_ms(900)
    turn.mark("first_say")  # ignored
    clock.advance_ms(10)
    result = turn.finish()
    assert result["first_say"] == pytest.approx(100.0)
    assert result["total"] == pytest.approx(1010.0)


def test_turns_do_not_share_marks(tel, clock):
    a = tel.turn_start("duck-01")
    clock.advance_ms(50)
    b = tel.turn_start("duck-02")
    a.mark("first_say")
    clock.advance_ms(50)
    b.mark("first_say")
    assert a.finish()["first_say"] == pytest.approx(50.0)
    assert b.finish()["first_say"] == pytest.approx(50.0)


def test_finish_is_idempotent(tel, clock):
    turn = tel.turn_start("duck-01")
    clock.advance_ms(40)
    first = turn.finish()
    clock.advance_ms(500)
    assert turn.finish() == first
    assert len(tel.recent) == 1


def test_finished_turn_is_appended_to_recent(tel, clock):
    turn = tel.turn_start("duck-01")
    clock.advance_ms(120)
    turn.mark("first_say")
    result = turn.finish()
    assert list(tel.recent) == [result]


def test_recent_is_bounded(tel, clock):
    for _ in range(RECENT_LIMIT + 5):
        turn = tel.turn_start("duck-01")
        clock.advance_ms(1)
        turn.finish()
    assert len(tel.recent) == RECENT_LIMIT


def test_summary_empty_without_data(tel):
    assert tel.summary() == {}


def test_summary_percentiles(tel, clock):
    # first_say: 1000..5000 ms, total: 2000..6000 ms
    for i in range(1, 6):
        turn = tel.turn_start("duck-01")
        clock.advance_ms(1000 * i)
        turn.mark("first_say")
        clock.advance_ms(1000)  # total = first_say + 1000
        turn.finish()

    s = tel.summary()
    assert s["turns"] == 5
    # linear interpolation over [1000, 2000, 3000, 4000, 5000]
    assert s["first_say_p50"] == pytest.approx(3000.0)
    assert s["first_say_p95"] == pytest.approx(4800.0)
    # [2000 .. 6000]
    assert s["total_p50"] == pytest.approx(4000.0)
    assert s["total_p95"] == pytest.approx(5800.0)


def test_summary_single_turn_uses_its_value(tel, clock):
    turn = tel.turn_start("duck-01")
    clock.advance_ms(700)
    turn.mark("first_say")
    clock.advance_ms(300)
    turn.finish()
    s = tel.summary()
    assert s["first_say_p50"] == pytest.approx(700.0)
    assert s["first_say_p95"] == pytest.approx(700.0)
    assert s["total_p50"] == pytest.approx(1000.0)


def test_summary_omits_keys_no_turn_recorded(tel, clock):
    turn = tel.turn_start("duck-01")
    clock.advance_ms(300)
    turn.finish()  # no first_say mark
    s = tel.summary()
    assert "first_say_p50" not in s
    assert s["total_p50"] == pytest.approx(300.0)


def test_finish_logs_one_line(tel, clock, caplog):
    caplog.set_level(logging.INFO, logger="embody.telemetry")
    turn = tel.turn_start("duck-01")
    clock.advance_ms(812)
    turn.mark("llm_first_token")
    clock.advance_ms(528)
    turn.mark("first_say")
    clock.advance_ms(270)
    turn.finish()

    records = [r for r in caplog.records if r.name == "embody.telemetry"]
    assert len(records) == 1
    assert records[0].levelno == logging.INFO
    assert records[0].getMessage() == (
        "turn device=duck-01 llm_first_token=812ms first_say=1340ms total=1610ms"
    )


def test_default_clock_is_monotonic():
    tel = LatencyTelemetry()
    turn = tel.turn_start("duck-01")
    assert isinstance(turn, Turn)
    assert turn.finish()["total"] >= 0.0
