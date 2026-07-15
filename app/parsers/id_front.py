# -*- coding: utf-8 -*-
#Author: WuFeng <763467339@qq.com>
#Date: 2026-07-09 10:20:58
#LastEditTime: 2026-07-15 13:41:06
#LastEditors: WuFeng <763467339@qq.com>
#Description: 身份证正面解析器
#FilePath: /ocr-server/app/parsers/id_front.py
#Copyright 版权声明
#
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

        all_lines = layout.all() or []

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

            m = re.search(r"民族\s*([\u4e00-\u9fff]{1,8})", text)
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

            addr_parts = []

            # 第一行：住址河南省渑池县洪阳镇德厚
            first_addr = addr_line.text.replace("住址", "", 1).strip()
            if first_addr:
                addr_parts.append(first_addr)

            # 找身份证号所在行，作为地址的下边界
            id_label_line = layout.find("公民身份号码")
            bottom_bound = None
            if id_label_line and id_label_line.top > addr_line.top:
                bottom_bound = id_label_line.top

            # 地址列范围：和首行大致同列即可
            # 注意：这里不要用严格的 nearest_below，因为下一行可能和上一行轻微重叠
            col_left = addr_line.left - 50
            col_right = addr_line.right + 300

            # 关键修复：
            # 不要求 next_line.top >= addr_line.bottom
            # 只要求它明显在 addr_line 的下半部分以后即可
            min_top = addr_line.top + int((addr_line.bottom - addr_line.top) * 0.55)

            # 收集候选续行
            candidates = []
            for line in all_lines:
                if line is addr_line:
                    continue
                if bottom_bound is not None and line.top >= bottom_bound:
                    continue
                if line.top < min_top:
                    continue

                # 与地址列有重叠即可
                if line.left < col_right and line.right > col_left:
                    candidates.append(line)

            candidates.sort(key=lambda x: (x.top, x.left))

            stop_keywords = ["公民身份号码", "姓名", "性别", "民族", "出生", "住址"]
            current_bottom = addr_line.bottom

            for line in candidates:
                text = (line.text or "").strip()
                if not text:
                    continue

                if any(k in text for k in stop_keywords):
                    break

                # 和上一地址行距离太大，认为不是地址续行
                if line.top - current_bottom > 40:
                    break

                addr_parts.append(text)
                current_bottom = max(current_bottom, line.bottom)

            data["address"] = "".join(addr_parts)

        # ---------------- 身份证号 ----------------

        # 优先从“公民身份号码”所在行提取
        id_line = layout.find("公民身份号码")
        if id_line:
            m = re.search(r"\d{17}[0-9Xx]", id_line.text)
            if m:
                data["id_number"] = m.group().upper()

        # 回退：全文提取
        if not data["id_number"]:
            full_text = "".join(layout.texts())
            full_text = full_text.replace(" ", "").replace("\n", "")

            m = re.search(r"\d{17}[0-9Xx]", full_text)
            if m:
                data["id_number"] = m.group().upper()

        return data