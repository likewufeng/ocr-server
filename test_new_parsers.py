# -*- coding: utf-8 -*-
#Author: WuFeng <763467339@qq.com>
#Date: 2026-07-28 10:32:24
#LastEditTime: 2026-07-28 10:32:38
#LastEditors: WuFeng <763467339@qq.com>
#Description: 测试新的解析器
#FilePath: /ocr-server/test_new_parsers.py
#Copyright 版权声明
#
# -*- coding: utf-8 -*-
import sys
import os

# 将 ocr-server 添加到系统路径，确保可以导入 app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".")))

from app.utils.layout import Layout, OCRLine
from app.parsers.parser import OCRParser

def test_bank_card():
    print("--- Testing Bank Card ---")
    lines = [
        OCRLine(text="中国工商银行", left=50, top=10, right=200, bottom=30, score=0.99),
        OCRLine(text="6222 0210 0112 3456 789", left=50, top=100, right=400, bottom=130, score=0.98),
        OCRLine(text="借记卡", left=50, top=150, right=100, bottom=170, score=0.95),
        OCRLine(text="VALID THRU 12/29", left=200, top=150, right=350, bottom=170, score=0.95),
    ]
    layout = Layout(lines)
    parser = OCRParser()
    result = parser.parse(layout)
    print("Bank Card Parsed Result:")
    print(result)
    assert result["type"] == "bank_card"
    assert result["bank_name"] == "中国工商银行"
    assert result["card_number"] == "6222021001123456789"
    assert result["card_type"] == "借记卡"
    assert result["valid_date"] == "12/29"
    print("Bank Card Test Passed! ✅")

def test_invoice():
    print("\n--- Testing VAT Invoice ---")
    lines = [
        OCRLine(text="发票代码: 1100192320", left=50, top=10, right=250, bottom=30, score=0.99),
        OCRLine(text="发票号码: 01234567", left=300, top=10, right=500, bottom=30, score=0.99),
        OCRLine(text="开票日期: 2026年07月28日", left=50, top=50, right=300, bottom=70, score=0.98),
        OCRLine(text="购买方", left=50, top=100, right=100, bottom=120, score=0.95),
        OCRLine(text="名称: 阿里巴巴(中国)有限公司", left=110, top=100, right=350, bottom=120, score=0.95),
        OCRLine(text="纳税人识别号: 91330100717621111X", left=110, top=130, right=350, bottom=150, score=0.95),
        OCRLine(text="销售方", left=50, top=200, right=100, bottom=220, score=0.95),
        OCRLine(text="名称: 北京京东世纪贸易有限公司", left=110, top=200, right=350, bottom=220, score=0.95),
        OCRLine(text="纳税人识别号: 91110115781312345Y", left=110, top=230, right=350, bottom=250, score=0.95),
        OCRLine(text="合计", left=50, top=300, right=100, bottom=320, score=0.95),
        OCRLine(text="¥1000.00", left=200, top=300, right=280, bottom=320, score=0.95),
        OCRLine(text="¥60.00", left=300, top=300, right=380, bottom=320, score=0.95),
        OCRLine(text="价税合计", left=50, top=350, right=100, bottom=370, score=0.95),
        OCRLine(text="小写 ¥1060.00", left=200, top=350, right=350, bottom=370, score=0.95),
    ]
    layout = Layout(lines)
    parser = OCRParser()
    result = parser.parse(layout)
    print("VAT Invoice Parsed Result:")
    print(result)
    assert result["type"] == "invoice"
    assert result["invoice_code"] == "1100192320"
    assert result["invoice_number"] == "01234567"
    assert result["issue_date"] == "2026年07月28日"
    assert result["buyer_name"] == "阿里巴巴(中国)有限公司"
    assert result["buyer_tax_id"] == "91330100717621111X"
    assert result["seller_name"] == "北京京东世纪贸易有限公司"
    assert result["seller_tax_id"] == "91110115781312345Y"
    assert result["total_amount"] == "1000.00"
    assert result["total_tax"] == "60.00"
    assert result["amount_with_tax"] == "1060.00"
    print("VAT Invoice Test Passed! ✅")

if __name__ == "__main__":
    test_bank_card()
    test_invoice()
