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
        red_mask = (
            ((hsv[:, :, 0] < 10) | (hsv[:, :, 0] > 170))
            & (hsv[:, :, 1] > 70)
            & (hsv[:, :, 2] > 70)
        )
        return {
            "red_ratio": float(np.mean(red_mask)),
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
    ) -> Dict[str, Any]:
        return await asyncio.wrap_future(
            ocr_service.submit_recognize(
                str(image_path),
                min_score=AUTHORIZATION_OCR_MIN_SCORE,
                request_id=request_id,
                output_dir=output_dir,
                document_type=document_type,
                auto_orientation=True,
            )
        )

    async def _recognize_attachment(
        self,
        image_path: Path,
        page_number: int,
        region: List[int],
        request_id: str,
        output_dir: Path,
    ) -> Optional[Dict[str, Any]]:
        ocr_result = await self._recognize(
            image_path, request_id, output_dir, document_type=None
        )
        document_type = self._classify_ocr_text(ocr_result.get("texts") or [])
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
    def _crop_id_region(
        image: np.ndarray, ocr_result: Dict[str, Any], document_type: str
    ) -> Optional[Tuple[np.ndarray, List[int]]]:
        keywords = (
            AuthorizationLetterService._FRONT_KEYWORDS
            if document_type == "id_front"
            else AuthorizationLetterService._BACK_KEYWORDS
        )
        selected = []
        for text, box in zip(
            ocr_result.get("texts") or [], ocr_result.get("boxes") or []
        ):
            if any(keyword in text for keyword in keywords) or (
                document_type == "id_front"
                and re.search(r"\d{17}[0-9Xx]", re.sub(r"\s+", "", text))
            ):
                selected.append([int(value) for value in box])
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
    def _detect_red_seals(
        image: np.ndarray,
        page_number: int,
        excluded_regions: List[List[int]],
    ) -> List[Dict[str, Any]]:
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        mask = (
            (
                ((hsv[:, :, 0] < 10) | (hsv[:, :, 0] > 170))
                & (hsv[:, :, 1] > 70)
                & (hsv[:, :, 2] > 70)
            ).astype(np.uint8)
            * 255
        )
        mask = cv2.morphologyEx(
            mask,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)),
        )
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        page_area = image.shape[0] * image.shape[1]
        seals = []
        for contour in contours:
            left, top, width, height = cv2.boundingRect(contour)
            region = [left, top, left + width, top + height]
            area_ratio = (width * height) / max(1, page_area)
            if not (0.0006 <= area_ratio <= 0.12) or min(width, height) < 28:
                continue
            center_x = left + width / 2
            center_y = top + height / 2
            if any(
                box[0] <= center_x <= box[2] and box[1] <= center_y <= box[3]
                for box in excluded_regions
            ):
                continue
            red_density = float(
                np.mean(mask[top : top + height, left : left + width] > 0)
            )
            if red_density < 0.04:
                continue
            seals.append(
                {
                    "status": "detected",
                    "confidence": round(min(0.99, 0.55 + red_density), 4),
                    "page_number": page_number,
                    "region": region,
                    "source": "red_color_region",
                    "manual_review_required": True,
                    "note": "仅检测红色印章区域是否存在，不验证印章内容、归属或真伪。",
                }
            )
        return seals

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
        seals: List[Dict[str, Any]] = []

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
                    if "授权委托书" in ocr_text or "委托人" in ocr_text:
                        page_texts.append(ocr_text)
                    page_type = self._classify_ocr_text(page_ocr.get("texts") or [])
                    if page_type:
                        if "授权委托书" in ocr_text or "委托人" in ocr_text:
                            crop_result = self._crop_id_region(
                                page_image, page_ocr, page_type
                            )
                            if crop_result:
                                crop, region = crop_result
                                card_regions.append(region)
                                crop_path = output_dir / (
                                    f"page_{page_index:03d}_{page_type}_region.jpg"
                                )
                                self._write_image(crop_path, crop)
                                attachment = await self._recognize_attachment(
                                    crop_path,
                                    page_index,
                                    region,
                                    request_id,
                                    output_dir,
                                )
                                if attachment:
                                    attachments[attachment["data"]["type"]].append(
                                        attachment
                                    )
                        else:
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

                seals.extend(
                    self._detect_red_seals(page_image, page_index, card_regions)
                )
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
        seal_result = (
            max(seals, key=lambda item: item.get("confidence", 0.0))
            if seals
            else {
                "status": "not_detected",
                "confidence": 0.0,
                "manual_review_required": True,
                "note": "未自动检测到红色印章；灰度扫描件或低饱和度印章需人工核验。",
            }
        )
        parsed.update(
            {
                "pages": page_records,
                "raw_text": raw_text,
                "source": "hybrid_pdf_ocr" if suffix == ".pdf" else "image_ocr",
                "delegator_signature": best_signature("delegator"),
                "trustee_signature": best_signature("trustee"),
                "seal": seal_result,
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
                "manual_review_notice": (
                    "签名、印章和身份证仅做存在性及字段一致性检查，真实性必须人工核验。"
                ),
            },
        )
        self._save_json(output_dir / "authorization_result.json", result)
        logger.bind(request_id=request_id).info(
            "Authorization letter parsed: pages={}, id_front={}, id_back={}, seal={}",
            len(page_records),
            bool(front),
            bool(back),
            seal_result["status"],
        )
        return result


authorization_letter_service = AuthorizationLetterService()
