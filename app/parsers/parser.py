'''
Author: WuFeng <763467339@qq.com>
Date: 2026-07-08 17:14:33
LastEditTime: 2026-07-08 17:14:51
LastEditors: WuFeng <763467339@qq.com>
Description: 
FilePath: \ocr-server\app\parsers\parser.py
Copyright 版权声明
'''
from app.parsers.business import BusinessParser
from app.parsers.detector import detect_type
from app.parsers.id_back import IDBackParser
from app.parsers.id_front import IDFrontParser


def parse(texts):

    tp = detect_type(texts)

    if tp == "id_front":
        return IDFrontParser().parse(texts)

    if tp == "id_back":
        return IDBackParser().parse(texts)

    if tp == "business_license":
        return BusinessParser().parse(texts)

    return {
        "type": "unknown",
        "texts": texts
    }