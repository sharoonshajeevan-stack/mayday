# ============================================================================
# MAYDAY OS - REAL-TIME VOICE SERVICE ENTRY POINT
# File: backend/pipecat_voice/service.py
# Purpose: Run the aiohttp control server and (optionally) the voice pipeline
#          in one process.
#
# Run from the backend directory with the backend virtualenv:
#
#     python -m pipecat_voice.service
#
# or, more conveniently:
#
#     python pipecat_service.py
# ============================================================================

import asyncio
import logging

from aiohttp import web

from pipecat_voice.agent import MaydayVoiceAgent
from pipecat_voice.config import VoiceServiceConfig
from pipecat_voice.control_server import ControlServer
from pipecat_voice.events import EventHub

logger = logging.getLogger(__name__)


def _configure_logging(level):
    logging.basicConfig(
        level=getattr(logging, str(level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def run_service(config=None):
    """Start the control server and block until cancelled."""
    config = config or VoiceServiceConfig.from_env()
    _configure_logging(config.log_level)

    # Imported here so importing this module stays cheap and side-effect free.
    from speech_to_text import stt_engine
    from text_to_speech import tts_engine

    hub = EventHub()
    hub.bind_loop(asyncio.get_running_loop())

    agent = MaydayVoiceAgent(
        config,
        hub,
        stt_engine=stt_engine,
        tts_engine=tts_engine,
    )

    stop_event = asyncio.Event()
    server = ControlServer(
        agent=agent,
        hub=hub,
        config=config,
        on_shutdown=stop_event.set,
    )

    app = server.build_app()
    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, config.host, config.port)
    await site.start()

    logger.info(
        "MAYDAY real-time voice service listening on %s (transport=%s)",
        config.base_url,
        config.transport,
    )

    if config.autostart:
        try:
            await agent.start()
        except Exception:  # noqa: BLE001
            logger.exception(
                "Autostart failed; the service is still available for control"
            )

    try:
        await stop_event.wait()
    finally:
        logger.info("Shutting down MAYDAY real-time voice service")
        await agent.stop()
        await runner.cleanup()


def main():
    try:
        asyncio.run(run_service())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
