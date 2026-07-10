'''
Author: WuFeng <763467339@qq.com>
Date: 2026-07-09 10:20:58
LastEditTime: 2026-07-09 10:59:33
LastEditors: WuFeng <763467339@qq.com>
Description: 
FilePath: \ocr-server\app\parsers\id_back.py
Copyright 版权声明
'''
import re

from app.utils.layout import Layout


class IDBackParser:

    def parse(self, layout: Layout):

        data = {
            "type": "id_back",
            "authority": "",
            "valid_date": ""
        }

        # ---------- 签发机关 ----------

        authority_line = layout.find("签发机关")

        if authority_line:

            text = authority_line.text

            if "签发机关" in text:

                data["authority"] = (
                    text.replace("签发机关", "")
                    .strip()
                )

            # OCR 将内容拆到下一行
            if not data["authority"]:

                next_line = layout.nearest_below(authority_line)

                if next_line:
                    data["authority"] = next_line.text.strip()

        # ---------- 有效期限 ----------

        valid_line = layout.find("有效期限")

        if valid_line:

            text = valid_line.text

            # 先直接匹配完整日期
            m = re.search(
                r"\d{4}\.\d{2}\.\d{2}[-—至]\d{4}\.\d{2}\.\d{2}",
                text
            )

            if not m:
                m = re.search(
                    r"\d{8}[-—至]\d{8}",
                    text
                )

            if m:
                data["valid_date"] = m.group()

            else:

                data["valid_date"] = (
                    text.replace("有效期限", "")
                    .strip()
                )

                # OCR 拆成两行
                if not data["valid_date"]:

                    next_line = layout.nearest_below(valid_line)

                    if next_line:
                        data["valid_date"] = next_line.text.strip()

        return data