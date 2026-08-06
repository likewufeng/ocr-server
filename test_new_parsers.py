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
from pathlib import Path
from tempfile import TemporaryDirectory

# 将 ocr-server 添加到系统路径，确保可以导入 app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".")))

from app.utils.layout import Layout, OCRLine
from app.parsers.parser import OCRParser
from app.utils.ocr_cache import OCRCache


def test_document_type_hint():
    print("--- Testing Document Type Hint ---")
    lines = [
        OCRLine(text="姓名吴烽", left=50, top=20, right=180, bottom=45, score=0.99),
        OCRLine(text="411221199108152534", left=50, top=80, right=320, bottom=110, score=0.99),
    ]
    parser = OCRParser()
    assert parser.parse(Layout(lines))["type"] == "unknown"
    hinted = parser.parse(Layout(lines), document_type="id_front")
    assert hinted["type"] == "id_front"
    assert hinted["name"] == "吴烽"
    assert hinted["id_number"] == "411221199108152534"
    print("Document Type Hint Test Passed!")


def test_document_type_detects_bank_card_from_luhn_number():
    print("\n--- Testing Bank Card Detection From Luhn Number ---")
    lines = [
        OCRLine(text="4532015112830366", left=50, top=80, right=350, bottom=110, score=0.99),
    ]
    assert OCRParser().parse(Layout(lines))["type"] == "bank_card"
    print("Bank Card Luhn Detection Test Passed!")


def test_ocr_cache_round_trip():
    print("\n--- Testing OCR Cache Round Trip ---")
    with TemporaryDirectory() as temp_dir:
        cache = OCRCache(Path(temp_dir), enabled=True)
        result = {"texts": ["测试"], "scores": [0.99]}
        assert cache.get("missing") is None
        cache.set("sample", result)
        assert cache.get("sample") == result
    print("OCR Cache Round Trip Test Passed!")


def test_business_license_with_missing_address_prefix():
    print("\n--- Testing Business License with Missing Address Prefix ---")
    lines = [
        OCRLine(text="营业执照", left=1636, top=1074, right=2682, bottom=1317, score=0.99),
        OCRLine(text="统一社会信用代码", left=654, top=1143, right=1250, bottom=1217, score=0.99),
        OCRLine(text="91410000692152338A", left=688, top=1221, right=1139, bottom=1278, score=0.99),
        OCRLine(text="称河南省信息化集团有限公司", left=922, top=1591, right=1700, bottom=1652, score=0.99),
        OCRLine(text="注册资本叁仟零柒拾柒万圆整", left=2371, top=1573, right=3238, bottom=1647, score=0.99),
        OCRLine(text="型其他有限责任公司", left=914, top=1708, right=1496, bottom=1787, score=0.99),
        OCRLine(text="成立日期2009年07月06日", left=2372, top=1704, right=3124, bottom=1778, score=0.99),
        OCRLine(text="所 郑州市郑东新区明理路祭城南正商", left=2609, top=1821, right=3545, bottom=1917, score=0.95),
        OCRLine(text="法定代表人王秀清", left=706, top=1843, right=1241, bottom=1917, score=0.99),
        OCRLine(text="博雅广场4号楼15层", left=2733, top=1921, right=3188, bottom=1982, score=0.99),
        OCRLine(text="经营范围", left=710, top=1969, right=1033, bottom=2047, score=0.99),
        OCRLine(text="许可项目：软件开发", left=1071, top=1960, right=2231, bottom=2004, score=0.99),
    ]
    result = OCRParser().parse(Layout(lines), document_type="business_license")
    assert result["address"] == "河南省郑州市郑东新区明理路祭城南正商博雅广场4号楼15层"
    print("Business License Missing Address Prefix Test Passed!")

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

def test_bank_card_with_split_bank_name():
    print("\n--- Testing Bank Card with Split Bank Name ---")
    lines = [
        OCRLine(text="中国", left=40, top=10, right=90, bottom=35, score=0.99),
        OCRLine(text="建设银行", left=95, top=10, right=190, bottom=35, score=0.99),
        OCRLine(text="6222 0210 0112 3455 781", left=50, top=100, right=430, bottom=130, score=0.99),
        OCRLine(text="VALID", left=180, top=150, right=230, bottom=175, score=0.99),
        OCRLine(text="THRU", left=235, top=150, right=285, bottom=175, score=0.99),
        OCRLine(text="1229", left=290, top=150, right=350, bottom=175, score=0.99),
    ]
    layout = Layout(lines)
    parser = OCRParser()
    result = parser.parse(layout)
    print("Bank Card Split Bank Parsed Result:")
    print(result)
    assert result["type"] == "bank_card"
    assert result["bank_name"] == "中国建设银行"
    assert result["card_number"] == "6222021001123455781"
    assert result["valid_date"] == "12/29"
    print("Bank Card Split Bank Test Passed!")


def test_bank_card_prefers_luhn_valid_candidate():
    print("\n--- Testing Bank Card Luhn Candidate Selection ---")
    lines = [
        OCRLine(text="4532015112830367", left=50, top=100, right=350, bottom=130, score=0.99),
        OCRLine(text="4532015112830366", left=50, top=150, right=350, bottom=180, score=0.80),
        OCRLine(text="EXP DATE 12/29", left=50, top=200, right=220, bottom=225, score=0.99),
    ]
    result = OCRParser().parse(Layout(lines), document_type="bank_card")
    assert result["card_number"] == "4532015112830366"
    assert result["valid_date"] == "12/29"
    print("Bank Card Luhn Candidate Selection Test Passed!")


def test_bank_card_uses_bin_when_bank_text_is_missing():
    print("\n--- Testing Bank Card BIN Fallback ---")
    lines = [
        OCRLine(text="6228480402564890018", left=50, top=100, right=400, bottom=130, score=0.99),
    ]
    result = OCRParser().parse(Layout(lines), document_type="bank_card")
    assert result["bank_name"] == "中国农业银行"
    assert result["card_type"] == "借记卡"
    print("Bank Card BIN Fallback Test Passed!")


def test_bank_card_unknown_type_is_not_guessed_by_length():
    print("\n--- Testing Bank Card Unknown Type ---")
    lines = [
        OCRLine(text="4532015112830366", left=50, top=100, right=350, bottom=130, score=0.99),
    ]
    result = OCRParser().parse(Layout(lines), document_type="bank_card")
    assert result["card_type"] == ""
    print("Bank Card Unknown Type Test Passed!")

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

def test_invoice_with_split_name_labels():
    print("\n--- Testing VAT Invoice with Split Name Labels ---")
    lines = [
        OCRLine(text="发票代码:1100192321", left=50, top=10, right=250, bottom=30, score=0.99),
        OCRLine(text="发票号码:01234567", left=300, top=10, right=500, bottom=30, score=0.99),
        OCRLine(text="开票日期", left=50, top=50, right=130, bottom=70, score=0.99),
        OCRLine(text="2026-7-8", left=140, top=50, right=230, bottom=70, score=0.99),
        OCRLine(text="购买方", left=50, top=100, right=100, bottom=120, score=0.99),
        OCRLine(text="名", left=110, top=100, right=130, bottom=120, score=0.99),
        OCRLine(text="称", left=135, top=100, right=155, bottom=120, score=0.99),
        OCRLine(text="腾讯科技(深圳)有限公司", left=165, top=100, right=360, bottom=120, score=0.99),
        OCRLine(text="识别号", left=110, top=130, right=170, bottom=150, score=0.99),
        OCRLine(text="91330100717621111X", left=180, top=130, right=350, bottom=150, score=0.99),
        OCRLine(text="销售方", left=50, top=200, right=100, bottom=220, score=0.99),
        OCRLine(text="名", left=110, top=200, right=130, bottom=220, score=0.99),
        OCRLine(text="称", left=135, top=200, right=155, bottom=220, score=0.99),
        OCRLine(text="百度在线网络技术有限公司", left=165, top=200, right=360, bottom=220, score=0.99),
        OCRLine(text="识别号", left=110, top=230, right=170, bottom=250, score=0.99),
        OCRLine(text="91110115781312345Y", left=180, top=230, right=350, bottom=250, score=0.99),
        OCRLine(text="合计", left=50, top=300, right=100, bottom=320, score=0.99),
        OCRLine(text="1000.00", left=200, top=300, right=280, bottom=320, score=0.99),
        OCRLine(text="60.00", left=300, top=300, right=380, bottom=320, score=0.99),
        OCRLine(text="价税合计", left=50, top=350, right=120, bottom=370, score=0.99),
        OCRLine(text="小写1060.00", left=200, top=350, right=320, bottom=370, score=0.99),
    ]
    layout = Layout(lines)
    parser = OCRParser()
    result = parser.parse(layout)
    print("VAT Invoice Split Labels Parsed Result:")
    print(result)
    assert result["type"] == "invoice"
    assert result["issue_date"] == "2026年07月08日"
    assert result["buyer_name"] == "腾讯科技(深圳)有限公司"
    assert result["seller_name"] == "百度在线网络技术有限公司"
    assert result["buyer_tax_id"] == "91330100717621111X"
    assert result["seller_tax_id"] == "91110115781312345Y"
    print("VAT Invoice Split Labels Test Passed!")

def test_business_license_with_common_ocr_variants():
    print("\n--- Testing Business License with Common OCR Variants ---")
    lines = [
        OCRLine(text="营业执照", left=300, top=20, right=500, bottom=60, score=0.99),
        OCRLine(text="统一社会信用代码91410100macer7b67p", left=50, top=90, right=420, bottom=120, score=0.99),
        OCRLine(text="名称测试科技有限公司", left=50, top=150, right=360, bottom=180, score=0.99),
        OCRLine(text="类型有限责任公司", left=50, top=190, right=330, bottom=220, score=0.99),
        OCRLine(text="法定代表人测试人", left=50, top=230, right=300, bottom=260, score=0.99),
        OCRLine(text="注册资本壹佰万元整", left=400, top=230, right=620, bottom=260, score=0.99),
        OCRLine(text="成立日期2023年4月1日", left=400, top=270, right=650, bottom=300, score=0.99),
        OCRLine(text="住所河南省关池县测试镇1号", left=50, top=310, right=420, bottom=340, score=0.99),
        OCRLine(text="经营范围软件开发", left=50, top=360, right=280, bottom=390, score=0.99),
    ]
    layout = Layout(lines)
    parser = OCRParser()
    result = parser.parse(layout)
    print("Business License Variants Parsed Result:")
    print(result)
    assert result["type"] == "business_license"
    assert result["credit_code"] == "91410100MACER7B67P"
    assert result["establish_date"] == "2023年04月01日"
    assert result["address"] == "河南省渑池县测试镇1号"
    print("Business License Variants Test Passed!")

def test_business_license_with_missing_name_prefix():
    print("\n--- Testing Business License with Missing Name Prefix ---")
    lines = [
        OCRLine(text="营业执照", left=436, top=149, right=817, bottom=236, score=0.9978643655776978),
        OCRLine(text="统一社会信用代码", left=55, top=177, right=276, bottom=205, score=0.999366283416748),
        OCRLine(text="91410100MACER7B67P", left=64, top=203, right=258, bottom=224, score=0.9971888661384583),
        OCRLine(text="称河南省吉米特信息技术有限公司", left=138, top=341, right=481, bottom=367, score=0.9995037913322449),
        OCRLine(text="注册资本", left=697, top=336, right=824, bottom=367, score=0.9998816847801208),
        OCRLine(text="伍佰万圆整", left=828, top=341, right=941, bottom=365, score=0.9995759129524231),
        OCRLine(text="类", left=41, top=391, right=72, bottom=419, score=0.9999831914901733),
        OCRLine(text="有限责任公司（自然人独资）", left=187, top=396, right=444, bottom=414, score=0.9959561228752136),
        OCRLine(text="成立日期2023年04月21日", left=698, top=385, right=983, bottom=418, score=0.9998270869255066),
        OCRLine(text="法定代表人", left=41, top=441, right=172, bottom=469, score=0.9997035264968872),
        OCRLine(text="王志勇", left=177, top=441, right=254, bottom=469, score=0.9997938275337219),
        OCRLine(text="住", left=698, top=436, right=732, bottom=465, score=0.9995580315589905),
        OCRLine(text="所", left=794, top=438, right=828, bottom=464, score=0.9999828338623047),
        OCRLine(text="河南省郑州市郑东新区平安大道与", left=840, top=441, right=1144, bottom=464, score=0.9991366267204285),
        OCRLine(text="明理路交叉口西南角博雅广场4号", left=843, top=474, right=1134, bottom=492, score=0.9988353252410889),
        OCRLine(text="楼2楼201", left=840, top=499, right=923, bottom=526, score=0.9997758269309998),
        OCRLine(text="经营范围", left=41, top=493, right=169, bottom=518, score=0.99979567527771),
        OCRLine(text="一般项目：信息系统集成服务", left=186, top=486, right=650, bottom=504, score=0.9702147245407104),
    ]
    layout = Layout(lines)
    parser = OCRParser()
    result = parser.parse(layout)
    print("Business License Missing Name Prefix Parsed Result:")
    print(result)
    assert result["type"] == "business_license"
    assert result["name"] == "河南省吉米特信息技术有限公司"
    assert result["credit_code"] == "91410100MACER7B67P"
    print("Business License Missing Name Prefix Test Passed!")

def test_business_license_with_missing_type_label_character():
    print("\n--- Testing Business License with Missing Type Label Character ---")
    lines = [
        OCRLine(text="营业执照", left=463, top=199, right=802, bottom=272, score=0.99),
        OCRLine(text="统一社会信用代码", left=132, top=227, right=322, bottom=245, score=0.99),
        OCRLine(text="91410100MACER7B67P", left=141, top=249, right=308, bottom=266, score=0.99),
        OCRLine(text="名", left=133, top=371, right=156, bottom=396, score=0.99),
        OCRLine(text="称河南省吉米特信息技术有限公司", left=211, top=371, right=506, bottom=393, score=0.99),
        OCRLine(text="注册资本伍佰万圆整", left=696, top=366, right=916, bottom=392, score=0.99),
        OCRLine(text="型有限责任公司（自然人独资）", left=200, top=415, right=477, bottom=438, score=0.99),
        OCRLine(text="成立日期", left=699, top=411, right=807, bottom=435, score=0.99),
        OCRLine(text="2023年04月21日", left=821, top=415, right=948, bottom=434, score=0.99),
        OCRLine(text="法定代表人王志勇", left=132, top=460, right=310, bottom=482, score=0.99),
        OCRLine(text="住", left=696, top=454, right=729, bottom=482, score=0.99),
        OCRLine(text="所", left=784, top=457, right=810, bottom=479, score=0.99),
        OCRLine(text="河南省郑州市郑东新区平安大道与", left=823, top=460, right=1090, bottom=478, score=0.99),
        OCRLine(text="明理路交叉口西南角博雅广场4号", left=825, top=487, right=1082, bottom=505, score=0.99),
        OCRLine(text="楼2楼201", left=823, top=512, right=898, bottom=534, score=0.99),
        OCRLine(text="经营范围", left=132, top=504, right=240, bottom=527, score=0.99),
        OCRLine(text="一般项目：信息系统集成服务", left=253, top=499, right=655, bottom=514, score=0.99),
    ]
    result = OCRParser().parse(Layout(lines), document_type="business_license")
    assert result["type_name"] == "有限责任公司（自然人独资）"
    print("Business License Missing Type Label Character Test Passed!")

def test_business_license_with_split_missing_type_label_character():
    print("\n--- Testing Business License with Split Missing Type Label Character ---")
    lines = [
        OCRLine(text="营业执照", left=1645, top=926, right=2771, bottom=1182, score=0.99),
        OCRLine(text="名", left=540, top=1452, right=935, bottom=1556, score=0.99),
        OCRLine(text="称河南省信息化集团有限公司", left=965, top=1465, right=1692, bottom=1543, score=0.99),
        OCRLine(text="型", left=540, top=1587, right=918, bottom=1695, score=0.99),
        OCRLine(text="其他有限责任公司", left=969, top=1613, right=1458, bottom=1686, score=0.99),
        OCRLine(text="法定代表人", left=543, top=1734, right=915, bottom=1835, score=0.99),
        OCRLine(text="王秀清", left=965, top=1752, right=1164, bottom=1830, score=0.99),
    ]
    result = OCRParser().parse(Layout(lines), document_type="business_license")
    assert result["type_name"] == "其他有限责任公司"
    print("Business License Split Missing Type Label Character Test Passed!")

def test_business_license_scope_order_with_tall_label():
    print("\n--- Testing Business License Scope Order with Tall Label ---")
    lines = [
        OCRLine(text="营业执照", left=1645, top=926, right=2771, bottom=1182, score=0.9983658194541931),
        OCRLine(text="统一社会信用代码", left=552, top=991, right=1207, bottom=1065, score=0.9987980127334595),
        OCRLine(text="91410000692152338A", left=582, top=1074, right=1084, bottom=1130, score=0.9953087568283081),
        OCRLine(text="名称", left=540, top=1452, right=935, bottom=1556, score=0.9996819496154785),
        OCRLine(text="河南省信息化集团有限公司", left=965, top=1465, right=1692, bottom=1543, score=0.9979178309440613),
        OCRLine(text="注册资本", left=2440, top=1465, right=2801, bottom=1543, score=0.9996041059494019),
        OCRLine(text="叁仟零柒拾柒万圆整", left=2843, top=1473, right=3396, bottom=1547, score=0.9940713047981262),
        OCRLine(text="类型", left=540, top=1587, right=918, bottom=1695, score=0.999326229095459),
        OCRLine(text="其他有限责任公司", left=969, top=1613, right=1458, bottom=1686, score=0.9990847110748291),
        OCRLine(text="成立日期", left=2426, top=1594, right=2802, bottom=1696, score=0.9999387264251709),
        OCRLine(text="2009年07月06日", left=2843, top=1617, right=3268, bottom=1691, score=0.9988440871238708),
        OCRLine(text="法定代表人", left=543, top=1734, right=915, bottom=1835, score=0.9994615316390991),
        OCRLine(text="王秀清", left=965, top=1752, right=1164, bottom=1830, score=0.9868562817573547),
        OCRLine(text="住", left=2435, top=1752, right=2524, bottom=1830, score=0.9998525381088257),
        OCRLine(text="所", left=2716, top=1756, right=2809, bottom=1826, score=0.9999452829360962),
        OCRLine(text="郑州市郑东新区明理路祭城南正商", left=2843, top=1760, right=3744, bottom=1834, score=0.9908179044723511),
        OCRLine(text="博雅广场4号楼15层", left=2843, top=1843, right=3362, bottom=1921, score=0.9959174394607544),
        OCRLine(text="经营范围", left=535, top=1877, right=915, bottom=1978, score=0.9995774626731873),
        OCRLine(text="许可项日，电子认证服务，电子政务电子认证服务，计机信息系统安全专用产品销件", left=965, top=1878, right=2274, bottom=1930, score=0.9589536786079407),
        OCRLine(text=";第一类增值电信业务：第二类增值电信业务（依法须经批准的项H，经相关部门批准后", left=965, top=1925, right=2308, bottom=1982, score=0.947127103805542),
        OCRLine(text="方可开展经营活动，具体经营项目以和关部门批准文件或许可证件为准）", left=960, top=1969, right=2049, bottom=2034, score=0.9544682502746582),
        OCRLine(text="一般项目：软件开发，网络与信总安全软件开发：计算机软硬件及辅助设备零售：网络设", left=965, top=2021, right=2308, bottom=2078, score=0.9256977438926697),
        OCRLine(text="备销售，仿息安全设备销售，技术服务、技术开发、技术资询、技术交流、技术转让、技", left=965, top=2073, right=2308, bottom=2126, score=0.8974995613098145),
        OCRLine(text="登记机关", left=3071, top=2654, right=3282, bottom=2731, score=0.9087705016136169),
    ]
    layout = Layout(lines)
    parser = OCRParser()
    result = parser.parse(layout)
    print("Business License Scope Order Parsed Result:")
    print(result)
    assert result["type"] == "business_license"
    assert result["business_scope"].startswith("许可项目")
    assert not result["business_scope"].startswith("博雅广场")
    assert "博雅广场4号楼15层" not in result["business_scope"]
    assert "第一类增值电信业务" in result["business_scope"]
    assert result["business_scope"].find("方可开展经营活动") > result["business_scope"].find("第一类增值电信业务")
    assert result["business_scope"].find("一般项目") > result["business_scope"].find("方可开展经营活动")
    assert "相关部门" in result["business_scope"]
    assert "网络设备销售" in result["business_scope"]
    assert "信息安全设备销售" in result["business_scope"]
    print("Business License Scope Order Test Passed!")

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

def test_id_front_with_merged_address_label_and_continuation():
    print("\n--- Testing ID Front With Merged Address Label ---")
    lines = [
        OCRLine(text="姓名吴烽", left=361, top=186, right=595, bottom=250, score=0.99),
        OCRLine(text="性别男", left=369, top=273, right=525, bottom=317, score=0.99),
        OCRLine(text="民族汉", left=514, top=273, right=703, bottom=311, score=0.99),
        OCRLine(text="出生1991年8月15日", left=373, top=334, right=782, bottom=385, score=0.99),
        OCRLine(text="住址河南省渑池县洪阳镇德厚", left=371, top=406, right=852, bottom=460, score=0.99),
        OCRLine(text="村七组1号", left=485, top=457, right=664, bottom=505, score=0.99),
        OCRLine(text="公民身份号码", left=380, top=589, right=602, bottom=641, score=0.99),
        OCRLine(text="411221199108152534", left=577, top=575, right=1114, bottom=633, score=0.99),
    ]
    result = OCRParser().parse(Layout(lines), document_type="id_front")
    assert result["address"] == "河南省渑池县洪阳镇德厚村七组1号", result
    print("ID Front Merged Address Label Test Passed!")


def test_id_front_with_admin_area_typo():
    print("\n--- Testing ID Front with Admin Area Typo ---")
    lines = [
        OCRLine(text="姓名测试用户", left=358, top=189, right=594, bottom=248, score=0.99),
        OCRLine(text="性别男民族汉", left=365, top=269, right=705, bottom=321, score=0.99),
        OCRLine(text="出生2000年01月01日", left=369, top=330, right=785, bottom=389, score=0.99),
        OCRLine(text="住址河南省关池县测试镇", left=372, top=415, right=851, bottom=461, score=0.99),
        OCRLine(text="公民身份号码00000020000101000X", left=380, top=571, right=1114, bottom=647, score=0.99),
    ]
    layout = Layout(lines)
    parser = OCRParser()
    result = parser.parse(layout)
    print("ID Front Admin Area Typo Parsed Result:")
    print(result)
    assert result["type"] == "id_front"
    assert result["address"] == "河南省渑池县测试镇"
    print("ID Front Admin Area Typo Test Passed!")

def test_id_front_with_split_birthday_and_admin_area_typo():
    print("\n--- Testing ID Front with Split Birthday and Admin Area Typo ---")
    lines = [
        OCRLine(text="姓名吴烽", left=358, top=189, right=594, bottom=248, score=0.99),
        OCRLine(text="性别男", left=365, top=269, right=526, bottom=321, score=0.99),
        OCRLine(text="民族汉", left=505, top=268, right=705, bottom=314, score=0.99),
        OCRLine(text="出生", left=369, top=330, right=489, bottom=389, score=0.99),
        OCRLine(text="1991年8月15日", left=482, top=330, right=785, bottom=389, score=0.99),
        OCRLine(text="住址", left=372, top=415, right=489, bottom=461, score=0.99),
        OCRLine(text="河南省绳池县洪阳镇德厚", left=466, top=405, right=851, bottom=460, score=0.99),
        OCRLine(text="村七组1号", left=482, top=454, right=665, bottom=508, score=0.99),
        OCRLine(text="公民身份号码", left=380, top=571, right=650, bottom=647, score=0.99),
        OCRLine(text="411221199108152534", left=630, top=571, right=1114, bottom=647, score=0.99),
    ]
    result = OCRParser().parse(Layout(lines))
    assert result["type"] == "id_front"
    assert result["birthday"] == "1991年8月15日"
    assert result["address"] == "河南省渑池县洪阳镇德厚村七组1号"
    assert result["id_number"] == "411221199108152534"
    print("ID Front Split Birthday and Admin Area Typo Test Passed!")

def test_id_front_birthday_fallback_from_id_number():
    print("\n--- Testing ID Front Birthday Fallback from ID Number ---")
    lines = [
        OCRLine(text="姓名吴烽", left=358, top=189, right=594, bottom=248, score=0.99),
        OCRLine(text="性别男民族汉", left=365, top=269, right=705, bottom=321, score=0.99),
        OCRLine(text="出生", left=369, top=330, right=489, bottom=389, score=0.99),
        OCRLine(text="住址河南省渑池县洪阳镇", left=372, top=415, right=851, bottom=461, score=0.99),
        OCRLine(text="公民身份号码411221199108152534", left=380, top=571, right=1114, bottom=647, score=0.99),
    ]
    result = OCRParser().parse(Layout(lines))
    assert result["birthday"] == "1991年8月15日"
    print("ID Front Birthday Fallback Test Passed!")


def test_id_front_with_noisy_birthday_month():
    print("\n--- Testing ID Front With Noisy Birthday Month ---")
    lines = [
        OCRLine(text="姓名苏龙格德·胡尔查巴特尔", left=41, top=59, right=577, bottom=111, score=0.99),
        OCRLine(text="性别男民族蒙古", left=34, top=118, right=428, bottom=169, score=0.91),
        OCRLine(text="出生1973年105月27日", left=32, top=172, right=524, bottom=227, score=0.92),
        OCRLine(text="住址", left=44, top=236, right=171, bottom=288, score=0.97),
        OCRLine(text="内蒙古赤峰市巴林右旗沙布", left=185, top=299, right=520, bottom=333, score=0.99),
        OCRLine(text="公民身份号码15222119731", left=161, top=393, right=616, bottom=435, score=0.99),
    ]
    result = OCRParser().parse(Layout(lines), document_type="id_front")
    assert result["birthday"] == "1973年10月27日"
    assert result["id_number"] == ""
    print("ID Front Noisy Birthday Month Test Passed!")


def test_id_front_with_misrecognized_name_label():
    print("\n--- Testing ID Front With Misrecognized Name Label ---")
    lines = [
        OCRLine(text="鲜名吴烽", left=458, top=633, right=689, bottom=695, score=0.961513340473175),
        OCRLine(text="性别男", left=448, top=703, right=610, bottom=741, score=0.9997360110282898),
        OCRLine(text="民族汉", left=654, top=698, right=794, bottom=736, score=0.9980664253234863),
        OCRLine(text="出生", left=441, top=765, right=526, bottom=792, score=0.9727777242660522),
        OCRLine(text="1991年8月15日", left=547, top=750, right=880, bottom=798, score=0.9987314939498901),
        OCRLine(text="住址", left=419, top=828, right=530, bottom=863, score=0.9332908391952515),
        OCRLine(text="河南省渑池县洪阳镇德厚", left=512, top=819, right=969, bottom=865, score=0.9498217105865479),
        OCRLine(text="村七组1号", left=526, top=863, right=736, bottom=920, score=0.98615962266922),
        OCRLine(text="公民身份号码", left=366, top=1014, right=631, bottom=1063, score=0.9993293285369873),
        OCRLine(text="411221199108152534", left=682, top=997, right=1317, bottom=1061, score=0.9977953433990479),
    ]
    result = OCRParser().parse(Layout(lines))
    assert result["type"] == "id_front"
    assert result["name"] == "吴烽"
    assert result["gender"] == "男"
    assert result["nation"] == "汉"
    assert result["birthday"] == "1991年8月15日"
    assert result["address"] == "河南省渑池县洪阳镇德厚村七组1号"
    assert result["id_number"] == "411221199108152534"
    print("ID Front Misrecognized Name Label Test Passed!")


def test_id_front_with_missing_gender_and_nation_text():
    print("\n--- Testing ID Front With Missing Gender And Nation Text ---")
    lines = [
        OCRLine(text="吴烽", left=147, top=64, right=255, bottom=115, score=0.7478779554367065),
        OCRLine(text="性别", left=48, top=140, right=145, bottom=180, score=0.7965892553329468),
        OCRLine(text="出生", left=49, top=208, right=132, bottom=247, score=0.9737291332244873),
        OCRLine(text="1991年8月15日", left=152, top=202, right=438, bottom=251, score=0.9763708114624023),
        OCRLine(text="住址", left=49, top=282, right=130, bottom=317, score=0.9439676403999329),
        OCRLine(text="河南省混池县洪阳镇德厚", left=150, top=280, right=510, bottom=321, score=0.9285207986831665),
        OCRLine(text="村七组1号", left=151, top=324, right=321, bottom=369, score=0.9516127705574036),
        OCRLine(text="公民身份号码", left=50, top=453, right=252, bottom=497, score=0.9825084209442139),
        OCRLine(text="411221199108152534", left=289, top=450, right=761, bottom=496, score=0.9956158399581909),
    ]
    result = OCRParser().parse(Layout(lines))
    assert result["type"] == "id_front"
    assert result["name"] == "吴烽"
    assert result["gender"] == "男"
    assert result["nation"] == ""
    assert result["address"] == "河南省渑池县洪阳镇德厚村七组1号"
    assert result["id_number"] == "411221199108152534"
    print("ID Front Missing Gender And Nation Text Test Passed!")


def test_id_front_with_supplemented_nation_crop():
    print("\n--- Testing ID Front With Supplemented Nation Crop ---")
    lines = [
        OCRLine(text="性别", left=48, top=140, right=145, bottom=180, score=0.80),
        OCRLine(text="族汉", left=225, top=110, right=425, bottom=210, score=0.84),
        OCRLine(
            text="411221199108152534",
            left=289,
            top=450,
            right=761,
            bottom=496,
            score=0.99,
        ),
    ]
    result = OCRParser().parse(Layout(lines), document_type="id_front")
    assert result["nation"] == "汉"
    print("ID Front Supplemented Nation Crop Test Passed!")


def test_id_front_with_mobile_label_typos():
    print("\n--- Testing ID Front With Mobile Label Typos ---")
    lines = [
        OCRLine(text="财省吴烽", left=147, top=64, right=255, bottom=115, score=0.75),
        OCRLine(text="性州男", left=48, top=140, right=190, bottom=180, score=0.80),
        OCRLine(text="闲族汉", left=225, top=140, right=380, bottom=180, score=0.84),
        OCRLine(
            text="411221199108152534",
            left=289,
            top=450,
            right=761,
            bottom=496,
            score=0.99,
        ),
    ]
    result = OCRParser().parse(Layout(lines), document_type="id_front")
    assert result["name"] == "吴烽"
    assert result["gender"] == "男"
    assert result["nation"] == "汉"
    print("ID Front Mobile Label Typos Test Passed!")


def test_id_front_with_sample_watermark_and_overlapping_id_number():
    print("\n--- Testing ID Front With Sample Watermark ---")
    lines = [
        OCRLine(text="姓名", left=49, top=61, right=106, bottom=86, score=0.99),
        OCRLine(text="李久熙", left=116, top=54, right=197, bottom=86, score=0.99),
        OCRLine(text="性期", left=49, top=105, right=105, bottom=130, score=0.87),
        OCRLine(text="女", left=118, top=106, right=141, bottom=127, score=0.99),
        OCRLine(text="民族汉", left=175, top=105, right=251, bottom=129, score=0.99),
        OCRLine(text="出生", left=50, top=148, right=104, bottom=173, score=0.99),
        OCRLine(text="1996年11月24日", left=116, top=151, right=306, bottom=174, score=0.99),
        OCRLine(text="住址", left=51, top=196, right=102, bottom=218, score=0.96),
        OCRLine(text="北京市海淀区双榆树东里", left=119, top=193, right=349, bottom=216, score=0.99),
        OCRLine(text="99区2号楼302室", left=115, top=214, right=273, bottom=242, score=0.99),
        OCRLine(text="样证", left=38, top=235, right=127, bottom=278, score=0.77),
        OCRLine(text="公民身份号码", left=51, top=304, right=182, bottom=330, score=0.99),
        OCRLine(text="110108199611240188", left=204, top=302, right=506, bottom=331, score=0.99),
    ]
    result = OCRParser().parse(Layout(lines), document_type="id_front")
    assert result["name"] == "李久熙"
    assert result["gender"] == "女"
    assert result["nation"] == "汉"
    assert result["address"] == "北京市海淀区双榆树东里99区2号楼302室"
    assert result["id_number"] == "110108199611240188"
    print("ID Front Sample Watermark Test Passed!")


def test_id_front_with_name_label_and_nearby_noise():
    print("\n--- Testing ID Front With Name Label And Nearby Noise ---")
    lines = [
        OCRLine(text="g", left=120, top=34, right=324, bottom=56, score=0.77),
        OCRLine(text="姓名", left=55, top=56, right=105, bottom=79, score=0.99),
        OCRLine(text="夏格仓·晋美平措朗杰", left=121, top=56, right=310, bottom=78, score=0.99),
        OCRLine(text="61", left=120, top=78, right=139, bottom=97, score=0.78),
        OCRLine(text="性别", left=55, top=99, right=105, bottom=123, score=0.99),
        OCRLine(text="男", left=121, top=99, right=144, bottom=122, score=0.99),
    ]
    result = OCRParser().parse(Layout(lines), document_type="id_front")
    assert result["name"] == "夏格仓·晋美平措朗杰"
    assert result["gender"] == "男"
    print("ID Front Name Label And Nearby Noise Test Passed!")


def test_business_license_with_supplemented_address_crop():
    print("\n--- Testing Business License With Supplemented Address Crop ---")
    lines = [
        OCRLine(text="称河南省信息化集团有限公司", left=207, top=356, right=486, bottom=373, score=0.99),
        OCRLine(text="所", left=790, top=434, right=810, bottom=455, score=0.99),
        OCRLine(text="郑州市郑东新区明理路祭城南正商", left=826, top=434, right=1060, bottom=455, score=0.99),
        OCRLine(text="博雅广场4号楼15层", left=826, top=466, right=970, bottom=484, score=0.99),
        OCRLine(text="博雅广场4号楼15层", left=826, top=466, right=970, bottom=484, score=0.99),
        OCRLine(text="经营范围", left=163, top=480, right=268, bottom=506, score=0.99),
    ]
    result = OCRParser().parse(Layout(lines), document_type="business_license")
    assert result["address"] == "河南省郑州市郑东新区明理路祭城南正商博雅广场4号楼15层"
    print("Business License Supplemented Address Crop Test Passed!")

def test_id_back_with_missing_authority_prefix():
    print("\n--- Testing ID Back with Missing Authority Prefix ---")
    lines = [
        OCRLine(text="中华人民共和国", left=886, top=231, right=1556, bottom=365, score=0.9979723691940308),
        OCRLine(text="居民身份证", left=832, top=353, right=1598, bottom=531, score=0.9991973638534546),
        OCRLine(text="签发机关池县公安局", left=738, top=693, right=1240, bottom=798, score=0.9944436550140381),
        OCRLine(text="有效期限20190624-20390624", left=729, top=799, right=1461, bottom=911, score=0.9621346592903137),
    ]
    layout = Layout(lines)
    parser = OCRParser()
    result = parser.parse(layout)
    print("ID Back Parsed Result:")
    print(result)
    assert result["type"] == "id_back"
    assert result["authority"] == "渑池县公安局"
    assert result["issue_date"] == "2019.06.24"
    assert result["expiry_date"] == "2039.06.24"
    print("ID Back Authority Prefix Test Passed!")

def test_id_back_with_wrong_authority_prefix():
    print("\n--- Testing ID Back with Wrong Authority Prefix ---")
    lines = [
        OCRLine(text="中华人民共和国", left=886, top=231, right=1556, bottom=365, score=0.99),
        OCRLine(text="居民身份证", left=832, top=353, right=1598, bottom=531, score=0.99),
        OCRLine(text="签发机关关池县公安局", left=738, top=693, right=1240, bottom=798, score=0.99),
        OCRLine(text="有效期限20190624-20390624", left=729, top=799, right=1461, bottom=911, score=0.99),
    ]
    layout = Layout(lines)
    parser = OCRParser()
    result = parser.parse(layout)
    print("ID Back Wrong Prefix Parsed Result:")
    print(result)
    assert result["type"] == "id_back"
    assert result["authority"] == "渑池县公安局"
    print("ID Back Wrong Authority Prefix Test Passed!")


def test_id_back_with_mixed_date_separators():
    print("\n--- Testing ID Back With Mixed Date Separators ---")
    lines = [
        OCRLine(text="签发机关", left=137, top=254, right=220, bottom=278, score=0.99),
        OCRLine(text="拉萨市公安局城关分局", left=235, top=255, right=434, bottom=276, score=0.95),
        OCRLine(text="有效期限", left=138, top=303, right=222, bottom=325, score=0.99),
        OCRLine(text="200410.27-2024.10.26", left=213, top=304, right=446, bottom=325, score=0.98),
    ]
    result = OCRParser().parse(Layout(lines), document_type="id_back")
    assert result["authority"] == "拉萨市公安局城关分局"
    assert result["issue_date"] == "2004.10.27"
    assert result["expiry_date"] == "2024.10.26"
    print("ID Back Mixed Date Separators Test Passed!")


def test_id_back_with_comma_date_separator():
    print("\n--- Testing ID Back With Comma Date Separator ---")
    lines = [
        OCRLine(text="签发机关北京市公安局海淀分局", left=143, top=258, right=441, bottom=283, score=0.99),
        OCRLine(text="有效期限2004.11,24-2009.11.23", left=141, top=304, right=453, bottom=331, score=0.95),
    ]
    result = OCRParser().parse(Layout(lines), document_type="id_back")
    assert result["authority"] == "北京市公安局海淀分局"
    assert result["issue_date"] == "2004.11.24"
    assert result["expiry_date"] == "2009.11.23"
    print("ID Back Comma Date Separator Test Passed!")


def test_id_back_with_overlapping_authority_box():
    print("\n--- Testing ID Back With Overlapping Authority Box ---")
    lines = [
        OCRLine(text="巴林右旗公安局", left=340, top=331, right=718, bottom=402, score=0.92),
        OCRLine(text="签发机关", left=197, top=341, right=365, bottom=388, score=0.99),
        OCRLine(text="有效期限2004.10.27-2024.10.26", left=133, top=392, right=673, bottom=467, score=0.92),
    ]
    result = OCRParser().parse(Layout(lines), document_type="id_back")
    assert result["authority"] == "巴林右旗公安局"
    assert result["issue_date"] == "2004.10.27"
    assert result["expiry_date"] == "2024.10.26"
    print("ID Back Overlapping Authority Box Test Passed!")


def test_id_back_with_truncated_balinyouqi_authority():
    print("\n--- Testing ID Back With Truncated Balinyouqi Authority ---")
    lines = [
        OCRLine(text="中华人民共和国", left=307, top=51, right=710, bottom=107, score=0.99),
        OCRLine(text="居民身份证", left=252, top=137, right=760, bottom=211, score=0.99),
        OCRLine(text="签发机关林旗安局", left=72, top=323, right=721, bottom=402, score=0.79),
        OCRLine(text="有效期限 2004.10.27-2024.10.26", left=138, top=396, right=671, bottom=462, score=0.98),
    ]
    result = OCRParser().parse(Layout(lines), document_type="id_back")
    assert result["authority"] == "巴林右旗公安局"
    assert result["issue_date"] == "2004.10.27"
    assert result["expiry_date"] == "2024.10.26"
    print("ID Back Truncated Balinyouqi Authority Test Passed!")

if __name__ == "__main__":
    test_document_type_hint()
    test_document_type_detects_bank_card_from_luhn_number()
    test_ocr_cache_round_trip()
    test_business_license_with_missing_address_prefix()
    test_id_front_with_split_id_label()
    test_id_front_with_split_address_and_nation()
    test_id_front_with_merged_address_label_and_continuation()
    test_id_front_with_admin_area_typo()
    test_id_front_with_split_birthday_and_admin_area_typo()
    test_id_front_birthday_fallback_from_id_number()
    test_id_front_with_noisy_birthday_month()
    test_id_front_with_misrecognized_name_label()
    test_id_front_with_missing_gender_and_nation_text()
    test_id_front_with_supplemented_nation_crop()
    test_id_front_with_mobile_label_typos()
    test_id_front_with_sample_watermark_and_overlapping_id_number()
    test_id_front_with_name_label_and_nearby_noise()
    test_business_license_with_supplemented_address_crop()
    test_id_back_with_missing_authority_prefix()
    test_id_back_with_wrong_authority_prefix()
    test_id_back_with_mixed_date_separators()
    test_id_back_with_comma_date_separator()
    test_id_back_with_overlapping_authority_box()
    test_id_back_with_truncated_balinyouqi_authority()
    test_bank_card_with_typos()
    test_bank_card_with_split_bank_name()
    test_bank_card_prefers_luhn_valid_candidate()
    test_bank_card_uses_bin_when_bank_text_is_missing()
    test_bank_card_unknown_type_is_not_guessed_by_length()
    test_invoice_with_typos()
    test_invoice_with_split_name_labels()
    test_business_license_with_common_ocr_variants()
    test_business_license_with_missing_name_prefix()
    test_business_license_with_missing_type_label_character()
    test_business_license_with_split_missing_type_label_character()
    test_business_license_scope_order_with_tall_label()
