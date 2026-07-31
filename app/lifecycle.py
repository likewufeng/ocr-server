import threading
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

    def init_model():
        try:
            ocr_service.initialize()
            logger.info("PaddleX OCR model initialized.")
        except Exception:
            logger.exception("PaddleX OCR model initialization failed.")

    init_thread = threading.Thread(target=init_model, daemon=True)
    init_thread.start()
    init_thread.join(timeout=300)

    if init_thread.is_alive():
        logger.warning("PaddleX OCR model initialization timed out.")

    try:
        yield
    finally:
        cleanup_stop_event.set()
        cleanup_thread.join(timeout=5)
        logger.info("Service stopped, runtime cleanup thread closed.")
