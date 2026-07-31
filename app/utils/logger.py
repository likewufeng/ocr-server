# 使用方式：
# from app.utils.logger import logger
# logger.info("xxxx")
# logger.error(e)

from pathlib import Path

from loguru import logger

from app.config import LOG_DIR, LOG_RETENTION_DAYS

logger.remove()

logger.configure(extra={"request_id": "-"})

log_format = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
    "request_id={extra[request_id]} | {name}:{function}:{line} - {message}"
)

logger.add(
    LOG_DIR / "ocr.log",
    rotation="00:00",
    retention=f"{LOG_RETENTION_DAYS} days",
    encoding="utf-8",
    enqueue=True,
    format=log_format,
)

logger.add(
    lambda msg: print(msg, end=""),
    format=log_format,
)
