'''
Author: WuFeng <763467339@qq.com>
Date: 2026-07-08 17:15:05
LastEditTime: 2026-07-08 20:50:29
LastEditors: WuFeng <763467339@qq.com>
Description: 
FilePath: \ocr-server\app\api\ocr.py
Copyright 版权声明
'''
import shutil
import uuid

from fastapi import APIRouter
from fastapi import File
from fastapi import UploadFile

from app.config import UPLOAD_DIR
from app.schemas.response import ApiResponse
from app.services.ocr_service import ocr_service

from app.parsers.parser import parse

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

        ocr_result = ocr_service.recognize(str(path))

        document = parse(ocr_result)

        return ApiResponse.success(document)

    finally:

        if path.exists():
            path.unlink()