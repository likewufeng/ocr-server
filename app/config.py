'''
Author: WuFeng <763467339@qq.com>
Date: 2026-07-08 17:10:38
LastEditTime: 2026-07-08 17:11:04
LastEditors: WuFeng <763467339@qq.com>
Description: 
FilePath: \ocr-server\app\config.py
Copyright 版权声明
'''
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

MODEL_DIR = BASE_DIR / "models"
MODEL_DIR.mkdir(exist_ok=True)

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)