# -*- coding: utf-8 -*-
#Author: WuFeng <763467339@qq.com>
#Date: 2026-07-09 10:20:58
#LastEditTime: 2026-07-10 11:13:19
#LastEditors: WuFeng <763467339@qq.com>
#Description: Health API
#FilePath: /ocr-server/app/api/health.py
#Copyright 版权声明
#
from fastapi import APIRouter, Response

from app.services.ocr_service import ocr_service

router = APIRouter(
    prefix="/health",
    tags=["Health"]
)


@router.get("")
def health(response: Response):
    model_ready = ocr_service.pipeline is not None
    if not model_ready:
        response.status_code = 503
    return {
        "status": "ok" if model_ready else "not_ready",
        "model_ready": model_ready,
    }
