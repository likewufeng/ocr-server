import shutil
import time
from pathlib import Path

from app.config import (
    CACHE_DIR,
    DYNAMIC_FILE_RETENTION_DAYS,
    LOG_DIR,
    LOG_RETENTION_DAYS,
    OUTPUT_DIR,
    UPLOAD_DIR,
)
from app.utils.logger import logger, reset_expired_active_log


def _remove_expired_entries(directory: Path, retention_days: int) -> int:
    cutoff = time.time() - retention_days * 24 * 60 * 60
    removed = 0

    for entry in directory.iterdir():
        try:
            if entry.stat().st_mtime >= cutoff:
                continue

            if entry.is_symlink() or entry.is_file():
                entry.unlink()
            elif entry.is_dir():
                shutil.rmtree(entry)
            else:
                continue
            removed += 1
        except FileNotFoundError:
            continue
        except Exception as exc:
            logger.warning("Failed to clean expired entry {}: {}", entry, exc)

    return removed


def _remove_expired_logs() -> int:
    cutoff = time.time() - LOG_RETENTION_DAYS * 24 * 60 * 60
    removed = 1 if reset_expired_active_log(cutoff) else 0

    for entry in LOG_DIR.iterdir():
        try:
            if not entry.is_file():
                continue
            if entry.stat().st_mtime >= cutoff:
                continue
            entry.unlink()
            removed += 1
        except FileNotFoundError:
            continue
        except Exception as exc:
            logger.warning("Failed to clean expired log {}: {}", entry, exc)

    return removed


def cleanup_runtime_data() -> None:
    uploads_removed = _remove_expired_entries(
        UPLOAD_DIR, DYNAMIC_FILE_RETENTION_DAYS
    )
    outputs_removed = _remove_expired_entries(
        OUTPUT_DIR, DYNAMIC_FILE_RETENTION_DAYS
    )
    cache_removed = _remove_expired_entries(
        CACHE_DIR, DYNAMIC_FILE_RETENTION_DAYS
    )
    logs_removed = _remove_expired_logs()

    if uploads_removed or outputs_removed or cache_removed or logs_removed:
        logger.info(
            "Runtime cleanup completed: uploads={}, outputs={}, cache={}, logs={}",
            uploads_removed,
            outputs_removed,
            cache_removed,
            logs_removed,
        )
