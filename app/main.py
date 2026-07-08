import os
import shutil
import uuid

from fastapi import FastAPI, UploadFile, File

from app.service import recognize
from app.parser import parse

app = FastAPI(
    title="OCR Service",
    version="1.0.0"
)

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ocr")
async def ocr(file: UploadFile = File(...)):
    ext = file.filename.split(".")[-1]
    filename = f"{uuid.uuid4()}.{ext}"
    path = os.path.join(UPLOAD_DIR, filename)

    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        texts = recognize(path)
        result = parse(texts)

        return {
            "code": 0,
            "msg": "success",
            "data": result
        }

    except Exception as e:
        return {
            "code": 500,
            "msg": str(e),
            "data": None
        }

    finally:
        if os.path.exists(path):
            os.remove(path)