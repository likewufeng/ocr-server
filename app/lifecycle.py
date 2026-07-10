from contextlib import asynccontextmanager

from app.services.ocr_service import ocr_service

from app.utils.logger import logger


@asynccontextmanager
async def lifespan(app):

    logger.info("Loading PaddleX OCR Model...")

    ocr_service.initialize()

    logger.info("OCR Ready.")

    yield

    logger.info("Server Closed.")