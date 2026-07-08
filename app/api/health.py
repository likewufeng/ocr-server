'''
Author: WuFeng <763467339@qq.com>
Date: 2026-07-08 18:02:23
LastEditTime: 2026-07-08 18:02:24
LastEditors: WuFeng <763467339@qq.com>
Description: 
FilePath: \ocr-server\app\api\health.py
Copyright 版权声明
'''
from fastapi import APIRouter

router = APIRouter(
    prefix="/health",
    tags=["Health"]
)


@router.get("")
def health():

    return {
        "status": "ok"
    }