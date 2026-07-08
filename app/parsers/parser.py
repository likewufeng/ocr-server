'''
Author: WuFeng <763467339@qq.com>
Date: 2026-07-08 17:14:33
LastEditTime: 2026-07-08 21:09:00
LastEditors: WuFeng <763467339@qq.com>
Description: 
FilePath: \ocr-server\app\parsers\parser.py
Copyright 版权声明
'''
from app.parsers.business import BusinessParser
from app.parsers.detector import detect_type
from app.parsers.id_back import IDBackParser
from app.parsers.id_front import IDFrontParser
from app.utils.layout import build_layout


class DocumentParser:

    def __init__(self):

        self.id_front_parser = IDFrontParser()
        self.id_back_parser = IDBackParser()
        self.business_parser = BusinessParser()

    def parse(self, ocr_result: dict):

        layout = build_layout(ocr_result)

        doc_type = detect_type(layout)

        if doc_type == "id_front":
            return self.id_front_parser.parse(layout)

        if doc_type == "id_back":
            return self.id_back_parser.parse(layout)

        if doc_type == "business_license":
            return self.business_parser.parse(layout)

        return {
            "type": "unknown",
            "ocr": {
                "texts": layout.texts()
            }
        }


document_parser = DocumentParser()


def parse(ocr_result: dict):
    """
    对外统一入口
    """
    return document_parser.parse(ocr_result)