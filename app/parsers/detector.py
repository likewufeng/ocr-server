'''
Author: WuFeng <763467339@qq.com>
Date: 2026-07-08 17:12:48
LastEditTime: 2026-07-08 21:10:08
LastEditors: WuFeng <763467339@qq.com>
Description: 
FilePath: \ocr-server\app\parsers\detector.py
Copyright 版权声明
'''
from app.utils.layout import Layout


def detect_type(layout: Layout):

    text = "".join(layout.texts())

    if "公民身份号码" in text:
        return "id_front"

    if "签发机关" in text:
        return "id_back"

    if "统一社会信用代码" in text:
        return "business_license"

    return "unknown"