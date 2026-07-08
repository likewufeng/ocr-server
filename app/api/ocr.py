import shutil
import uuid

from fastapi import APIRouter
from fastapi import File
from fastapi import UploadFile

from app.config import UPLOAD_DIR
from app.schemas.response import ApiResponse
from app.services.ocr_service import ocr_service

router = APIRouter(
    prefix="",
    tags=["OCR"]
)


@router.post("/ocr")
async def ocr(
    file: UploadFile = File(...)
):

    suffix = file.filename.split(".")[-1]

    filename = f"{uuid.uuid4()}.{suffix}"

    path = UPLOAD_DIR / filename

    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:

        result = ocr_service.recognize(
            str(path)
        )

        return ApiResponse.success(
            result
        )

    finally:

        if path.exists():
            path.unlink()