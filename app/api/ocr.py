# -*- coding: utf-8 -*-
#Author: WuFeng <763467339@qq.com>
#Date: 2026-07-09 10:20:58
#LastEditTime: 2026-07-13 14:59:12
#LastEditors: WuFeng <763467339@qq.com>
#Description: OCR 识别接口
#FilePath: /ocr-server/app/api/ocr.py
#Copyright 版权声明
#
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


@router.post("/ocr/raw")
async def ocr_raw(file: UploadFile = File(...)):
    """
    原始 OCR 识别接口
    
    直接返回 PaddleX OCR 的原始识别结果，不经过布局分析和文档解析。
    
    返回数据包含：
    - texts: 识别出的文本列表
    - scores: 置信度分数列表  
    - boxes: 文本框坐标列表
    - polys: 文本多边形坐标列表
    - angle: 文档倾斜角度
    """

    suffix = file.filename.split(".")[-1]

    filename = f"{uuid.uuid4()}.{suffix}"

    path = UPLOAD_DIR / filename

    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:

        # PaddleX OCR - 直接返回原始结果
        ocr_result = ocr_service.recognize(str(path))

        return ApiResponse.success(ocr_result)

    finally:

        if path.exists():
            path.unlink()