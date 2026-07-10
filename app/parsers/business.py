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
        # 通用取值
        # ----------------------------------------------------

        def value(*keywords):

            label = layout.find_any(*keywords)

            if not label:
                return ""

            # 标签和值在同一个 OCRLine
            for kw in keywords:

                if kw in label.text:

                    v = label.text.replace(kw, "").strip()

                    if v:
                        return v

            # 同行最近右侧
            right = layout.nearest_right(
                label,
                tolerance=40
            )

            if not right:
                return ""

            # OCR 把标签拆成：
            #
            # 名
            # 称
            # XXX
            #
            if right.text in {"称", "型", "所"}:

                second = layout.nearest_right(
                    right,
                    tolerance=40
                )

                if second:
                    return second.text.strip()

            return right.text.strip()

        # ----------------------------------------------------
        # 名称
        # ----------------------------------------------------

        data["name"] = value(
            "名称",
            "名 称",
            "名"
        )

        # ----------------------------------------------------
        # 类型
        # ----------------------------------------------------

        data["type_name"] = value(
            "类型",
            "类 型",
            "类"
        )

        # ----------------------------------------------------
        # 法定代表人
        # ----------------------------------------------------

        data["legal_person"] = value(
            "法定代表人",
            "负责人",
            "经营者"
        )

        # ----------------------------------------------------
        # 注册资本
        # ----------------------------------------------------

        data["capital"] = value(
            "注册资本"
        )

        # ----------------------------------------------------
        # 成立日期
        # ----------------------------------------------------

        data["establish_date"] = value(
            "成立日期"
        )

        # ----------------------------------------------------
        # 地址
        # ----------------------------------------------------

        addr_line = layout.find_any(
            "住所",
            "住 所",
            "所"
        )

        if addr_line:

            first = layout.nearest_right(
                addr_line,
                tolerance=40
            )

            if first:

                addr_parts = [first.text]

                current = first

                while True:

                    below = layout.nearest_below(current)

                    if not below:
                        break

                    # 距离太远，不属于地址
                    if below.top - current.bottom > 120:
                        break

                    # 遇到新的字段
                    stop_words = [
                        "经营范围",
                        "注册资本",
                        "成立日期",
                        "法定代表人",
                        "登记",
                        "市场监督"
                    ]

                    if any(word in below.text for word in stop_words):
                        break

                    # 左边界变化太大，不属于地址续行
                    if abs(below.left - first.left) > 200:
                        break

                    addr_parts.append(below.text)

                    current = below

                data["address"] = "".join(addr_parts)

        # ----------------------------------------------------
        # 经营范围
        # ----------------------------------------------------

        scope_line = layout.find("经营范围")

        if scope_line:

            scope_parts = []

            # 第一行（经营范围右侧）
            rights = layout.right_of(
                scope_line,
                tolerance=40
            )

            for item in rights:
                scope_parts.append(item.text)

            # 后续多行
            current = scope_line

            while True:

                below = layout.nearest_below(current)

                if not below:
                    break

                stop_words = [
                    "登记",
                    "市场监督",
                    "国家企业信用信息公示系统",
                    "http://"
                ]

                if any(word in below.text for word in stop_words):
                    break

                # 经营范围通常位于左半区域
                if below.left > 2200:
                    break

                scope_parts.append(below.text)

                current = below

            data["business_scope"] = "".join(scope_parts)

        return data