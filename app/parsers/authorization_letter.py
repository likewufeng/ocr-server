"""授权委托书结构化解析器。

解析器只负责文本字段抽取。PDF 渲染、OCR、身份证附件及签章检测由
``AuthorizationLetterService`` 负责，避免把模型调用和业务规则混在一起。
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyPDF2 import PdfReader


class AuthorizationLetterParser:
    """从原生 PDF 文本或 OCR 文本中提取授权书字段。"""

    _ID_PATTERN = re.compile(r"(?<!\d)\d{17}[0-9Xx](?![0-9Xx])")
    _NAME_PATTERN = r"[\u3400-\u9fff·]{2,30}"

    def __init__(self, ocr_service=None):
        self.ocr_service = ocr_service

    @staticmethod
    def _normalize_text(text: str) -> str:
        text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
        text = text.replace("\u00a0", " ").replace("\u3000", " ")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _clean_value(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        value = re.sub(r"[_＿]+", " ", value)
        value = re.sub(r"\s+", " ", value)
        value = re.sub(r"(?<=[\u3400-\u9fff0-9])\s+(?=[\u3400-\u9fff0-9])", "", value)
        value = value.strip(" ：:，,。.;；()（）[]【】_-")
        return value or None

    @classmethod
    def _compact_id_numbers(cls, text: str) -> List[str]:
        compact = re.sub(r"[\s_＿]", "", text or "")
        values = []
        for match in cls._ID_PATTERN.finditer(compact):
            value = match.group(0).upper()
            if value not in values:
                values.append(value)
        return values

    @staticmethod
    def _format_date(year: str, month: str, day: str) -> Optional[str]:
        try:
            year_value = int(year)
            month_value = int(month)
            day_value = int(day)
        except (TypeError, ValueError):
            return None
        if not (1 <= month_value <= 12 and 1 <= day_value <= 31):
            return None
        return f"{year_value:04d}-{month_value:02d}-{day_value:02d}"

    @classmethod
    def _extract_validity_period(cls, text: str) -> Optional[Dict[str, str]]:
        pattern = re.compile(
            r"有效期限?自\D{0,20}(\d{4})\D{0,12}年\D{0,12}(\d{1,2})"
            r"\D{0,12}月\D{0,12}(\d{1,2})\D{0,12}日?起?至"
            r"\D{0,20}(\d{4})\D{0,12}年\D{0,12}(\d{1,2})"
            r"\D{0,12}月\D{0,12}(\d{1,2})\D{0,12}日",
            re.DOTALL,
        )
        match = pattern.search(text)
        if not match:
            return None
        start_date = cls._format_date(*match.groups()[:3])
        end_date = cls._format_date(*match.groups()[3:])
        if not start_date or not end_date:
            return None
        return {"start_date": start_date, "end_date": end_date}

    @classmethod
    def _extract_signing_date(cls, text: str) -> Optional[str]:
        match = re.search(
            r"签署日期\D{0,20}(\d{4})\D{0,12}年\D{0,12}(\d{1,2})"
            r"\D{0,12}月\D{0,12}(\d{1,2})\D{0,12}日",
            text,
            re.DOTALL,
        )
        return cls._format_date(*match.groups()) if match else None

    def extract_text_from_pdf(self, pdf_path: str) -> List[str]:
        """提取每页原生文本；扫描页返回空字符串。"""
        try:
            reader = PdfReader(pdf_path)
            return [(page.extract_text() or "") for page in reader.pages]
        except Exception as exc:
            raise ValueError(f"无法读取 PDF 文件: {exc}") from exc

    def parse_text_content(self, text: str) -> Dict[str, Any]:
        """解析正文文本，附件区域不会参与人员字段的兜底判断。"""
        normalized = self._normalize_text(text)
        main_text = re.split(
            r"附件\s*[:：]?\s*受托人身份证明文件|身份证复印件\s*[（(]正反面[）)]\s*粘贴处",
            normalized,
            maxsplit=1,
        )[0]

        result: Dict[str, Any] = {
            "delegator": None,
            "delegator_id": None,
            "delegator_address": None,
            "delegator_phone": None,
            "trustee": None,
            "trustee_id": None,
            "validity_period": None,
            "signing_date": None,
        }

        delegator_match = re.search(
            rf"委托人(?!因|办理)(?:\s*[（(][^）)]*[）)])?\s*[:：]?\s*[_＿\s]*"
            rf"({self._NAME_PATTERN})",
            main_text,
        )
        if delegator_match:
            result["delegator"] = self._clean_value(delegator_match.group(1))

        trustee_match = re.search(
            rf"兹委托受托人\s*[:：]?\s*[_＿\s]*({self._NAME_PATTERN})"
            r"(?=\s*[（(]|\s*身份证|\s*$)",
            main_text,
            re.DOTALL,
        )
        if not trustee_match:
            trustee_match = re.search(
                rf"受托人(?!身份证|证明)(?:\s*[（(]签字[）)])?\s*[:：]\s*"
                rf"[_＿\s]*({self._NAME_PATTERN})",
                main_text,
            )
        if trustee_match:
            result["trustee"] = self._clean_value(trustee_match.group(1))

        delegator_id_match = re.search(
            r"身份证(?:号码|号)\s*[:：]?\s*[_＿\s]*"
            r"((?:\d[\s_＿]*){17}[0-9Xx])",
            main_text,
        )
        if delegator_id_match:
            result["delegator_id"] = re.sub(
                r"[\s_＿]", "", delegator_id_match.group(1)
            ).upper()

        trustee_id_match = re.search(
            r"兹委托受托人.*?[（(]\s*身份证(?:号码|号)\s*[:：]?\s*"
            r"((?:\d[\s_＿]*){17}[0-9Xx])",
            main_text,
            re.DOTALL,
        )
        if trustee_id_match:
            result["trustee_id"] = re.sub(
                r"[\s_＿]", "", trustee_id_match.group(1)
            ).upper()

        all_ids = self._compact_id_numbers(main_text)
        if not result["delegator_id"] and all_ids:
            result["delegator_id"] = all_ids[0]
        if not result["trustee_id"]:
            result["trustee_id"] = next(
                (value for value in all_ids if value != result["delegator_id"]),
                None,
            )

        address_match = re.search(
            r"住址\s*[:：]?\s*[_＿\s]*(.+?)(?=\n\s*(?:联系电话|鉴于)\s*[:：]?)",
            main_text,
            re.DOTALL,
        )
        if address_match:
            result["delegator_address"] = self._clean_value(address_match.group(1))

        phone_match = re.search(
            r"联系电话\s*[:：]?\s*[_＿\s]*([0-9][0-9\s-]{6,20})",
            main_text,
        )
        if phone_match:
            result["delegator_phone"] = re.sub(r"\D", "", phone_match.group(1))

        result["validity_period"] = self._extract_validity_period(main_text)
        result["signing_date"] = self._extract_signing_date(normalized)
        return self.postprocess_result(result)

    def parse_pdf(self, pdf_path: str) -> Dict[str, Any]:
        """兼容旧调用：仅做原生文本抽取，不执行 OCR。"""
        page_texts = self.extract_text_from_pdf(pdf_path)
        parsed = self.parse_text_content("\n".join(page_texts))
        parsed.update(
            {
                "pages": page_texts,
                "raw_text": "\n".join(page_texts),
                "source": "native_pdf_text",
            }
        )
        return parsed

    def postprocess_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        for key in ("delegator", "trustee", "delegator_address"):
            if result.get(key):
                result[key] = self._clean_value(str(result[key]))
        for key in ("delegator_id", "trustee_id"):
            if result.get(key):
                result[key] = re.sub(r"\s+", "", str(result[key])).upper()
        return result

    def to_dict(
        self,
        result: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """生成稳定的授权书接口结构，并允许服务层追加检测证据。"""
        data = {
            "type": "authorization_letter",
            "delegator": result.get("delegator"),
            "delegator_id": result.get("delegator_id"),
            "delegator_address": result.get("delegator_address"),
            "delegator_phone": result.get("delegator_phone"),
            "trustee": result.get("trustee"),
            "trustee_id": result.get("trustee_id"),
            "validity_period": result.get("validity_period"),
            "signing_date": result.get("signing_date"),
            "delegator_signature": result.get("delegator_signature"),
            "trustee_signature": result.get("trustee_signature"),
            "trustee_id_front": result.get("trustee_id_front"),
            "trustee_id_back": result.get("trustee_id_back"),
        }
        response_metadata = {
            "pages_count": len(result.get("pages", [])),
            "source": result.get("source", "text"),
        }
        if metadata:
            response_metadata.update(metadata)
        return {"status": "success", "data": data, "metadata": response_metadata}


def is_pdf_path(path: str) -> bool:
    return Path(path).suffix.lower() == ".pdf"
