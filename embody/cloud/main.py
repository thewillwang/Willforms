"""`embody-cloud` entrypoint: wire memory, telemetry, brain factory, and run uvicorn."""
from __future__ import annotations

import asyncio
import logging
import sys

from embody.cloud.config import Settings


def main() -> None:
    settings = Settings()
    level = settings.log_level.upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("embody.gateway")

    try:
        from embody.cloud.brain import ClaudeBrain
        from embody.cloud.memory import SqliteMemory
        from embody.cloud.telemetry import LatencyTelemetry
    except ImportError as e:
        sys.exit(f"embody-cloud: cannot start, a required module is missing or broken: {e}")

    import uvicorn

    from embody.cloud.gateway import create_app
    from embody.cloud.ports import BodyPort, Brain
    from embody.cloud.voice.null import NullASR

    if not settings.device_token:
        log.warning("EMBODY_DEVICE_TOKEN is empty: device auth disabled (LAN dev only)")

    memory = SqliteMemory(settings.db_path)
    telemetry = LatencyTelemetry()

    def brain_factory(body: BodyPort) -> Brain:
        return ClaudeBrain(body, memory, telemetry, settings, tts=None)

    app = create_app(settings, brain_factory, asr_factory=NullASR)
    try:
        uvicorn.run(app, host=settings.host, port=settings.port, log_level=level.lower())
    finally:
        try:
            asyncio.run(memory.close())
        except Exception:
            log.exception("memory.close failed")


if __name__ == "__main__":
    main()
