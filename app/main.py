'''
HTTP

        │

        ▼

OCR API

        │

        ▼

OCRService

        │

        ▼

PaddleX

        │

        ▼

OCR Result

        │

        ▼

Layout

        │

        ▼

Detector

        │

        ▼

Parser

        │

        ▼

JSON
'''
from fastapi import FastAPI

from app.api.health import router as health_router

from app.api.ocr import router as ocr_router

from app.lifecycle import lifespan

from app.config import APP_NAME

app = FastAPI(

    title=APP_NAME,

    version="1.0.0",

    lifespan=lifespan

)

app.include_router(health_router)

app.include_router(ocr_router)