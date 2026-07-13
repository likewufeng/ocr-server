from contextlib import asynccontextmanager
from fastapi import FastAPI
import threading
import time

from app.services.ocr_service import ocr_service
from app.utils.logger import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化 PaddleX（只加载一次）
    logger.info("正在初始化 PaddleX OCR 模型...")
    
    # 使用线程异步初始化模型，避免阻塞 FastAPI 启动
    def init_model():
        try:
            ocr_service.initialize()
            logger.info("PaddleX OCR 模型初始化完成！")
        except Exception as e:
            logger.error(f"模型初始化失败: {e}")
    
    # 启动初始化线程
    init_thread = threading.Thread(target=init_model, daemon=True)
    init_thread.start()
    
    # 等待模型初始化完成（最多 300 秒）
    init_thread.join(timeout=300)
    
    if init_thread.is_alive():
        logger.warning("模型初始化超时，请检查网络或模型文件")
    
    yield
    
    # 关闭时清理
    logger.info("服务关闭，清理资源...")