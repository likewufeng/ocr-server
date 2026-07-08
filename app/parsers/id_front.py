r'''
Author: WuFeng <763467339@qq.com>
Date: 2026-07-08 17:13:25
LastEditTime: 2026-07-08 21:10:35
LastEditors: WuFeng <763467339@qq.com>
Description: 
FilePath: \ocr-server\app\parsers\id_front.py
Copyright 版权声明
'''
import re

from app.utils.layout import Layout


class IDFrontParser:

    def parse(self, layout: Layout):

        data = {
            "type": "id_front",
            "name": "",
            "gender": "",
            "nation": "",
            "birthday": "",
            "address": "",
            "id_number": ""
        }

        # ---------------- 姓名 ----------------

        name_line = layout.find("姓名")

        if name_line:

            # OCR 已经识别成：姓名吴烽
            m = re.search(r"姓名\s*(.+)", name_line.text)
            if m:
                data["name"] = m.group(1).strip()

            # 如果没有识别出来，再走布局
            if not data["name"]:
                right = layout.right_of(name_line)
                if right:
                    data["name"] = "".join(i.text for i in right).strip()

        # ---------------- 性别、民族 ----------------

        gender_line = layout.find("性别")

        if gender_line:

            text = gender_line.text

            m = re.search(r"性别\s*(男|女)", text)
            if m:
                data["gender"] = m.group(1)

            m = re.search(r"民族\s*(.+)", text)
            if m:
                data["nation"] = m.group(1).strip()

        # ---------------- 出生 ----------------

        birth_line = layout.find("出生")

        if birth_line:

            m = re.search(
                r"\d{4}年\d{1,2}月\d{1,2}日",
                birth_line.text
            )

            if m:
                data["birthday"] = m.group()

        # ---------------- 地址 ----------------

        addr_line = layout.find("住址")

        if addr_line:

            addr = addr_line.text.replace("住址", "").strip()

            next_line = layout.nearest_below(addr_line)

            if next_line and "公民身份号码" not in next_line.text:
                addr += next_line.text

            data["address"] = addr

        # ---------------- 身份证号 ----------------

        full_text = "".join(layout.texts())

        full_text = (
            full_text
            .replace(" ", "")
            .replace("\n", "")
        )

        m = re.search(
            r"\d{17}[0-9Xx]",
            full_text
        )

        if m:
            data["id_number"] = m.group()

        return data