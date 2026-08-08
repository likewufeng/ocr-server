"""Evaluate the current /ocr result against a reviewed ID-front CSV gold set."""

import argparse
import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List

from prepare_id_front_review_set import FIELD_NAMES, call_ocr
from report_id_front_review_accuracy import COUNTED_STATUSES, normalize, rate


def request_ocr_with_retry(url: str, image_path: Path, timeout: float) -> Dict[str, object]:
    last_error = None
    for attempt in range(3):
        try:
            return call_ocr(url, "ocr", image_path, timeout)
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    raise last_error


def normalize_for_comparison(field: str, value: object, ignore_synthetic_watermark: bool) -> str:
    text = normalize(field, value)
    if field == "address" and ignore_synthetic_watermark:
        # The generated review images contain a known watermark in the address
        # area. Its separator is OCR-sensitive and is not an address character.
        text = re.sub(r"[-—–_一]*自制数据集", "", text)
    return text


def render_markdown(report: Dict[str, object]) -> str:
    """Render a privacy-safe report for results returned by the current API."""
    lines = [
        "# ID Front OCR API Regression Report",
        "",
        "This report evaluates the current /ocr API against the latest human-reviewed gold set.",
        "No source document field values are included.",
        "",
        "| Metric | Result |",
        "| --- | ---: |",
        "| Reviewed samples | {} |".format(report["reviewed_samples"]),
        "| Successful requests | {} |".format(report["successful_requests"]),
        "| Failed requests | {} |".format(report["failed_requests"]),
        "| All-fields exact accuracy | {}% |".format(report["all_fields_exact_rate"]),
        "",
        "## Field Accuracy",
        "",
        "| Field | Correct | Total | Accuracy |",
        "| --- | ---: | ---: | ---: |",
    ]
    for field in FIELD_NAMES:
        item = report["field_accuracy"][field]
        lines.append(
            "| {} | {} | {} | {}% |".format(
                field,
                item["correct"],
                item["total"],
                item["accuracy_percent"],
            )
        )
    lines.extend(
        [
            "",
            "## Evaluation Scope",
            "",
            "- Includes rows marked `confirmed` or `corrected` in the reviewed CSV.",
            "- Field values are normalized before exact comparison.",
            "- Request failures are reported separately and are excluded from field totals.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate current ID-front OCR against reviewed CSV")
    parser.add_argument("--input-csv", required=True, type=Path)
    parser.add_argument("--images-dir", required=True, type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-markdown", type=Path)
    parser.add_argument(
        "--ignore-synthetic-watermark",
        action="store_true",
        help="Ignore the known generated-image address watermark when comparing fields",
    )
    args = parser.parse_args()

    from report_id_front_review_accuracy import read_review_rows

    rows = read_review_rows(args.input_csv)
    reviewed_rows = [
        row
        for row in rows
        if (row.get("review_status") or "").strip().lower() in COUNTED_STATUSES
    ]
    correct = Counter()
    all_fields_correct = 0
    failures: List[Dict[str, str]] = []
    for index, row in enumerate(reviewed_rows, start=1):
        image_file = row.get("image_file") or ""
        try:
            actual = request_ocr_with_retry(
                args.url, args.images_dir / image_file, args.timeout
            )
        except Exception as exc:
            failures.append({"image": image_file, "error": type(exc).__name__})
            continue
        row_all_correct = True
        for field in FIELD_NAMES:
            if normalize_for_comparison(
                field, actual.get(field), args.ignore_synthetic_watermark
            ) == normalize_for_comparison(
                field, row.get("final_{}".format(field)), args.ignore_synthetic_watermark
            ):
                correct[field] += 1
            else:
                row_all_correct = False
        if row_all_correct:
            all_fields_correct += 1
        if index % 25 == 0 or index == len(reviewed_rows):
            print("evaluated [{}/{}]".format(index, len(reviewed_rows)), flush=True)

    successful = len(reviewed_rows) - len(failures)
    report = {
        "reviewed_samples": len(reviewed_rows),
        "successful_requests": successful,
        "failed_requests": len(failures),
        "all_fields_exact_correct": all_fields_correct,
        "all_fields_exact_rate": rate(all_fields_correct, successful),
        "field_accuracy": {
            field: {
                "correct": correct[field],
                "total": successful,
                "accuracy_percent": rate(correct[field], successful),
            }
            for field in FIELD_NAMES
        },
        "failures": failures,
        "comparison_options": {
            "ignore_synthetic_watermark": args.ignore_synthetic_watermark
        },
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.output_markdown:
        args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
        args.output_markdown.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
