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
from app.config import OCR_BUSINESS_SCOPE_ROI_MAX_SIDE
from app.config import OCR_BUSINESS_SCOPE_ROI_MIN_CHARS
from app.config import OCR_BUSINESS_SCOPE_ROI_MIN_SCORE
from app.config import OCR_BUSINESS_SCOPE_ROI_RETRY_ENABLED
from app.config import OCR_BUSINESS_SCOPE_ROI_SCALE
from app.config import OCR_BUSINESS_LICENSE_DETECTION_SIDE_LIMIT
from app.config import OCR_BUSINESS_FIELD_ROI_MIN_SCORE
from app.config import OCR_BUSINESS_FIELD_ROI_RETRY_ENABLED
from app.config import OCR_BUSINESS_FIELD_ROI_SCALE
from app.config import OCR_ID_FRONT_MIN_SCORE
from app.config import OCR_ID_FRONT_FIELD_ROI_MIN_SCORE
from app.config import OCR_ID_FRONT_FIELD_ROI_SCALE
from app.config import OCR_ID_FRONT_QUALITY_RETRY_ENABLED
from app.config import OCR_ID_FRONT_RETRY_BLUR_THRESHOLD
from app.config import OCR_ID_FRONT_RETRY_BRIGHT_MEAN
from app.config import OCR_ID_FRONT_RETRY_CLIPPED_RATIO
from app.config import OCR_ID_FRONT_RETRY_DARK_MEAN
from app.config import OCR_ID_FRONT_RETRY_MAX_SIDE
from app.config import OCR_ID_FRONT_RETRY_MIN_SIDE
from app.config import OCR_ID_FRONT_RETRY_ON_INCOMPLETE
from app.config import OCR_ID_FRONT_RETRY_SCALE
from app.config import OCR_ID_FRONT_USE_DOC_UNWARPING
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
from app.parsers.id_front import IDFrontParser

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
    "business_license": OCR_BUSINESS_LICENSE_DETECTION_SIDE_LIMIT,
}
DEFAULT_DETECTION_SIDE_LIMIT = 960
ID_FRONT_NATION_CROP_SCALE = 4
ID_FRONT_NATION_MIN_SCORE = 0.5
ID_FRONT_GENDER_LABEL_PATTERN = re.compile(r"性[别州期]")
ID_FRONT_NATION_LABEL_PATTERN = re.compile(r"[民闲]族\s*[\u4e00-\u9fff]")
BUSINESS_ADDRESS_KEYWORDS = ("省", "市", "区", "县", "路", "街", "广场", "楼", "层")


def _build_ocr_config(use_fine_tuned: bool = True) -> dict[str, Any]:
    """为 PaddleX OCR pipeline 构造显式配置，可选择官方模型或自训练模型。"""
    configured_doc_unwarping = OCR_USE_DOC_UNWARPING or OCR_ID_FRONT_USE_DOC_UNWARPING
    use_doc_preprocessor = not use_fine_tuned and (
        OCR_ENABLE_DOC_ORIENTATION_MODEL or configured_doc_unwarping
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
        if configured_doc_unwarping:
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
                "use_doc_unwarping": configured_doc_unwarping,
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

        effective_unwarping = self._effective_unwarping(document_type)
        settings = {
            "version": OCR_CACHE_VERSION,
            "model_version": OCR_MODEL_VERSION,
            "profile": OCR_MODEL_PROFILE,
            "model_engine": OCR_MODEL_ENGINE,
            "fine_tuned": OCR_USE_FINE_TUNED_MODEL,
            "inference_backend": OCR_INFERENCE_BACKEND,
            "orientation": self._effective_orientation(auto_orientation),
            "unwarping": effective_unwarping,
            "id_front_quality_retry": OCR_ID_FRONT_QUALITY_RETRY_ENABLED,
            "id_front_retry_on_incomplete": OCR_ID_FRONT_RETRY_ON_INCOMPLETE,
            "id_front_retry_scale": OCR_ID_FRONT_RETRY_SCALE,
            "id_front_retry_blur": OCR_ID_FRONT_RETRY_BLUR_THRESHOLD,
            "id_front_retry_min_side": OCR_ID_FRONT_RETRY_MIN_SIDE,
            "business_scope_roi_retry": OCR_BUSINESS_SCOPE_ROI_RETRY_ENABLED,
            "business_scope_roi_min_chars": OCR_BUSINESS_SCOPE_ROI_MIN_CHARS,
            "business_scope_roi_scale": OCR_BUSINESS_SCOPE_ROI_SCALE,
            "business_field_roi_retry": OCR_BUSINESS_FIELD_ROI_RETRY_ENABLED,
            "business_field_roi_scale": OCR_BUSINESS_FIELD_ROI_SCALE,
            "document_type": document_type,
            "detection_side_limit": self._detection_side_limit(document_type),
            "min_score": effective_min_score,
        }
        serialized = json.dumps(settings, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _effective_unwarping(document_type: Optional[str]) -> bool:
        return OCR_USE_DOC_UNWARPING or (
            document_type == "id_front" and OCR_ID_FRONT_USE_DOC_UNWARPING
        )

    @staticmethod
    def _analyze_image_quality(image_path: str) -> dict[str, Any]:
        """Calculate cheap image-quality signals before deciding on a retry."""
        image = cv2.imread(image_path)
        if image is None:
            return {
                "available": False,
                "retry_risk": False,
                "reasons": ["image_read_failed"],
            }

        height, width = image.shape[:2]
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        mean = float(np.mean(gray))
        blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        clipped_ratio = float(
            np.mean((gray <= 5) | (gray >= 250))
        )
        reasons = []
        if min(height, width) < OCR_ID_FRONT_RETRY_MIN_SIDE:
            reasons.append("low_resolution")
        if blur < OCR_ID_FRONT_RETRY_BLUR_THRESHOLD:
            reasons.append("blur")
        if mean < OCR_ID_FRONT_RETRY_DARK_MEAN:
            reasons.append("underexposed")
        if mean > OCR_ID_FRONT_RETRY_BRIGHT_MEAN:
            reasons.append("overexposed")
        if clipped_ratio > OCR_ID_FRONT_RETRY_CLIPPED_RATIO:
            reasons.append("clipped_highlights_or_shadows")

        return {
            "available": True,
            "width": width,
            "height": height,
            "min_side": min(height, width),
            "mean_gray": round(mean, 3),
            "laplacian_variance": round(blur, 3),
            "clipped_ratio": round(clipped_ratio, 5),
            "retry_risk": bool(reasons),
            "reasons": reasons,
        }

    @staticmethod
    def _is_id_front_retry_candidate(
        document_type: Optional[str], texts: list[str]
    ) -> bool:
        if document_type == "id_front":
            return True
        if document_type is not None:
            return False
        joined = "".join(texts)
        return (
            bool(re.search(r"性[别州期]", joined))
            and "住址" in joined
            and not ("营业执照" in joined or "统一社会信用代码" in joined)
        )

    @staticmethod
    def _id_front_evidence(texts: list[str]) -> dict[str, bool]:
        joined = "".join(texts)
        return {
            "name": "姓名" in joined,
            "gender": bool(re.search(r"性[别州期].*[男女]", joined)),
            "nation": bool(re.search(r"[民族闲]族\s*[\u4e00-\u9fff]", joined)),
            "birthday": bool(
                re.search(r"\d{4}年\d{1,4}月\d{1,4}日", joined)
            ),
            "address": "住址" in joined,
            "id_number": bool(re.search(r"\d{15,18}[0-9Xx]?", joined)),
        }

    @classmethod
    def _id_front_result_rank(cls, result: dict[str, Any]) -> tuple[int, float]:
        evidence = cls._id_front_evidence(result.get("texts", []))
        weights = {
            "name": 2,
            "gender": 1,
            "nation": 1,
            "birthday": 3,
            "address": 2,
            "id_number": 3,
        }
        completeness = sum(
            weight for field, weight in weights.items() if evidence[field]
        )
        scores = result.get("scores", [])
        average_score = sum(scores) / len(scores) if scores else 0.0
        return completeness, average_score

    @staticmethod
    def _scale_ocr_result(result: dict[str, Any], scale: float) -> dict[str, Any]:
        if scale <= 1.0:
            return result

        scaled = dict(result)
        scaled["boxes"] = [
            [int(round(float(value) / scale)) for value in box]
            for box in result.get("boxes", [])
        ]
        scaled["polys"] = [
            [
                [int(round(float(point[0]) / scale)), int(round(float(point[1]) / scale))]
                for point in poly
            ]
            for poly in result.get("polys", [])
        ]
        return scaled

    @staticmethod
    def _id_front_retry_is_safe(
        first_result: dict[str, Any], retry_result: dict[str, Any]
    ) -> tuple[bool, str]:
        """Only accept a retry that fills blanks without changing known fields."""
        try:
            from app.parsers.parser import OCRParser
            from app.utils.layout import build_layout

            parser = OCRParser()
            first = parser.parse(
                build_layout(first_result), document_type="id_front"
            )
            retry = parser.parse(
                build_layout(retry_result), document_type="id_front"
            )
        except Exception:
            return False, "structured_parse_failed"

        fields = ("name", "gender", "nation", "birthday", "address", "id_number")
        filled_fields = []
        for field in fields:
            first_value = str(first.get(field) or "").strip()
            retry_value = str(retry.get(field) or "").strip()
            if first_value and first_value != retry_value:
                return False, "retry_changed_{}".format(field)
            if not first_value and retry_value:
                filled_fields.append(field)

        if not filled_fields:
            return False, "retry_did_not_fill_field"
        return True, "filled_{}".format(",".join(filled_fields))

    def _create_id_front_retry_image(
        self,
        image_path: str,
        output_dir: Optional[Union[str, Path]],
    ) -> tuple[str, float, Optional[str]]:
        image = cv2.imread(image_path)
        if image is None:
            raise ValueError(f"Unable to read image for retry: {image_path}")

        height, width = image.shape[:2]
        scale = OCR_ID_FRONT_RETRY_SCALE
        if max(height, width) * scale > OCR_ID_FRONT_RETRY_MAX_SIDE:
            scale = OCR_ID_FRONT_RETRY_MAX_SIDE / max(height, width)
        scale = max(1.0, scale)
        if scale > 1.0:
            image = cv2.resize(
                image,
                None,
                fx=scale,
                fy=scale,
                interpolation=cv2.INTER_CUBIC,
            )

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=1.6, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        softened = cv2.GaussianBlur(enhanced, (0, 0), 1.0)
        enhanced = cv2.addWeighted(enhanced, 1.25, softened, -0.25, 0)

        temporary_path = None
        if output_dir is not None and OCR_SAVE_PREPROCESSED_IMAGE:
            retry_path = Path(output_dir) / "preprocessed_id_front_retry.jpg"
        else:
            descriptor, temporary_path = tempfile.mkstemp(suffix=".jpg")
            os.close(descriptor)
            retry_path = Path(temporary_path)

        if not cv2.imwrite(
            str(retry_path),
            enhanced,
            [cv2.IMWRITE_JPEG_QUALITY, OCR_PREPROCESSED_JPEG_QUALITY],
        ):
            if temporary_path:
                os.remove(temporary_path)
            raise OSError(f"Failed to save retry image: {retry_path}")
        return str(retry_path), scale, temporary_path

    def _schedule_quality_info(
        self,
        quality_info: dict[str, Any],
        output_dir: Optional[Union[str, Path]],
    ) -> None:
        if output_dir is None:
            return
        output_path = Path(output_dir) / "quality_info.json"

        def save() -> None:
            try:
                with output_path.open("w", encoding="utf-8") as file:
                    json.dump(quality_info, file, ensure_ascii=False, indent=2)
            except OSError as exc:
                logger.warning("Failed to save quality info: {}", exc)

        try:
            self._artifact_executor.submit(save)
        except RuntimeError as exc:
            logger.warning("Failed to schedule quality info save: {}", exc)

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

    def submit_recover_id_front_fields(self, image_path: str, **kwargs):
        """Run conditional ID-front field recovery on the predictor-owning thread."""
        return self._inference_executor.submit(
            self.recover_id_front_fields, image_path, **kwargs
        )

    def submit_recover_business_license_scope(self, image_path: str, **kwargs):
        """Run business-scope ROI recovery on the predictor-owning thread."""
        return self._inference_executor.submit(
            self.recover_business_license_scope, image_path, **kwargs
        )

    def submit_recover_business_license_fields(self, image_path: str, **kwargs):
        """Run missing business-field ROI recovery on the predictor-owning thread."""
        return self._inference_executor.submit(
            self.recover_business_license_fields, image_path, **kwargs
        )

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
        return "营业执照" in joined_text and any(
            label in joined_text for label in ("统一社会信用代码", "注册号", "注册号码")
        )

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

    @staticmethod
    def should_recover_business_license_scope(document: dict[str, Any]) -> bool:
        """Only retry a scope that is missing or clearly shorter than configured."""
        if document.get("type") != "business_license":
            return False
        scope = re.sub(r"\s+", "", str(document.get("business_scope") or ""))
        return not scope or len(scope) < OCR_BUSINESS_SCOPE_ROI_MIN_CHARS

    @staticmethod
    def _business_scope_anchor_index(texts: list[str], boxes: list[list]) -> Optional[int]:
        for index, (text, box) in enumerate(zip(texts, boxes)):
            if len(box) >= 4 and "经营范围" in (text or ""):
                return index
        return None

    @staticmethod
    def _map_crop_box(
        crop_box: list, crop_left: int, crop_top: int, scale: float
    ) -> list[int]:
        return [
            int(crop_left + float(value) / scale)
            if position % 2 == 0
            else int(crop_top + float(value) / scale)
            for position, value in enumerate(crop_box[:4])
        ]

    def recover_business_license_scope(
        self,
        image_path: str,
        ocr_result: dict[str, Any],
        output_dir: Optional[Union[str, Path]] = None,
        request_logger=None,
    ) -> dict[str, Any]:
        """OCR the scope region and return mapped lines without mutating first-pass OCR."""
        metadata = {
            "attempted": False,
            "artifact": None,
            "recognized_line_count": 0,
        }
        empty_result = {"texts": [], "scores": [], "boxes": [], "polys": [], "angle": 0}
        texts = ocr_result.get("texts") or []
        boxes = ocr_result.get("boxes") or []
        anchor_index = self._business_scope_anchor_index(texts, boxes)
        if anchor_index is None:
            metadata["reason"] = "scope_label_not_found"
            return {"result": empty_result, "metadata": metadata}

        image = cv2.imread(image_path)
        if image is None:
            metadata["reason"] = "image_read_failed"
            return {"result": empty_result, "metadata": metadata}

        anchor = boxes[anchor_index]
        left, top, right, bottom = (int(value) for value in anchor[:4])
        anchor_height = max(1, bottom - top)
        image_height, image_width = image.shape[:2]
        footer_tops = [
            int(box[1])
            for text, box in zip(texts, boxes)
            if len(box) >= 4
            and int(box[1]) > bottom
            and any(marker in (text or "") for marker in ("登记机关", "市场监督", "国家企业信用"))
        ]
        crop_left = 0
        crop_right = image_width
        crop_top = max(0, top - anchor_height)
        default_bottom = bottom + max(520, anchor_height * 22)
        crop_bottom = min(image_height, min(footer_tops) if footer_tops else default_bottom)
        if crop_right <= crop_left or crop_bottom <= crop_top:
            metadata["reason"] = "invalid_crop_bounds"
            return {"result": empty_result, "metadata": metadata}

        crop = image[crop_top:crop_bottom, crop_left:crop_right]
        scale = OCR_BUSINESS_SCOPE_ROI_SCALE
        max_side = max(crop.shape[:2])
        if max_side * scale > OCR_BUSINESS_SCOPE_ROI_MAX_SIDE:
            scale = max(1.0, OCR_BUSINESS_SCOPE_ROI_MAX_SIDE / max_side)
        enlarged_crop = crop
        if scale > 1.0:
            enlarged_crop = cv2.resize(
                crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC
            )

        temporary_crop = None
        artifact_name = "business_license_scope_roi.jpg"
        if output_dir is not None:
            crop_path = Path(output_dir) / artifact_name
            metadata["artifact"] = artifact_name
        else:
            descriptor, temporary_crop = tempfile.mkstemp(suffix=".jpg")
            os.close(descriptor)
            crop_path = Path(temporary_crop)

        metadata.update(
            {
                "attempted": True,
                "crop_bounds": [crop_left, crop_top, crop_right, crop_bottom],
                "scale": round(scale, 3),
            }
        )
        try:
            if not cv2.imwrite(str(crop_path), enlarged_crop):
                metadata["reason"] = "crop_write_failed"
                return {"result": empty_result, "metadata": metadata}

            recovered = {"texts": [], "scores": [], "boxes": [], "polys": [], "angle": 0}
            predict_options = {"text_det_limit_side_len": 1280, "text_det_limit_type": "max"}
            if not self.pipeline_uses_fine_tuned_detector:
                predict_options.update(
                    {"use_doc_orientation_classify": False, "use_doc_unwarping": False}
                )
            for prediction in self.pipeline.predict(str(crop_path), **predict_options):
                for index, score in enumerate(prediction["rec_scores"]):
                    if float(score) < OCR_BUSINESS_SCOPE_ROI_MIN_SCORE:
                        continue
                    text = self.postprocess_texts([prediction["rec_texts"][index]])[0]
                    if not text:
                        continue
                    mapped_box = self._map_crop_box(
                        prediction["rec_boxes"][index].tolist(), crop_left, crop_top, scale
                    )
                    recovered["texts"].append(text)
                    recovered["scores"].append(float(score))
                    recovered["boxes"].append(mapped_box)
                    recovered["polys"].append(
                        [
                            [mapped_box[0], mapped_box[1]],
                            [mapped_box[2], mapped_box[1]],
                            [mapped_box[2], mapped_box[3]],
                            [mapped_box[0], mapped_box[3]],
                        ]
                    )
                break
            metadata["recognized_line_count"] = len(recovered["texts"])
            return {"result": recovered, "metadata": metadata}
        except Exception as exc:
            metadata["reason"] = "roi_ocr_failed"
            if request_logger is not None:
                request_logger.warning("Business scope ROI OCR failed: {}", exc)
            return {"result": empty_result, "metadata": metadata}
        finally:
            if temporary_crop:
                try:
                    os.remove(temporary_crop)
                except OSError:
                    pass

    @staticmethod
    def _business_field_anchor_index(
        texts: list[str], boxes: list[list], field: str
    ) -> Optional[int]:
        for index, (text, box) in enumerate(zip(texts, boxes)):
            if len(box) < 4:
                continue
            compact = re.sub(r"\s+", "", text or "")
            if field == "credit_code" and any(
                label in compact
                for label in ("统一社会信用代码", "社会信用代码", "信用代码", "注册号", "注册号码")
            ):
                return index
            if field == "name" and ("名称" in compact or compact in {"名", "称"}):
                return index
            if field == "legal_person" and any(
                label in compact for label in ("法定代表人", "负责人")
            ):
                return index
        return None

    @staticmethod
    def _business_field_crop_bounds(
        field: str,
        anchor_box: list,
        image_width: int,
        image_height: int,
    ) -> tuple[int, int, int, int]:
        left, top, right, bottom = (int(value) for value in anchor_box[:4])
        width = max(1, right - left)
        height = max(1, bottom - top)
        if field == "credit_code":
            crop_left = max(0, left - int(height * 0.5))
            crop_right = min(image_width, right + max(360, int(width * 1.8)))
            crop_top = max(0, top - int(height * 0.8))
            crop_bottom = min(image_height, bottom + max(110, int(height * 3.8)))
        else:
            crop_left = max(0, left - int(height * 0.5))
            crop_right = min(image_width, right + max(260, int(width * 3.2)))
            crop_top = max(0, top - int(height * 1.1))
            crop_bottom = min(image_height, bottom + int(height * 1.5))
        return crop_left, crop_top, crop_right, crop_bottom

    def recover_business_license_fields(
        self,
        image_path: str,
        ocr_result: dict[str, Any],
        fields: list[str],
        output_dir: Optional[Union[str, Path]] = None,
        request_logger=None,
    ) -> dict[str, Any]:
        """Run label-anchored local OCR for missing business-license fields."""
        metadata = {"attempted_fields": [], "artifacts": [], "results": {}}
        texts = ocr_result.get("texts") or []
        boxes = ocr_result.get("boxes") or []
        image = cv2.imread(image_path)
        if image is None:
            metadata["reason"] = "image_read_failed"
            return metadata
        image_height, image_width = image.shape[:2]

        for field in fields:
            anchor_index = self._business_field_anchor_index(texts, boxes, field)
            if anchor_index is None:
                metadata["results"][field] = {"reason": "label_not_found"}
                continue
            crop_left, crop_top, crop_right, crop_bottom = self._business_field_crop_bounds(
                field, boxes[anchor_index], image_width, image_height
            )
            if crop_right <= crop_left or crop_bottom <= crop_top:
                metadata["results"][field] = {"reason": "invalid_crop_bounds"}
                continue
            metadata["attempted_fields"].append(field)
            crop = image[crop_top:crop_bottom, crop_left:crop_right]
            enlarged_crop = cv2.resize(
                crop,
                None,
                fx=OCR_BUSINESS_FIELD_ROI_SCALE,
                fy=OCR_BUSINESS_FIELD_ROI_SCALE,
                interpolation=cv2.INTER_CUBIC,
            )
            temporary_crop = None
            artifact_name = "business_license_{}_roi.jpg".format(field)
            if output_dir is not None:
                crop_path = Path(output_dir) / artifact_name
                metadata["artifacts"].append(artifact_name)
            else:
                descriptor, temporary_crop = tempfile.mkstemp(suffix=".jpg")
                os.close(descriptor)
                crop_path = Path(temporary_crop)
            try:
                if not cv2.imwrite(str(crop_path), enlarged_crop):
                    metadata["results"][field] = {"reason": "crop_write_failed"}
                    continue
                recovered = {"texts": [], "scores": [], "boxes": [], "polys": [], "angle": 0}
                options = {"text_det_limit_side_len": 960, "text_det_limit_type": "max"}
                if not self.pipeline_uses_fine_tuned_detector:
                    options.update(
                        {"use_doc_orientation_classify": False, "use_doc_unwarping": False}
                    )
                for prediction in self.pipeline.predict(str(crop_path), **options):
                    for index, score in enumerate(prediction["rec_scores"]):
                        if float(score) < OCR_BUSINESS_FIELD_ROI_MIN_SCORE:
                            continue
                        text = self.postprocess_texts([prediction["rec_texts"][index]])[0]
                        if not text:
                            continue
                        mapped_box = self._map_crop_box(
                            prediction["rec_boxes"][index].tolist(),
                            crop_left,
                            crop_top,
                            OCR_BUSINESS_FIELD_ROI_SCALE,
                        )
                        recovered["texts"].append(text)
                        recovered["scores"].append(float(score))
                        recovered["boxes"].append(mapped_box)
                        recovered["polys"].append(
                            [
                                [mapped_box[0], mapped_box[1]],
                                [mapped_box[2], mapped_box[1]],
                                [mapped_box[2], mapped_box[3]],
                                [mapped_box[0], mapped_box[3]],
                            ]
                        )
                    break
                metadata["results"][field] = {
                    "reason": "ok",
                    "recognized_line_count": len(recovered["texts"]),
                    "ocr_result": recovered,
                }
            except Exception as exc:
                metadata["results"][field] = {"reason": "roi_ocr_failed"}
                if request_logger is not None:
                    request_logger.warning("Business field ROI failed: field={}, error={}", field, exc)
            finally:
                if temporary_crop:
                    try:
                        os.remove(temporary_crop)
                    except OSError:
                        pass
        return metadata

    @staticmethod
    def _id_front_field_anchor_index(
        texts: list[str], boxes: list[list], field: str
    ) -> Optional[int]:
        """Find the first reliable label box for a locally recoverable field."""
        for index, (text, box) in enumerate(zip(texts, boxes)):
            if not isinstance(box, (list, tuple)) or len(box) < 4:
                continue
            compact = re.sub(r"\s+", "", text or "")
            if field == "name":
                if IDFrontParser._NAME_LABEL_PATTERN.match(compact) or "\u59d3\u540d" in compact:
                    return index
            elif field == "birthday" and "\u51fa\u751f" in compact:
                return index
        return None

    @staticmethod
    def _id_front_field_crop_bounds(
        field: str,
        anchor_box: list,
        image_width: int,
        image_height: int,
    ) -> Optional[tuple[int, int, int, int]]:
        """Return a conservative crop around the value to the right of its label."""
        left, top, right, bottom = (int(value) for value in anchor_box[:4])
        width = max(1, right - left)
        height = max(1, bottom - top)

        if field == "name":
            crop_left = max(0, left - int(height * 0.3))
            crop_right = min(image_width, right + max(180, int(width * 3.5)))
            crop_top = max(0, top - int(height * 0.9))
            crop_bottom = min(image_height, bottom + int(height * 0.9))
        elif field == "birthday":
            crop_left = max(0, left - int(height * 0.4))
            crop_right = min(image_width, right + max(260, int(width * 5.0)))
            crop_top = max(0, top - int(height * 1.1))
            crop_bottom = min(image_height, bottom + int(height * 1.1))
        else:
            return None

        if crop_right <= crop_left or crop_bottom <= crop_top:
            return None
        return crop_left, crop_top, crop_right, crop_bottom

    @staticmethod
    def _map_id_front_crop_box(
        crop_box: list, crop_left: int, crop_top: int, scale: float
    ) -> list[int]:
        """Map a recognizer box from the enlarged crop back to source pixels."""
        return [
            int(crop_left + float(value) / scale)
            if position % 2 == 0
            else int(crop_top + float(value) / scale)
            for position, value in enumerate(crop_box[:4])
        ]

    @staticmethod
    def _id_front_field_candidate(field: str, text: str) -> str:
        """Extract only a valid name or date from one crop recognition result."""
        compact = re.sub(r"\s+", "", text or "")
        if field == "name":
            label_match = IDFrontParser._NAME_LABEL_PATTERN.match(compact)
            if label_match:
                compact = compact[label_match.end():]
            return IDFrontParser._clean_person_name(compact)
        if field == "birthday":
            return IDFrontParser._extract_birthday(compact)
        return ""

    def _recover_id_front_field(
        self,
        image: np.ndarray,
        field: str,
        anchor_box: list,
        output_dir: Optional[Union[str, Path]],
        request_logger,
    ) -> Optional[dict[str, Any]]:
        """Recognize one missing ID-front field from a small enlarged source crop."""
        image_height, image_width = image.shape[:2]
        bounds = self._id_front_field_crop_bounds(
            field, anchor_box, image_width, image_height
        )
        if bounds is None:
            return None
        crop_left, crop_top, crop_right, crop_bottom = bounds
        crop = image[crop_top:crop_bottom, crop_left:crop_right]
        enlarged_crop = cv2.resize(
            crop,
            None,
            fx=OCR_ID_FRONT_FIELD_ROI_SCALE,
            fy=OCR_ID_FRONT_FIELD_ROI_SCALE,
            interpolation=cv2.INTER_CUBIC,
        )

        temporary_crop = None
        artifact_name = "id_front_{}_roi.jpg".format(field)
        if output_dir is not None:
            crop_path = Path(output_dir) / artifact_name
        else:
            descriptor, temporary_crop = tempfile.mkstemp(suffix=".jpg")
            os.close(descriptor)
            crop_path = Path(temporary_crop)

        try:
            if not cv2.imwrite(str(crop_path), enlarged_crop):
                request_logger.warning("ID-front field ROI skipped: failed to save crop")
                return None

            predict_options = {
                "text_det_limit_side_len": 960,
                "text_det_limit_type": "max",
            }
            if not self.pipeline_uses_fine_tuned_detector:
                predict_options.update(
                    {
                        "use_doc_orientation_classify": False,
                        "use_doc_unwarping": False,
                    }
                )

            for result in self.pipeline.predict(str(crop_path), **predict_options):
                for index, score in enumerate(result["rec_scores"]):
                    if float(score) < OCR_ID_FRONT_FIELD_ROI_MIN_SCORE:
                        continue
                    recognized_text = self.postprocess_texts(
                        [result["rec_texts"][index]]
                    )[0]
                    candidate = self._id_front_field_candidate(field, recognized_text)
                    if not candidate:
                        continue
                    mapped_box = self._map_id_front_crop_box(
                        result["rec_boxes"][index].tolist(),
                        crop_left,
                        crop_top,
                        OCR_ID_FRONT_FIELD_ROI_SCALE,
                    )
                    return {
                        "field": field,
                        "text": candidate,
                        "score": float(score),
                        "box": mapped_box,
                        "artifact": artifact_name if output_dir is not None else None,
                    }
        except Exception as exc:
            request_logger.warning("ID-front field ROI OCR failed: field={}, error={}", field, exc)
        finally:
            if temporary_crop:
                try:
                    os.remove(temporary_crop)
                except OSError:
                    pass
        return None

    def recover_id_front_fields(
        self,
        image_path: str,
        ocr_result: dict[str, Any],
        document: dict[str, Any],
        output_dir: Optional[Union[str, Path]] = None,
        request_logger=None,
    ) -> dict[str, Any]:
        """Append validated local OCR evidence only for missing name/birthday fields."""
        metadata = {
            "attempted_fields": [],
            "recovered_fields": [],
            "artifacts": [],
        }
        if document.get("type") != "id_front":
            return metadata

        missing_fields = [
            field for field in ("name", "birthday") if not document.get(field)
        ]
        if not missing_fields:
            return metadata

        texts = ocr_result.get("texts")
        scores = ocr_result.get("scores")
        boxes = ocr_result.get("boxes")
        polys = ocr_result.get("polys")
        if not all(isinstance(value, list) for value in (texts, scores, boxes, polys)):
            return metadata

        image = cv2.imread(image_path)
        if image is None:
            request_logger.warning("ID-front field ROI skipped: failed to load image")
            return metadata

        for field in missing_fields:
            anchor_index = self._id_front_field_anchor_index(texts, boxes, field)
            if anchor_index is None:
                continue
            metadata["attempted_fields"].append(field)
            recovered = self._recover_id_front_field(
                image, field, boxes[anchor_index], output_dir, request_logger
            )
            if recovered is None:
                continue

            mapped_box = recovered["box"]
            texts.append(recovered["text"])
            scores.append(recovered["score"])
            boxes.append(mapped_box)
            polys.append(
                [
                    [mapped_box[0], mapped_box[1]],
                    [mapped_box[2], mapped_box[1]],
                    [mapped_box[2], mapped_box[3]],
                    [mapped_box[0], mapped_box[3]],
                ]
            )
            metadata["recovered_fields"].append(field)
            if recovered["artifact"]:
                metadata["artifacts"].append(recovered["artifact"])
            request_logger.info(
                "ID-front field recovered from ROI: field={}, score={:.3f}",
                field,
                recovered["score"],
            )

        return metadata

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
        effective_unwarping = self._effective_unwarping(document_type)
        detection_side_limit = self._detection_side_limit(document_type)
        effective_min_score = min_score
        if document_type == "id_front":
            effective_min_score = min(min_score, OCR_ID_FRONT_MIN_SCORE)
        quality_info = {
            "document_type": document_type or "auto",
            "retry_enabled": bool(
                OCR_ID_FRONT_QUALITY_RETRY_ENABLED
                and document_type == "id_front"
            ),
        }
        retry_temp_path = None
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
                        "use_doc_unwarping": effective_unwarping,
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

                first_result = {
                    "texts": texts,
                    "scores": scores,
                    "boxes": boxes,
                    "polys": polys,
                    "angle": doc_preprocessor_res.get("angle", 0)
                    if (doc_preprocessor_res := result.get("doc_preprocessor_res") or {})
                    else 0,
                }

                # 低质量身份证正面只做一次条件重试；正常图片和其它证件不增加推理。
                retry_candidate = self._is_id_front_retry_candidate(
                    document_type, texts
                )
                evidence = self._id_front_evidence(texts) if retry_candidate else {}
                incomplete = retry_candidate and not all(evidence.values())
                if (
                    retry_candidate
                    and OCR_ID_FRONT_QUALITY_RETRY_ENABLED
                    and "available" not in quality_info
                ):
                    quality_info.update(self._analyze_image_quality(image_path))
                quality_info["retry_enabled"] = bool(
                    OCR_ID_FRONT_QUALITY_RETRY_ENABLED and retry_candidate
                )
                should_retry = bool(
                    OCR_ID_FRONT_QUALITY_RETRY_ENABLED
                    and retry_candidate
                    and not effective_unwarping
                    and (
                        quality_info.get("retry_risk", False)
                        or (
                            OCR_ID_FRONT_RETRY_ON_INCOMPLETE
                            and incomplete
                        )
                    )
                )
                quality_info.update(
                    {
                        "first_pass_evidence": evidence,
                        "first_pass_incomplete": incomplete,
                        "retry_triggered": should_retry,
                    }
                )

                selected_result = first_result
                if should_retry:
                    try:
                        retry_path, retry_scale, retry_temp_path = (
                            self._create_id_front_retry_image(image_path, output_dir)
                        )
                        retry_started_at = time.perf_counter()
                        retry_options = {
                            "text_det_limit_side_len": detection_side_limit,
                            "text_det_limit_type": "max",
                        }
                        if not self.pipeline_uses_fine_tuned_detector:
                            retry_options.update(
                                {
                                    "use_doc_orientation_classify": effective_orientation,
                                    "use_doc_unwarping": False,
                                }
                            )

                        retry_result = None
                        for retry_prediction in self.pipeline.predict(
                            retry_path, **retry_options
                        ):
                            retry_texts = []
                            retry_scores = []
                            retry_boxes = []
                            retry_polys = []
                            for index, score in enumerate(
                                retry_prediction["rec_scores"]
                            ):
                                if score >= effective_min_score:
                                    retry_texts.append(
                                        retry_prediction["rec_texts"][index]
                                    )
                                    retry_scores.append(float(score))
                                    retry_boxes.append(
                                        retry_prediction["rec_boxes"][index].tolist()
                                    )
                                    retry_polys.append(
                                        retry_prediction["dt_polys"][index].tolist()
                                    )
                            retry_texts = self.postprocess_texts(retry_texts)
                            retry_result = {
                                "texts": retry_texts,
                                "scores": retry_scores,
                                "boxes": retry_boxes,
                                "polys": retry_polys,
                                "angle": (
                                    retry_prediction.get("doc_preprocessor_res") or {}
                                ).get("angle", 0),
                            }

                            self._recover_id_front_nation(
                                retry_path,
                                retry_texts,
                                retry_scores,
                                retry_boxes,
                                retry_polys,
                                output_dir,
                                request_logger,
                                document_type,
                            )

                        retry_ms = (time.perf_counter() - retry_started_at) * 1000
                        quality_info["retry_duration_ms"] = round(retry_ms, 2)
                        quality_info["retry_scale"] = round(retry_scale, 3)
                        if retry_result is not None:
                            first_rank = self._id_front_result_rank(first_result)
                            retry_rank = self._id_front_result_rank(retry_result)
                            quality_info["first_pass_rank"] = first_rank
                            quality_info["retry_rank"] = retry_rank
                            if retry_rank > first_rank:
                                retry_is_safe, retry_reason = (
                                    self._id_front_retry_is_safe(
                                        first_result, retry_result
                                    )
                                )
                                quality_info["retry_selection_reason"] = retry_reason
                                if retry_is_safe:
                                    selected_result = self._scale_ocr_result(
                                        retry_result, retry_scale
                                    )
                                    quality_info["selected_pass"] = "retry"
                                else:
                                    quality_info["selected_pass"] = "first"
                            else:
                                quality_info["selected_pass"] = "first"
                        request_logger.info(
                            "ID front quality retry completed: selected={}, duration_ms={:.2f}",
                            quality_info.get("selected_pass", "first"),
                            retry_ms,
                        )
                    except Exception as exc:
                        quality_info["retry_error"] = str(exc)
                        request_logger.warning(
                            "ID front quality retry failed; keeping first result: {}",
                            exc,
                        )

                self._schedule_quality_info(quality_info, output_dir)
                if not self.pipeline_uses_fine_tuned_detector and (
                    effective_orientation or effective_unwarping
                ):
                    self._schedule_platform_preprocessed_image(
                        doc_preprocessor_res, output_dir, request_logger
                    )

                return selected_result

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
            if retry_temp_path and os.path.exists(retry_temp_path):
                try:
                    os.remove(retry_temp_path)
                except OSError as exc:
                    logger.warning("Failed to clean retry image: {}", exc)


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
