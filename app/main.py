from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.ocr import router
from app.services.ocr_service import ocr_service


@asynccontextmanager
async def lifespan(app: FastAPI):

    print("Loading PaddleX OCR...")

    ocr_service.initialize()

    print("OCR Ready.")

    yield


app = FastAPI(

    title="Document OCR",

    version="1.0.0",

    lifespan=lifespan

)

app.include_router(router)