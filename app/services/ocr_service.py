from typing import Any, Optional, Union
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import re
import os
import time
import tempfile
from pathlib import Path
import cv2
import numpy as np

from paddlex import create_pipeline
from paddlex.inference import PaddlePredictorOption

from app.utils.logger import logger
from app.utils.metrics import metrics

# 1. 确保在文件顶部导入了我们在 config.py 里配置好的 MODEL_DIR
from app.config import MODEL_DIR
from app.config import OCR_CPU_THREADS
from app.config import OCR_DEVICE
from app.config import OCR_ENABLE_DOC_ORIENTATION_MODEL
from app.config import OCR_ENABLE_MKLDNN
from app.config import OCR_INFERENCE_BACKEND
from app.config import OCR_CACHE_VERSION
from app.config import OCR_ID_FRONT_MIN_SCORE
from app.config import OCR_MODEL_PROFILE
from app.config import OCR_MODEL_ENGINE
from app.config import OCR_MODEL_VARIANT
from app.config import OCR_MODEL_VERSION
from app.config import OCR_PREPROCESSED_JPEG_QUALITY
from app.config import OCR_SAVE_PREPROCESSED_IMAGE
from app.config import OCR_TEXT_RECOGNITION_BATCH_SIZE
from app.config import OCR_USE_DOC_ORIENTATION
from app.config import OCR_USE_DOC_UNWARPING
from app.config import OCR_USE_FINE_TUNED_MODEL

# 2. 拼接出精准的本地模型绝对路径（跨平台，防写死路径报错）
fine_tuned_model_path = str(MODEL_DIR / "my_bank_card_det")
official_detection_model = f"PP-OCR{OCR_MODEL_VERSION}_{OCR_MODEL_VARIANT}_det"
official_recognition_model = f"PP-OCR{OCR_MODEL_VERSION}_{OCR_MODEL_VARIANT}_rec"
use_dynamic_official_models = (
    OCR_INFERENCE_BACKEND == "paddle" and OCR_MODEL_ENGINE == "paddle_dynamic"
)
official_model_dir_suffix = "_safetensors" if use_dynamic_official_models else ""
official_detection_model_path = (
    MODEL_DIR
    / "official_models"
    / f"{official_detection_model}{official_model_dir_suffix}"
)
official_recognition_model_path = (
    MODEL_DIR
    / "official_models"
    / f"{official_recognition_model}{official_model_dir_suffix}"
)
doc_orientation_model_path = (
    MODEL_DIR / "official_models" / "PP-LCNet_x1_0_doc_ori"
)
doc_unwarping_model_path = MODEL_DIR / "official_models" / "UVDoc"

DOCUMENT_DETECTION_SIDE_LIMITS = {
    "id_front": 768,
    "id_back": 768,
}
DEFAULT_DETECTION_SIDE_LIMIT = 960
ID_FRONT_NATION_CROP_SCALE = 4
ID_FRONT_NATION_MIN_SCORE = 0.5
ID_FRONT_GENDER_LABEL_PATTERN = re.compile(r"性[别州期]")
ID_FRONT_NATION_LABEL_PATTERN = re.compile(r"[民闲]族\s*[\u4e00-\u9fff]")
BUSINESS_ADDRESS_KEYWORDS = ("省", "市", "区", "县", "路", "街", "广场", "楼", "层")


def _build_ocr_config(use_fine_tuned: bool = True) -> dict[str, Any]:
    """为 PaddleX OCR pipeline 构造显式配置，可选择官方模型或自训练模型。"""
    use_doc_preprocessor = not use_fine_tuned and (
        OCR_ENABLE_DOC_ORIENTATION_MODEL or OCR_USE_DOC_UNWARPING
    )
    text_detection_config = {
        "model_name": (
            "PP-OCRv5_server_det" if use_fine_tuned else official_detection_model
        ),
        # 官方 PP-OCRv5 默认值是 1.5；2.0 是为了银行卡微调检测模型扩大检测框。
        "unclip_ratio": 2.0 if use_fine_tuned else 1.5,
    }
    if use_fine_tuned:
        text_detection_config["model_dir"] = fine_tuned_model_path
    elif official_detection_model_path.is_dir():
        text_detection_config["model_dir"] = str(official_detection_model_path)
    if not use_fine_tuned and OCR_INFERENCE_BACKEND == "paddle":
        text_detection_config["engine"] = OCR_MODEL_ENGINE

    text_recognition_config = {
        "model_name": official_recognition_model,
        "batch_size": OCR_TEXT_RECOGNITION_BATCH_SIZE,
    }
    if official_recognition_model_path.is_dir():
        text_recognition_config["model_dir"] = str(official_recognition_model_path)
    if OCR_INFERENCE_BACKEND == "paddle":
        text_recognition_config["engine"] = OCR_MODEL_ENGINE

    config = {
        "pipeline_name": "OCR",
        "text_type": "general",
        "use_doc_preprocessor": use_doc_preprocessor,
        "use_textline_orientation": False,
        "batch_size": 1,
        "SubModules": {
            "TextDetection": text_detection_config,
            "TextRecognition": text_recognition_config,
        },
    }

    if use_doc_preprocessor:
        doc_preprocessor_modules = {}
        if OCR_ENABLE_DOC_ORIENTATION_MODEL:
            doc_preprocessor_modules["DocOrientationClassify"] = {
                "module_name": "doc_text_orientation",
                "model_name": "PP-LCNet_x1_0_doc_ori",
            }
            if doc_orientation_model_path.is_dir():
                doc_preprocessor_modules["DocOrientationClassify"]["model_dir"] = str(
                    doc_orientation_model_path
                )
        if OCR_USE_DOC_UNWARPING:
            doc_preprocessor_modules["DocUnwarping"] = {
                "module_name": "image_unwarping",
                "model_name": "UVDoc",
            }
            if doc_unwarping_model_path.is_dir():
                doc_preprocessor_modules["DocUnwarping"]["model_dir"] = str(
                    doc_unwarping_model_path
                )

        config["SubPipelines"] = {
            "DocPreprocessor": {
                "pipeline_name": "doc_preprocessor",
                "use_doc_orientation_classify": OCR_ENABLE_DOC_ORIENTATION_MODEL,
                "use_doc_unwarping": OCR_USE_DOC_UNWARPING,
                "SubModules": doc_preprocessor_modules,
            },
        }

    return config


def _create_ocr_pipeline(config: dict[str, Any]):
    create_options = {
        "pipeline": "OCR",
        "config": config,
        "device": OCR_DEVICE,
    }
    if OCR_INFERENCE_BACKEND == "openvino":
        create_options.update(
            {
                "use_hpip": True,
                "hpi_config": {
                    "auto_config": False,
                    "backend": "openvino",
                    "backend_config": {"cpu_num_threads": OCR_CPU_THREADS},
                    "auto_paddle2onnx": True,
                },
            }
        )
    elif OCR_DEVICE == "cpu":
        create_options["pp_option"] = PaddlePredictorOption(
            run_mode="mkldnn" if OCR_ENABLE_MKLDNN else "paddle",
            cpu_threads=OCR_CPU_THREADS,
        )
    return create_pipeline(**create_options)


class OCRService:

    def __init__(self):
        self.pipeline = None
        self.layout_pipeline = None
        self.pipeline_uses_fine_tuned_detector = False
        self._inference_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="ocr-inference"
        )
        self._artifact_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="ocr-artifact"
        )

    @staticmethod
    def _effective_orientation(auto_orientation: Optional[bool]) -> bool:
        if auto_orientation is None:
            return OCR_USE_DOC_ORIENTATION
        return auto_orientation

    @staticmethod
    def _detection_side_limit(document_type: Optional[str]) -> int:
        return DOCUMENT_DETECTION_SIDE_LIMITS.get(
            document_type, DEFAULT_DETECTION_SIDE_LIMIT
        )

    def cache_signature(
        self,
        document_type: Optional[str],
        auto_orientation: Optional[bool],
        min_score: float = 0.7,
    ) -> str:
        effective_min_score = min_score
        if document_type == "id_front":
            effective_min_score = min(min_score, OCR_ID_FRONT_MIN_SCORE)

        settings = {
            "version": OCR_CACHE_VERSION,
            "model_version": OCR_MODEL_VERSION,
            "profile": OCR_MODEL_PROFILE,
            "model_engine": OCR_MODEL_ENGINE,
            "fine_tuned": OCR_USE_FINE_TUNED_MODEL,
            "inference_backend": OCR_INFERENCE_BACKEND,
            "orientation": self._effective_orientation(auto_orientation),
            "unwarping": OCR_USE_DOC_UNWARPING,
            "document_type": document_type,
            "detection_side_limit": self._detection_side_limit(document_type),
            "min_score": effective_min_score,
        }
        serialized = json.dumps(settings, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]

    def initialize(self):
        if self.pipeline is not None:
            return

        if OCR_USE_FINE_TUNED_MODEL:
            logger.info("Initializing PaddleX OCR Pipeline with fine-tuned detector: {}", fine_tuned_model_path)

            try:
                self.pipeline = _create_ocr_pipeline(
                    _build_ocr_config(use_fine_tuned=True)
                )
                self.pipeline_uses_fine_tuned_detector = True
                metrics.set_model_ready(True)
                logger.info("PaddleX OCR Pipeline Ready with fine-tuned detector.")
                return
            except Exception as exc:
                logger.warning("Fine-tuned detector failed to load, falling back to official PaddleX model: {}", exc)

        logger.info(
            "Initializing PaddleX OCR Pipeline: version={}, profile={}, "
            "detector={}, recognizer={}, engine={}, device={}, "
            "backend={}, cpu_threads={}, rec_batch_size={}, mkldnn={}.",
            OCR_MODEL_VERSION,
            OCR_MODEL_PROFILE,
            official_detection_model,
            official_recognition_model,
            OCR_MODEL_ENGINE,
            OCR_DEVICE,
            OCR_INFERENCE_BACKEND,
            OCR_CPU_THREADS,
            OCR_TEXT_RECOGNITION_BATCH_SIZE,
            OCR_ENABLE_MKLDNN,
        )
        self.pipeline = _create_ocr_pipeline(
            _build_ocr_config(use_fine_tuned=False)
        )
        self.pipeline_uses_fine_tuned_detector = False
        metrics.set_model_ready(True)
        logger.info(
            "PaddleX OCR Pipeline Ready with official {} models.",
            OCR_MODEL_VERSION,
        )

    def submit_initialize(self):
        """在固定推理线程中初始化模型，保持 Paddle predictor 线程亲和性。"""
        return self._inference_executor.submit(self.initialize)

    def submit_recognize(self, image_path: str, **kwargs):
        """将推理提交到唯一的固定线程，避免 predictor 跨线程复用。"""
        return self._inference_executor.submit(self.recognize, image_path, **kwargs)

    def submit_recognize_with_layout(self, image_path: str):
        """将布局分析提交到同一个推理线程，避免阻塞事件循环。"""
        return self._inference_executor.submit(
            self.recognize_with_layout, image_path
        )

    def initialize_layout_pipeline(self):
        """初始化布局分析 pipeline"""
        if self.layout_pipeline is not None:
            return

        if OCR_USE_FINE_TUNED_MODEL:
            logger.info("Initializing PaddleX OCR Layout Pipeline with fine-tuned detector: {}", fine_tuned_model_path)

            layout_config = _build_ocr_config(use_fine_tuned=True)

            try:
                self.layout_pipeline = _create_ocr_pipeline(layout_config)
                logger.info("PaddleX OCR Layout Pipeline Ready with fine-tuned detector.")
                return
            except Exception as exc:
                logger.warning("Fine-tuned detector failed for layout pipeline, falling back to official model: {}", exc)

        logger.info("Initializing PaddleX OCR Layout Pipeline with official detector.")
        layout_config = _build_ocr_config(use_fine_tuned=False)
        self.layout_pipeline = _create_ocr_pipeline(layout_config)
        logger.info("PaddleX OCR Layout Pipeline Ready with official detector.")

    def preprocess_image(
        self, image_path: str, output_dir: Optional[Union[str, Path]] = None
    ) -> str:
        """
        图片预处理：自动增强图片质量
        返回预处理后的临时文件路径
        """
        img = cv2.imread(image_path)
        if img is None:
            raise ValueError(f"无法读取图片文件: {image_path}")

        # 转换为灰度图
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # CLAHE 自适应直方图均衡化 - 提升对比度
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)

        # 锐化处理 - 使文字更清晰
        kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
        sharpened = cv2.filter2D(enhanced, -1, kernel)

        # 自动对比度调整
        sharpened = cv2.convertScaleAbs(sharpened, alpha=1.2, beta=30)

        # 保存临时文件
        temp_dir = (
            Path(output_dir)
            if output_dir
            else Path(image_path).parent / "temp_preprocessed"
        )
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = temp_dir / "preprocessed_fine_tuned.png"
        if not cv2.imwrite(str(temp_path), sharpened):
            raise OSError(f"Failed to save preprocessed image: {temp_path}")

        return str(temp_path)

    @staticmethod
    def _save_platform_preprocessed_image(
        output_img: np.ndarray,
        output_path: Path,
        request_logger,
    ) -> None:
        if cv2.imwrite(
            str(output_path),
            output_img,
            [cv2.IMWRITE_JPEG_QUALITY, OCR_PREPROCESSED_JPEG_QUALITY],
        ):
            request_logger.info(
                "Platform preprocessed image saved asynchronously: {}", output_path
            )
        else:
            request_logger.warning(
                "Failed to save platform preprocessed image: {}", output_path
            )

    def _schedule_platform_preprocessed_image(
        self,
        doc_preprocessor_res: dict[str, Any],
        output_dir: Optional[Union[str, Path]],
        request_logger,
    ) -> None:
        if output_dir is None or not OCR_SAVE_PREPROCESSED_IMAGE:
            return

        output_img = doc_preprocessor_res.get("output_img")
        if not isinstance(output_img, np.ndarray):
            request_logger.warning(
                "Platform preprocessor did not return an output image"
            )
            return

        output_path = Path(output_dir) / "preprocessed_platform.jpg"
        try:
            self._artifact_executor.submit(
                self._save_platform_preprocessed_image,
                output_img,
                output_path,
                request_logger,
            )
        except RuntimeError as exc:
            request_logger.warning(
                "Failed to schedule preprocessed image save: {}", exc
            )

    def shutdown(self) -> None:
        self._inference_executor.shutdown(wait=True)
        self._artifact_executor.shutdown(wait=True)
        metrics.set_model_ready(False)

    @staticmethod
    def _looks_like_alphanumeric_code(text: str) -> bool:
        """
        判断文本是否像编码类字符串（如统一社会信用代码、身份证号等）。
        这类文本不应做字母→数字的替换。
        """
        # 连续 15+ 位的字母数字混合串
        if re.search(r'[0-9A-Za-z]{15,}', text):
            return True
        return False

    def postprocess_texts(self, texts: list[str]) -> list[str]:
        """
        文本后处理：修正常见 OCR 错误
        
        修正策略：
        1. 清理空格和引号（安全操作，适用于所有文本）
        2. 修正部分中文标点为英文标点（保留中文冒号、括号，营业执照标签常用）
        3. 仅对中文文本做汉字误识别修正
        
        重要：不再对字母做 字母→数字 的全局替换。
        因为统一社会信用代码等编码中包含合法字母（B, L, M, N 等），
        盲目替换（如 B→8, S→5）会破坏编码。
        编码级的修正改由各 Parser 内部按需处理。
        """
        # 汉字误识别修正（仅在中文上下文安全使用）
        han_corrections = {
            # '淹': '渑',  # 常见汉字误识别：淹→渑（身份证地址）
            # '祭': '商',  # 常见汉字误识别：祭→商
        }

        # 符号修正（保留 '：' '（' '）' '、' '·'，中文文档标签常用）
        symbol_corrections = {
            '；': ';', '。': '.',
            '【': '[', '】': ']',
            '「': '(', '」': ')',
            '\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"',
        }

        processed = []
        for text in texts:
            if not text or not isinstance(text, str):
                processed.append("")
                continue

            # 策略1：清理多余空格和引号
            text = re.sub(r'\s+', ' ', text).strip()
            text = text.strip('"').strip("'").strip()

            # 策略2：修正符号
            for wrong, right in symbol_corrections.items():
                text = text.replace(wrong, right)

            # 策略3：仅对非编码类文本做汉字修正
            if not self._looks_like_alphanumeric_code(text):
                for wrong, right in han_corrections.items():
                    text = text.replace(wrong, right)

            processed.append(text)

        return processed

    @staticmethod
    def _is_id_front_candidate(
        document_type: Optional[str], texts: list[str]
    ) -> bool:
        if document_type == "id_front":
            return True
        if document_type is not None:
            return False

        joined_text = "".join(texts)
        return (
            bool(ID_FRONT_GENDER_LABEL_PATTERN.search(joined_text))
            and "住址" in joined_text
            and bool(re.search(r"\d{17}[0-9Xx]", joined_text))
        )

    @staticmethod
    def _has_id_front_nation(texts: list[str]) -> bool:
        return any(
            ID_FRONT_NATION_LABEL_PATTERN.search(text or "")
            for text in texts
        )

    def _recover_id_front_nation(
        self,
        image_path: str,
        texts: list[str],
        scores: list[float],
        boxes: list[list],
        polys: list[list],
        output_dir: Optional[Union[str, Path]],
        request_logger,
        document_type: Optional[str],
    ) -> None:
        """对缺少民族字段的身份证正面做一次局部放大补识别。"""
        if (
            not self._is_id_front_candidate(document_type, texts)
            or self._has_id_front_nation(texts)
        ):
            return

        gender_index = next(
            (
                index
                for index, text in enumerate(texts)
                if ID_FRONT_GENDER_LABEL_PATTERN.search(text)
            ),
            None,
        )
        if gender_index is None:
            return

        image = cv2.imread(image_path)
        if image is None:
            request_logger.warning("Nation crop skipped: failed to load image")
            return

        gender_box = boxes[gender_index]
        left, top, right, bottom = (int(value) for value in gender_box[:4])
        label_width = max(1, right - left)
        label_height = max(1, bottom - top)
        image_height, image_width = image.shape[:2]
        crop_left = min(
            image_width, right + max(70, int(label_width * 0.7))
        )
        crop_right = min(
            image_width, right + max(280, int(label_width * 3)))
        crop_top = max(0, top - int(label_height * 0.75))
        crop_bottom = min(image_height, bottom + int(label_height * 0.75))
        if crop_right <= crop_left or crop_bottom <= crop_top:
            return

        crop = image[crop_top:crop_bottom, crop_left:crop_right]
        enlarged_crop = cv2.resize(
            crop,
            None,
            fx=ID_FRONT_NATION_CROP_SCALE,
            fy=ID_FRONT_NATION_CROP_SCALE,
            interpolation=cv2.INTER_CUBIC,
        )

        temporary_crop = None
        if output_dir is not None:
            crop_path = Path(output_dir) / "id_front_nation_crop.jpg"
        else:
            descriptor, temporary_crop = tempfile.mkstemp(suffix=".jpg")
            os.close(descriptor)
            crop_path = Path(temporary_crop)

        try:
            if not cv2.imwrite(str(crop_path), enlarged_crop):
                request_logger.warning("Nation crop skipped: failed to save crop")
                return

            crop_predict_options = {
                "text_det_limit_side_len": 960,
                "text_det_limit_type": "max",
            }
            if not self.pipeline_uses_fine_tuned_detector:
                crop_predict_options.update(
                    {
                        "use_doc_orientation_classify": False,
                        "use_doc_unwarping": False,
                    }
                )

            crop_texts = []
            for result in self.pipeline.predict(str(crop_path), **crop_predict_options):
                crop_texts = list(
                    zip(result["rec_texts"], result["rec_scores"])
                )

            for text, score in crop_texts:
                normalized_text = self.postprocess_texts([text])[0]
                if score < ID_FRONT_NATION_MIN_SCORE or "族" not in normalized_text:
                    continue

                texts.append(normalized_text)
                scores.append(float(score))
                boxes.append([crop_left, crop_top, crop_right, crop_bottom])
                polys.append(
                    [
                        [crop_left, crop_top],
                        [crop_right, crop_top],
                        [crop_right, crop_bottom],
                        [crop_left, crop_bottom],
                    ]
                )
                request_logger.info(
                    "ID front nation recovered from crop: text={}, score={:.3f}",
                    normalized_text,
                    score,
                )
                return
        except Exception as exc:
            request_logger.warning("Nation crop OCR failed: {}", exc)
        finally:
            if temporary_crop:
                try:
                    os.remove(temporary_crop)
                except OSError:
                    pass

    @staticmethod
    def _is_business_license_candidate(
        document_type: Optional[str], texts: list[str]
    ) -> bool:
        if document_type == "business_license":
            return True
        if document_type is not None:
            return False

        joined_text = "".join(texts)
        return "营业执照" in joined_text and "统一社会信用代码" in joined_text

    @staticmethod
    def _has_business_address_label(texts: list[str]) -> bool:
        return any(
            "住所" in (text or "") or (text or "").strip() in {"住", "所"}
            for text in texts
        )

    def _recover_business_license_address(
        self,
        image_path: str,
        texts: list[str],
        scores: list[float],
        boxes: list[list],
        polys: list[list],
        output_dir: Optional[Union[str, Path]],
        request_logger,
        document_type: Optional[str],
    ) -> None:
        """对住所标签及首行地址漏检的营业执照做一次局部放大补识别。"""
        if (
            not self._is_business_license_candidate(document_type, texts)
            or self._has_business_address_label(texts)
            or not boxes
        ):
            return

        document_width = max(int(box[2]) for box in boxes if len(box) >= 4)
        tail_index = next(
            (
                index
                for index, (text, box) in enumerate(zip(texts, boxes))
                if len(box) >= 4
                and int(box[0]) >= document_width * 0.55
                and any(keyword in (text or "") for keyword in BUSINESS_ADDRESS_KEYWORDS)
            ),
            None,
        )
        if tail_index is None:
            return

        image = cv2.imread(image_path)
        if image is None:
            request_logger.warning("Business address crop skipped: failed to load image")
            return

        tail_box = boxes[tail_index]
        left, top, right, bottom = (int(value) for value in tail_box[:4])
        tail_width = max(1, right - left)
        tail_height = max(1, bottom - top)
        image_height, image_width = image.shape[:2]
        crop_left = max(0, left - max(180, int(tail_width * 1.25)))
        crop_right = min(image_width, right + max(110, int(tail_width * 0.75)))
        crop_top = max(0, top - max(56, tail_height * 3))
        crop_bottom = min(image_height, bottom + max(26, int(tail_height * 1.5)))
        if crop_right <= crop_left or crop_bottom <= crop_top:
            return

        crop = image[crop_top:crop_bottom, crop_left:crop_right]
        enlarged_crop = cv2.resize(
            crop,
            None,
            fx=ID_FRONT_NATION_CROP_SCALE,
            fy=ID_FRONT_NATION_CROP_SCALE,
            interpolation=cv2.INTER_CUBIC,
        )

        temporary_crop = None
        if output_dir is not None:
            crop_path = Path(output_dir) / "business_license_address_crop.jpg"
        else:
            descriptor, temporary_crop = tempfile.mkstemp(suffix=".jpg")
            os.close(descriptor)
            crop_path = Path(temporary_crop)

        try:
            if not cv2.imwrite(str(crop_path), enlarged_crop):
                request_logger.warning("Business address crop skipped: failed to save crop")
                return

            crop_predict_options = {
                "text_det_limit_side_len": 1280,
                "text_det_limit_type": "max",
            }
            if not self.pipeline_uses_fine_tuned_detector:
                crop_predict_options.update(
                    {
                        "use_doc_orientation_classify": False,
                        "use_doc_unwarping": False,
                    }
                )

            for result in self.pipeline.predict(str(crop_path), **crop_predict_options):
                for index, score in enumerate(result["rec_scores"]):
                    text = self.postprocess_texts([result["rec_texts"][index]])[0]
                    if score < 0.7 or not text:
                        continue
                    if not (
                        text in {"住", "所"}
                        or text.startswith("所")
                        or any(keyword in text for keyword in BUSINESS_ADDRESS_KEYWORDS)
                    ):
                        continue

                    crop_box = result["rec_boxes"][index].tolist()
                    mapped_box = [
                        int(crop_left + value / ID_FRONT_NATION_CROP_SCALE)
                        if position % 2 == 0
                        else int(crop_top + value / ID_FRONT_NATION_CROP_SCALE)
                        for position, value in enumerate(crop_box)
                    ]
                    texts.append(text)
                    scores.append(float(score))
                    boxes.append(mapped_box)
                    polys.append(
                        [
                            [mapped_box[0], mapped_box[1]],
                            [mapped_box[2], mapped_box[1]],
                            [mapped_box[2], mapped_box[3]],
                            [mapped_box[0], mapped_box[3]],
                        ]
                    )

                request_logger.info("Business license address recovered from crop")
                return
        except Exception as exc:
            request_logger.warning("Business address crop OCR failed: {}", exc)
        finally:
            if temporary_crop:
                try:
                    os.remove(temporary_crop)
                except OSError:
                    pass

    def recognize(
        self,
        image_path: str,
        min_score: float = 0.7,
        request_id: Optional[str] = None,
        output_dir: Optional[Union[str, Path]] = None,
        document_type: Optional[str] = None,
        auto_orientation: Optional[bool] = None,
    ) -> dict[str, Any]:
        """
        OCR 识别接口（带优化）
        
        Args:
            image_path: 图片路径
            min_score: 最低置信度阈值（默认 0.7，范围 0-1）
        
        Returns:
            识别结果字典，包含 texts, scores, boxes, polys, angle
        """
        if self.pipeline is None:
            # 延迟初始化：如果 pipeline 未初始化，自动初始化
            self.initialize()

        # 图片预处理
        temp_path = None
        request_logger = logger.bind(request_id=request_id or "-")
        recognize_started_at = time.perf_counter()
        effective_orientation = self._effective_orientation(auto_orientation)
        detection_side_limit = self._detection_side_limit(document_type)
        effective_min_score = min_score
        if document_type == "id_front":
            effective_min_score = min(min_score, OCR_ID_FRONT_MIN_SCORE)
        try:
            if self.pipeline_uses_fine_tuned_detector:
                temp_path = self.preprocess_image(image_path, output_dir=output_dir)
                ocr_input_path = temp_path
                request_logger.info("Preprocessed image saved: {}", temp_path)
            else:
                ocr_input_path = image_path

            # OCR 识别
            prediction_started_at = time.perf_counter()
            predict_options = {
                "text_det_limit_side_len": detection_side_limit,
                "text_det_limit_type": "max",
            }
            if not self.pipeline_uses_fine_tuned_detector:
                predict_options.update(
                    {
                        "use_doc_orientation_classify": effective_orientation,
                        "use_doc_unwarping": OCR_USE_DOC_UNWARPING,
                    }
                )

            request_logger.info(
                "OCR inference options: document_type={}, auto_orientation={}, "
                "det_side_limit={}, min_score={}",
                document_type or "auto",
                effective_orientation,
                detection_side_limit,
                effective_min_score,
            )
            for result in self.pipeline.predict(ocr_input_path, **predict_options):
                prediction_seconds = time.perf_counter() - prediction_started_at
                prediction_ms = prediction_seconds * 1000
                metrics.observe_prediction(
                    document_type or "auto", prediction_seconds
                )
                request_logger.info(
                    "PaddleX prediction completed: duration_ms={:.2f}", prediction_ms
                )

                # 置信度过滤
                texts = []
                scores = []
                boxes = []
                polys = []

                for i, score in enumerate(result["rec_scores"]):
                    if score >= effective_min_score:
                        texts.append(result["rec_texts"][i])
                        scores.append(float(score))
                        boxes.append(result["rec_boxes"][i].tolist())
                        polys.append(result["dt_polys"][i].tolist())

                # 文本后处理
                texts = self.postprocess_texts(texts)

                self._recover_id_front_nation(
                    ocr_input_path,
                    texts,
                    scores,
                    boxes,
                    polys,
                    output_dir,
                    request_logger,
                    document_type,
                )
                self._recover_business_license_address(
                    ocr_input_path,
                    texts,
                    scores,
                    boxes,
                    polys,
                    output_dir,
                    request_logger,
                    document_type,
                )

                doc_preprocessor_res = result.get("doc_preprocessor_res") or {}
                if not self.pipeline_uses_fine_tuned_detector and (
                    effective_orientation or OCR_USE_DOC_UNWARPING
                ):
                    self._schedule_platform_preprocessed_image(
                        doc_preprocessor_res, output_dir, request_logger
                    )

                return {
                    "texts": texts,
                    "scores": scores,
                    "boxes": boxes,
                    "polys": polys,
                    "angle": doc_preprocessor_res.get("angle", 0)
                }

            return {
                "texts": [],
                "scores": [],
                "boxes": [],
                "polys": [],
                "angle": 0,
                "raw": None
            }

        finally:
            total_ms = (time.perf_counter() - recognize_started_at) * 1000
            request_logger.info("OCR service finished: duration_ms={:.2f}", total_ms)
            # 清理临时文件
            if temp_path and output_dir is None and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception as e:
                    logger.warning(f"清理临时文件失败: {e}")


    def recognize_with_layout(self, image_path: str) -> list[dict[str, Any]]:
        """
        布局分析 OCR 识别接口
        
        使用布局分析 pipeline 处理文档，返回结构化结果
        
        Args:
            image_path: 图片或 PDF 文件路径
        
        Returns:
            布局分析结果列表，每个元素代表一页的分析结果
        """
        if self.layout_pipeline is None:
            self.initialize_layout_pipeline()

        def convert_to_serializable(obj):
            """递归将 numpy 数组和其他非序列化对象转换为可序列化格式"""
            if isinstance(obj, dict):
                return {k: convert_to_serializable(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_to_serializable(item) for item in obj]
            elif isinstance(obj, tuple):
                return tuple(convert_to_serializable(item) for item in obj)
            elif isinstance(obj, np.ndarray):
                return obj.tolist()
            elif isinstance(obj, np.integer):
                return int(obj)
            elif isinstance(obj, np.floating):
                return float(obj)
            elif isinstance(obj, np.bool_):
                return bool(obj)
            else:
                return obj

        # 执行布局分析
        layout_results = []
        for result in self.layout_pipeline.predict(image_path):
            # 转换为可序列化格式
            serializable_result = convert_to_serializable(result)
            layout_results.append(serializable_result)

        return layout_results


ocr_service = OCRService()
