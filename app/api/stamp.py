"""印章 OCR 接口。"""

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, Query, UploadFile
from starlette.concurrency import run_in_threadpool

from app.config import OUTPUT_DIR, UPLOAD_DIR
from app.schemas.response import ApiResponse
from app.services.stamp_service import StampServiceTimeout, StampServiceUnavailable, stamp_service
from app.utils.logger import logger
from app.utils.request_context import get_request_id


router = APIRouter(prefix="/api/ocr", tags=["Stamp OCR"])


def _suffix(filename: Optional[str]) -> str:
    suffix = Path((filename or "").replace("\\", "/")).suffix.lower()
    return suffix if re.fullmatch(r"\.[a-z0-9]{1,10}", suffix) else ".bin"


async def _save_upload(file: UploadFile, request_id: str) -> Path:
    directory = UPLOAD_DIR / request_id
    output_dir = OUTPUT_DIR / request_id
    directory.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = directory / ("original" + _suffix(file.filename))
    digest = hashlib.sha256()
    with path.open("wb") as target:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            target.write(chunk)
            digest.update(chunk)
    with (output_dir / "upload_info.json").open("w", encoding="utf-8") as info:
        json.dump({"original_filename": file.filename, "stored_filename": path.name,
                   "content_type": file.content_type, "file_size": path.stat().st_size,
                   "sha256": digest.hexdigest()}, info, ensure_ascii=False, indent=2)
    return path


async def _recognize_stamp(path: Path, request_id: str, output_dir: Path, debug: bool, prefix: str) -> dict:
    content = await run_in_threadpool(path.read_bytes)
    image = await run_in_threadpool(stamp_service.decode_image, content)
    return await run_in_threadpool(stamp_service.recognize_image, image, request_id, output_dir, debug, prefix)


@router.post(
    "/stamp",
    summary="单印章文字识别",
    response_description="印章形状、展开后的文字、文字框和置信度；不执行审核或对比",
)
async def recognize_stamp(
    file: UploadFile = File(..., description="单个印章图片，支持 JPG、PNG、WEBP；透明 PNG 优先使用 Alpha 前景。"),
    debug: bool = Query(False, description="是否保存印章 mask 和圆章/椭圆章展开图，便于排查。"),
):
    request_id = get_request_id() or uuid.uuid4().hex
    output_dir = OUTPUT_DIR / request_id
    request_logger = logger.bind(request_id=request_id)
    try:
        path = await _save_upload(file, request_id)
        result = await _recognize_stamp(path, request_id, output_dir, debug, "stamp")
        if not result.get("text"):
            request_logger.warning("Stamp OCR returned no text")
            return ApiResponse.error("印章图片无法识别", code=4001, request_id=request_id)
        with (output_dir / "stamp_result.json").open("w", encoding="utf-8") as saved:
            json.dump(result, saved, ensure_ascii=False, indent=2)
        return ApiResponse.success({"type": "stamp", **result}, request_id=request_id)
    except (ValueError, OSError) as exc:
        request_logger.warning("Stamp image failed: {}", exc)
        return ApiResponse.error("印章图片无法识别", code=4001, request_id=request_id)
    except Exception:
        request_logger.exception("Stamp OCR failed")
        return ApiResponse.error("印章 OCR 服务异常", code=5001, request_id=request_id)
    finally:
        await file.close()


@router.post(
    "/document-stamps",
    summary="多印章文档文字识别",
    response_description="调用 stamp-ai-service 获取印章裁切图后逐个识别，不执行审核或对比",
)
async def recognize_document_stamps(
    file: UploadFile = File(..., description="整张采集表、合同或票据图片。印章检测由 stamp-ai-service 完成。"),
    debug: bool = Query(False, description="是否保存每个印章的展开图和 OCR 中间图。"),
):
    request_id = get_request_id() or uuid.uuid4().hex
    output_dir = OUTPUT_DIR / request_id
    request_logger = logger.bind(request_id=request_id)
    try:
        path = await _save_upload(file, request_id)
        extracted = await run_in_threadpool(stamp_service.extract_remote, path)
        stamps = []
        for index, item in enumerate(extracted, start=1):
            crop_path = output_dir / ("stamp_{:03d}.png".format(index))
            crop_path.write_bytes(item["image"])
            try:
                result = await _recognize_stamp(crop_path, request_id, output_dir, debug, "stamp_{:03d}".format(index))
            except Exception as exc:
                request_logger.warning("Stamp {} OCR failed: {}", index, exc)
                result = {"shape": "unknown", "shape_confidence": 0.0, "text": "", "confidence": 0.0, "words": [], "error": "印章 OCR 失败"}
            result["index"] = index
            result["box"] = item.get("box", {})
            stamps.append(result)
        result = {"type": "stamp_document", "count": len(stamps), "stamps": stamps}
        with (output_dir / "stamp_document_result.json").open("w", encoding="utf-8") as saved:
            json.dump(result, saved, ensure_ascii=False, indent=2)
        return ApiResponse.success(result, request_id=request_id)
    except StampServiceTimeout as exc:
        request_logger.error("Stamp dependency timed out: {}", exc)
        return ApiResponse.error("印章检测依赖服务超时: {}".format(exc), code=5041, request_id=request_id)
    except StampServiceUnavailable as exc:
        request_logger.error("Stamp dependency failed: {}", exc)
        return ApiResponse.error("印章检测依赖服务不可用: {}".format(exc), code=5021, request_id=request_id)
    except (ValueError, OSError) as exc:
        request_logger.warning("Document stamp image failed: {}", exc)
        return ApiResponse.error("印章文档图片无法识别", code=4001, request_id=request_id)
    except Exception:
        request_logger.exception("Document stamp OCR failed")
        return ApiResponse.error("多印章 OCR 服务异常", code=5001, request_id=request_id)
    finally:
        await file.close()
