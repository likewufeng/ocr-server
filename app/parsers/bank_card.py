# -*- coding: utf-8 -*-
"""银行卡 OCR 结果解析。"""

import re
from typing import Dict, List, Optional, Tuple

from app.config import BANK_CARD_CATALOG_FILE
from app.parsers.bank_card_catalog import BankCardCatalog
from app.schemas.bank_card import CardType, MatchSource
from app.utils.layout import Layout


class BankCardParser:
    """兼容不同银行卡版面的结构化解析器。"""

    catalog = BankCardCatalog.load(BANK_CARD_CATALOG_FILE)
    EXPIRY_KEYWORDS = (
        "valid thru", "validthrough", "valid till", "validtill",
        "good thru", "goodthrough", "good till", "goodtill",
        "valid", "expiry", "expire", "exp date", "expdate",
        "有效期", "有效期限", "到期",
    )
    CARD_NUMBER_SEPARATOR_CHARS = "~*·•_"

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
        pattern = (
            r"(?<![A-Za-z0-9])([0-9A-Za-z](?:[0-9A-Za-z\s~*·•_-]{13,23})"
            r"[0-9A-Za-z])(?![A-Za-z0-9])"
        )
        for match in re.finditer(pattern, text):
            raw_candidate = match.group(1)
            candidate = self._clean_to_digits_with_lookalikes(raw_candidate)
            if 15 <= len(candidate) <= 19:
                candidates.append(candidate)

            # 凸印卡号中单个字符可能被 OCR 识别为 ~、* 等符号。仅在 Luhn
            # 校验能唯一支持某个数字时，才将该符号还原为数字候选。
            repaired_candidates = set()
            for index, char in enumerate(raw_candidate):
                if char not in self.CARD_NUMBER_SEPARATOR_CHARS:
                    continue
                for digit in "0123456789":
                    repaired = self._clean_to_digits_with_lookalikes(
                        f"{raw_candidate[:index]}{digit}{raw_candidate[index + 1:]}"
                    )
                    if 15 <= len(repaired) <= 19 and self._luhn_valid(repaired):
                        repaired_candidates.add(repaired)
            if len(repaired_candidates) == 1:
                candidates.extend(repaired_candidates)
        return list(dict.fromkeys(candidates))

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

    def _extract_bank_name(
        self, layout: Layout, card_number: str
    ) -> Tuple[str, MatchSource, float]:
        all_lines = layout.all() or []

        for line in all_lines:
            row = layout.same_row(line, tolerance=max(15, min(35, line.height)))
            row_text = "".join((item.text or "").strip() for item in row)
            bank_name = self.catalog.find_bank_name(row_text)
            if bank_name:
                confidence = sum(item.score for item in row) / len(row)
                return bank_name, MatchSource.OCR_ALIAS, confidence

        for line in all_lines:
            text = (line.text or "").strip()
            if "银行" not in text or any(
                keyword in text for keyword in ("卡号", "账号", "电话", "热线", "客服", "号码")
            ):
                continue
            match = re.search(r"([A-Za-z\u4e00-\u9fff]*?银行)", text)
            if match:
                return match.group(), MatchSource.OCR_GENERIC, line.score * 0.8

        bin_rule = self.catalog.find_bin_rule(card_number)
        if bin_rule:
            return bin_rule.bank_name, MatchSource.BIN, 0.98
        return "", MatchSource.UNKNOWN, 0.0

    def _extract_card_type(
        self, layout: Layout, card_number: str
    ) -> Tuple[CardType, MatchSource, float]:
        all_lines = layout.all() or []
        for line in all_lines:
            row = layout.same_row(line, tolerance=max(15, min(35, line.height)))
            card_type = self.catalog.find_card_type(
                "".join((item.text or "").strip() for item in row)
            )
            if card_type != CardType.UNKNOWN:
                confidence = sum(item.score for item in row) / len(row)
                return card_type, MatchSource.CARD_FACE, confidence

        bin_rule = self.catalog.find_bin_rule(card_number)
        if bin_rule:
            return bin_rule.card_type, MatchSource.BIN, 0.98

        # 不能仅凭 16/19 位长度可靠判断借记卡或信用卡，未知时保留为空。
        return CardType.UNKNOWN, MatchSource.UNKNOWN, 0.0

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
        year_month_match = re.search(
            r"(?<!\d)((?:(?:19|20)\d{2}|\d{2}))\s*/\s*(0[1-9]|1[0-2])(?!\d)",
            normalized,
        )
        if year_month_match:
            return f"{year_month_match.group(2)}/{year_month_match.group(1)[-2:]}"
        match = re.search(
            r"(?<!\d)(0[1-9]|1[0-2])\s*/?\s*((?:(?:19|20)\d{2}|\d{2}))(?!\d)",
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
            "bank_name_source": MatchSource.UNKNOWN.value,
            "bank_name_confidence": 0.0,
            "card_number": "",
            "card_type": CardType.UNKNOWN.value,
            "card_type_source": MatchSource.UNKNOWN.value,
            "card_type_confidence": 0.0,
            "valid_date": "",
        }

        candidate = self._select_card_candidate(layout)
        card_number = candidate["number"] if candidate else ""
        card_line_ids = {
            id(item) for item in (candidate["items"] if candidate else [])
        }
        data["card_number"] = card_number
        bank_name, bank_name_source, bank_name_confidence = self._extract_bank_name(
            layout, card_number
        )
        card_type, card_type_source, card_type_confidence = self._extract_card_type(
            layout, card_number
        )
        data["bank_name"] = bank_name
        data["bank_name_source"] = bank_name_source.value
        data["bank_name_confidence"] = round(bank_name_confidence, 4)
        data["card_type"] = card_type.value
        data["card_type_source"] = card_type_source.value
        data["card_type_confidence"] = round(card_type_confidence, 4)
        data["valid_date"] = self._extract_valid_date(layout, card_line_ids)
        return data
