import threading
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import CLEANUP_INTERVAL_SECONDS
from app.services.ocr_service import ocr_service
from app.utils.cleanup import cleanup_runtime_data
from app.utils.logger import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    cleanup_stop_event = threading.Event()

    def cleanup_loop():
        while not cleanup_stop_event.wait(CLEANUP_INTERVAL_SECONDS):
            cleanup_runtime_data()

    cleanup_runtime_data()
    cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
    cleanup_thread.start()

    logger.info("Initializing PaddleX OCR model...")

    init_future = ocr_service.submit_initialize()
    try:
        init_future.result(timeout=300)
        logger.info("PaddleX OCR model initialized.")
    except FutureTimeoutError:
        logger.warning("PaddleX OCR model initialization timed out.")
    except Exception:
        logger.exception("PaddleX OCR model initialization failed.")

    try:
        yield
    finally:
        cleanup_stop_event.set()
        cleanup_thread.join(timeout=5)
        ocr_service.shutdown()
        logger.info("Service stopped, runtime cleanup thread closed.")
