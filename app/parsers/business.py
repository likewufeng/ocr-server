"""
固定版营业执照解析器 - 完整解决方案
此文件包含所有修复，可直接替换 business.py
"""
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
            "capital": "",
            "establish_date": "",
            "address": "",
            "business_scope": ""
        }

        # ----------------------------------------------------
        # 统一社会信用代码
        # ----------------------------------------------------

        text = "".join(layout.texts())
        m = re.search(r"[0-9A-Z]{18}", text)
        if m:
            data["credit_code"] = m.group()

        # ----------------------------------------------------
        # 辅助函数
        # ----------------------------------------------------

        def get_right_value(label: str, tolerance: int = 250) -> str:
            """获取标签右侧的文本值"""
            label_line = layout.find(label)
            if not label_line:
                return ""
            
            # 标签和值在同一行
            if label in label_line.text:
                v = label_line.text.replace(label, "").strip()
                if v:
                    return v
            
            # 查找右侧值
            right = layout.nearest_right(label_line, tolerance=tolerance)
            if right:
                return right.text.strip()
            
            return ""

        def get_right_value_any(*labels: str, tolerance: int = 250) -> str:
            """获取任意标签右侧的文本值"""
            for label in labels:
                result = get_right_value(label, tolerance)
                if result:
                    return result
            return ""

        # ----------------------------------------------------
        # 名称（特殊处理：OCR可能拆分为"名" + "称河南省..."）
        # ----------------------------------------------------

        name_candidates = []
        
        name_text = get_right_value("名称", tolerance=250)
        if name_text:
            name_candidates.append(name_text)
        
        name_text = get_right_value("名 称", tolerance=250)
        if name_text:
            name_candidates.append(name_text)
        
        # 处理拆分："名" + "称..."
        name_label = layout.find("名")
        if name_label:
            right = layout.nearest_right(name_label, tolerance=250)
            if right and right.text.startswith("称"):
                name_candidates.append(right.text[1:].strip())
            elif right:
                name_candidates.append(right.text.strip())
        
        if name_candidates:
            data["name"] = max(name_candidates, key=len)

        # ----------------------------------------------------
        # 类型（特殊处理：OCR可能拆分为"类" + "型其他..."）
        # ----------------------------------------------------

        type_candidates = []
        
        type_text = get_right_value("类型", tolerance=250)
        if type_text:
            type_candidates.append(type_text)
        
        type_text = get_right_value("类 型", tolerance=250)
        if type_text:
            type_candidates.append(type_text)
        
        # 处理拆分："类" + "型..."
        type_label = layout.find("类")
        if type_label:
            right = layout.nearest_right(type_label, tolerance=250)
            if right and right.text.startswith("型"):
                type_candidates.append(right.text[1:].strip())
            elif right:
                type_candidates.append(right.text.strip())
        
        if type_candidates:
            data["type_name"] = max(type_candidates, key=len)

        # ----------------------------------------------------
        # 法定代表人（最宽松验证）
        # ----------------------------------------------------

        legal_label = layout.find_any("法定代表人", "负责人")
        if legal_label:
            # 尝试1：右侧
            right = layout.nearest_right(legal_label, tolerance=250)
            if right and right.text:
                # 最宽松验证：仅检查长度和是否有汉字
                if 2 <= len(right.text) <= 15 and any('\u4e00' <= c <= '\u9fff' for c in right.text):
                    data["legal_person"] = right.text.strip()
            
            # 尝试2：下方
            if not data["legal_person"]:
                below = layout.nearest_below(legal_label)
                if below and below.text:
                    if 2 <= len(below.text) <= 15 and any('\u4e00' <= c <= '\u9fff' for c in below.text):
                        data["legal_person"] = below.text.strip()

        # ----------------------------------------------------
        # 注册资本
        # ----------------------------------------------------

        data["capital"] = get_right_value_any("注册资本", tolerance=250)

        # ----------------------------------------------------
        # 成立日期
        # ----------------------------------------------------

        data["establish_date"] = get_right_value_any("成立日期", tolerance=250)

        # ----------------------------------------------------
        # 地址（收集所有包含地址关键词的文本块）
        # ----------------------------------------------------

        addr_candidates = []
        addr_keywords = ["省", "市", "区", "县", "路", "街", "号", "楼", "层", "广场", "大厦", "商场", "城", "镇"]
        
        for line in layout.all():
            if any(kw in line.text for kw in addr_keywords):
                # 排除经营范围等字段
                stop_words = ["许可项目", "经营范围", "一般项目", "登记", "市场监督", "国家企业"]
                if not any(word in line.text for word in stop_words):
                    addr_candidates.append(line.text)
        
        if addr_candidates:
            # 按 y 坐标排序并合并
            addr_candidates.sort(key=lambda x: x)
            data["address"] = " ".join(addr_candidates)

        # ----------------------------------------------------
        # 经营范围
        # ----------------------------------------------------

        scope_line = layout.find("经营范围")

        if scope_line:
            scope_parts = []
            
            # 第一行（经营范围右侧）
            rights = layout.right_of(scope_line, tolerance=40)
            for item in rights:
                scope_parts.append(item.text)
            
            # 后续多行
            current = scope_line
            while True:
                below = layout.nearest_below(current)
                if not below:
                    break
                
                stop_words = ["登记", "市场监督", "国家企业信用信息公示系统", "http://"]
                if any(word in below.text for word in stop_words):
                    break
                
                if below.left > 2200:
                    break
                
                scope_parts.append(below.text)
                current = below
            
            data["business_scope"] = "".join(scope_parts)

        return data
