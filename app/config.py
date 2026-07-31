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

MODEL_DIR = BASE_DIR / os.getenv("MODEL_DIR", "models")

LOG_DIR = BASE_DIR / os.getenv("LOG_DIR", "data/logs")

DYNAMIC_FILE_RETENTION_DAYS = int(os.getenv("DYNAMIC_FILE_RETENTION_DAYS", "1"))

LOG_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "3"))

CLEANUP_INTERVAL_SECONDS = int(os.getenv("CLEANUP_INTERVAL_SECONDS", "3600"))

OCR_USE_FINE_TUNED_MODEL = _env_bool("OCR_USE_FINE_TUNED_MODEL", True)

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MODEL_DIR.mkdir(parents=True, exist_ok=True)

LOG_DIR.mkdir(parents=True, exist_ok=True)
