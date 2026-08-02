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
import time
import uuid

from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import JSONResponse

from app.api.health import router as health_router
from app.api.metrics import router as metrics_router
from app.api.ocr import router as ocr_router
from app.api.authorization_letter import router as auth_letter_router
from app.lifecycle import lifespan
from app.config import APP_NAME
from app.schemas.response import ApiResponse
from app.utils.logger import logger
from app.utils.metrics import metrics
from app.utils.request_context import reset_request_id, set_request_id

app = FastAPI(
    title=APP_NAME,
    version="1.0.0",
    lifespan=lifespan
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = uuid.uuid4().hex
    request.state.request_id = request_id
    token = set_request_id(request_id)
    started_at = time.perf_counter()
    monitor_request = request.url.path not in {"/metrics", "/metrics/json"}
    if monitor_request:
        metrics.http_started()

    with logger.contextualize(request_id=request_id):
        logger.info("Request started: {} {}", request.method, request.url.path)
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "Unhandled request error: {} {}", request.method, request.url.path
            )
            response = JSONResponse(
                status_code=500,
                content=ApiResponse.error(
                    "Internal server error", request_id=request_id
                ),
            )

        response.headers["X-Request-ID"] = request_id
        duration_seconds = time.perf_counter() - started_at
        duration_ms = duration_seconds * 1000
        route = request.scope.get("route")
        route_path = getattr(route, "path", None) or "unmatched"
        if monitor_request:
            metrics.http_completed(
                request.method, route_path, response.status_code, duration_seconds
            )
        logger.info(
            "Request completed: {} {} status={} duration_ms={:.2f}",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )

    reset_request_id(token)
    return response

app.include_router(health_router)
app.include_router(metrics_router)
app.include_router(ocr_router)
app.include_router(auth_letter_router)

@app.get("/")
async def root():
    return {"message": "OCR 服务已启动（本地热重载模式）"}
