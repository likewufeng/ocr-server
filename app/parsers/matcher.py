# -*- coding: utf-8 -*-
#Author: WuFeng <763467339@qq.com>
#Date: 2026-07-09 10:50:10
#LastEditTime: 2026-07-10 11:15:00
#LastEditors: WuFeng <763467339@qq.com>
#Description: 
    # Matcher 确实有一些方法（例如 find()、merge()）和 Layout 重复了。如果继续这样设计，后面维护会比较混乱。这一点我建议调整。

    # 我建议明确职责划分：

    # layout.py：负责"空间关系"

    # 它只关心 OCR 的几何布局，不关心业务。
#FilePath: /ocr-server/app/parsers/matcher.py
#Copyright 版权声明
#
import re


class Matcher:
    """
    文本匹配工具

    只负责处理字符串，不处理坐标。
    """

    @staticmethod
    def clean(text: str) -> str:
        """
        文本标准化
        """

        if not text:
            return ""

        return (
            text.replace(" ", "")
                .replace("　", "")
                .replace("：", ":")
                .replace("（", "(")
                .replace("）", ")")
                .strip()
        )

    @staticmethod
    def extract_after(text: str, keyword: str) -> str:
        """
        提取关键字后面的内容

        姓名吴烽
            ↓
        吴烽
        """

        text = Matcher.clean(text)

        if keyword not in text:
            return ""

        return text.split(keyword, 1)[1].strip()

    @staticmethod
    def extract_before(text: str, keyword: str) -> str:
        """
        提取关键字前面的内容
        """

        text = Matcher.clean(text)

        if keyword not in text:
            return ""

        return text.split(keyword, 1)[0].strip()

    @staticmethod
    def regex(text: str, pattern: str) -> str:
        """
        正则匹配

        返回第一个分组，没有分组则返回整个匹配。
        """

        text = Matcher.clean(text)

        m = re.search(pattern, text)

        if not m:
            return ""

        if m.groups():
            return m.group(1)

        return m.group()

    @staticmethod
    def contains(text: str, keyword: str) -> bool:
        """
        是否包含关键字
        """

        return keyword in Matcher.clean(text)

    @staticmethod
    def is_empty(text: str) -> bool:
        """
        是否为空
        """

        return Matcher.clean(text) == ""