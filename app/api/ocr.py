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

from app.config import OCR_MAX_CONCURRENT_REQUESTS, OUTPUT_DIR, UPLOAD_DIR
from app.parsers.parser import OCRParser
from app.schemas.response import ApiResponse
from app.services.ocr_service import ocr_service
from app.utils.layout import build_layout
from app.utils.logger import logger
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
    cached_result = await run_in_threadpool(ocr_cache.get, cache_key)
    if cached_result is not None:
        request_logger.info("OCR cache hit before queue: key={}", cache_key)
        return cached_result, True

    queued_at = time.perf_counter()
    async with ocr_slots:
        queue_ms = (time.perf_counter() - queued_at) * 1000
        request_logger.info("OCR execution slot acquired: queue_ms={:.2f}", queue_ms)
        cached_result = await run_in_threadpool(ocr_cache.get, cache_key)
        if cached_result is not None:
            request_logger.info("OCR cache hit after queue: key={}", cache_key)
            return cached_result, True

        result = await run_in_threadpool(
            ocr_service.recognize,
            str(path),
            request_id=request_id,
            output_dir=output_dir,
            document_type=document_type,
            auto_orientation=auto_orientation,
        )
        await run_in_threadpool(ocr_cache.set, cache_key, result)
        request_logger.info("OCR cache stored: key={}", cache_key)
        return result, False


@router.post("/ocr")
async def ocr(
    response: Response,
    file: UploadFile = File(...),
    document_type: Optional[DocumentType] = Query(default=None),
    auto_orientation: Optional[bool] = Query(default=None),
):
    request_id = get_request_id() or uuid.uuid4().hex
    request_logger = logger.bind(request_id=request_id)
    path, output_dir = _prepare_request_paths(file, request_id)

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
        await run_in_threadpool(
            _save_json, output_dir / "ocr_result.json", ocr_result
        )

        layout = build_layout(ocr_result)
        document = parser.parse(layout, document_type=document_type)
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
        return ApiResponse.success(document, request_id=request_id)
    except Exception:
        request_logger.exception("OCR request failed")
        raise
    finally:
        await file.close()


@router.post("/ocr/raw")
async def ocr_raw(
    response: Response,
    file: UploadFile = File(...),
    document_type: Optional[DocumentType] = Query(default=None),
    auto_orientation: Optional[bool] = Query(default=None),
):
    request_id = get_request_id() or uuid.uuid4().hex
    request_logger = logger.bind(request_id=request_id)
    path, output_dir = _prepare_request_paths(file, request_id)

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
        return ApiResponse.success(ocr_result, request_id=request_id)
    except Exception:
        request_logger.exception("Raw OCR request failed")
        raise
    finally:
        await file.close()
