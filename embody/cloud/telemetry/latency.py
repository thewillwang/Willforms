"""Per-turn latency marks. In memory only; one INFO log line per finished turn.

A turn is created with `LatencyTelemetry.turn_start(device)`. The brain calls
`mark(key)` at each milestone (see `embody.cloud.ports.Telemetry` for the key
names) and `finish()` when the turn ends. Offsets are milliseconds from turn start.
"""
from __future__ import annotations

import logging
import math
import time
from collections import deque
from typing import Callable

log = logging.getLogger("embody.telemetry")

RECENT_LIMIT = 200


class Turn:
    """Timer for one agent turn. Only the first `mark` of each key counts."""

    def __init__(
        self,
        device: str,
        start: float,
        clock: Callable[[], float],
        sink: deque[dict[str, float]],
    ) -> None:
        self.device = device
        self._start = start
        self._clock = clock
        self._sink = sink
        self._marks: dict[str, float] = {}
        self._result: dict[str, float] | None = None

    def mark(self, key: str) -> None:
        if self._result is None and key not in self._marks:
            self._marks[key] = self._clock()

    def finish(self) -> dict[str, float]:
        """Return {key: ms since start, ..., "total": ms}. Idempotent: a second
        call returns the same dict and does not record the turn twice."""
        if self._result is not None:
            return dict(self._result)
        end = self._clock()
        offsets = {k: (t - self._start) * 1000.0 for k, t in self._marks.items()}
        offsets["total"] = (end - self._start) * 1000.0
        self._result = offsets
        self._sink.append(dict(offsets))
        log.info(
            "turn device=%s %s",
            self.device,
            " ".join(f"{k}={v:.0f}ms" for k, v in offsets.items()),
        )
        return dict(offsets)


class LatencyTelemetry:
    """Keeps the last `RECENT_LIMIT` finished turns and summarises them."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self.recent: deque[dict[str, float]] = deque(maxlen=RECENT_LIMIT)

    def turn_start(self, device: str) -> Turn:
        return Turn(device, self._clock(), self._clock, self.recent)

    def summary(self) -> dict[str, float]:
        """p50 / p95 (ms) of `first_say` and `total` over `recent`, plus the turn
        count. Empty dict when no turn has finished yet. A key that no recent
        turn recorded is left out."""
        if not self.recent:
            return {}
        out: dict[str, float] = {"turns": len(self.recent)}
        for key in ("first_say", "total"):
            values = sorted(d[key] for d in self.recent if key in d)
            if values:
                out[f"{key}_p50"] = _percentile(values, 50)
                out[f"{key}_p95"] = _percentile(values, 95)
        return out


def _percentile(sorted_values: list[float], p: float) -> float:
    """Linear interpolation between closest ranks (same as numpy's default)."""
    k = (len(sorted_values) - 1) * p / 100.0
    lo, hi = math.floor(k), math.ceil(k)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)
