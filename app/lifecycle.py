'''
Author: WuFeng <763467339@qq.com>
Date: 2026-07-08 18:03:10
LastEditTime: 2026-07-08 18:03:30
LastEditors: WuFeng <763467339@qq.com>
Description: 
FilePath: \ocr-server\app\lifecycle.py
Copyright 版权声明
'''
from contextlib import asynccontextmanager

from app.services.ocr_service import ocr_service

from app.utils.logger import logger


@asynccontextmanager
async def lifespan(app):

    logger.info("Loading PaddleX OCR Model...")

    ocr_service.initialize()

    logger.info("OCR Ready.")

    yield

    logger.info("Server Closed.")