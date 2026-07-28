# -*- coding: utf-8 -*-
#Author: WuFeng <763467339@qq.com>
#Date: 2026-07-28
#Description: 银行卡解析器
#FilePath: /ocr-server/app/parsers/bank_card.py
#

import re
from app.utils.layout import Layout


class IDCardParser:
    pass


class BankCardParser:
    """银行卡解析器"""

    def parse(self, layout: Layout):
        data = {
            "type": "bank_card",
            "bank_name": "",
            "card_number": "",
            "card_type": "",
            "valid_date": ""
        }

        all_lines = layout.all() or []
        all_text_joined = "".join(layout.texts() or []).replace(" ", "")

        # 1. 提取银行卡号 (15-19位纯数字，或者被空格分隔的数字组合)
        card_number_found = ""
        # 优先在单行里找
        for line in all_lines:
            text = line.text.strip().replace(" ", "").replace("-", "")
            # 常见银行卡号为 15 到 19 位纯数字
            match = re.search(r"\b\d{15,19}\b", text)
            if match:
                card_number_found = match.group()
                break

        # 如果单行没找到完整的，尝试在整行文本拼合后过滤出所有数字，再寻找匹配长度
        if not card_number_found:
            # 去除所有非数字字符
            clean_digits = re.sub(r"\D", "", all_text_joined)
            match = re.search(r"\d{15,19}", clean_digits)
            if match:
                card_number_found = match.group()

        data["card_number"] = card_number_found

        # 2. 提取银行名称
        # 寻找包含 "银行" 且不含其他干扰词的行
        bank_name_found = ""
        for line in all_lines:
            text = line.text.strip()
            if "银行" in text and not any(kw in text for kw in ["卡号", "账号", "电话", "热线", "客服", "号码"]):
                # 寻找以 "银行" 结尾的前缀
                match = re.search(r"([A-Za-z\u4e00-\u9fff]*?银行)", text)
                if match:
                    bank_name_found = match.group(1).strip()
                    break

        if not bank_name_found:
            for line in all_lines:
                if "银行" in line.text:
                    bank_name_found = line.text.strip()
                    break

        # 清理常见的 OCR 冗余
        if bank_name_found:
            # 提取中文字符序列，如 "招商银行" 
            cn_match = re.search(r"[\u4e00-\u9fff]+银行", bank_name_found)
            if cn_match:
                bank_name_found = cn_match.group()

        data["bank_name"] = bank_name_found

        # 3. 提取卡片类型 (借记卡 / 储蓄卡 / 信用卡 / 贷记卡)
        card_type_found = ""
        debit_kws = ["借记卡", "储蓄卡", "一卡通", "DEBIT", "Debit", "SAVINGS", "Savings"]
        credit_kws = ["信用卡", "贷记卡", "CREDIT", "Credit"]

        for kw in debit_kws:
            if kw.lower() in all_text_joined.lower():
                card_type_found = "借记卡"
                break
        if not card_type_found:
            for kw in credit_kws:
                if kw.lower() in all_text_joined.lower():
                    card_type_found = "信用卡"
                    break

        # 无法判断时的智能推导
        if not card_type_found:
            if len(card_number_found) == 19:
                card_type_found = "借记卡"
            elif len(card_number_found) == 16:
                card_type_found = "信用卡"
            else:
                card_type_found = "借记卡" # 默认储蓄卡居多

        data["card_type"] = card_type_found

        # 4. 提取有效期 (通常是 MM/YY 格式，如 12/28)
        valid_date_found = ""
        for line in all_lines:
            text = line.text.strip()
            # 匹配 12/28 格式，或者 VALID THRU 12/28
            match = re.search(r"\b(0[1-9]|1[0-2])\s*/\s*([0-9]{2})\b", text)
            if match:
                valid_date_found = f"{match.group(1)}/{match.group(2)}"
                break

        if not valid_date_found:
            # 宽松匹配 MM/YY
            match = re.search(r"(0[1-9]|1[0-2])\s*/\s*([0-9]{2})", all_text_joined)
            if match:
                valid_date_found = f"{match.group(1)}/{match.group(2)}"

        data["valid_date"] = valid_date_found

        return data
