# -*- coding: utf-8 -*-
#Author: WuFeng <763467339@qq.com>
#Date: 2026-07-28
#Description: 增值税发票解析器 (含智能纠错版)
#FilePath: /ocr-server/app/parsers/invoice.py
#

import re
from statistics import median
from typing import Optional, List
from app.utils.layout import Layout, OCRLine


class InvoiceParser:
    """增值税发票解析器"""

    def _clean_numeric_string(self, text: str) -> str:
        """纯数字字段纠错（发票代码、号码、金额等）"""
        if not text:
            return ""
        t = text.strip().upper().replace(" ", "")
        replacements = {
            "O": "0", "I": "1", "L": "1", "S": "5", 
            "Z": "2", "B": "8", "G": "6", "T": "7"
        }
        for wrong, right in replacements.items():
            t = t.replace(wrong, right)
        return re.sub(r"\D", "", t)

    def _clean_tax_id(self, text: str) -> str:
        """纳税人识别号纠错（15, 17, 18 或 20 位纯数字/字母组合）"""
        if not text:
            return ""
        t = text.strip().upper().replace(" ", "").replace("-", "")
        # 前17位或前部多不含容易混淆的 I、O、S、V、Z
        # 常见 OCR 误识别字映射：
        # 特别在数字位：把 I, O, S 误识为字母；在字母位：把数字误识为字母等
        replacements = {
            "I": "1", "O": "0", "S": "5", "V": "U", "Z": "2",
            "L": "1", "G": "6", "B": "8"
        }
        
        # 尝试使用 18 位社会信用代码校验机制对其纠正
        if len(t) == 18:
            chars = list(t)
            # 2-7位纯数字区
            for idx in range(2, 8):
                if chars[idx].isalpha():
                    chars[idx] = replacements.get(chars[idx], chars[idx])
            # 其余混合编码区纠正容易混淆的字
            for idx in list(range(0, 2)) + list(range(8, 18)):
                if chars[idx] not in "0123456789ABCDEFGHJKLMNPQRTUWXY":
                    chars[idx] = replacements.get(chars[idx], chars[idx])
            t = "".join(chars)
            
        return t

    def _clean_amount(self, text: str) -> str:
        """金额纠错：支持负数、小数点、千分位，并处理字母误识别"""
        if not text:
            return ""
        t = text.strip().upper().replace(" ", "").replace(",", "").replace("*", "")
        # 去除前导符号
        t = re.sub(r"^[￥¥\-*]+", "", t)
        
        # 形似字纠正
        replacements = {
            "O": "0", "I": "1", "L": "1", "S": "5", "Z": "2", "B": "8"
        }
        for wrong, right in replacements.items():
            t = t.replace(wrong, right)
            
        # 寻找首个符合金额格式的小数
        m = re.search(r"\d+\.\d{2}", t)
        if m:
            return m.group()
        # 如果漏掉了小数点，但长度较长，尝试在最后两位数前补上小数点
        if t.isdigit() and len(t) >= 3:
            return f"{t[:-2]}.{t[-2:]}"
        return t

    def parse(self, layout: Layout):
        data = {
            "type": "invoice",
            "invoice_code": "",         # 发票代码
            "invoice_number": "",       # 发票号码
            "issue_date": "",           # 开票日期
            "buyer_name": "",           # 购买方名称
            "buyer_tax_id": "",         # 购买方纳税人识别号
            "seller_name": "",          # 销售方名称
            "seller_tax_id": "",        # 销售方纳税人识别号
            "total_amount": "",         # 合计金额 (不含税)
            "total_tax": "",            # 合计税额
            "amount_with_tax": ""       # 价税合计 (含税小写)
        }

        all_lines = list(layout.all() or [])
        if not all_lines:
            return data

        # 排序
        all_lines.sort(key=lambda x: (x.top, x.left))
        all_text_joined = "".join(layout.texts() or []).replace(" ", "")

        # 估算基本行高
        line_heights = [max(1, line.bottom - line.top) for line in all_lines]
        base_h = int(median(line_heights)) if line_heights else 20

        # Helper functions
        def strip_label(text: str, *labels: str) -> str:
            for label in labels:
                if label in text:
                    return text.replace(label, "", 1).lstrip(":：").strip()
            return text.strip()

        # ---------------- 1. 发票代码 ----------------
        invoice_code_found = ""
        code_line = layout.find_any("发票代码", "代码")
        if code_line:
            m = re.search(r"(?:发票代码|代码)[：:]?\s*([0-9A-Za-z]{10,12})", code_line.text)
            if m:
                invoice_code_found = self._clean_numeric_string(m.group(1))
            else:
                rights = layout.right_of(code_line, tolerance=40)
                for item in rights:
                    m = re.search(r"([0-9A-Za-z]{10,12})", item.text)
                    if m:
                        invoice_code_found = self._clean_numeric_string(m.group(1))
                        break

        if not invoice_code_found:
            # 宽松匹配混有字母的 10或12位组合
            matches = re.findall(r"\b[0-9A-Za-z]{10,12}\b", all_text_joined)
            if matches:
                invoice_code_found = self._clean_numeric_string(matches[0])

        data["invoice_code"] = invoice_code_found

        # ---------------- 2. 发票号码 ----------------
        invoice_number_found = ""
        num_line = layout.find_any("发票号码", "号码")
        if num_line:
            m = re.search(r"(?:发票号码|号码)[：:]?\s*([0-9A-Za-z]{8})", num_line.text)
            if m:
                invoice_number_found = self._clean_numeric_string(m.group(1))
            else:
                rights = layout.right_of(num_line, tolerance=40)
                for item in rights:
                    m = re.search(r"([0-9A-Za-z]{8})", item.text)
                    if m:
                        invoice_number_found = self._clean_numeric_string(m.group(1))
                        break

        if not invoice_number_found:
            matches = re.findall(r"\b[0-9A-Za-z]{8}\b", all_text_joined)
            if matches:
                for m in matches:
                    cleaned_m = self._clean_numeric_string(m)
                    if cleaned_m != invoice_code_found[:8] and cleaned_m != invoice_code_found[-8:]:
                        invoice_number_found = cleaned_m
                        break
                if not invoice_number_found:
                    invoice_number_found = self._clean_numeric_string(matches[0])

        data["invoice_number"] = invoice_number_found

        # ---------------- 3. 开票日期 ----------------
        issue_date_found = ""
        
        def clean_date_text(d_text: str) -> str:
            # 日期形似字转换 (如把 O 转换成 0, l/I 转换成 1)
            d_text = d_text.upper().replace(" ", "")
            repls = {"O": "0", "I": "1", "L": "1", "G": "6"}
            for w, r in repls.items():
                d_text = d_text.replace(w, r)
            return d_text

        date_line = layout.find_any("开票日期", "日期")
        if date_line:
            cleaned_txt = clean_date_text(date_line.text)
            m = re.search(r"(\d{4}年\d{1,2}月\d{1,2}日|\d{4}-\d{1,2}-\d{1,2})", cleaned_txt)
            if m:
                issue_date_found = m.group(1)
            else:
                rights = layout.right_of(date_line, tolerance=40)
                for item in rights:
                    cleaned_item = clean_date_text(item.text)
                    m = re.search(r"(\d{4}年\d{1,2}月\d{1,2}日|\d{4}-\d{1,2}-\d{1,2})", cleaned_item)
                    if m:
                        issue_date_found = m.group(1)
                        break

        if not issue_date_found:
            cleaned_joined = clean_date_text(all_text_joined)
            m = re.search(r"(\d{4}年\d{1,2}月\d{1,2}日|\d{4}-\d{1,2}-\d{1,2})", cleaned_joined)
            if m:
                issue_date_found = m.group(1)

        data["issue_date"] = issue_date_found

        # ---------------- 4. 购买方/销售方区域划分 ----------------
        buyer_anchor = layout.find_any("购买方", "购 买 方")
        seller_anchor = layout.find_any("销售方", "销 售 方")

        name_lines = layout.find_all("名称")
        name_lines.extend(layout.find_all("名 称"))
        name_lines = sorted(list({id(line): line for line in name_lines}.values()), key=lambda x: x.top)

        tax_id_lines = layout.find_all("纳税人识别号")
        tax_id_lines.extend(layout.find_all("识别号"))
        tax_id_lines = sorted(list({id(line): line for line in tax_id_lines}.values()), key=lambda x: x.top)

        def extract_value_right_of_label(label_line: OCRLine) -> str:
            if not label_line:
                return ""
            val = strip_label(label_line.text, "名称", "名 称", "纳税人识别号", "识别号")
            if val and len(val) > 2:
                return val
            rights = layout.right_of(label_line, tolerance=max(15, int(base_h * 0.8)))
            if rights:
                parts = []
                for item in rights:
                    t = item.text.strip()
                    if any(kw in t for kw in ["纳税人识别号", "识别号", "地址", "电话", "开户行", "账号"]):
                        break
                    parts.append(t)
                return "".join(parts).strip()
            return ""

        # 分配名称
        if len(name_lines) >= 2:
            data["buyer_name"] = extract_value_right_of_label(name_lines[0])
            data["seller_name"] = extract_value_right_of_label(name_lines[1])
        elif len(name_lines) == 1:
            line = name_lines[0]
            if buyer_anchor and seller_anchor:
                if abs(line.top - buyer_anchor.top) < abs(line.top - seller_anchor.top):
                    data["buyer_name"] = extract_value_right_of_label(line)
                else:
                    data["seller_name"] = extract_value_right_of_label(line)
            else:
                data["buyer_name"] = extract_value_right_of_label(line)

        # 分配并纠正税号
        if len(tax_id_lines) >= 2:
            data["buyer_tax_id"] = self._clean_tax_id(extract_value_right_of_label(tax_id_lines[0]))
            data["seller_tax_id"] = self._clean_tax_id(extract_value_right_of_label(tax_id_lines[1]))
        elif len(tax_id_lines) == 1:
            line = tax_id_lines[0]
            if buyer_anchor and seller_anchor:
                if abs(line.top - buyer_anchor.top) < abs(line.top - seller_anchor.top):
                    data["buyer_tax_id"] = self._clean_tax_id(extract_value_right_of_label(line))
                else:
                    data["seller_tax_id"] = self._clean_tax_id(extract_value_right_of_label(line))
            else:
                data["buyer_tax_id"] = self._clean_tax_id(extract_value_right_of_label(line))

        # ---------------- 5. 金额提取与算术复核 ----------------
        total_line = layout.find_any("合计", "合 计")
        if total_line:
            rights = layout.right_of(total_line, tolerance=40)
            prices = []
            for item in rights:
                # 捕获可能的含形似字符金额串（如 1,OOO.0O）
                matches = re.findall(r"[-*¥￥]?\s*([0-9A-Za-z,]+\.[0-9A-Za-z]{2})", item.text)
                if matches:
                    prices.extend([self._clean_amount(m) for m in matches])

            if len(prices) >= 1:
                data["total_amount"] = prices[0]
            if len(prices) >= 2:
                data["total_tax"] = prices[1]

        # 价税合计 (含税金额)
        with_tax_line = layout.find_any("价税合计", "价税合计（大写）", "价税合计(大写)")
        if with_tax_line:
            rights = layout.right_of(with_tax_line, tolerance=40)
            text_to_search = with_tax_line.text + "".join(i.text for i in rights)
            m = re.search(r"(?:小写|￥|¥)\s*[-*]?\s*([0-9A-Za-z,]+\.[0-9A-Za-z]{2})", text_to_search)
            if m:
                data["amount_with_tax"] = self._clean_amount(m.group(1))
            else:
                matches = re.findall(r"([0-9A-Za-z,]+\.[0-9A-Za-z]{2})", text_to_search)
                if matches:
                    data["amount_with_tax"] = self._clean_amount(matches[-1])

        # 全文高鲁棒性加减法纠错与配对
        if not data["total_amount"] or not data["amount_with_tax"] or not data["total_tax"]:
            # 搜索全文中所有可能的浮点数
            raw_floats = re.findall(r"[-*¥￥]?\s*([0-9A-Za-z,]+\.[0-9A-Za-z]{2})", all_text_joined)
            if not raw_floats:
                raw_floats = re.findall(r"([0-9A-Za-z,]+\.[0-9A-Za-z]{2})", all_text_joined)
            
            cleaned_prices = []
            for item in raw_floats:
                cleaned = self._clean_amount(item)
                if cleaned:
                    cleaned_prices.append(cleaned)
                    
            if len(cleaned_prices) >= 2:
                try:
                    # 消除重复
                    unique_prices = sorted(list(set([float(p) for p in cleaned_prices])))
                    found = False
                    # 双重循环复核: a + b = c，也就是 不含税金额 + 税额 = 价税合计
                    for i in range(len(unique_prices)):
                        for j in range(len(unique_prices)):
                            if i == j:
                                continue
                            for k in range(len(unique_prices)):
                                if k == i or k == j:
                                    continue
                                a, b, c = unique_prices[i], unique_prices[j], unique_prices[k]
                                # 允许 0.05 元的小误差（OCR舍入误差）
                                if abs(a + b - c) < 0.05 and c > a and c > b:
                                    data["total_amount"] = f"{a:.2f}"
                                    data["total_tax"] = f"{b:.2f}"
                                    data["amount_with_tax"] = f"{c:.2f}"
                                    found = True
                                    break
                            if found:
                                break
                        if found:
                            break
                except ValueError:
                    pass

        return data
