"""银行卡结构化字段使用的枚举。"""

from enum import Enum


class CardType(str, Enum):
    """银行卡种类，枚举值与 API 的既有返回值保持一致。"""

    DEBIT = "借记卡"
    CREDIT = "信用卡"
    UNKNOWN = ""


class MatchSource(str, Enum):
    """字段值的识别来源。"""

    OCR_ALIAS = "ocr_alias"
    OCR_GENERIC = "ocr_generic"
    CARD_FACE = "card_face"
    BIN = "bin"
    UNKNOWN = "unknown"
