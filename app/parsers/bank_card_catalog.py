"""可配置的银行名称、卡种文案与 BIN/IIN 数据目录。"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

from app.schemas.bank_card import CardType


@dataclass(frozen=True)
class BinRule:
    """单条 BIN/IIN 规则。"""

    bank_name: str
    card_type: CardType


class BankCardCatalog:
    """加载本地 JSON 数据，避免把银行和 BIN 规则硬编码到解析器。"""

    def __init__(
        self,
        bank_aliases: Dict[str, str],
        bin_rules: Dict[str, BinRule],
        card_type_aliases: Dict[CardType, Tuple[str, ...]],
    ) -> None:
        self._bank_aliases = dict(
            sorted(bank_aliases.items(), key=lambda item: len(item[0]), reverse=True)
        )
        self._bin_rules = dict(
            sorted(bin_rules.items(), key=lambda item: len(item[0]), reverse=True)
        )
        self._card_type_aliases = card_type_aliases

    @staticmethod
    def normalize(text: str) -> str:
        """统一大小写并删除空白，适配 OCR 对英文单词的分框结果。"""
        return re.sub(r"\s+", "", (text or "").upper())

    @staticmethod
    def _parse_card_type(value: str) -> CardType:
        normalized = (value or "").strip().upper()
        external_types = {
            "DEBIT": CardType.DEBIT,
            "CREDIT": CardType.CREDIT,
        }
        if normalized in external_types:
            return external_types[normalized]
        return CardType((value or "").strip())

    @classmethod
    def load(cls, path: Path, iin_path: Optional[Path] = None) -> "BankCardCatalog":
        try:
            with path.open("r", encoding="utf-8") as catalog_file:
                raw = json.load(catalog_file)
        except FileNotFoundError as exc:
            raise RuntimeError(f"Bank card catalog does not exist: {path}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid bank card catalog JSON: {path}") from exc

        banks = raw.get("banks")
        bin_rules = raw.get("bin_rules")
        card_type_aliases = raw.get("card_type_aliases")
        if not isinstance(banks, list) or not isinstance(bin_rules, list):
            raise RuntimeError("Bank card catalog requires banks and bin_rules lists")
        if not isinstance(card_type_aliases, dict):
            raise RuntimeError("Bank card catalog requires card_type_aliases object")

        aliases: Dict[str, str] = {}
        for bank in banks:
            name = str(bank.get("name", "")).strip()
            values: Iterable[str] = bank.get("aliases", [])
            if not name or not isinstance(values, list):
                raise RuntimeError("Each bank catalog entry requires name and aliases")
            for alias in [name, *values]:
                normalized_alias = cls.normalize(str(alias))
                if normalized_alias:
                    aliases[normalized_alias] = name

        parsed_bin_rules: Dict[str, BinRule] = {}
        for rule in bin_rules:
            prefix = str(rule.get("prefix", "")).strip()
            bank_name = str(rule.get("bank_name", "")).strip()
            card_type = str(rule.get("card_type", "")).strip()
            if not re.fullmatch(r"\d{6,8}", prefix) or not bank_name:
                raise RuntimeError(f"Invalid bank card BIN rule: {rule}")
            try:
                parsed_card_type = cls._parse_card_type(card_type)
            except ValueError as exc:
                raise RuntimeError(f"Invalid card type in BIN rule: {rule}") from exc
            if prefix in parsed_bin_rules:
                raise RuntimeError(f"Duplicate bank card BIN prefix: {prefix}")
            parsed_bin_rules[prefix] = BinRule(bank_name, parsed_card_type)

        # 外部 IIN 数据作为补充，主目录中的人工校准规则优先级更高。
        if iin_path is not None:
            try:
                with iin_path.open("r", encoding="utf-8") as iin_file:
                    iin_raw = json.load(iin_file)
            except FileNotFoundError as exc:
                raise RuntimeError(f"Bank card IIN catalog does not exist: {iin_path}") from exc
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Invalid bank card IIN catalog JSON: {iin_path}") from exc

            records = iin_raw.get("records")
            if not isinstance(records, list):
                raise RuntimeError("Bank card IIN catalog requires a records list")
            for record in records:
                prefix = str(record.get("prefix", "")).strip()
                bank_name = str(record.get("bank_name", "")).strip()
                card_type = str(record.get("card_type", "")).strip()
                if not re.fullmatch(r"\d{6,8}", prefix) or not bank_name:
                    raise RuntimeError(f"Invalid bank card IIN record: {record}")
                try:
                    parsed_card_type = cls._parse_card_type(card_type)
                except ValueError as exc:
                    raise RuntimeError(f"Invalid card type in IIN record: {record}") from exc
                parsed_bin_rules.setdefault(prefix, BinRule(bank_name, parsed_card_type))

        parsed_card_type_aliases: Dict[CardType, Tuple[str, ...]] = {}
        for raw_card_type, values in card_type_aliases.items():
            try:
                card_type = CardType(raw_card_type)
            except ValueError as exc:
                raise RuntimeError(f"Invalid card type alias group: {raw_card_type}") from exc
            if card_type == CardType.UNKNOWN or not isinstance(values, list):
                raise RuntimeError(f"Invalid card type aliases: {raw_card_type}")
            parsed_card_type_aliases[card_type] = tuple(
                cls.normalize(str(value)) for value in values if cls.normalize(str(value))
            )

        return cls(aliases, parsed_bin_rules, parsed_card_type_aliases)

    def find_bank_name(self, text: str) -> str:
        normalized_text = self.normalize(text)
        for alias, bank_name in self._bank_aliases.items():
            if alias in normalized_text:
                return bank_name
        return ""

    def find_card_type(self, text: str) -> CardType:
        normalized_text = self.normalize(text)
        for card_type, aliases in self._card_type_aliases.items():
            if any(alias in normalized_text for alias in aliases):
                return card_type
        return CardType.UNKNOWN

    def find_bin_rule(self, card_number: str) -> Optional[BinRule]:
        for prefix, rule in self._bin_rules.items():
            if card_number.startswith(prefix):
                canonical_name = self.find_bank_name(rule.bank_name) or rule.bank_name
                return BinRule(canonical_name, rule.card_type)
        return None
