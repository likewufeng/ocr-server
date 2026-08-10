"""Start an isolated server for ID-front field-ROI A/B evaluation."""

import argparse
import os
import sys
from pathlib import Path

import uvicorn


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--roi", action="store_true")
    args = parser.parse_args()

    os.environ["OCR_ID_FRONT_FIELD_ROI_RETRY_ENABLED"] = "true" if args.roi else "false"
    os.environ["OCR_ID_FRONT_QUALITY_RETRY_ENABLED"] = "false"
    os.environ["OCR_CACHE_ENABLED"] = "false"
    uvicorn.run("app.main:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
