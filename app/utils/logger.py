# 使用方式：
# from app.utils.logger import logger
# logger.info("xxxx")
# logger.error(e)

from pathlib import Path

from loguru import logger

from app.config import LOG_DIR

logger.remove()

logger.add(
    LOG_DIR / "ocr.log",
    rotation="100 MB",
    retention="30 days",
    encoding="utf-8",
    enqueue=True
)

logger.add(
    lambda msg: print(msg, end="")
)