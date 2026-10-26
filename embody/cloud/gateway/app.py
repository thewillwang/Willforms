"""FastAPI app: `GET /healthz` and WebSocket `/ws`."""
from __future__ import annotations

import logging
from typing import Callable

from fastapi import FastAPI, WebSocket

from embody.cloud.config import Settings
from embody.cloud.ports import ASR, BodyPort, Brain

from .session import DeviceSession

log = logging.getLogger("embody.gateway")


def create_app(
    settings: Settings,
    brain_factory: Callable[[BodyPort], Brain],
    asr_factory: Callable[[], ASR] | None = None,
) -> FastAPI:
    app = FastAPI(title="embody-cloud")
    app.state.settings = settings
    app.state.sessions = {}  # dict[session_id, DeviceSession]

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True, "devices": len(app.state.sessions)}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        peer = f"{ws.client.host}:{ws.client.port}" if ws.client else "?"
        session = DeviceSession(
            ws, settings, brain_factory, asr=asr_factory() if asr_factory else None
        )
        registered = False
        try:
            if await session.handshake():
                app.state.sessions[session.session_id] = session
                registered = True
                await session.serve()
        except Exception:
            session.close_reason = "error"
            log.exception("session error for %s (%s)", session.device_id, peer)
        finally:
            if registered:
                app.state.sessions.pop(session.session_id, None)
            await session.close()
            log.info("device %s disconnected (session=%s peer=%s reason=%s)",
                     session.device_id, session.session_id or "-", peer, session.close_reason)

    return app
