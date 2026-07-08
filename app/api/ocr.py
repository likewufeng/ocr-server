'''
Author: WuFeng <763467339@qq.com>
Date: 2026-07-08 17:15:05
LastEditTime: 2026-07-08 17:17:10
LastEditors: WuFeng <763467339@qq.com>
Description: 
FilePath: \ocr-server\app\api\ocr.py
Copyright 版权声明
'''
import os
import shutil
import uuid

from fastapi import APIRouter, File, UploadFile

from app.config import UPLOAD_DIR
from app.parsers.parser import parse
from app.schemas.response import ApiResponse
from app.services.ocr_service import ocr_service

router = APIRouter()


@router.post("/ocr")
async def ocr(file: UploadFile = File(...)):

    ext = file.filename.split(".")[-1]

    filename = f"{uuid.uuid4()}.{ext}"

    path = UPLOAD_DIR / filename

    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:

        result = ocr_service.recognize(str(path))

        return ApiResponse.success(
            parse(result["texts"])
        )

    except Exception as e:

        return ApiResponse.error(str(e))

    finally:

        if os.path.exists(path):
            os.remove(path)