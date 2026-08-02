from pathlib import Path

from dotenv import load_dotenv

import os

load_dotenv()


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


BASE_DIR = Path(__file__).resolve().parent.parent

APP_NAME = os.getenv("APP_NAME")

HOST = os.getenv("HOST")

PORT = int(os.getenv("PORT"))

UPLOAD_DIR = BASE_DIR / os.getenv("UPLOAD_DIR", "data/uploads")

OUTPUT_DIR = BASE_DIR / os.getenv("OUTPUT_DIR", "data/outputs")

CACHE_DIR = BASE_DIR / os.getenv("CACHE_DIR", "data/cache")

MODEL_DIR = BASE_DIR / os.getenv("MODEL_DIR", "models")

LOG_DIR = BASE_DIR / os.getenv("LOG_DIR", "data/logs")

DYNAMIC_FILE_RETENTION_DAYS = int(os.getenv("DYNAMIC_FILE_RETENTION_DAYS", "1"))

LOG_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "3"))

CLEANUP_INTERVAL_SECONDS = int(os.getenv("CLEANUP_INTERVAL_SECONDS", "3600"))

OCR_USE_FINE_TUNED_MODEL = _env_bool("OCR_USE_FINE_TUNED_MODEL", True)

OCR_MODEL_PROFILE = os.getenv("OCR_MODEL_PROFILE", "server").strip().lower()
if OCR_MODEL_PROFILE not in {"mobile", "server"}:
    raise ValueError("OCR_MODEL_PROFILE must be 'mobile' or 'server'")

OCR_DEVICE = os.getenv("OCR_DEVICE", "cpu").strip().lower()

OCR_ENABLE_MKLDNN = _env_bool("OCR_ENABLE_MKLDNN", True)

OCR_CPU_THREADS = max(
    1, int(os.getenv("OCR_CPU_THREADS", str(min(8, os.cpu_count() or 1))))
)

OCR_TEXT_RECOGNITION_BATCH_SIZE = max(
    1, int(os.getenv("OCR_TEXT_RECOGNITION_BATCH_SIZE", "6"))
)

OCR_ENABLE_DOC_ORIENTATION_MODEL = _env_bool(
    "OCR_ENABLE_DOC_ORIENTATION_MODEL", True
)

OCR_USE_DOC_ORIENTATION = _env_bool("OCR_USE_DOC_ORIENTATION", True)

OCR_USE_DOC_UNWARPING = _env_bool("OCR_USE_DOC_UNWARPING", False)

OCR_SAVE_PREPROCESSED_IMAGE = _env_bool("OCR_SAVE_PREPROCESSED_IMAGE", True)

OCR_PREPROCESSED_JPEG_QUALITY = min(
    100, max(1, int(os.getenv("OCR_PREPROCESSED_JPEG_QUALITY", "90")))
)

OCR_CACHE_ENABLED = _env_bool("OCR_CACHE_ENABLED", True)

OCR_CACHE_VERSION = os.getenv("OCR_CACHE_VERSION", "1").strip()

OCR_MAX_CONCURRENT_REQUESTS = max(
    1, int(os.getenv("OCR_MAX_CONCURRENT_REQUESTS", "1"))
)

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CACHE_DIR.mkdir(parents=True, exist_ok=True)

MODEL_DIR.mkdir(parents=True, exist_ok=True)

LOG_DIR.mkdir(parents=True, exist_ok=True)
