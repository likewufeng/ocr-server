# -*- coding: utf-8 -*-
"""银行卡 OCR 结果解析。"""

import re
from typing import Dict, List, Optional

from app.utils.layout import Layout, OCRLine


class BankCardParser:
    """兼容不同银行卡版面的结构化解析器。"""

    KNOWN_BANK_NAMES = sorted(
        [
            "中国工商银行", "中国农业银行", "中国银行", "中国建设银行", "交通银行",
            "招商银行", "中信银行", "中国光大银行", "华夏银行", "中国民生银行",
            "广发银行", "平安银行", "兴业银行", "上海浦东发展银行", "浦发银行",
            "中国邮政储蓄银行", "邮政储蓄银行", "北京银行", "上海银行", "宁波银行",
            "南京银行", "杭州银行", "江苏银行", "浙商银行", "渤海银行",
            "天津银行", "徽商银行", "上海农商银行", "北京农商银行", "重庆农商银行",
            "农村商业银行", "农村信用社", "厦门国际银行", "汇丰银行", "花旗银行",
            "恒生银行",
        ],
        key=len,
        reverse=True,
    )

    # 只放入高置信度的常见号段。号段库不是完整银行卡数据库，后续可按业务样本继续扩展。
    # 候选中已经识别出银行名称时，优先相信 OCR 文本，不用号段覆盖它。
    BIN_RULES = {
        "436742": ("中国建设银行", "信用卡"),
        "622700": ("中国建设银行", "借记卡"),
        "622848": ("中国农业银行", "借记卡"),
        "621660": ("中国银行", "借记卡"),
        "622202": ("中国工商银行", "借记卡"),
        "622588": ("招商银行", "借记卡"),
        "622188": ("中国邮政储蓄银行", "借记卡"),
        "622622": ("中国民生银行", "借记卡"),
        "622155": ("平安银行", "借记卡"),
    }

    DEBIT_KEYWORDS = ("借记卡", "储蓄卡", "一卡通", "debit", "savings")
    CREDIT_KEYWORDS = ("信用卡", "贷记卡", "credit")
    EXPIRY_KEYWORDS = (
        "valid thru", "validthrough", "valid till", "validtill",
        "good thru", "goodthrough", "good till", "goodtill",
        "valid", "expiry", "expire", "exp date", "expdate",
        "有效期", "有效期限", "到期",
    )

    def _clean_to_digits_with_lookalikes(self, text: str) -> str:
        """将 OCR 文本转换为数字，同时修正常见数字/字母混淆。"""
        if not text:
            return ""
        replacements = {
            "O": "0", "I": "1", "L": "1", "S": "5", "Z": "2",
            "B": "8", "G": "6", "T": "7", "Q": "9",
        }
        normalized = text.strip().upper()
        for wrong, right in replacements.items():
            normalized = normalized.replace(wrong, right)
        return re.sub(r"\D", "", normalized)

    @staticmethod
    def _luhn_valid(number: str) -> bool:
        if not 12 <= len(number) <= 19 or not number.isdigit():
            return False
        checksum = 0
        for index, char in enumerate(reversed(number)):
            digit = int(char)
            if index % 2 == 1:
                digit *= 2
                if digit > 9:
                    digit -= 9
            checksum += digit
        return checksum % 10 == 0

    def _extract_card_candidates(self, text: str) -> List[str]:
        """从单个文本框中提取连续或带空格/横线的卡号候选。"""
        if not text:
            return []

        candidates = []
        pattern = r"(?<![A-Za-z0-9])([0-9A-Za-z](?:[0-9A-Za-z\s-]{13,23})[0-9A-Za-z])(?![A-Za-z0-9])"
        for match in re.finditer(pattern, text):
            candidate = self._clean_to_digits_with_lookalikes(match.group(1))
            if 15 <= len(candidate) <= 19:
                candidates.append(candidate)
        return candidates

    def _collect_card_candidates(self, layout: Layout) -> List[Dict]:
        all_lines = layout.all() or []
        candidates: List[Dict] = []
        seen_groups = set()

        # 先按文本框和同行文本框分别尝试，覆盖普通卡号、四段分框和轻微倾斜版面。
        groups = [[line] for line in all_lines]
        for line in all_lines:
            row = layout.same_row(line, tolerance=max(15, min(35, line.height)))
            row = sorted(row, key=lambda item: item.left)
            group_key = tuple(id(item) for item in row)
            if group_key not in seen_groups:
                seen_groups.add(group_key)
                groups.append(row)

        for items in groups:
            text = "".join((item.text or "").strip() for item in items)
            for number in self._extract_card_candidates(text):
                average_score = sum(item.score for item in items) / len(items)
                label_bonus = 20 if any(
                    keyword in text.lower()
                    for keyword in ("卡号", "card", "account", "账号")
                ) else 0
                separator_bonus = 2 if re.search(r"[\s-]", text) else 0
                score = average_score + label_bonus + separator_bonus
                candidates.append(
                    {
                        "number": number,
                        "items": items,
                        "text": text,
                        "luhn": self._luhn_valid(number),
                        "score": score,
                    }
                )

        # 同一个卡号可能由单框和同行框各提取一次，只保留得分更高的候选。
        deduplicated = {}
        for candidate in candidates:
            number = candidate["number"]
            previous = deduplicated.get(number)
            if previous is None or candidate["score"] > previous["score"]:
                deduplicated[number] = candidate
        return list(deduplicated.values())

    def _select_card_candidate(self, layout: Layout) -> Optional[Dict]:
        candidates = self._collect_card_candidates(layout)
        if not candidates:
            return None

        # Luhn 合法候选优先；对旧卡样本或合成测试数据，才回退到非 Luhn 候选。
        candidates.sort(
            key=lambda item: (
                item["luhn"],
                len(item["number"]) in {16, 19},
                item["score"],
            ),
            reverse=True,
        )
        return candidates[0]

    def _extract_bank_name(self, layout: Layout, card_number: str) -> str:
        all_lines = layout.all() or []
        bank_name = ""

        for line in all_lines:
            row_text = "".join(
                (item.text or "").strip()
                for item in layout.same_row(line, tolerance=max(15, min(35, line.height)))
            )
            for name in self.KNOWN_BANK_NAMES:
                if name in row_text:
                    bank_name = name
                    break
            if bank_name:
                break

        if not bank_name:
            for line in all_lines:
                text = (line.text or "").strip()
                if "银行" not in text or any(
                    keyword in text for keyword in ("卡号", "账号", "电话", "热线", "客服", "号码")
                ):
                    continue
                match = re.search(r"([A-Za-z\u4e00-\u9fff]*?银行)", text)
                if match:
                    bank_name = match.group(1).strip()
                    break

        if bank_name:
            match = re.search(r"[\u4e00-\u9fff]+银行", bank_name)
            if match:
                return match.group()

        for prefix in sorted(self.BIN_RULES, key=len, reverse=True):
            if card_number.startswith(prefix):
                return self.BIN_RULES[prefix][0]
        return ""

    def _extract_card_type(self, layout: Layout, card_number: str) -> str:
        text = "".join(layout.texts() or []).replace(" ", "").lower()
        if any(keyword.lower() in text for keyword in self.DEBIT_KEYWORDS):
            return "借记卡"
        if any(keyword.lower() in text for keyword in self.CREDIT_KEYWORDS):
            return "信用卡"

        for prefix in sorted(self.BIN_RULES, key=len, reverse=True):
            if card_number.startswith(prefix):
                return self.BIN_RULES[prefix][1]

        # 不能仅凭 16/19 位长度可靠判断借记卡或信用卡，未知时保留为空。
        return ""

    @staticmethod
    def _clean_valid_text(text: str) -> str:
        replacements = {
            "O": "0", "I": "1", "L": "1", "B": "8", "Z": "2",
            "Q": "9", "G": "6", "S": "5",
        }
        normalized = (text or "").upper().replace(" ", "")
        for wrong, right in replacements.items():
            normalized = normalized.replace(wrong, right)
        return normalized.replace(".", "/").replace("-", "/").replace("\\", "/")

    @classmethod
    def _extract_valid_date_from_text(cls, text: str) -> str:
        normalized = cls._clean_valid_text(text)
        match = re.search(
            r"(?<!\d)(0[1-9]|1[0-2])\s*/?\s*((?:20)?[2-3]\d)(?!\d)",
            normalized,
        )
        if not match:
            return ""
        year = match.group(2)
        return f"{match.group(1)}/{year[-2:]}"

    def _extract_valid_date(self, layout: Layout, card_line_ids: set) -> str:
        all_lines = layout.all() or []
        candidates = []
        seen_groups = set()

        for line in all_lines:
            row = [
                item for item in layout.same_row(
                    line, tolerance=max(15, min(35, line.height))
                )
                if id(item) not in card_line_ids
            ]
            row.sort(key=lambda item: item.left)
            group_key = tuple(id(item) for item in row)
            if not row or group_key in seen_groups:
                continue
            seen_groups.add(group_key)

            text = "".join((item.text or "").strip() for item in row)
            value = self._extract_valid_date_from_text(text)
            if not value:
                continue
            lower_text = text.lower().replace(" ", "")
            has_label = any(keyword in lower_text for keyword in self.EXPIRY_KEYWORDS)
            score = 100 if has_label else 0
            score += sum(item.score for item in row) / len(row)
            candidates.append((has_label, score, value))

        if not candidates:
            return ""
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return candidates[0][2]

    def parse(self, layout: Layout):
        data = {
            "type": "bank_card",
            "bank_name": "",
            "card_number": "",
            "card_type": "",
            "valid_date": "",
        }

        candidate = self._select_card_candidate(layout)
        card_number = candidate["number"] if candidate else ""
        card_line_ids = {
            id(item) for item in (candidate["items"] if candidate else [])
        }
        data["card_number"] = card_number
        data["bank_name"] = self._extract_bank_name(layout, card_number)
        data["card_type"] = self._extract_card_type(layout, card_number)
        data["valid_date"] = self._extract_valid_date(layout, card_line_ids)
        return data
