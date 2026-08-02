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

_file_sink_id = None


def _configure_sinks() -> None:
    global _file_sink_id

    logger.remove()
    logger.configure(extra={"request_id": "-"})
    _file_sink_id = logger.add(
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


def reset_expired_active_log(cutoff: float) -> bool:
    """Rotate away an inactive active log file that is older than cutoff."""
    log_path = LOG_DIR / "ocr.log"
    try:
        if not log_path.exists() or log_path.stat().st_mtime >= cutoff:
            return False
    except FileNotFoundError:
        return False

    if _file_sink_id is not None:
        logger.remove(_file_sink_id)
    try:
        log_path.unlink(missing_ok=True)
    except Exception as exc:
        _configure_sinks()
        logger.warning("Failed to remove expired active log {}: {}", log_path, exc)
        return False
    _configure_sinks()
    return True


_configure_sinks()
