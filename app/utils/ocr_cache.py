import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Optional

from app.config import CACHE_DIR, OCR_CACHE_ENABLED
from app.utils.logger import logger


class OCRCache:
    def __init__(self, directory: Path = CACHE_DIR, enabled: bool = OCR_CACHE_ENABLED):
        self.directory = Path(directory)
        self.enabled = enabled
        self._lock = threading.Lock()
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(self, key: str) -> Optional[dict[str, Any]]:
        if not self.enabled:
            return None

        path = self._path(key)
        with self._lock:
            try:
                with path.open("r", encoding="utf-8") as cache_file:
                    result = json.load(cache_file)
                os.utime(path, None)
            except FileNotFoundError:
                return None
            except (OSError, ValueError, TypeError) as exc:
                logger.warning("Failed to read OCR cache {}: {}", path, exc)
                return None

        return result if isinstance(result, dict) else None

    def set(self, key: str, result: dict[str, Any]) -> None:
        if not self.enabled:
            return

        path = self._path(key)
        temp_path = self.directory / f".{key}.{uuid.uuid4().hex}.tmp"
        with self._lock:
            try:
                with temp_path.open("w", encoding="utf-8") as cache_file:
                    json.dump(result, cache_file, ensure_ascii=False)
                os.replace(temp_path, path)
            except (OSError, TypeError, ValueError) as exc:
                logger.warning("Failed to write OCR cache {}: {}", path, exc)
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass


ocr_cache = OCRCache()
