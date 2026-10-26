"""Software duck: speaks the same WebSocket protocol as the real ESP32 duck."""
from .body import DuckBody
from .client import DuckClient

__all__ = ["DuckBody", "DuckClient"]
