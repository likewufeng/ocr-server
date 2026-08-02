# -*- coding: utf-8 -*-
#Author: WuFeng <763467339@qq.com>
#Date: 2026-07-09 10:20:58
#LastEditTime: 2026-07-28 10:35:48
#LastEditors: WuFeng <763467339@qq.com>
#Description: 通用解析器
# 用于根据文档类型自动选择并执行解析操作。
#FilePath: /ocr-server/app/parsers/parser.py
#Copyright 版权声明
#
from app.utils.layout import Layout
from app.parsers.detector import DocumentDetector
from app.parsers.id_front import IDFrontParser
from app.parsers.id_back import IDBackParser
from app.parsers.business import BusinessParser
from app.parsers.bank_card import BankCardParser
from app.parsers.invoice import InvoiceParser

class OCRParser:
    def __init__(self):
        self.detector = DocumentDetector()
        self.parsers = {
            "id_front": IDFrontParser(),
            "id_back": IDBackParser(),
            "business_license": BusinessParser(),
            "bank_card": BankCardParser(),
            "invoice": InvoiceParser()
        }

    def parse(self, layout: Layout, document_type=None):
        # 调用方明确给出类型时，跳过自动检测并直接走对应解析器。
        doc_type = document_type or self.detector.detect(layout)
        
        # 2. 选择对应的解析器
        parser = self.parsers.get(doc_type)
        
        if not parser:
            return {
                "type": "unknown",
                "error": "未能识别证件类型",
                "raw_texts": layout.texts()
            }
        
        # 3. 执行解析
        try:
            result = parser.parse(layout)
            return result
        except Exception as e:
            return {
                "type": doc_type,
                "error": f"解析失败: {str(e)}"
            }
