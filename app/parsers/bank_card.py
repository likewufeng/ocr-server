# -*- coding: utf-8 -*-
#Author: WuFeng <763467339@qq.com>
#Date: 2026-07-28
#Description: 银行卡解析器 (含智能纠错与防错防混版)
#FilePath: /ocr-server/app/parsers/bank_card.py
#

import re
from app.utils.layout import Layout


class BankCardParser:
    """银行卡解析器"""

    def _clean_to_digits_with_lookalikes(self, text: str) -> str:
        """将文字转换为纯数字，同时矫正形似的英文字母"""
        if not text:
            return ""
        t = text.strip().upper()
        # 常见数字形似字母映射表
        replacements = {
            "O": "0", "I": "1", "L": "1", 
            "S": "5", "Z": "2", "B": "8", "G": "6",
            "T": "7", "Q": "9"
        }
        for wrong, right in replacements.items():
            t = t.replace(wrong, right)
        # 过滤掉非数字字符
        return re.sub(r"\D", "", t)

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

        # ---------------- 1. 提取银行卡号 (15-19位数字) ----------------
        card_number_found = ""
        card_number_line = None # 记录卡号所在的行，后续提取日期时排除该行，防止卡号混淆
        
        # 策略A：单行正则匹配（支持字母纠偏，因此匹配 [0-9A-Z] 组合）
        for line in all_lines:
            text = line.text.strip().replace(" ", "").replace("-", "")
            match = re.search(r"\b[0-9A-Za-z]{15,19}\b", text)
            if match:
                candidate = self._clean_to_digits_with_lookalikes(match.group())
                if 15 <= len(candidate) <= 19:
                    card_number_found = candidate
                    card_number_line = line
                    break

        # 策略B：全文拼接检索
        if not card_number_found:
            clean_digits = self._clean_to_digits_with_lookalikes(all_text_joined)
            match = re.search(r"\d{15,19}", clean_digits)
            if match:
                card_number_found = match.group()

        data["card_number"] = card_number_found

        # ---------------- 2. 提取银行名称 ----------------
        bank_name_found = ""
        for line in all_lines:
            text = line.text.strip()
            if "银行" in text and not any(kw in text for kw in ["卡号", "账号", "电话", "热线", "客服", "号码"]):
                match = re.search(r"([A-Za-z\u4e00-\u9fff]*?银行)", text)
                if match:
                    bank_name_found = match.group(1).strip()
                    break

        if not bank_name_found:
            for line in all_lines:
                if "银行" in line.text:
                    bank_name_found = line.text.strip()
                    break

        if bank_name_found:
            # 提取第一个汉字序列
            cn_match = re.search(r"[\u4e00-\u9fff]+银行", bank_name_found)
            if cn_match:
                bank_name_found = cn_match.group()

        data["bank_name"] = bank_name_found

        # ---------------- 3. 提取卡片类型 (借记卡 / 储蓄卡 / 信用卡) ----------------
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

        # 智能推导
        if not card_type_found:
            if len(card_number_found) == 19:
                card_type_found = "借记卡"
            elif len(card_number_found) == 16:
                card_type_found = "信用卡"
            else:
                card_type_found = "借记卡"

        data["card_type"] = card_type_found

        # ---------------- 4. 提取有效期 (通常是 MM/YY 格式，如 12/28) ----------------
        valid_date_found = ""
        
        # 定义有效期形似字纠错逻辑
        def clean_valid_text(t: str) -> str:
            t = t.upper().replace(" ", "")
            # 常见误识别：O->0, I->1, L->1, B->8, Z->2, Q->9, G->6, S->5
            repls = {"O": "0", "I": "1", "L": "1", "B": "8", "Z": "2", "Q": "9", "G": "6", "S": "5"}
            for w, r in repls.items():
                t = t.replace(w, r)
            # 将常见日期分隔符统一为斜杠 '/'
            t = t.replace(".", "/").replace("-", "/").replace("\\", "/")
            return t

        for line in all_lines:
            # 排除已被认定为卡号所在的行，且排除数字或符号过多（长度大于12）的卡号形态行
            if card_number_line and line is card_number_line:
                continue
            cleaned_line_digits = self._clean_to_digits_with_lookalikes(line.text)
            if len(cleaned_line_digits) >= 12:
                continue
                
            text = clean_valid_text(line.text)
            # 匹配 01-12 月份，以及 20-39 年份
            match = re.search(r"\b(0[1-9]|1[0-2])\s*/\s*([2-3][0-9])\b", text)
            if match:
                valid_date_found = f"{match.group(1)}/{match.group(2)}"
                break

        if not valid_date_found:
            # 如果单行没匹配到，遍历排除了长数字/卡号行以外的文字片段进行合并分析
            candidate_texts = []
            for line in all_lines:
                if card_number_line and line is card_number_line:
                    continue
                cleaned_line_digits = self._clean_to_digits_with_lookalikes(line.text)
                if len(cleaned_line_digits) >= 12:
                    continue
                candidate_texts.append(line.text)
                
            joined_candidates = "".join(candidate_texts).replace(" ", "")
            cleaned_joined = clean_valid_text(joined_candidates)
            
            match = re.search(r"(0[1-9]|1[0-2])\s*/\s*([2-3][0-9])", cleaned_joined)
            if match:
                valid_date_found = f"{match.group(1)}/{match.group(2)}"
            else:
                # 尝试无斜杠连笔 4 位数纠错 (比如 1229)
                match_digits = re.search(r"\b(0[1-9]|1[0-2])([2-3][0-9])\b", cleaned_joined)
                if match_digits:
                    valid_date_found = f"{match_digits.group(1)}/{match_digits.group(2)}"

        data["valid_date"] = valid_date_found

        return data
