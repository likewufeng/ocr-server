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
    assert result["valid_date"] == "2019.06.24-2039.06.24"
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

if __name__ == "__main__":
    test_id_front_with_split_id_label()
    test_id_front_with_split_address_and_nation()
    test_id_front_with_admin_area_typo()
    test_id_back_with_missing_authority_prefix()
    test_id_back_with_wrong_authority_prefix()
    test_bank_card_with_typos()
    test_bank_card_with_split_bank_name()
    test_invoice_with_typos()
    test_invoice_with_split_name_labels()
    test_business_license_with_common_ocr_variants()
    test_business_license_with_missing_name_prefix()
    test_business_license_scope_order_with_tall_label()
