"""Runtime configuration from environment variables. Single source of truth."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(slots=True)
class Settings:
    host: str = field(default_factory=lambda: _env("EMBODY_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(_env("EMBODY_PORT", "8765")))
    # Devices must present this token in `hello.token`. Empty = no auth (LAN dev only).
    device_token: str = field(default_factory=lambda: _env("EMBODY_DEVICE_TOKEN", ""))
    # LLM
    model: str = field(default_factory=lambda: _env("EMBODY_MODEL", "claude-opus-5-5"))
    effort: str = field(default_factory=lambda: _env("EMBODY_EFFORT", "low"))  # chat latency matters
    max_tokens: int = field(default_factory=lambda: int(_env("EMBODY_MAX_TOKENS", "2048")))
    # Server-side refusal fallback (Claude API only). Set to "0" if the proxy rejects the beta.
    fallbacks: bool = field(default_factory=lambda: _env("EMBODY_FALLBACKS", "1") == "1")
    history_turns: int = field(default_factory=lambda: int(_env("EMBODY_HISTORY_TURNS", "20")))
    # Persona name used in the system prompt.
    persona: str = field(default_factory=lambda: _env("EMBODY_PERSONA", "duck"))
    # Memory
    db_path: str = field(default_factory=lambda: _env("EMBODY_DB", "embody.sqlite3"))
    # Heartbeat
    ping_interval_s: float = field(default_factory=lambda: float(_env("EMBODY_PING_S", "3")))
    ping_misses: int = field(default_factory=lambda: int(_env("EMBODY_PING_MISSES", "3")))
    log_level: str = field(default_factory=lambda: _env("EMBODY_LOG", "INFO"))


settings = Settings()
