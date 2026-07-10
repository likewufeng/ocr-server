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

        # ----------------------------------------------------
        # 信用代码
        # ----------------------------------------------------

        text = "".join(layout.texts())

        m = re.search(
            r"[0-9A-Z]{18}",
            text
        )

        if m:
            data["credit_code"] = m.group()

        # ----------------------------------------------------
        # 通用取值
        # ----------------------------------------------------

        def value(*keywords):

            label = layout.find_any(*keywords)

            if not label:
                return ""

            # 标签和值在同一个 OCR
            for kw in keywords:

                if kw in label.text:

                    v = label.text.replace(
                        kw,
                        ""
                    ).strip()

                    if v:
                        return v

            # 最近右侧
            right = layout.nearest_right(
                label,
                tolerance=40
            )

            if not right:
                return ""

            # OCR 拆成
            #
            # 名
            # 称
            # XXX
            #
            if (
                len(right.text) <= 2
                and right.text in {
                    "称",
                    "型",
                    "所"
                }
            ):

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
        # 法人
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

        addr = ""

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

                    # 与上一行距离太远，结束
                    if below.top - current.bottom > 120:
                        break

                    # 遇到新的字段，结束
                    stop_words = [
                        "经营范围",
                        "注册资本",
                        "成立日期",
                        "法定代表人",
                        "登记机关"
                    ]

                    if any(word in below.text for word in stop_words):
                        break

                    # 地址续行通常与第一行左边界接近
                    if abs(below.left - first.left) > 200:
                        break

                    addr_parts.append(below.text)

                    current = below

                addr = "".join(addr_parts)

        data["address"] = addr

        return data