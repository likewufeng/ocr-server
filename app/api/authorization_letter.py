"""授权委托书解析 API。"""

import hashlib
import json
import re
from pathlib import Path
from typing import Optional, Set, Tuple

import fitz
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from starlette.concurrency import run_in_threadpool

from app.config import OUTPUT_DIR, UPLOAD_DIR
from app.parsers.authorization_letter import AuthorizationLetterParser
from app.schemas.response import ApiResponse
from app.services.authorization_letter_service import authorization_letter_service
from app.utils.logger import logger
from app.utils.request_context import get_request_id


router = APIRouter(prefix="/authorization", tags=["Authorization Letter"])
text_parser = AuthorizationLetterParser()
SUPPORTED_DOCUMENT_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}


def _safe_suffix(filename: Optional[str]) -> str:
    suffix = Path((filename or "").replace("\\", "/")).suffix.lower()
    return suffix if re.fullmatch(r"\.[a-z0-9]{1,10}", suffix) else ".bin"


async def _persist_upload(
    file: UploadFile, request_id: str, allowed_suffixes: Set[str]
) -> Tuple[Path, Path, int]:
    suffix = _safe_suffix(file.filename)
    if suffix not in allowed_suffixes:
        allowed = "、".join(sorted(value.lstrip(".").upper() for value in allowed_suffixes))
        raise HTTPException(status_code=400, detail=f"仅支持 {allowed} 文件")

    upload_dir = UPLOAD_DIR / request_id
    output_dir = OUTPUT_DIR / request_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = upload_dir / f"original{suffix}"
    digest = hashlib.sha256()
    size = 0
    with path.open("wb") as output:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    with (output_dir / "upload_info.json").open("w", encoding="utf-8") as output:
        json.dump(
            {
                "original_filename": file.filename,
                "stored_filename": path.name,
                "content_type": file.content_type,
                "file_size": size,
                "sha256": digest.hexdigest(),
            },
            output,
            ensure_ascii=False,
            indent=2,
        )
    return path, output_dir, size


async def _parse_uploaded_document(file: UploadFile):
    request_id = get_request_id() or "-"
    request_logger = logger.bind(request_id=request_id)
    path, output_dir, file_size = await _persist_upload(
        file, request_id, SUPPORTED_DOCUMENT_SUFFIXES
    )
    request_logger.info("Authorization source saved: {}", path)
    try:
        result = await authorization_letter_service.parse_document(
            path, output_dir, request_id
        )
        result["metadata"]["filename"] = file.filename
        result["metadata"]["file_size"] = file_size
        return ApiResponse.success(result)
    except HTTPException:
        raise
    except Exception as exc:
        request_logger.exception("Authorization letter parsing failed")
        return ApiResponse.error(f"授权委托书解析失败: {exc}")


@router.post(
    "/letter/parse",
    summary="解析授权委托书",
    response_description="授权书字段、附件和一致性校验结果",
)
async def parse_authorization_letter(
    file: UploadFile = File(
        ...,
        description=(
            "授权委托书 PDF 或扫描图片。文本型 PDF 优先读取原生字符层；扫描页、"
            "粘贴的身份证正反面及图片型文件会调用当前 PP-OCRv6 模型识别。"
        ),
    ),
):
    """完整解析授权书；与 /letter/parse-ocr 使用同一条生产链路。"""
    return await _parse_uploaded_document(file)


@router.post(
    "/letter/parse-ocr",
    summary="解析扫描或混合型授权委托书",
    response_description="授权书字段、身份证附件、签章证据和一致性校验结果",
)
async def parse_authorization_letter_ocr(
    file: UploadFile = File(
        ...,
        description=(
            "支持 PDF、JPG、JPEG、PNG、WEBP。适用于打印后手写签名、粘贴身份证"
            "复印件、加盖实体印章，再扫描形成的最终材料。接口只检测签名和印章"
            "是否存在，不验证真伪。"
        ),
    ),
):
    """
    采用混合策略解析文档：

    - 文本 PDF 直接读取字符层，减少整页 OCR 延迟。
    - 扫描页使用当前 PP-OCRv6 模型。
    - 身份证区域单独裁剪识别，并复用身份证正反面解析器。
    - 返回正文受托人与身份证附件的姓名、号码一致性校验。
    - 手写签名和红色印章只返回存在性证据，必须人工核验真实性。
    """
    return await _parse_uploaded_document(file)


@router.post(
    "/letter/parse-text",
    summary="解析授权委托书文本",
    response_description="从调用方提供的文本中提取授权书字段",
)
async def parse_authorization_letter_text(
    text: str = Query(
        ...,
        min_length=1,
        description=(
            "已从授权委托书提取出的正文文本。该接口不处理身份证附件，也不检测"
            "签名和印章；需要完整材料检查时应调用 /letter/parse-ocr。"
        ),
    )
):
    try:
        parsed = await run_in_threadpool(text_parser.parse_text_content, text)
        parsed.update(
            {
                "source": "provided_text",
                "pages": [],
                "delegator_signature": {
                    "status": "not_checked",
                    "manual_review_required": True,
                },
                "trustee_signature": {
                    "status": "not_checked",
                    "manual_review_required": True,
                },
                "seal": {
                    "status": "not_checked",
                    "manual_review_required": True,
                },
                "review_required": True,
            }
        )
        return ApiResponse.success(text_parser.to_dict(parsed))
    except Exception as exc:
        logger.exception("Authorization text parsing failed")
        return ApiResponse.error(f"授权委托书文本解析失败: {exc}")


@router.post(
    "/letter/parse-raw",
    summary="读取授权书 PDF 原始文本",
    response_description="PDF 每页原生字符层，不执行 OCR",
)
async def parse_authorization_letter_raw(
    file: UploadFile = File(
        ...,
        description=(
            "仅支持 PDF。返回每页原生字符层，扫描页通常为空；该接口用于排查 PDF"
            "本身是否包含可提取文本，不执行身份证、签名或印章识别。"
        ),
    ),
):
    request_id = get_request_id() or "-"
    path, output_dir, file_size = await _persist_upload(file, request_id, {".pdf"})
    try:
        document = fitz.open(str(path))
        try:
            pages = []
            raw_text_parts = []
            for index, page in enumerate(document, start=1):
                page_text = page.get_text("text") or ""
                pages.append(
                    {
                        "page_number": index,
                        "text": page_text,
                        "char_count": len(page_text),
                    }
                )
                raw_text_parts.append(page_text)
        finally:
            document.close()
        result = {
            "filename": file.filename,
            "file_size": file_size,
            "pages_count": len(pages),
            "pages": pages,
            "raw_text": "\n".join(raw_text_parts),
        }
        with (output_dir / "raw_pdf_text.json").open("w", encoding="utf-8") as output:
            json.dump(result, output, ensure_ascii=False, indent=2)
        return ApiResponse.success(result)
    except Exception as exc:
        logger.bind(request_id=request_id).exception("Raw PDF reading failed")
        return ApiResponse.error(f"读取 PDF 失败: {exc}")
