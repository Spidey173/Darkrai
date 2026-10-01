import asyncio
import logging
import signal
import sys
from pathlib import Path

# Add project root directory to path to resolve backend package imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.core.logging import setup_logging
from backend.app.services.queue import event_queue

setup_logging()
logger = logging.getLogger("app.worker")

async def run_worker():
    logger.info("Starting Darkrai Standalone Distributed Queue Worker...")
    await event_queue.start_worker()

    stop_event = asyncio.Event()

    def handle_signal():
        logger.info("Received termination signal. Shutting down worker gracefully...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_signal)
        except NotImplementedError:
            # Signal handling might not be implemented on some non-Unix platforms
            pass

    await stop_event.wait()
    await event_queue.stop_worker()
    logger.info("Worker shutdown complete.")

if __name__ == "__main__":
    try:
        asyncio.run(run_worker())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Worker terminated.")
