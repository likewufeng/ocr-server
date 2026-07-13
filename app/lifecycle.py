from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.services.ocr_service import ocr_service
from app.utils.logger import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化 PaddleX（只加载一次）
    logger.info("正在初始化 PaddleX OCR 模型...")
    ocr_service.initialize()
    logger.info("PaddleX OCR 模型初始化完成！")
    
    yield
    
    # 关闭时清理
    logger.info("服务关闭，清理资源...")