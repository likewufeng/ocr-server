import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, UploadFile

from app.config import OUTPUT_DIR, UPLOAD_DIR
from app.parsers.parser import OCRParser
from app.schemas.response import ApiResponse
from app.services.ocr_service import ocr_service
from app.utils.layout import build_layout
from app.utils.logger import logger
from app.utils.request_context import get_request_id


router = APIRouter(prefix="", tags=["OCR"])
parser = OCRParser()


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


def _save_upload_info(file: UploadFile, path: Path, output_dir: Path) -> None:
    _save_json(
        output_dir / "upload_info.json",
        {
            "original_filename": file.filename,
            "stored_filename": path.name,
            "content_type": file.content_type,
            "file_size": path.stat().st_size,
        },
    )


@router.post("/ocr")
async def ocr(file: UploadFile = File(...)):
    request_id = get_request_id() or uuid.uuid4().hex
    request_logger = logger.bind(request_id=request_id)
    path, output_dir = _prepare_request_paths(file, request_id)

    try:
        with path.open("wb") as upload_file:
            shutil.copyfileobj(file.file, upload_file)
        _save_upload_info(file, path, output_dir)
        request_logger.info("Original upload saved: {}", path)

        ocr_result = ocr_service.recognize(
            str(path), request_id=request_id, output_dir=output_dir
        )
        _save_json(output_dir / "ocr_result.json", ocr_result)

        layout = build_layout(ocr_result)
        document = parser.parse(layout)
        _save_json(output_dir / "parsed_result.json", document)

        request_logger.info(
            "OCR request completed: document_type={}", document.get("type")
        )
        return ApiResponse.success(document, request_id=request_id)
    except Exception:
        request_logger.exception("OCR request failed")
        raise
    finally:
        await file.close()


@router.post("/ocr/raw")
async def ocr_raw(file: UploadFile = File(...)):
    request_id = get_request_id() or uuid.uuid4().hex
    request_logger = logger.bind(request_id=request_id)
    path, output_dir = _prepare_request_paths(file, request_id)

    try:
        with path.open("wb") as upload_file:
            shutil.copyfileobj(file.file, upload_file)
        _save_upload_info(file, path, output_dir)
        request_logger.info("Original upload saved: {}", path)

        ocr_result = ocr_service.recognize(
            str(path), request_id=request_id, output_dir=output_dir
        )
        _save_json(output_dir / "ocr_result.json", ocr_result)

        request_logger.info("Raw OCR request completed")
        return ApiResponse.success(ocr_result, request_id=request_id)
    except Exception:
        request_logger.exception("Raw OCR request failed")
        raise
    finally:
        await file.close()
