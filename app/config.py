from pathlib import Path

from dotenv import load_dotenv

import os

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

APP_NAME = os.getenv("APP_NAME")

HOST = os.getenv("HOST")

PORT = int(os.getenv("PORT"))

UPLOAD_DIR = BASE_DIR / os.getenv("UPLOAD_DIR")

MODEL_DIR = BASE_DIR / os.getenv("MODEL_DIR")

LOG_DIR = BASE_DIR / os.getenv("LOG_DIR")

UPLOAD_DIR.mkdir(exist_ok=True)

MODEL_DIR.mkdir(exist_ok=True)

LOG_DIR.mkdir(exist_ok=True)