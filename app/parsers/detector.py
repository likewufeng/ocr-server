# -*- coding: utf-8 -*-
#Author: WuFeng <763467339@qq.com>
#Date: 2026-07-09 10:20:58
#LastEditTime: 2026-07-28 15:51:20
#LastEditors: WuFeng <763467339@qq.com>
#Description: 证件类型器
#FilePath: /ocr-server/app/parsers/detector.py
#Copyright 版权声明
#
# Description: 证件类型器 这个文件负责根据图片文字特征，自动告诉程序这是身份证还是营业执照。
import re
from app.utils.layout import Layout

class DocumentDetector:
    @staticmethod
    def _luhn_valid(number: str) -> bool:
        if not 15 <= len(number) <= 19 or not number.isdigit():
            return False
        checksum = 0
        for index, char in enumerate(reversed(number)):
            digit = int(char)
            if index % 2 == 1:
                digit *= 2
                if digit > 9:
                    digit -= 9
            checksum += digit
        return checksum % 10 == 0

    @staticmethod
    def _has_id_number_label(text: str) -> bool:
        if any(label in text for label in ("公民身份号码", "公民身份证号码", "身份号码", "身份证号码")):
            return True

        return "公民" in text and "身份" in text and "号码" in text

    def detect(self, layout: Layout) -> str:
        """
        返回证件类型: id_front, id_back, business_license, bank_card, invoice, unknown
        """
        all_text = "".join(layout.texts())
        all_text_no_space = all_text.replace(" ", "").replace("\n", "")
        
        # 1. 身份证判定
        has_id_number = bool(re.search(r"\d{17}[0-9Xx]", all_text_no_space))
        id_front_keywords = ("姓名", "性别", "民族", "出生", "住址")
        matching_id_front_kws = sum(1 for kw in id_front_keywords if kw in all_text_no_space)

        if "姓名" in all_text_no_space and self._has_id_number_label(all_text_no_space):
            return "id_front"

        if has_id_number and matching_id_front_kws >= 3:
            return "id_front"
        
        if "签发机关" in all_text and "有效期限" in all_text:
            return "id_back"
        
        # 2. 营业执照判定
        if "营业执照" in all_text or "统一社会信用代码" in all_text:
            return "business_license"
            
        # 3. 补充判定：如果只有信用代码但没印“营业执照”四个字
        if "注册资本" in all_text and "法定代表人" in all_text:
            return "business_license"

        # 4. 增值税发票判定
        invoice_keywords = ["发票代码", "发票号码", "纳税人识别号", "价税合计", "开票日期"]
        matching_invoice_kws = sum(1 for kw in invoice_keywords if kw in all_text_no_space)
        if "发票" in all_text_no_space or matching_invoice_kws >= 2:
            return "invoice"

        # 5. 银行卡判定
        bank_card_keywords = ["银行", "银联", "UnionPay", "借记卡", "储蓄卡", "信用卡", "贷记卡", "DEBIT", "CREDIT"]
        has_bank_kw = any(kw in all_text or kw.lower() in all_text.lower() for kw in bank_card_keywords)
        
        # 寻找卡号特征：清洗掉横线、空格、并替换形似英文字母，检测是否有 15-19位 连续数字组合
        clean_text_for_card = all_text_no_space.upper().replace("-", "").replace(".", "").replace("/", "")
        replacements = {
            "O": "0", "I": "1", "L": "1", "S": "5", "Z": "2", "B": "8", "G": "6"
        }
        for wrong, right in replacements.items():
            clean_text_for_card = clean_text_for_card.replace(wrong, right)
            
        has_card_num = bool(re.search(r"\d{15,19}", clean_text_for_card))
        has_luhn_card_num = any(
            self._luhn_valid(match.group())
            for match in re.finditer(r"\d{15,19}", clean_text_for_card)
        )
        
        if has_bank_kw and has_card_num:
            return "bank_card"
        if has_bank_kw and any(kw in all_text_no_space for kw in ["借记卡", "储蓄卡", "信用卡", "贷记卡"]):
            return "bank_card"

        # 银行名称、卡种文案都可能因 logo、反光或版面原因漏检；
        # 排除其它证件特征后，Luhn 合法卡号足以支持银行卡自动分流。
        if has_luhn_card_num and not any(
            keyword in all_text_no_space
            for keyword in ("营业执照", "统一社会信用代码", "发票", "公民身份", "身份证")
        ):
            return "bank_card"
            
        return "unknown"
