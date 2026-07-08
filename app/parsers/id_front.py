'''
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

        text = "".join(layout.texts())

        data = {
            "type": "id_front",
            "name": "",
            "gender": "",
            "nation": "",
            "birthday": "",
            "address": "",
            "id_number": ""
        }

        m = re.search(r"姓名(.+?)(性别|$)", text)
        if m:
            data["name"] = m.group(1).strip()

        m = re.search(r"性别(男|女)", text)
        if m:
            data["gender"] = m.group(1)

        m = re.search(r"民族(.+?)(出生|$)", text)
        if m:
            data["nation"] = m.group(1).strip()

        m = re.search(r"出生(.+?)(住址|$)", text)
        if m:
            data["birthday"] = m.group(1).strip()

        m = re.search(r"住址(.+?)(公民身份号码|$)", text)
        if m:
            data["address"] = m.group(1).strip()

        m = re.search(r"\d{17}[0-9Xx]", text)
        if m:
            data["id_number"] = m.group()

        return data