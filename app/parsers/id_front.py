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
from datetime import datetime

from app.utils.layout import Layout
from app.utils.ocr_corrections import normalize_known_admin_text


class IDFrontParser:
    _NAME_LABEL_PATTERN = re.compile(r"^(?:姓名|[鲜娃牲姪性]名|财省)[:：]?")
    _GENDER_LABEL_PATTERN = re.compile(r"性[别州期]")
    _NATION_LABEL_PATTERN = re.compile(r"[民闲]族")
    _PERSON_NAME_PATTERN = re.compile(r"^[\u4e00-\u9fff·]{2,20}$")
    _NON_NAME_TEXTS = {
        "姓名", "性别", "民族", "出生", "住址", "公民身份", "公民身份号码",
    }
    _NATION_NAMES = {
        "汉", "蒙古", "回", "藏", "维吾尔", "苗", "彝", "壮", "布依",
        "朝鲜", "满", "侗", "瑶", "白", "土家", "哈尼", "哈萨克", "傣",
        "黎", "傈僳", "佤", "畲", "高山", "拉祜", "水", "东乡", "纳西",
        "景颇", "柯尔克孜", "土", "达斡尔", "仫佬", "羌", "布朗", "撒拉",
        "毛南", "仡佬", "锡伯", "阿昌", "普米", "塔吉克", "怒", "乌孜别克",
        "俄罗斯", "鄂温克", "德昂", "保安", "裕固", "京", "塔塔尔", "独龙",
        "鄂伦春", "赫哲", "门巴", "珞巴", "基诺",
    }

    @classmethod
    def _extract_nation(cls, text: str) -> str:
        candidate = re.sub(r"\s+", "", text or "")
        for nation in sorted(cls._NATION_NAMES, key=len, reverse=True):
            if candidate == nation or candidate.endswith(f"族{nation}"):
                return nation
        return ""

    @staticmethod
    def _extract_birthday(text: str) -> str:
        candidate = re.sub(r"\s+", "", text or "")
        strict_match = re.search(r"\d{4}年\d{1,2}月\d{1,2}日", candidate)
        if strict_match:
            return strict_match.group()

        # 藏文、水印等可能在月份或日期后面混入一个数字，例如“1973年105月27日”。
        # 对异常字段只截取可组成有效日期的前两位，且必须通过日期有效性校验。
        noisy_match = re.search(r"(\d{4})年(\d{3,4})月(\d{1,4})日", candidate)
        if not noisy_match:
            return ""

        year, month_digits, day_digits = noisy_match.groups()
        for month_length in range(min(2, len(month_digits)), 0, -1):
            month = int(month_digits[:month_length])
            for day_length in range(min(2, len(day_digits)), 0, -1):
                day = int(day_digits[:day_length])
                try:
                    datetime(int(year), month, day)
                except ValueError:
                    continue
                return f"{year}年{month}月{day}日"

        return ""

    @classmethod
    def _find_name_label_line(cls, layout: Layout, gender_line=None):
        line = layout.find("姓名")
        if line:
            return line

        for item in layout.all() or []:
            text = re.sub(r"\s+", "", item.text or "")
            if not cls._NAME_LABEL_PATTERN.match(text):
                continue
            # 姓名位于性别字段上方；该约束避免将其它“...名”文本误判为姓名。
            if gender_line and item.center_y >= gender_line.center_y:
                continue
            return item

        return None

    @classmethod
    def _clean_person_name(cls, text: str) -> str:
        candidate = re.sub(r"\s+", "", text or "").strip(":：")
        if candidate.startswith("财省"):
            candidate = candidate[2:]
        for keyword in ("性别", "民族", "出生", "住址", "公民身份"):
            candidate = candidate.split(keyword, 1)[0]
        if candidate in cls._NON_NAME_TEXTS:
            return ""
        return candidate if cls._PERSON_NAME_PATTERN.fullmatch(candidate) else ""

    @classmethod
    def _find_gender_line(cls, layout: Layout):
        for item in layout.all() or []:
            if cls._GENDER_LABEL_PATTERN.search(item.text or ""):
                return item
        return None

    @classmethod
    def _find_name_without_label(cls, layout: Layout, gender_line) -> str:
        if not gender_line:
            return ""

        candidates = []
        for item in layout.all() or []:
            if item is gender_line or item.bottom > gender_line.top:
                continue
            if gender_line.top - item.bottom > max(120, gender_line.height * 3):
                continue
            if item.left < gender_line.left:
                continue

            candidate = cls._clean_person_name(item.text)
            if candidate:
                candidates.append(
                    (gender_line.top - item.bottom, abs(item.left - gender_line.right), candidate)
                )

        if not candidates:
            return ""
        candidates.sort(key=lambda value: (value[0], value[1]))
        return candidates[0][2]

    @staticmethod
    def _find_id_number_label_line(layout: Layout):
        line = layout.find_any("公民身份号码", "公民身份证号码", "身份证号码", "身份号码", "公民身份")
        if line:
            return line

        for item in layout.all() or []:
            text = (item.text or "").replace(" ", "")
            if "身份" in text and "号码" in text:
                return item

        return None

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

        gender_line = self._find_gender_line(layout)
        name_line = self._find_name_label_line(layout, gender_line)

        if name_line:
            normalized_name_text = re.sub(r"\s+", "", name_line.text or "")
            label_match = self._NAME_LABEL_PATTERN.match(normalized_name_text)
            if label_match:
                data["name"] = self._clean_person_name(
                    normalized_name_text[label_match.end():]
                )

            # 如果没有识别出来，再走布局
            if not data["name"]:
                right = layout.right_of(name_line)
                if right:
                    # 姓名右侧可能混入藏文、证件水印等 OCR 噪声。优先选择
                    # 单个可校验的人名框，避免噪声与真实姓名拼接后整体失效。
                    for item in right:
                        candidate = self._clean_person_name(item.text)
                        if candidate:
                            data["name"] = candidate
                            break

                    # 兼容姓名被拆成多个单字框的情况。
                    if not data["name"]:
                        data["name"] = self._clean_person_name(
                            "".join(i.text for i in right)
                        )

        if not data["name"]:
            data["name"] = self._find_name_without_label(layout, gender_line)

        # ---------------- 性别、民族 ----------------

        if gender_line:

            text = "".join(i.text for i in layout.same_row(gender_line, tolerance=30))

            m = re.search(r"性[别州]\s*(男|女)", text)
            if m:
                data["gender"] = m.group(1)

            # 藏文、证件底纹等噪声可能插入“性别”和“男/女”之间，
            # 此时按独立文本框兜底，不依赖同行文本拼接结果。
            if not data["gender"]:
                for item in layout.same_row(gender_line, tolerance=30):
                    candidate = (item.text or "").strip()
                    if candidate in {"男", "女"}:
                        data["gender"] = candidate
                        break

            m = re.search(r"[民闲]族\s*([\u4e00-\u9fff]{1,8})", text)
            if m:
                data["nation"] = m.group(1).strip()

            if not data["nation"]:
                for item in layout.same_row(gender_line, tolerance=30):
                    nation = self._extract_nation(item.text)
                    if nation:
                        data["nation"] = nation
                        break

        # ---------------- 出生 ----------------

        birth_line = layout.find("出生")

        if birth_line:
            birth_row_text = "".join(
                line.text for line in layout.same_row(birth_line, tolerance=35)
            )
            data["birthday"] = self._extract_birthday(birth_row_text)

        # ---------------- 地址 ----------------

        addr_line = layout.find("住址")

        if addr_line:

            addr_parts = []

            # 第一行：住址河南省渑池县洪阳镇德厚
            first_addr = addr_line.text.replace("住址", "", 1).strip()
            if first_addr:
                addr_parts.append(first_addr)

            # 平台模型常把“住址”和第一段地址拆成同行两个框，且地址框 top 可能略高于“住址”框。
            # 这里的容差比通用同行判断更严格，避免第二行地址与标签轻微重叠时
            # 被提前排到首行地址之前。
            address_row_tolerance = max(10, int(addr_line.height * 0.75))
            same_row_addr_lines = [
                line for line in layout.same_row(
                    addr_line, tolerance=address_row_tolerance
                )
                if line is not addr_line and line.center_x > addr_line.center_x
            ]
            for line in same_row_addr_lines:
                text = (line.text or "").strip()
                if text and "住址" not in text:
                    addr_parts.append(text)

            # 找身份证号所在行，作为地址的下边界
            id_label_line = self._find_id_number_label_line(layout)
            bottom_bound = None
            if id_label_line and id_label_line.top > addr_line.top:
                bottom_bound = id_label_line.top

            # 地址列范围：和首行大致同列即可
            # 注意：这里不要用严格的 nearest_below，因为下一行可能和上一行轻微重叠
            if first_addr:
                # PP-OCRv6 may merge the address label and first address line into
                # one box. Estimate the content column so narrower continuation
                # lines are not rejected as being too far left.
                label_width = min(100, max(40, addr_line.height * 2))
                content_left = addr_line.left + label_width
            else:
                content_left = min(
                    [addr_line.right] + [line.left for line in same_row_addr_lines]
                )
            col_left = max(addr_line.left - 50, content_left - 30)
            col_right = addr_line.right + 300

            # 关键修复：
            # 不要求 next_line.top >= addr_line.bottom
            # 只要求它明显在 addr_line 的下半部分以后即可
            min_top = addr_line.top + int((addr_line.bottom - addr_line.top) * 0.55)
            same_row_bottom = max(
                [addr_line.bottom] + [line.bottom for line in same_row_addr_lines]
            )

            # 收集候选续行
            candidates = []
            for line in all_lines:
                if line is addr_line:
                    continue
                if line.text in addr_parts:
                    continue
                # 身份证号的数值框可能比“公民身份号码”标签略高，
                # 因此按 bottom 判断，避免把号码框误拼进地址。
                if bottom_bound is not None and line.bottom > bottom_bound:
                    continue
                if line.top < min_top:
                    continue

                # 与地址列有重叠即可
                if (
                    line.left < col_right
                    and line.right > col_left
                    and line.center_x >= content_left - 10
                ):
                    candidates.append(line)

            candidates.sort(key=lambda x: (x.top, x.left))

            stop_keywords = ["公民身份号码", "公民身份证号码", "身份证号码", "身份号码", "公民身份", "姓名", "性别", "民族", "出生", "住址", "样证"]
            current_bottom = same_row_bottom

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

            data["address"] = normalize_known_admin_text("".join(addr_parts))

        # ---------------- 身份证号 ----------------

        # 优先从“公民身份号码”所在行提取
        id_line = self._find_id_number_label_line(layout)
        if id_line:
            same_row_text = "".join(i.text for i in layout.same_row(id_line, tolerance=30))
            near_right_text = "".join(i.text for i in layout.right_of(id_line, tolerance=30))
            m = re.search(r"\d{17}[0-9Xx]", id_line.text + same_row_text + near_right_text)
            if m:
                data["id_number"] = m.group().upper()

        # 回退：全文提取
        if not data["id_number"]:
            full_text = "".join(layout.texts())
            full_text = full_text.replace(" ", "").replace("\n", "")

            m = re.search(r"\d{17}[0-9Xx]", full_text)
            if m:
                data["id_number"] = m.group().upper()

        # 身份证号码第 17 位为性别校验位：奇数男、偶数女。仅在 OCR 没识别出性别时兜底。
        if not data["gender"] and len(data["id_number"]) == 18:
            gender_digit = data["id_number"][16]
            if gender_digit.isdigit():
                data["gender"] = "男" if int(gender_digit) % 2 else "女"

        # 平台/移动模型可能把“出生”和日期拆框，甚至漏掉日期框。
        # 身份证号码中的出生日期是结构化字段，可作为可靠兜底。
        if not data["birthday"] and data["id_number"]:
            birth_digits = data["id_number"][6:14]
            try:
                birth_date = datetime.strptime(birth_digits, "%Y%m%d")
            except ValueError:
                pass
            else:
                data["birthday"] = (
                    f"{birth_date.year}年{birth_date.month}月{birth_date.day}日"
                )

        return data
