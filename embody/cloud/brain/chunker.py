"""Split streamed model text into speakable sentences.

Pure and synchronous. Feed text deltas as they stream in; complete sentences
come back as soon as their boundary is certain, so TTS can start on the first
sentence while the model is still writing the rest.

Boundaries:
- Chinese / full-width  。！？；… (cut right after the punctuation run)
- ASCII  . ! ?  only when followed by whitespace (so "3.14" and "a.b" stay whole)
- newline
Closing quotes/brackets right after the punctuation stay with the sentence.

The FIRST sentence is released early: if no boundary has appeared after
``first_soft_limit`` characters, it is cut at the last comma-like mark
(，、,：:). Later sentences get the same treatment only past ``soft_limit``.

A boundary at the very end of the buffer is held until one more character
arrives (it might be followed by a closing quote, or be "3." of "3.5");
callers flush when a text block ends.
"""
from __future__ import annotations

_CJK_TERMINATORS = "。！？；…"
_ASCII_TERMINATORS = ".!?"
_TERMINATORS = _CJK_TERMINATORS + _ASCII_TERMINATORS
_CLOSERS = "\"'”’」』）)】]》〉"
_CJK_SOFT = "，、：；"
_ASCII_SOFT = ",:;"


class SentenceChunker:
    def __init__(self, first_soft_limit: int = 40, soft_limit: int = 160, min_soft_chunk: int = 4) -> None:
        self.first_soft_limit = first_soft_limit
        self.soft_limit = soft_limit
        self.min_soft_chunk = min_soft_chunk
        self._buf = ""
        self._emitted = 0

    @property
    def pending(self) -> str:
        """Text received but not yet released."""
        return self._buf

    @property
    def emitted(self) -> int:
        return self._emitted

    def feed(self, delta: str) -> list[str]:
        """Add a text delta; return the sentences that are now complete (possibly none)."""
        if delta:
            self._buf += delta
        out: list[str] = []
        while True:
            cut = self._find_cut()
            if cut is None:
                break
            sentence = self._buf[:cut].strip()
            self._buf = self._buf[cut:]
            if sentence:
                out.append(sentence)
                self._emitted += 1
        return out

    def flush(self) -> str:
        """Return whatever is left (stripped; may be empty) and clear the buffer."""
        rest = self._buf.strip()
        self._buf = ""
        if rest:
            self._emitted += 1
        return rest

    def reset(self) -> None:
        """Start a new utterance (re-enables the early first-sentence split)."""
        self._buf = ""
        self._emitted = 0

    # ───────────────────────── internals ─────────────────────────

    def _find_cut(self) -> int | None:
        buf = self._buf
        n = len(buf)
        i = 0
        while i < n:
            ch = buf[i]
            if ch == "\n":
                return i + 1
            if ch in _TERMINATORS:
                j = i
                while j + 1 < n and buf[j + 1] in _TERMINATORS:
                    j += 1
                k = j + 1
                while k < n and buf[k] in _CLOSERS:
                    k += 1
                if k >= n:
                    return None  # need one more char to be sure
                run = buf[i : j + 1]
                if any(c in _CJK_TERMINATORS for c in run) or buf[k].isspace():
                    return k
                i = k
                continue
            i += 1
        return self._soft_cut()

    def _soft_cut(self) -> int | None:
        buf = self._buf
        limit = self.first_soft_limit if self._emitted == 0 else self.soft_limit
        if len(buf.strip()) < limit:
            return None
        for p in range(len(buf) - 1, self.min_soft_chunk - 1, -1):
            ch = buf[p]
            if ch in _CJK_SOFT:
                return p + 1
            if ch in _ASCII_SOFT and p + 1 < len(buf) and buf[p + 1].isspace():
                return p + 1
        return None


__all__ = ["SentenceChunker"]
