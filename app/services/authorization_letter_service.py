"""授权委托书的混合 PDF、图片识别服务。"""

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import fitz
import numpy as np

from app.config import (
    AUTHORIZATION_NATIVE_TEXT_MIN_CHARS,
    AUTHORIZATION_OCR_MIN_SCORE,
    AUTHORIZATION_RENDER_DPI,
    OCR_DEVICE,
    OCR_MODEL_PROFILE,
    OCR_MODEL_VERSION,
)
from app.parsers.authorization_letter import AuthorizationLetterParser
from app.parsers.parser import OCRParser
from app.services.ocr_service import ocr_service
from app.utils.layout import build_layout
from app.utils.logger import logger


class AuthorizationLetterService:
    """按页选择原生文本、PP-OCRv6 和证件局部 OCR。"""

    _FRONT_KEYWORDS = ("姓名", "性别", "民族", "出生", "住址", "公民身份号码")
    _BACK_KEYWORDS = ("中华人民共和国", "居民身份证", "签发机关", "有效期限")

    def __init__(self) -> None:
        self.text_parser = AuthorizationLetterParser(ocr_service=ocr_service)
        self.ocr_parser = OCRParser()

    @staticmethod
    def _save_json(path: Path, value: Any) -> None:
        with path.open("w", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False, indent=2)

    @staticmethod
    def _write_image(path: Path, image: np.ndarray) -> None:
        if image.size == 0 or not cv2.imwrite(str(path), image):
            raise ValueError(f"无法保存排查图片: {path.name}")

    @staticmethod
    def _image_signals(image: np.ndarray) -> Dict[str, float]:
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        return {
            "saturated_ratio": float(np.mean(hsv[:, :, 1] > 30)),
            "dark_ratio": float(np.mean(gray < 180)),
        }

    @staticmethod
    def _classify_ocr_text(texts: List[str]) -> Optional[str]:
        joined = "".join(texts)
        front_score = sum(keyword in joined for keyword in AuthorizationLetterService._FRONT_KEYWORDS)
        back_score = sum(keyword in joined for keyword in AuthorizationLetterService._BACK_KEYWORDS)
        if back_score >= 2 and back_score >= front_score:
            return "id_back"
        if front_score >= 2 or (
            re.search(r"\d{17}[0-9Xx]", joined) and ("姓名" in joined or "住址" in joined)
        ):
            return "id_front"
        return None

    @staticmethod
    def _attachment_rank(attachment: Dict[str, Any]) -> Tuple[int, float]:
        data = attachment.get("data") or {}
        populated = sum(bool(value) for key, value in data.items() if key != "type")
        return populated, float(attachment.get("ocr_confidence") or 0.0)

    async def _recognize(
        self,
        image_path: Path,
        request_id: str,
        output_dir: Path,
        document_type: Optional[str] = None,
        auto_orientation: bool = True,
    ) -> Dict[str, Any]:
        return await asyncio.wrap_future(
            ocr_service.submit_recognize(
                str(image_path),
                min_score=AUTHORIZATION_OCR_MIN_SCORE,
                request_id=request_id,
                output_dir=output_dir,
                document_type=document_type,
                auto_orientation=auto_orientation,
            )
        )

    async def _recognize_attachment(
        self,
        image_path: Path,
        page_number: int,
        region: List[int],
        request_id: str,
        output_dir: Path,
        document_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        ocr_result = await self._recognize(
            image_path, request_id, output_dir, document_type=document_type
        )
        document_type = document_type or self._classify_ocr_text(
            ocr_result.get("texts") or []
        )
        if document_type not in {"id_front", "id_back"}:
            return None

        document = self.ocr_parser.parse(
            build_layout(ocr_result), document_type=document_type
        )
        confidence_values = ocr_result.get("scores") or []
        attachment = {
            "status": "detected",
            "page_number": page_number,
            "region": region,
            "data": document,
            "ocr_confidence": round(
                float(sum(confidence_values) / len(confidence_values)), 4
            )
            if confidence_values
            else 0.0,
            "manual_review_required": True,
            "note": "身份证字段已自动识别，证件真实性和复印件有效性仍需人工核验。",
        }
        self._save_json(
            output_dir / f"page_{page_number:03d}_{document_type}_ocr.json",
            ocr_result,
        )
        return attachment

    @staticmethod
    def _id_side_boxes(
        ocr_result: Dict[str, Any], document_type: str
    ) -> List[List[int]]:
        keywords = (
            AuthorizationLetterService._FRONT_KEYWORDS
            if document_type == "id_front"
            else AuthorizationLetterService._BACK_KEYWORDS
        )
        selected = []
        for text, box in zip(
            ocr_result.get("texts") or [], ocr_result.get("boxes") or []
        ):
            compact_text = re.sub(r"\s+", "", text or "")
            if any(keyword in compact_text for keyword in keywords) or (
                document_type == "id_front"
                and re.search(r"\d{17}[0-9Xx]", compact_text)
            ):
                selected.append([int(value) for value in box])
        return selected

    @classmethod
    def _crop_id_region(
        cls,
        image: np.ndarray, ocr_result: Dict[str, Any], document_type: str
    ) -> Optional[Tuple[np.ndarray, List[int]]]:
        selected = cls._id_side_boxes(ocr_result, document_type)
        if len(selected) < 2:
            return None

        height, width = image.shape[:2]
        left = min(box[0] for box in selected)
        top = min(box[1] for box in selected)
        right = max(box[2] for box in selected)
        bottom = max(box[3] for box in selected)
        content_width = max(1, right - left)
        content_height = max(1, bottom - top)
        left -= int(content_width * 0.18)
        right += int(content_width * 0.18)
        top -= int(content_height * 0.45)
        bottom += int(content_height * 0.35)

        target_ratio = 1.58
        crop_width = right - left
        crop_height = bottom - top
        if crop_width / max(1, crop_height) < target_ratio:
            extra = int((crop_height * target_ratio - crop_width) / 2)
            left -= extra
            right += extra
        else:
            extra = int((crop_width / target_ratio - crop_height) / 2)
            top -= extra
            bottom += extra

        left = max(0, left)
        top = max(0, top)
        right = min(width, right)
        bottom = min(height, bottom)
        if right - left < 160 or bottom - top < 100:
            return None
        return image[top:bottom, left:right], [left, top, right, bottom]

    @classmethod
    def _split_id_regions(
        cls, image: np.ndarray, ocr_result: Dict[str, Any]
    ) -> Dict[str, Tuple[np.ndarray, List[int]]]:
        """Locate front and back independently on a page containing both sides."""
        crops = {}
        for document_type in ("id_front", "id_back"):
            crop_result = cls._crop_id_region(image, ocr_result, document_type)
            if crop_result is not None:
                crops[document_type] = crop_result

        # A page with both sets of keywords must result in two independently
        # cropped cards. Never use the full page as an id_front fallback.
        if len(crops) == 2:
            front_boxes = cls._id_side_boxes(ocr_result, "id_front")
            back_boxes = cls._id_side_boxes(ocr_result, "id_back")
            front_center_x = sum((box[0] + box[2]) / 2 for box in front_boxes) / len(
                front_boxes
            )
            back_center_x = sum((box[0] + box[2]) / 2 for box in back_boxes) / len(
                back_boxes
            )
            front_center_y = sum((box[1] + box[3]) / 2 for box in front_boxes) / len(
                front_boxes
            )
            back_center_y = sum((box[1] + box[3]) / 2 for box in back_boxes) / len(
                back_boxes
            )

            # Aspect-ratio expansion in _crop_id_region is useful for a single
            # card, but can make two horizontally adjacent cards overlap. Split
            # at the midpoint between their text evidence and rebuild the crops.
            if abs(front_center_x - back_center_x) > abs(front_center_y - back_center_y):
                divider = int((front_center_x + back_center_x) / 2)
                front_crop, front_region = crops["id_front"]
                back_crop, back_region = crops["id_back"]
                if front_center_x < back_center_x:
                    front_region[2] = min(front_region[2], divider - 1)
                    back_region[0] = max(back_region[0], divider + 1)
                else:
                    back_region[2] = min(back_region[2], divider - 1)
                    front_region[0] = max(front_region[0], divider + 1)

                for document_type, region in (
                    ("id_front", front_region),
                    ("id_back", back_region),
                ):
                    left, top, right, bottom = region
                    if right - left < 160 or bottom - top < 100:
                        return {}
                    crops[document_type] = (image[top:bottom, left:right], region)
            return crops
        return {}

    @staticmethod
    def _signature_from_region(
        image: np.ndarray,
        page_number: int,
        region: List[int],
        source: str,
    ) -> Dict[str, Any]:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        binary = (gray < 155).astype(np.uint8) * 255
        horizontal_size = max(20, binary.shape[1] // 6)
        horizontal = cv2.morphologyEx(
            binary,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (horizontal_size, 1)),
        )
        handwriting = cv2.subtract(binary, horizontal)
        count, _, stats, _ = cv2.connectedComponentsWithStats(handwriting, 8)
        components = [
            item for item in stats[1:] if item[4] >= 8 and item[2] >= 2 and item[3] >= 3
        ]
        ink_pixels = int(np.count_nonzero(handwriting))
        density = ink_pixels / max(1, handwriting.size)
        max_height = max((int(item[3]) for item in components), default=0)
        detected = bool(
            ink_pixels >= max(45, int(handwriting.size * 0.0015))
            and max_height >= max(8, int(handwriting.shape[0] * 0.12))
        )
        confidence = min(0.99, 0.45 + density * 20 + min(max_height / 80, 0.3))
        if not detected:
            confidence = min(0.9, 0.35 + max(0.0, 0.02 - density) * 5)
        return {
            "status": "detected" if detected else "not_detected",
            "confidence": round(float(confidence), 4),
            "page_number": page_number,
            "region": region,
            "source": source,
            "manual_review_required": True,
            "note": "仅检测签名笔迹是否存在，不验证签名人身份或签名真伪。",
        }

    @classmethod
    def _signature_near_pdf_label(
        cls,
        page: fitz.Page,
        page_image: np.ndarray,
        scale: float,
        role: str,
        page_number: int,
    ) -> Optional[Dict[str, Any]]:
        phrases = (
            (
                "委托人（签名/摁手印）：",
                "委托人（签名/摁手印）",
                "委托人（签名",
                "委托人 (签名",
            )
            if role == "delegator"
            else (
                "受托人（签字）：",
                "受托人（签字）",
                "受托人 (签字",
                "受托人（签字",
            )
        )
        rects: List[fitz.Rect] = []
        for phrase in phrases:
            rects.extend(page.search_for(phrase))
        if not rects:
            return None
        anchor_top = min(rect.y0 for rect in rects)
        anchor_right = max(rect.x1 for rect in rects)
        anchor_bottom = max(rect.y1 for rect in rects)
        height, width = page_image.shape[:2]
        left = min(
            width - 1,
            max(0, int(anchor_right * scale) + int(width * 0.06)),
        )
        top = max(0, int(anchor_top * scale) - 55)
        right = min(width, left + int(width * 0.48))
        bottom = min(height, int(anchor_bottom * scale) + 10)
        if right - left < 30 or bottom - top < 20:
            return None
        region = [left, top, right, bottom]
        return cls._signature_from_region(
            page_image[top:bottom, left:right],
            page_number,
            region,
            source="label_region",
        )

    @staticmethod
    def _nearest_signature_role(
        page: fitz.Page,
        region: List[int],
        scale: float,
    ) -> str:
        center_y = (region[1] + region[3]) / 2
        labels = {
            "delegator": ("委托人（签名", "委托人 (签名"),
            "trustee": ("受托人（签字", "受托人 (签字"),
        }
        distances = {}
        for role, phrases in labels.items():
            rects = []
            for phrase in phrases:
                rects.extend(page.search_for(phrase))
            if rects:
                label_y = sum(
                    ((rect.y0 + rect.y1) / 2) * scale for rect in rects
                ) / len(rects)
                distances[role] = abs(center_y - label_y)
        return min(distances, key=distances.get) if distances else "trustee"

    @classmethod
    def _signature_near_ocr_label(
        cls,
        page_image: np.ndarray,
        ocr_result: Dict[str, Any],
        role: str,
        page_number: int,
    ) -> Optional[Dict[str, Any]]:
        role_text = "委托人" if role == "delegator" else "受托人"
        candidates = []
        for text, box in zip(
            ocr_result.get("texts") or [], ocr_result.get("boxes") or []
        ):
            if role_text in text and ("签" in text or "手印" in text):
                candidates.append([int(value) for value in box])
        if not candidates:
            return None
        anchor = candidates[0]
        height, width = page_image.shape[:2]
        left = min(width - 1, max(0, anchor[2] + int(width * 0.04)))
        top = max(0, anchor[1] - 55)
        right = min(width, left + int(width * 0.48))
        bottom = min(height, anchor[3] + 25)
        if right - left < 30 or bottom - top < 20:
            return None
        region = [left, top, right, bottom]
        return cls._signature_from_region(
            page_image[top:bottom, left:right],
            page_number,
            region,
            source="ocr_label_region",
        )

    @staticmethod
    def _signature_from_template_region(
        page_image: np.ndarray, role: str, page_number: int
    ) -> Dict[str, Any]:
        """Use the stable personal-authorization template instead of an OCR box."""
        height, width = page_image.shape[:2]
        if role == "delegator":
            left, top, right, bottom = (
                int(width * 0.35),
                int(height * 0.64),
                int(width * 0.80),
                int(height * 0.73),
            )
        else:
            left, top, right, bottom = (
                int(width * 0.30),
                int(height * 0.70),
                int(width * 0.73),
                int(height * 0.79),
            )
        region = [left, top, right, bottom]
        return AuthorizationLetterService._signature_from_region(
            page_image[top:bottom, left:right],
            page_number,
            region,
            source="template_signature_region",
        )

    @staticmethod
    def _is_valid_id_number(value: str) -> bool:
        normalized = re.sub(r"\s+", "", value or "").upper()
        if not re.fullmatch(r"\d{17}[0-9X]", normalized):
            return False
        weights = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
        check_codes = "10X98765432"
        checksum = sum(
            int(digit) * weight
            for digit, weight in zip(normalized[:17], weights)
        )
        return normalized[-1] == check_codes[checksum % 11]

    @staticmethod
    def _is_plausible_person_name(value: Optional[str]) -> bool:
        candidate = re.sub(r"\s+", "", value or "")
        if not re.fullmatch(r"[\u3400-\u9fff·]{2,8}", candidate):
            return False
        disallowed = (
            "委托人", "受托人", "授权", "代理", "身份证", "办理", "相关", "事项",
            "地址", "电话", "日期", "托人", "身份", "需要", "业务",
        )
        return not any(token in candidate for token in disallowed)

    @classmethod
    def _role_name_from_text(cls, text: str, role: str) -> str:
        compact = re.sub(r"\s+", "", text or "")
        if role == "delegator":
            match = re.search(
                r"委托人[：:]*([^：:]{2,12}?)(?=身份证|住址|联系电话|因办理|$)",
                compact,
            )
        else:
            match = re.search(
                r"受托人[：:]*([^：:]{1,12}?)(?=身份证|身份|证号|作为|办理|$)",
                compact,
            )
        if not match:
            return ""
        value = re.sub(r"[^\u3400-\u9fff·]", "", match.group(1))
        if cls._is_plausible_person_name(value):
            return value
        return ""

    @classmethod
    def _should_recover_form_fields(
        cls, page_image: np.ndarray, ocr_result: Dict[str, Any], parsed: Dict[str, Any]
    ) -> bool:
        joined = "".join(ocr_result.get("texts") or [])
        if "授权委托书" not in joined or "委托人" not in joined:
            return False
        if not cls._is_plausible_person_name(parsed.get("delegator")):
            return True
        if not cls._is_plausible_person_name(parsed.get("trustee")):
            return True
        if not cls._is_valid_id_number(parsed.get("delegator_id") or ""):
            return True
        if not cls._is_valid_id_number(parsed.get("trustee_id") or ""):
            return True

        height, width = page_image.shape[:2]
        for score, box in zip(
            ocr_result.get("scores") or [], ocr_result.get("boxes") or []
        ):
            if (
                float(score) < 0.96
                and int(box[1]) < int(height * 0.40)
                and int(box[2]) - int(box[0]) > int(width * 0.20)
            ):
                return True
        return False

    @staticmethod
    def _template_field_regions(image: np.ndarray) -> Dict[str, List[int]]:
        """Return normalized field regions for the supplied personal-letter template."""
        height, width = image.shape[:2]

        def box(left, top, right, bottom):
            return [
                int(width * left),
                int(height * top),
                int(width * right),
                int(height * bottom),
            ]

        return {
            "delegator": box(0.25, 0.09, 0.63, 0.17),
            "delegator_id": box(0.27, 0.14, 0.67, 0.22),
            "delegator_address": box(0.20, 0.17, 0.90, 0.25),
            "delegator_phone": box(0.25, 0.20, 0.67, 0.28),
            "trustee": box(0.66, 0.25, 0.88, 0.34),
            "trustee_id": box(0.18, 0.29, 0.78, 0.37),
            "validity_period": box(0.45, 0.55, 0.95, 0.66),
            "signing_date": box(0.24, 0.72, 0.80, 0.81),
        }

    @classmethod
    def _ocr_field_regions(
        cls, image: np.ndarray, ocr_result: Dict[str, Any]
    ) -> Dict[str, List[int]]:
        """Locate form fields from OCR lines, with normalized template fallbacks.

        The handwritten sample has large, slanted OCR boxes. Using those boxes
        keeps the title and neighboring paragraphs out of the second OCR pass.
        The template coordinates remain a fallback for fields whose label was
        not detected.
        """
        height, width = image.shape[:2]
        fallback = cls._template_field_regions(image)
        items = []
        for text, box in zip(
            ocr_result.get("texts") or [], ocr_result.get("boxes") or []
        ):
            if len(box) < 4:
                continue
            left, top, right, bottom = [int(value) for value in box[:4]]
            if right <= left or bottom <= top:
                continue
            items.append(
                {
                    "text": re.sub(r"\s+", "", text or ""),
                    "box": [
                        max(0, left),
                        max(0, top),
                        min(width, right),
                        min(height, bottom),
                    ],
                }
            )

        def padded(region: List[int], x_pad: float = 0.02, y_pad: float = 0.18):
            left, top, right, bottom = region
            x = max(8, int((right - left) * x_pad))
            y = max(8, int((bottom - top) * y_pad))
            return [
                max(0, left - x),
                max(0, top - y),
                min(width, right + x),
                min(height, bottom + y),
            ]

        def first(predicate, max_top=0.45, min_top=0.0):
            matches = [
                item
                for item in items
                if predicate(item["text"])
                and item["box"][1] < int(height * max_top)
                and item["box"][1] >= int(height * min_top)
            ]
            return min(matches, key=lambda item: item["box"][1]) if matches else None

        regions = dict(fallback)
        line_matches = {
            "delegator": first(
                lambda text: "委托人" in text and "因" not in text,
                0.25,
            ),
            "delegator_id": first(
                lambda text: "身份证号码" in text or "身份证号" in text,
                0.25,
            ),
            "delegator_address": first(lambda text: "住址" in text, 0.30),
            "delegator_phone": first(lambda text: "联系电话" in text, 0.32),
            "trustee": first(
                lambda text: "兹委托受托人" in text or "受托人" in text,
                0.48,
            ),
            "trustee_id": first(
                lambda text: bool(re.search(r"\d{15,18}", text)),
                0.48,
                0.25,
            ),
            "signing_date": first(lambda text: "签署日期" in text, 0.90),
        }
        for field, item in line_matches.items():
            if item:
                regions[field] = padded(item["box"])

        validity_items = [
            item
            for item in items
            if ("有效期限" in item["text"] or "期限自" in item["text"])
            and item["box"][1] > int(height * 0.45)
        ]
        if validity_items:
            selected = list(validity_items)
            anchor_bottom = max(item["box"][3] for item in selected)
            # The handwritten end day is often detected as a separate line.
            for item in items:
                box = item["box"]
                if anchor_bottom <= box[1] <= anchor_bottom + int(height * 0.08):
                    selected.append(item)
            regions["validity_period"] = padded(
                [
                    min(item["box"][0] for item in selected),
                    min(item["box"][1] for item in selected),
                    max(item["box"][2] for item in selected),
                    max(item["box"][3] for item in selected),
                ],
                x_pad=0.02,
                y_pad=0.12,
            )
        return regions

    @staticmethod
    def _first_person_name(text: str) -> str:
        compact = re.sub(r"\s+", "", text or "")
        compact = re.sub(
            r"(授权委托书|委托人|受托人|托人|身份证号码|身份证号|身份证|号码|身份|住址|联系电话|签署日期|授权代理人|代理人)",
            "",
            compact,
        )
        candidates = re.findall(r"[\u3400-\u9fff·]{2,8}", compact)
        return next(
            (
                candidate
                for candidate in candidates
                if AuthorizationLetterService._is_plausible_person_name(candidate)
            ),
            "",
        )

    @classmethod
    def _field_value_from_ocr(cls, field: str, texts: List[str]) -> Any:
        compact = re.sub(r"\s+", "", "".join(texts or []))
        if field in {"delegator", "trustee"}:
            return cls._role_name_from_text(compact, field)
        if field in {"delegator_id", "trustee_id"}:
            matches = re.findall(r"\d{17}[0-9Xx]", compact)
            return next(
                (value.upper() for value in matches if cls._is_valid_id_number(value)),
                "",
            )
        if field == "delegator_phone":
            match = re.search(r"1[3-9]\d{9}", compact)
            return match.group(0) if match else ""
        if field == "delegator_address":
            address_match = re.search(
                r"(?:住址|地址)[:：]?(.+?)(?=身份证|联系电话|电话|委托人|$)",
                compact,
            )
            value = address_match.group(1) if address_match else compact
            if any(label in value for label in ("身份证", "联系电话", "电话", "委托人")):
                return ""
            return value if len(value) >= 6 else ""
        if field == "validity_period":
            match = re.search(
                r"(\d{4})年(\d{1,2})月(\d{1,2})日.*?(\d{4})年(\d{1,2})月(\d{1,2})日",
                compact,
            )
            if match:
                start = "-".join(
                    (match.group(1), match.group(2).zfill(2), match.group(3).zfill(2))
                )
                end = "-".join(
                    (match.group(4), match.group(5).zfill(2), match.group(6).zfill(2))
                )
                return {"start_date": start, "end_date": end}
            return None
        if field == "signing_date":
            match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", compact)
            if match:
                return "-".join(
                    (match.group(1), match.group(2).zfill(2), match.group(3).zfill(2))
                )
            return ""
        return ""

    @staticmethod
    def _remove_form_lines(image: np.ndarray) -> np.ndarray:
        """Remove long template rules while retaining handwriting strokes."""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        inverted = cv2.threshold(
            gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
        )[1]
        kernel_width = max(24, image.shape[1] // 7)
        horizontal = cv2.morphologyEx(
            inverted,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_width, 1)),
        )
        cleaned = gray.copy()
        cleaned[horizontal > 0] = 255
        return cv2.cvtColor(cleaned, cv2.COLOR_GRAY2BGR)

    @staticmethod
    def _field_needs_variant(field: str, value: Any, ocr_result: Dict[str, Any]) -> bool:
        scores = ocr_result.get("scores") or []
        average_score = float(sum(scores) / len(scores)) if scores else 0.0
        if field in {"delegator", "trustee"}:
            return (
                not AuthorizationLetterService._is_plausible_person_name(value)
                or average_score < 0.95
            )
        if field in {"delegator_id", "trustee_id"}:
            compact = re.sub(r"\s+", "", "".join(ocr_result.get("texts") or []))
            return not any(
                AuthorizationLetterService._is_valid_id_number(match)
                for match in re.findall(r"\d{17}[0-9Xx]", compact)
            )
        if field == "delegator_address":
            return not bool(value) or average_score < 0.95
        if field == "validity_period":
            return not bool(value) or average_score < 0.95
        if field == "signing_date":
            return not bool(value) or average_score < 0.95
        return False

    async def _recover_form_fields(
        self,
        image: np.ndarray,
        page_number: int,
        request_id: str,
        output_dir: Path,
        page_ocr: Dict[str, Any],
    ) -> Dict[str, Any]:
        recovered: Dict[str, Any] = {"attempted": True, "page_number": page_number, "fields": {}}
        for field, region in self._ocr_field_regions(image, page_ocr).items():
            left, top, right, bottom = region
            crop = image[top:bottom, left:right]
            if crop.size == 0:
                continue
            enlarged = cv2.resize(
                crop, None, fx=1.75, fy=1.75, interpolation=cv2.INTER_CUBIC
            )
            crop_path = output_dir / f"page_{page_number:03d}_{field}_roi.jpg"
            self._write_image(crop_path, enlarged)
            ocr_result = await self._recognize(
                crop_path,
                request_id,
                output_dir,
                document_type=None,
                auto_orientation=False,
            )
            self._save_json(
                output_dir / f"page_{page_number:03d}_{field}_roi_ocr.json",
                ocr_result,
            )
            candidates = [("original", crop_path.name, ocr_result)]
            value = self._field_value_from_ocr(field, ocr_result.get("texts") or [])
            if self._field_needs_variant(field, value, ocr_result):
                variant = self._remove_form_lines(crop)
                variant = cv2.resize(
                    variant, None, fx=1.75, fy=1.75, interpolation=cv2.INTER_CUBIC
                )
                variant_path = output_dir / f"page_{page_number:03d}_{field}_roi_clean.jpg"
                self._write_image(variant_path, variant)
                variant_ocr = await self._recognize(
                    variant_path,
                    request_id,
                    output_dir,
                    document_type=None,
                    auto_orientation=False,
                )
                self._save_json(
                    output_dir / f"page_{page_number:03d}_{field}_roi_clean_ocr.json",
                    variant_ocr,
                )
                candidates.append(("line_removed", variant_path.name, variant_ocr))

            def candidate_value(candidate_ocr: Dict[str, Any]) -> Any:
                return self._field_value_from_ocr(
                    field, candidate_ocr.get("texts") or []
                )

            valid_candidates = []
            for source, artifact, candidate_ocr in candidates:
                candidate = candidate_value(candidate_ocr)
                raw_candidate = candidate
                if field in {"delegator_id", "trustee_id"}:
                    raw_matches = re.findall(
                        r"\d{17}[0-9Xx]",
                        re.sub(
                            r"\s+", "", "".join(candidate_ocr.get("texts") or [])
                        ),
                    )
                    raw_candidate = raw_matches[0].upper() if raw_matches else ""
                score_values = candidate_ocr.get("scores") or []
                avg_score = (
                    float(sum(score_values) / len(score_values))
                    if score_values
                    else 0.0
                )
                valid_candidates.append(
                    {
                        "source": source,
                        "artifact": artifact,
                        "value": raw_candidate,
                        "checksum_valid": bool(
                            field in {"delegator_id", "trustee_id"}
                            and raw_candidate
                            and self._is_valid_id_number(raw_candidate)
                        ),
                        "score": round(avg_score, 4),
                    }
                )

            if field in {"delegator", "trustee"}:
                usable = [
                    item
                    for item in valid_candidates
                    if self._is_plausible_person_name(item["value"])
                ]
            elif field in {"delegator_id", "trustee_id"}:
                usable = [item for item in valid_candidates if item["checksum_valid"]]
            else:
                usable = [item for item in valid_candidates if item["value"]]
            selected = max(usable or valid_candidates, key=lambda item: item["score"])
            raw_value = selected["value"]
            recovered["fields"][field] = {
                "value": raw_value,
                "region": region,
                "artifact": selected["artifact"],
                "scores": selected.get("score"),
                "candidates": valid_candidates,
            }
            if field in {"delegator_id", "trustee_id"}:
                recovered["fields"][field]["checksum_valid"] = selected["checksum_valid"]
        return recovered

    @staticmethod
    def _check(
        code: str,
        expected: Optional[str],
        actual: Optional[str],
        label: str,
    ) -> Dict[str, Any]:
        if not expected or not actual:
            status = "unavailable"
        else:
            status = "passed" if expected == actual else "failed"
        return {
            "code": code,
            "label": label,
            "status": status,
            "expected": expected,
            "actual": actual,
        }

    def _build_consistency_checks(
        self,
        parsed: Dict[str, Any],
        front: Optional[Dict[str, Any]],
        back: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        front_data = (front or {}).get("data") or {}
        checks = [
            self._check(
                "trustee_name_matches_id_front",
                parsed.get("trustee"),
                front_data.get("name"),
                "正文受托人姓名与身份证正面姓名一致",
            ),
            self._check(
                "trustee_id_matches_id_front",
                parsed.get("trustee_id"),
                front_data.get("id_number"),
                "正文受托人身份证号与身份证正面号码一致",
            ),
            {
                "code": "id_front_present",
                "label": "已检测到受托人身份证正面",
                "status": "passed" if front else "failed",
            },
            {
                "code": "id_back_present",
                "label": "已检测到受托人身份证反面",
                "status": "passed" if back else "failed",
            },
        ]
        if (
            front_data.get("id_number")
            and parsed.get("delegator_id")
            and front_data["id_number"] == parsed["delegator_id"]
            and front_data["id_number"] != parsed.get("trustee_id")
        ):
            checks.append(
                {
                    "code": "attachment_matches_delegator_not_trustee",
                    "label": "附件身份证属于委托人而非正文受托人",
                    "status": "failed",
                    "expected": parsed.get("trustee_id"),
                    "actual": front_data.get("id_number"),
                }
            )
        return checks

    async def parse_document(
        self,
        path: Path,
        output_dir: Path,
        request_id: str,
    ) -> Dict[str, Any]:
        suffix = path.suffix.lower()
        output_dir.mkdir(parents=True, exist_ok=True)
        page_records: List[Dict[str, Any]] = []
        page_texts: List[str] = []
        attachments: Dict[str, List[Dict[str, Any]]] = {
            "id_front": [],
            "id_back": [],
        }
        signature_candidates: Dict[str, List[Dict[str, Any]]] = {
            "delegator": [],
            "trustee": [],
        }
        form_pages: List[Tuple[int, np.ndarray, Dict[str, Any]]] = []

        if suffix == ".pdf":
            document = fitz.open(str(path))
            pages = [(page, None) for page in document]
        else:
            image = cv2.imread(str(path))
            if image is None:
                raise ValueError("无法读取上传的图片")
            document = None
            pages = [(None, image)]

        try:
            scale = AUTHORIZATION_RENDER_DPI / 72.0
            for page_index, (page, supplied_image) in enumerate(pages, start=1):
                native_text = page.get_text("text") if page is not None else ""
                if page is not None:
                    pixmap = page.get_pixmap(
                        matrix=fitz.Matrix(scale, scale), alpha=False
                    )
                    page_image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                        pixmap.height, pixmap.width, pixmap.n
                    )
                    page_image = cv2.cvtColor(page_image, cv2.COLOR_RGB2BGR)
                else:
                    page_image = supplied_image
                    scale = 1.0

                page_path = output_dir / f"page_{page_index:03d}.jpg"
                self._write_image(page_path, page_image)
                card_regions: List[List[int]] = []
                embedded_count = 0

                if page is not None:
                    seen_regions = set()
                    for image_info in page.get_images(full=True):
                        for rect in page.get_image_rects(image_info[0]):
                            region = (
                                max(0, int(rect.x0 * scale)),
                                max(0, int(rect.y0 * scale)),
                                min(page_image.shape[1], int(rect.x1 * scale)),
                                min(page_image.shape[0], int(rect.y1 * scale)),
                            )
                            if region in seen_regions:
                                continue
                            seen_regions.add(region)
                            left, top, right, bottom = region
                            crop = page_image[top:bottom, left:right]
                            if crop.size == 0:
                                continue
                            embedded_count += 1
                            crop_path = output_dir / (
                                f"page_{page_index:03d}_embedded_{embedded_count:02d}.jpg"
                            )
                            self._write_image(crop_path, crop)
                            width = right - left
                            height = bottom - top
                            area_ratio = width * height / max(
                                1, page_image.shape[0] * page_image.shape[1]
                            )
                            aspect_ratio = width / max(1, height)
                            signals = self._image_signals(crop)
                            region_list = [left, top, right, bottom]

                            if (
                                1.30 <= aspect_ratio <= 1.90
                                and area_ratio >= 0.025
                                and min(width, height) >= 120
                            ):
                                card_regions.append(region_list)
                                attachment = await self._recognize_attachment(
                                    crop_path,
                                    page_index,
                                    region_list,
                                    request_id,
                                    output_dir,
                                )
                                if attachment:
                                    attachments[attachment["data"]["type"]].append(
                                        attachment
                                    )
                            elif (
                                area_ratio <= 0.025
                                and signals["saturated_ratio"] < 0.08
                                and 0.003 <= signals["dark_ratio"] <= 0.25
                            ):
                                role = self._nearest_signature_role(
                                    page, region_list, scale
                                )
                                signature_candidates[role].append(
                                    self._signature_from_region(
                                        crop,
                                        page_index,
                                        region_list,
                                        source="embedded_image",
                                    )
                                )

                native_char_count = len(re.sub(r"\s+", "", native_text))
                needs_page_ocr = (
                    suffix != ".pdf"
                    or (
                        native_char_count < AUTHORIZATION_NATIVE_TEXT_MIN_CHARS
                        and not card_regions
                    )
                )
                page_ocr = None
                if needs_page_ocr:
                    page_ocr = await self._recognize(
                        page_path, request_id, output_dir, document_type=None
                    )
                    self._save_json(
                        output_dir / f"page_{page_index:03d}_ocr.json", page_ocr
                    )
                    ocr_text = "\n".join(page_ocr.get("texts") or [])
                    is_form_page = "授权委托书" in ocr_text or "委托人" in ocr_text
                    if is_form_page:
                        page_texts.append(ocr_text)
                        form_pages.append((page_index, page_image, page_ocr))

                    split_regions = self._split_id_regions(page_image, page_ocr)
                    if split_regions:
                        for document_type, (crop, region) in split_regions.items():
                            card_regions.append(region)
                            crop_path = output_dir / (
                                f"page_{page_index:03d}_{document_type}_region.jpg"
                            )
                            self._write_image(crop_path, crop)
                            attachment = await self._recognize_attachment(
                                crop_path,
                                page_index,
                                region,
                                request_id,
                                output_dir,
                                document_type=document_type,
                            )
                            if attachment:
                                attachments[document_type].append(attachment)
                    else:
                        page_type = self._classify_ocr_text(
                            page_ocr.get("texts") or []
                        )
                        if page_type and not is_form_page:
                            document_data = self.ocr_parser.parse(
                                build_layout(page_ocr), document_type=page_type
                            )
                            score_values = page_ocr.get("scores") or []
                            attachments[page_type].append(
                                {
                                    "status": "detected",
                                    "page_number": page_index,
                                    "region": [
                                        0,
                                        0,
                                        page_image.shape[1],
                                        page_image.shape[0],
                                    ],
                                    "data": document_data,
                                    "ocr_confidence": round(
                                        float(sum(score_values) / len(score_values)), 4
                                    )
                                    if score_values
                                    else 0.0,
                                    "manual_review_required": True,
                                    "note": "身份证字段已自动识别，证件真实性和复印件有效性仍需人工核验。",
                                }
                            )

                    for role in ("delegator", "trustee"):
                        if is_form_page:
                            signature_candidates[role].append(
                                self._signature_from_template_region(
                                    page_image, role, page_index
                                )
                            )
                        signature = self._signature_near_ocr_label(
                            page_image, page_ocr, role, page_index
                        )
                        if signature:
                            signature_candidates[role].append(signature)
                else:
                    page_texts.append(native_text)
                    for role in ("delegator", "trustee"):
                        signature = self._signature_near_pdf_label(
                            page, page_image, scale, role, page_index
                        )
                        if signature:
                            signature_candidates[role].append(signature)

                page_records.append(
                    {
                        "page_number": page_index,
                        "native_text_chars": native_char_count,
                        "ocr_performed": page_ocr is not None,
                        "embedded_regions": embedded_count,
                        "artifact": page_path.name,
                    }
                )
        finally:
            if document is not None:
                document.close()

        raw_text = "\n".join(page_texts)
        parsed = self.text_parser.parse_text_content(raw_text)
        field_recovery = []
        for page_number, page_image, page_ocr in form_pages:
            if not self._should_recover_form_fields(page_image, page_ocr, parsed):
                continue
            recovery = await self._recover_form_fields(
                page_image, page_number, request_id, output_dir, page_ocr
            )
            field_recovery.append(recovery)
            for field, detail in recovery["fields"].items():
                value = detail["value"]
                if field in {"delegator", "trustee"}:
                    if self._is_plausible_person_name(value):
                        parsed[field] = value
                    elif not self._is_plausible_person_name(parsed.get(field)):
                        parsed[field] = None
                elif field in {"delegator_id", "trustee_id"}:
                    if detail.get("checksum_valid"):
                        parsed[field] = value
                    elif value:
                        parsed[field] = None
                elif field == "delegator_address" and not value:
                    parsed[field] = None
                elif value:
                    parsed[field] = value

        front = (
            max(attachments["id_front"], key=self._attachment_rank)
            if attachments["id_front"]
            else None
        )
        back = (
            max(attachments["id_back"], key=self._attachment_rank)
            if attachments["id_back"]
            else None
        )

        def best_signature(role: str) -> Dict[str, Any]:
            values = signature_candidates[role]
            if not values:
                return {
                    "status": "not_detected",
                    "confidence": 0.0,
                    "manual_review_required": True,
                    "note": "未自动检测到签名笔迹，仍需人工核验原件。",
                }
            return max(
                values,
                key=lambda item: (
                    item.get("status") == "detected",
                    item.get("confidence", 0.0),
                ),
            )

        consistency_checks = self._build_consistency_checks(parsed, front, back)
        parsed.update(
            {
                "pages": page_records,
                "raw_text": raw_text,
                "source": "hybrid_pdf_ocr" if suffix == ".pdf" else "image_ocr",
                "delegator_signature": best_signature("delegator"),
                "trustee_signature": best_signature("trustee"),
                "trustee_id_front": front,
                "trustee_id_back": back,
                "consistency_checks": consistency_checks,
                "review_required": True,
            }
        )
        result = self.text_parser.to_dict(
            parsed,
            metadata={
                "model": {
                    "ocr": f"PP-OCR{OCR_MODEL_VERSION}-{OCR_MODEL_PROFILE}",
                    "device": OCR_DEVICE,
                },
                "pages": page_records,
                "artifacts_dir": str(output_dir),
                "field_roi_recovery": field_recovery,
                "manual_review_notice": (
                    "签名和身份证仅做存在性及字段一致性检查，真实性必须人工核验。"
                ),
            },
        )
        self._save_json(output_dir / "authorization_result.json", result)
        logger.bind(request_id=request_id).info(
            "Authorization letter parsed: pages={}, id_front={}, id_back={}, field_roi={}",
            len(page_records),
            bool(front),
            bool(back),
            len(field_recovery),
        )
        return result


authorization_letter_service = AuthorizationLetterService()
