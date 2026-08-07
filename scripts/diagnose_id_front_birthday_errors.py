"""Classify ID-front birthday misses using a reviewed CSV and raw OCR results."""

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from report_id_front_review_accuracy import read_review_rows
from prepare_id_front_review_set import call_ocr
from app.utils.layout import build_layout
from app.parsers.id_front import IDFrontParser


def compact(value: object) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def normalized_date(value: object) -> str:
    match = re.search(r"(\d{4})\D*(\d{1,2})\D*(\d{1,2})", compact(value))
    if not match:
        return ""
    return "{}{:02d}{:02d}".format(
        match.group(1), int(match.group(2)), int(match.group(3))
    )


def raw_has_date(raw_text: str, target_date: str) -> bool:
    if not target_date:
        return False
    year, month, day = target_date[:4], str(int(target_date[4:6])), str(int(target_date[6:]))
    pattern = r"{}\D{{0,3}}{}\D{{0,3}}{}".format(year, month, day)
    return bool(re.search(pattern, raw_text))


def request_raw_with_retry(url: str, image_path: Path, timeout: float) -> Dict[str, object]:
    last_error = None
    for attempt in range(3):
        try:
            return call_ocr(url, "ocr/raw", image_path, timeout)
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    raise last_error


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose reviewed ID-front birthday errors")
    parser.add_argument("--input-csv", required=True, type=Path)
    parser.add_argument("--images-dir", required=True, type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument(
        "--all-reviewed",
        action="store_true",
        help="Validate the global strict-date candidate across every reviewed sample.",
    )
    args = parser.parse_args()

    rows = read_review_rows(args.input_csv)
    reviewed_rows = [
        row
        for row in rows
        if (row.get("review_status") or "").strip().lower() in {"confirmed", "corrected"}
    ]
    birthday_errors = (
        reviewed_rows
        if args.all_reviewed
        else [
            row
            for row in reviewed_rows
            if compact(row.get("pre_birthday")) != compact(row.get("final_birthday"))
        ]
    )
    categories = Counter()
    failures: List[Dict[str, str]] = []
    for index, row in enumerate(birthday_errors, start=1):
        image_file = row.get("image_file") or ""
        image_path = args.images_dir / image_file
        try:
            raw = request_raw_with_retry(args.url, image_path, args.timeout)
        except Exception as exc:
            failures.append({"image": image_file, "error": type(exc).__name__})
            continue

        raw_text = compact("".join(str(value) for value in raw.get("texts", [])))
        target_date = normalized_date(row.get("final_birthday"))
        has_birth_label = "出生" in raw_text
        has_target_date = raw_has_date(raw_text, target_date)
        layout = build_layout(raw)
        birth_line = layout.find("出生")
        same_row_text = ""
        if birth_line:
            same_row_text = compact(
                "".join(item.text for item in layout.same_row(birth_line, tolerance=35))
            )
        if has_target_date:
            categories["raw_contains_correct_birthday"] += 1
        elif has_birth_label:
            categories["birth_label_without_correct_birthday"] += 1
        else:
            categories["birth_label_not_detected"] += 1
        if birth_line:
            categories["layout_finds_birth_label"] += 1
        else:
            categories["layout_does_not_find_birth_label"] += 1
        if birth_line and raw_has_date(same_row_text, target_date):
            categories["birth_row_contains_correct_birthday"] += 1
        global_birthday = IDFrontParser._extract_birthday(
            compact("".join(layout.original_texts()))
        )
        if normalized_date(global_birthday) == target_date:
            categories["original_sequence_extracts_correct_birthday"] += 1
        print("diagnosed [{}/{}]".format(index, len(birthday_errors)), flush=True)

    report = {
        "birthday_error_samples": len(birthday_errors),
        "all_reviewed": args.all_reviewed,
        "raw_requests_succeeded": len(birthday_errors) - len(failures),
        "raw_request_failures": len(failures),
        "categories": dict(sorted(categories.items())),
        "failures": failures,
        "notes": {
            "raw_contains_correct_birthday": "Raw OCR has the annotated birthday; parser/layout extraction can be improved.",
            "birth_label_without_correct_birthday": "Birth label is visible but raw recognition is missing or corrupt; parser improvements may have limited effect.",
            "birth_label_not_detected": "Raw OCR did not detect the birth label; this is a model/detection limitation.",
        },
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
