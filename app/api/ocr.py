import shutil
import uuid

from fastapi import APIRouter
from fastapi import File
from fastapi import UploadFile

from app.config import UPLOAD_DIR
from app.schemas.response import ApiResponse
from app.services.ocr_service import ocr_service

from app.utils.layout import build_layout
from app.parsers.parser import OCRParser


router = APIRouter(
    prefix="",
    tags=["OCR"]
)

parser = OCRParser()


@router.post("/ocr")
async def ocr(file: UploadFile = File(...)):

    suffix = file.filename.split(".")[-1]

    filename = f"{uuid.uuid4()}.{suffix}"

    path = UPLOAD_DIR / filename

    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:

        # PaddleX OCR
        ocr_result = ocr_service.recognize(str(path))

        # OCR -> Layout
        layout = build_layout(ocr_result)

        # Layout -> Document
        document = parser.parse(layout)

        return ApiResponse.success(document)

    finally:

        if path.exists():
            path.unlink()