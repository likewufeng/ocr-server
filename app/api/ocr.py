import asyncio
import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, File, Query, Response, UploadFile
from starlette.concurrency import run_in_threadpool

from app.config import (
    OCR_ID_FRONT_FIELD_ROI_RETRY_ENABLED,
    OCR_MAX_CONCURRENT_REQUESTS,
    OUTPUT_DIR,
    UPLOAD_DIR,
)
from app.parsers.parser import OCRParser
from app.schemas.response import ApiResponse
from app.services.ocr_service import ocr_service
from app.utils.layout import build_layout
from app.utils.logger import logger
from app.utils.metrics import metrics
from app.utils.ocr_cache import ocr_cache
from app.utils.request_context import get_request_id


router = APIRouter(prefix="", tags=["OCR"])
parser = OCRParser()
ocr_slots = asyncio.Semaphore(OCR_MAX_CONCURRENT_REQUESTS)
DocumentType = Literal[
    "id_front", "id_back", "business_license", "bank_card", "invoice"
]


def _safe_extension(filename: Optional[str]) -> str:
    normalized = (filename or "").replace("\\", "/")
    basename = normalized.rsplit("/", 1)[-1]
    extension = Path(basename).suffix.lower()
    if re.fullmatch(r"\.[a-z0-9]{1,10}", extension):
        return extension
    return ".bin"


def _prepare_request_paths(file: UploadFile, request_id: str) -> tuple[Path, Path]:
    upload_dir = UPLOAD_DIR / request_id
    output_dir = OUTPUT_DIR / request_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir / f"original{_safe_extension(file.filename)}", output_dir


def _save_json(path: Path, data: object) -> None:
    with path.open("w", encoding="utf-8") as output_file:
        json.dump(data, output_file, ensure_ascii=False, indent=2)


def _save_upload_info(
    file: UploadFile, path: Path, output_dir: Path, content_sha256: str
) -> None:
    _save_json(
        output_dir / "upload_info.json",
        {
            "original_filename": file.filename,
            "stored_filename": path.name,
            "content_type": file.content_type,
            "file_size": path.stat().st_size,
            "sha256": content_sha256,
        },
    )


def _persist_upload(file: UploadFile, path: Path, output_dir: Path) -> str:
    content_hash = hashlib.sha256()
    with path.open("wb") as upload_file:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            upload_file.write(chunk)
            content_hash.update(chunk)

    content_sha256 = content_hash.hexdigest()
    _save_upload_info(file, path, output_dir, content_sha256)
    return content_sha256


def _cache_key(
    content_sha256: str,
    document_type: Optional[str],
    auto_orientation: Optional[bool],
) -> str:
    signature = ocr_service.cache_signature(document_type, auto_orientation)
    return hashlib.sha256(
        f"{content_sha256}:{signature}".encode("ascii")
    ).hexdigest()


async def _recognize(
    path: Path,
    request_id: str,
    output_dir: Path,
    request_logger,
    cache_key: str,
    document_type: Optional[str],
    auto_orientation: Optional[bool],
) -> tuple[dict, bool]:
    metric_document_type = document_type or "auto"
    cached_result = await run_in_threadpool(ocr_cache.get, cache_key)
    if cached_result is not None:
        metrics.record_cache("hit")
        request_logger.info("OCR cache hit before queue: key={}", cache_key)
        return cached_result, True

    queued_at = time.perf_counter()
    metrics.queue_started()
    slot_acquired = False
    try:
        await ocr_slots.acquire()
        slot_acquired = True
        queue_seconds = time.perf_counter() - queued_at
        metrics.queue_acquired(metric_document_type, queue_seconds)
        queue_ms = queue_seconds * 1000
        request_logger.info("OCR execution slot acquired: queue_ms={:.2f}", queue_ms)
        cached_result = await run_in_threadpool(ocr_cache.get, cache_key)
        if cached_result is not None:
            metrics.record_cache("hit")
            request_logger.info("OCR cache hit after queue: key={}", cache_key)
            return cached_result, True

        metrics.record_cache("miss")
        metrics.inference_started()
        try:
            result = await asyncio.wrap_future(
                ocr_service.submit_recognize(
                    str(path),
                    request_id=request_id,
                    output_dir=output_dir,
                    document_type=document_type,
                    auto_orientation=auto_orientation,
                )
            )
        finally:
            metrics.inference_completed()
        await run_in_threadpool(ocr_cache.set, cache_key, result)
        request_logger.info("OCR cache stored: key={}", cache_key)
        return result, False
    finally:
        if slot_acquired:
            ocr_slots.release()
        else:
            metrics.queue_abandoned()


@router.post(
    "/ocr",
    summary="证件 OCR 识别",
    response_description="结构化证件识别结果",
)
async def ocr(
    response: Response,
    file: UploadFile = File(
        ...,
        description=(
            "待识别的证件或票据图片。支持项目当前 OCR 能读取的 JPG、JPEG、"
            "PNG、WEBP 等图片格式；原文件会按本次 request_id 保存到 "
            "data/uploads/{request_id}/。"
        ),
    ),
    document_type: Optional[DocumentType] = Query(
        default=None,
        description=(
            "可选的文档类型提示。调用方已明确图片类型时建议传入，可跳过自动"
            "类型判断，并使用对应的推理参数；身份证正反面还会使用更快的检测"
            "尺寸。可选值：id_front（身份证正面）、id_back（身份证反面）、"
            "business_license（营业执照）、bank_card（银行卡）、invoice（发票）。"
            "不传时由 OCR 文本自动判断类型。传错类型可能导致字段解析错误。"
        ),
    ),
    auto_orientation: Optional[bool] = Query(
        default=None,
        description=(
            "是否执行图片方向检测和自动旋转。true：适合手机拍摄、图片方向不确定"
            "的场景，会增加少量推理耗时；false：适合调用方已保证图片方向正确的"
            "场景，响应更快。不传时使用服务端 OCR_USE_DOC_ORIENTATION 配置，"
            "当前默认值为 true。"
        ),
    ),
):
    """
    识别身份证、营业执照、银行卡和发票，并返回结构化字段。

    默认会执行图片方向检测，适合手机拍摄等方向不可控的场景。调用方明确证件
    类型时建议传入 `document_type`；只有在调用方能够保证图片方向正确时，才建议
    显式设置 `auto_orientation=false` 来减少方向模型的推理开销。相同图片和推理
    参数会复用一天内的 OCR 缓存，但每次调用仍会生成独立的 `request_id`。
    """
    request_id = get_request_id() or uuid.uuid4().hex
    request_logger = logger.bind(request_id=request_id)
    path, output_dir = _prepare_request_paths(file, request_id)
    cache_status = "unknown"

    try:
        content_sha256 = await run_in_threadpool(
            _persist_upload, file, path, output_dir
        )
        request_logger.info("Original upload saved: {}", path)

        cache_key = _cache_key(content_sha256, document_type, auto_orientation)
        ocr_result, cache_hit = await _recognize(
            path,
            request_id,
            output_dir,
            request_logger,
            cache_key,
            document_type,
            auto_orientation,
        )
        response.headers["X-OCR-Cache"] = "HIT" if cache_hit else "MISS"
        cache_status = "hit" if cache_hit else "miss"
        layout = build_layout(ocr_result)
        document = parser.parse(layout, document_type=document_type)
        field_roi_recovery = None
        if (
            OCR_ID_FRONT_FIELD_ROI_RETRY_ENABLED
            and document.get("type") == "id_front"
            and (not document.get("name") or not document.get("birthday"))
        ):
            field_roi_recovery = await asyncio.wrap_future(
                ocr_service.submit_recover_id_front_fields(
                    str(path),
                    ocr_result=ocr_result,
                    document=document,
                    output_dir=output_dir,
                    request_logger=request_logger,
                )
            )
            if field_roi_recovery["recovered_fields"]:
                layout = build_layout(ocr_result)
                document = parser.parse(layout, document_type=document_type)
            await run_in_threadpool(
                _save_json,
                output_dir / "field_roi_recovery.json",
                field_roi_recovery,
            )

        await run_in_threadpool(
            _save_json, output_dir / "ocr_result.json", ocr_result
        )
        await run_in_threadpool(
            _save_json, output_dir / "parsed_result.json", document
        )
        await run_in_threadpool(
            _save_json,
            output_dir / "cache_info.json",
            {
                "cache_hit": cache_hit,
                "cache_key": cache_key,
                "sha256": content_sha256,
            },
        )

        request_logger.info(
            "OCR request completed: document_type={}, cache_hit={}",
            document.get("type"),
            cache_hit,
        )
        metrics.record_ocr_request(
            document.get("type") or document_type or "unknown",
            cache_status,
            "success",
        )
        return ApiResponse.success(document, request_id=request_id)
    except Exception:
        metrics.record_ocr_request(
            document_type or "auto", cache_status, "error"
        )
        request_logger.exception("OCR request failed")
        raise
    finally:
        await file.close()


@router.post(
    "/ocr/raw",
    summary="原始 OCR 识别",
    response_description="OCR 文本、置信度及坐标结果",
)
async def ocr_raw(
    response: Response,
    file: UploadFile = File(
        ...,
        description="待识别的原始图片文件。",
    ),
    document_type: Optional[DocumentType] = Query(
        default=None,
        description=(
            "可选的文档类型提示，用于选择对应推理参数；不传时使用通用参数。"
        ),
    ),
    auto_orientation: Optional[bool] = Query(
        default=None,
        description=(
            "是否执行图片方向检测和自动旋转；不传时使用服务端配置。"
        ),
    ),
):
    """执行 OCR 并返回文本、置信度和坐标等原始识别结果。"""
    request_id = get_request_id() or uuid.uuid4().hex
    request_logger = logger.bind(request_id=request_id)
    path, output_dir = _prepare_request_paths(file, request_id)
    cache_status = "unknown"

    try:
        content_sha256 = await run_in_threadpool(
            _persist_upload, file, path, output_dir
        )
        request_logger.info("Original upload saved: {}", path)

        cache_key = _cache_key(content_sha256, document_type, auto_orientation)
        ocr_result, cache_hit = await _recognize(
            path,
            request_id,
            output_dir,
            request_logger,
            cache_key,
            document_type,
            auto_orientation,
        )
        response.headers["X-OCR-Cache"] = "HIT" if cache_hit else "MISS"
        cache_status = "hit" if cache_hit else "miss"
        await run_in_threadpool(
            _save_json, output_dir / "ocr_result.json", ocr_result
        )
        await run_in_threadpool(
            _save_json,
            output_dir / "cache_info.json",
            {
                "cache_hit": cache_hit,
                "cache_key": cache_key,
                "sha256": content_sha256,
            },
        )

        request_logger.info("Raw OCR request completed: cache_hit={}", cache_hit)
        metrics.record_ocr_request(
            document_type or "auto", cache_status, "success"
        )
        return ApiResponse.success(ocr_result, request_id=request_id)
    except Exception:
        metrics.record_ocr_request(
            document_type or "auto", cache_status, "error"
        )
        request_logger.exception("Raw OCR request failed")
        raise
    finally:
        await file.close()
