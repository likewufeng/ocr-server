r'''
Author: WuFeng <763467339@qq.com>
Date: 2026-07-09 10:20:58
LastEditTime: 2026-07-09 11:10:40
LastEditors: WuFeng <763467339@qq.com>
Description: 营业执照解析器
FilePath: \ocr-server\app\parsers\business.py
Copyright 版权声明
'''
import re
from app.utils.layout import Layout

class BusinessParser:
    def parse(self, layout: Layout):
        data = {
            "type": "business_license",
            "credit_code": "",
            "name": "",
            "type_name": "",
            "legal_person": "",
            "address": "",
            "capital": "",
            "establish_date": ""
        }

        # 1. 统一社会信用代码 (通常在最上方)
        all_text = "".join(layout.texts())
        code_match = re.search(r"[0-9A-Z]{18}", all_text)
        if code_match:
            data["credit_code"] = code_match.group()

        # 2. 定义双列布局的关键词 (用于防止左列内容抓到右列)
        # 右列标签名单，用来当做“防火墙”
        right_column_labels = ["注册资本", "成立日期", "住所", "营业场所"]

        # 定义提取函数
        def get_value_smart(label_keywords):
            # 兼容带空格的标签识别 (比如 "名 称")
            label_line = None
            for kw in label_keywords:
                label_line = layout.find(kw)
                if label_line: break
            
            # 如果没找到，尝试找首字和尾字 (比如 OCR 把 "名" 和 "称" 分开了)
            if not label_line and len(label_keywords[0]) > 1:
                label_line = layout.find(label_keywords[0][0]) 

            if not label_line:
                return ""

            # 获取右侧所有内容
            rights = layout.right_of(label_line, tolerance=40)
            if not rights:
                # 尝试查找下方靠近的行 (备选方案)
                below = layout.nearest_below(label_line)
                if below and (below.top - label_line.bottom < 50):
                    return below.text.strip()
                return ""

            # 【核心逻辑】截断右侧干扰
            # 我们只取右侧的内容，但一旦遇到右列的标签，立即停止
            value_parts = []
            for item in rights:
                # 如果这一块内容包含了右列的标签关键词，直接结束
                if any(rl in item.text for rl in right_column_labels):
                    break
                # 如果两个框之间距离太远 (超过 200 像素)，通常说明跨到了第二列
                if value_parts and (item.left - rights[rights.index(item)-1].right > 200):
                    break
                value_parts.append(item.text)

            val = "".join(value_parts).strip()
            # 清理可能残留的冒号
            return val.replace(":", "").replace("：", "").strip()

        # 3. 提取各个字段
        data["name"] = get_value_smart(["名称", "名 称"])
        data["type_name"] = get_value_smart(["类型", "类 型"])
        data["legal_person"] = get_value_smart(["法定代表人", "负责人", "经营者"])
        data["capital"] = get_value_smart(["注册资本", "注册资金"])
        data["establish_date"] = get_value_smart(["成立日期"])

        # 4. 住所/地址 (专项修复版)
        addr_val = ""
        # 扩大搜索范围：匹配 "住所"、"住 所"、"营业场所"、或者同时包含 "住" 和 "所"
        addr_label = (
            layout.find("住所") or 
            layout.find("住 所") or 
            layout.find("场所") or
            layout.find("住") # 兜底策略：如果拆分了，先找“住”
        )

        if addr_label:
            # 拿到标签右侧的所有内容
            rights = layout.right_of(addr_label, tolerance=40)
            
            # 过滤逻辑：如果右侧内容包含标签本身（比如 OCR 把 "住" 和 "所 郑州市..." 分开了）
            temp_text = "".join([r.text for r in rights])
            addr_val = temp_text.replace("所", "").replace(":", "").replace("：", "").strip()

            # 处理跨行：营业执照住所经常是两行
            curr = addr_label
            # 找寻下方行，直到遇到“登记机关”或明显不是地址的内容
            for _ in range(3):
                below = layout.nearest_below(curr)
                if below:
                    # 停止条件：距离太远、包含其他核心标签、或是登记机关
                    if (below.top - curr.bottom > 60) or \
                        ("机关" in below.text) or \
                        ("年" in below.text and "月" in below.text) or \
                        ("：" in below.text):
                        break
                    
                    # 坐标判定：地址的续行通常和第一行地址在水平位置上接近
                    addr_val += below.text.strip()
                    curr = below
                else:
                    break
            data["address"] = addr_val.strip()

        return data