# -*- coding: utf-8 -*-
#Author: WuFeng <763467339@qq.com>
#Date: 2026-07-28 10:32:24
#LastEditTime: 2026-07-28 15:48:06
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

def test_bank_card_with_typos():
    print("--- Testing Bank Card with OCR Typos ---")
    lines = [
        OCRLine(text="中国建设银行招商银行", left=50, top=10, right=250, bottom=30, score=0.99), # 重叠干扰
        # 卡号包含混淆英文字母 O, I, S, L, Z 和连字符
        OCRLine(text="6222-O210-0112-345S-78L", left=50, top=100, right=400, bottom=130, score=0.98),
        OCRLine(text="DEBIT CARD", left=50, top=150, right=100, bottom=170, score=0.95),
        # 有效期含有 Q (纠正为9) 且格式为 12.2Q
        OCRLine(text="VALID THRU 12.2Q", left=200, top=150, right=350, bottom=170, score=0.95),
    ]
    layout = Layout(lines)
    parser = OCRParser()
    result = parser.parse(layout)
    print("Bank Card Typos Parsed Result:")
    print(result)
    assert result["type"] == "bank_card"
    assert result["bank_name"] == "中国建设银行" # 会智能截取第一个完整的中文序列并丢弃干扰
    assert result["card_number"] == "6222021001123455781" # O->0, S->5, L->1 纠正成功
    assert result["card_type"] == "借记卡"
    assert result["valid_date"] == "12/29" # '.'->'/', Q->9 纠正成功
    print("Bank Card Typos Test Passed!")

def test_invoice_with_typos():
    print("\n--- Testing VAT Invoice with OCR Typos ---")
    lines = [
        # 发票代码 10位 含有混淆字母 O 和 I 
        OCRLine(text="发票代码: 11OO19232I", left=50, top=10, right=250, bottom=30, score=0.99),
        # 发票号码 8位 含有混淆字母 L
        OCRLine(text="发票号码: O1234567", left=300, top=10, right=500, bottom=30, score=0.99),
        # 日期混有字母 O 和 l
        OCRLine(text="开票日期: 2O26年O7月28日", left=50, top=50, right=300, bottom=70, score=0.98),
        OCRLine(text="购买方", left=50, top=100, right=100, bottom=120, score=0.95),
        OCRLine(text="名 称: 腾讯科技(深圳)有限公司", left=110, top=100, right=350, bottom=120, score=0.95),
        # 纳税人识别号有混淆字母 I、O、S 等，程序会进行 18 位信用代码精细化还原
        OCRLine(text="纳税人识别号: 9133O1OO717621111X", left=110, top=130, right=350, bottom=150, score=0.95),
        OCRLine(text="销售方", left=50, top=200, right=100, bottom=220, score=0.95),
        OCRLine(text="名称: 百度在线网络技术有限公司", left=110, top=200, right=350, bottom=220, score=0.95),
        OCRLine(text="识别号: 9111O115781312345Y", left=110, top=230, right=350, bottom=250, score=0.95),
        OCRLine(text="合计", left=50, top=300, right=100, bottom=320, score=0.95),
        # 金额含有 * 且小数点后含有 O 和 l
        OCRLine(text="¥*1,OOO.OO", left=200, top=300, right=280, bottom=320, score=0.95),
        OCRLine(text="¥6O.OO", left=300, top=300, right=380, bottom=320, score=0.95),
        OCRLine(text="价税合计", left=50, top=350, right=100, bottom=370, score=0.95),
        OCRLine(text="小写 ¥1,O6O.OO", left=200, top=350, right=350, bottom=370, score=0.95),
    ]
    layout = Layout(lines)
    parser = OCRParser()
    result = parser.parse(layout)
    print("VAT Invoice Typos Parsed Result:")
    print(result)
    assert result["type"] == "invoice"
    assert result["invoice_code"] == "1100192321" # I->1, O->0 纠正成功
    assert result["invoice_number"] == "01234567" # O->0 纠正成功
    assert result["issue_date"] == "2026年07月28日" # O->0 纠正成功
    assert result["buyer_name"] == "腾讯科技(深圳)有限公司"
    assert result["buyer_tax_id"] == "91330100717621111X" # O->0 纠正成功
    assert result["seller_name"] == "百度在线网络技术有限公司"
    assert result["seller_tax_id"] == "91110115781312345Y" # O->0 纠正成功
    assert result["total_amount"] == "1000.00" # O->0 纠正成功
    assert result["total_tax"] == "60.00" # O->0 纠正成功
    assert result["amount_with_tax"] == "1060.00" # O->0 纠正成功
    print("VAT Invoice Typos Test Passed!")

def test_id_front_with_split_id_label():
    print("\n--- Testing ID Front with Split ID Label ---")
    lines = [
        OCRLine(text="姓名测试用户", left=50, top=20, right=180, bottom=45, score=0.99),
        OCRLine(text="性别男民族汉", left=50, top=70, right=200, bottom=95, score=0.98),
        OCRLine(text="出生2000年01月01日", left=50, top=120, right=260, bottom=145, score=0.98),
        OCRLine(text="住址测试省测试市测试区", left=50, top=170, right=320, bottom=195, score=0.98),
        OCRLine(text="公民身份", left=50, top=230, right=155, bottom=255, score=0.95),
        OCRLine(text="00000020000101000X", left=180, top=230, right=420, bottom=255, score=0.99),
    ]
    layout = Layout(lines)
    parser = OCRParser()
    result = parser.parse(layout)
    print("ID Front Split Label Parsed Result:")
    print(result)
    assert result["type"] == "id_front"
    assert result["name"] == "测试用户"
    assert result["gender"] == "男"
    assert result["nation"] == "汉"
    assert result["birthday"] == "2000年01月01日"
    assert result["id_number"] == "00000020000101000X"
    print("ID Front Split Label Test Passed!")

def test_id_front_with_split_address_and_nation():
    print("\n--- Testing ID Front with Split Address and Nation ---")
    lines = [
        OCRLine(text="姓名吴烽", left=358, top=189, right=594, bottom=248, score=0.8657310009002686),
        OCRLine(text="性别男", left=365, top=269, right=526, bottom=321, score=0.9992308616638184),
        OCRLine(text="民族汉", left=505, top=268, right=705, bottom=314, score=0.9970760345458984),
        OCRLine(text="出生1991年8月15日", left=369, top=330, right=785, bottom=389, score=0.9874458909034729),
        OCRLine(text="住址", left=372, top=415, right=489, bottom=461, score=0.9989250898361206),
        OCRLine(text="河南省渑池县洪阳镇德厚", left=466, top=405, right=851, bottom=460, score=0.9590575695037842),
        OCRLine(text="村七组1号", left=482, top=454, right=665, bottom=508, score=0.9967519640922546),
        OCRLine(text="公民身份号码411221199108152534", left=380, top=571, right=1114, bottom=647, score=0.9967567324638367),
    ]
    layout = Layout(lines)
    parser = OCRParser()
    result = parser.parse(layout)
    print("ID Front Split Address Parsed Result:")
    print(result)
    assert result["type"] == "id_front"
    assert result["nation"] == "汉"
    assert result["address"] == "河南省渑池县洪阳镇德厚村七组1号"
    assert result["id_number"] == "411221199108152534"
    print("ID Front Split Address Test Passed!")

if __name__ == "__main__":
    test_id_front_with_split_id_label()
    test_id_front_with_split_address_and_nation()
    test_bank_card_with_typos()
    test_invoice_with_typos()
