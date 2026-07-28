# -*- coding: utf-8 -*-
#Author: WuFeng <763467339@qq.com>
#Date: 2026-07-28
#Description: 增值税发票解析器
#FilePath: /ocr-server/app/parsers/invoice.py
#

import re
from statistics import median
from typing import Optional, List
from app.utils.layout import Layout, OCRLine


class InvoiceParser:
    """增值税发票解析器"""

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
            # 尝试在同块中提取
            m = re.search(r"(?:发票代码|代码)[：:]?\s*(\d{10,12})", code_line.text)
            if m:
                invoice_code_found = m.group(1)
            else:
                # 尝试在右侧寻找
                rights = layout.right_of(code_line, tolerance=40)
                for item in rights:
                    m = re.search(r"(\d{10,12})", item.text)
                    if m:
                        invoice_code_found = m.group(1)
                        break

        # 全文回退寻找 10或12位纯数字
        if not invoice_code_found:
            matches = re.findall(r"\b\d{10,12}\b", all_text_joined)
            if matches:
                invoice_code_found = matches[0]

        data["invoice_code"] = invoice_code_found

        # ---------------- 2. 发票号码 ----------------
        invoice_number_found = ""
        num_line = layout.find_any("发票号码", "号码")
        if num_line:
            m = re.search(r"(?:发票号码|号码)[：:]?\s*(\d{8})", num_line.text)
            if m:
                invoice_number_found = m.group(1)
            else:
                rights = layout.right_of(num_line, tolerance=40)
                for item in rights:
                    m = re.search(r"(\d{8})", item.text)
                    if m:
                        invoice_number_found = m.group(1)
                        break

        # 全文回退寻找 8位纯数字 (通常在发票代码后面或附近)
        if not invoice_number_found:
            matches = re.findall(r"\b\d{8}\b", all_text_joined)
            if matches:
                # 排除发票代码的前8位或后8位
                for m in matches:
                    if m != invoice_code_found[:8] and m != invoice_code_found[-8:]:
                        invoice_number_found = m
                        break
                if not invoice_number_found:
                    invoice_number_found = matches[0]

        data["invoice_number"] = invoice_number_found

        # ---------------- 3. 开票日期 ----------------
        issue_date_found = ""
        date_line = layout.find_any("开票日期", "日期")
        if date_line:
            # 常见格式：2023年06月15日 或 2023-06-15
            m = re.search(r"(\d{4}年\d{1,2}月\d{1,2}日|\d{4}-\d{1,2}-\d{1,2})", date_line.text)
            if m:
                issue_date_found = m.group(1)
            else:
                rights = layout.right_of(date_line, tolerance=40)
                for item in rights:
                    m = re.search(r"(\d{4}年\d{1,2}月\d{1,2}日|\d{4}-\d{1,2}-\d{1,2})", item.text)
                    if m:
                        issue_date_found = m.group(1)
                        break

        if not issue_date_found:
            m = re.search(r"(\d{4}年\d{1,2}月\d{1,2}日|\d{4}-\d{1,2}-\d{1,2})", all_text_joined)
            if m:
                issue_date_found = m.group(1)

        data["issue_date"] = issue_date_found

        # ---------------- 4. 购买方/销售方区域划分与信息提取 ----------------
        # 寻找购买方、销售方锚点
        buyer_anchor = layout.find_any("购买方", "购 买 方")
        seller_anchor = layout.find_any("销售方", "销 售 方")

        # 辅助寻找名称与纳税人识别号
        name_lines = layout.find_all("名称")
        # 兼容 "名 称"
        name_lines.extend(layout.find_all("名 称"))
        # 去重并排序
        name_lines = sorted(list({id(line): line for line in name_lines}.values()), key=lambda x: x.top)

        tax_id_lines = layout.find_all("纳税人识别号")
        tax_id_lines.extend(layout.find_all("识别号"))
        tax_id_lines = sorted(list({id(line): line for line in tax_id_lines}.values()), key=lambda x: x.top)

        # 提取名称的具体逻辑
        def extract_value_right_of_label(label_line: OCRLine) -> str:
            if not label_line:
                return ""
            # 同块提取
            val = strip_label(label_line.text, "名称", "名 称", "纳税人识别号", "识别号")
            if val and len(val) > 2: # 排除残缺标签
                return val
            # 右侧提取
            rights = layout.right_of(label_line, tolerance=max(15, int(base_h * 0.8)))
            if rights:
                # 拼接右侧连续短块，并排除其他明显标签
                parts = []
                for item in rights:
                    t = item.text.strip()
                    if any(kw in t for kw in ["纳税人识别号", "识别号", "地址", "电话", "开户行", "账号"]):
                        break
                    parts.append(t)
                return "".join(parts).strip()
            return ""

        # 分配购买方和销售方名称
        # 规则：如果有两个名称标签，y坐标较小的为购买方，较大的为销售方
        # 如果只有一个名称标签，看它与 buyer_anchor 和 seller_anchor 的距离
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
                # 默认如果是单张发票，顶部的大多是购买方
                data["buyer_name"] = extract_value_right_of_label(line)

        # 分配纳税人识别号
        if len(tax_id_lines) >= 2:
            data["buyer_tax_id"] = extract_value_right_of_label(tax_id_lines[0])
            data["seller_tax_id"] = extract_value_right_of_label(tax_id_lines[1])
        elif len(tax_id_lines) == 1:
            line = tax_id_lines[0]
            if buyer_anchor and seller_anchor:
                if abs(line.top - buyer_anchor.top) < abs(line.top - seller_anchor.top):
                    data["buyer_tax_id"] = extract_value_right_of_label(line)
                else:
                    data["seller_tax_id"] = extract_value_right_of_label(line)
            else:
                data["buyer_tax_id"] = extract_value_right_of_label(line)

        # ---------------- 5. 金额提取 (合计金额, 合计税额, 价税合计) ----------------
        # 寻找 "合计" 和 "价税合计"
        total_line = layout.find_any("合计", "合 计")
        if total_line:
            # 合计行右侧往往有两个金额：一个是金额，一个是税额
            rights = layout.right_of(total_line, tolerance=40)
            prices = []
            for item in rights:
                # 匹配金额：如 ￥1234.56, 1,234.56, -1234.56, ***123.45等
                matches = re.findall(r"[-*¥￥]?\s*([\d,]+\.\d{2})", item.text)
                if matches:
                    prices.extend([m.replace(",", "") for m in matches])

            if len(prices) >= 1:
                data["total_amount"] = prices[0]
            if len(prices) >= 2:
                data["total_tax"] = prices[1]

        # 价税合计 (含税金额)
        with_tax_line = layout.find_any("价税合计", "价税合计（大写）", "价税合计(大写)")
        if with_tax_line:
            # 寻找同块或右侧带(小写)或￥的数字
            rights = layout.right_of(with_tax_line, tolerance=40)
            # 在同一行或其右侧寻找
            text_to_search = with_tax_line.text + "".join(i.text for i in rights)
            m = re.search(r"(?:小写|￥|¥)\s*[-*]?\s*([\d,]+\.\d{2})", text_to_search)
            if m:
                data["amount_with_tax"] = m.group(1).replace(",", "")
            else:
                # 备用：匹配任何小数字符串
                matches = re.findall(r"([\d,]+\.\d{2})", text_to_search)
                if matches:
                    data["amount_with_tax"] = matches[-1].replace(",", "")

        # 如果没有在合计行成功提取金额，用全文正则回退
        if not data["total_amount"] or not data["amount_with_tax"]:
            all_prices = re.findall(r"¥\s*([\d,]+\.\d{2})", all_text_joined)
            if not all_prices:
                all_prices = re.findall(r"([\d,]+\.\d{2})", all_text_joined)
            
            cleaned_prices = [p.replace(",", "") for p in all_prices]
            if len(cleaned_prices) >= 3:
                # 排序或按通常顺序：不含税金额 < 价税合计金额
                # 通常：合计金额(不含税) + 税额 = 价税合计(含税)
                # 我们可以尝试对应分配
                try:
                    floats = [float(p) for p in cleaned_prices]
                    # 寻找三个数 a, b, c，满足 a + b = c (允许微小误差)
                    found = False
                    for i in range(len(floats)):
                        for j in range(len(floats)):
                            if i == j:
                                continue
                            for k in range(len(floats)):
                                if k == i or k == j:
                                    continue
                                if abs(floats[i] + floats[j] - floats[k]) < 0.5:
                                    data["total_amount"] = f"{floats[i]:.2f}"
                                    data["total_tax"] = f"{floats[j]:.2f}"
                                    data["amount_with_tax"] = f"{floats[k]:.2f}"
                                    found = True
                                    break
                            if found:
                                break
                        if found:
                            break
                except ValueError:
                    pass

        return data
