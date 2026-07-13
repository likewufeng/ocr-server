# -*- coding: utf-8 -*-
#Author: WuFeng <763467339@qq.com>
#Date: 2026-07-09 10:20:58
#LastEditTime: 2026-07-13 17:11:51
#LastEditors: WuFeng <763467339@qq.com>
#Description: 
#FilePath: /ocr-server/app/main.py
#Copyright 版权声明
#
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
from app.api.authorization_letter import router as auth_letter_router
from app.lifecycle import lifespan
from app.config import APP_NAME

app = FastAPI(
    title=APP_NAME,
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(health_router)
app.include_router(ocr_router)
app.include_router(auth_letter_router)

@app.get("/")
async def root():
    return {"message": "OCR 服务已启动（本地热重载模式）"}