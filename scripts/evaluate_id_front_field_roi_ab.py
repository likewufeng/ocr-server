"""Compare ID-front field ROI recovery on a reviewed gold set."""

import argparse
import json
import math
import statistics
import time
from pathlib import Path
from typing import Dict, List

from evaluate_id_front_retry_ab import (
    FIELD_NAMES,
    COUNTED_STATUSES,
    field_matches,
    normalize,
    read_review_rows,
    request_ocr,
    rate,
)


def percentile(values: List[float], percent: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[max(0, math.ceil(len(ordered) * percent) - 1)]


def select_rows(rows: List[Dict[str, str]], all_reviewed: bool) -> List[Dict[str, str]]:
    reviewed = [
        row
        for row in rows
        if (row.get("review_status") or "").strip().lower() in COUNTED_STATUSES
    ]
    if all_reviewed:
        return reviewed
    return [
        row
        for row in reviewed
        if any(
            normalize(field, row.get("pre_{}".format(field)))
            != normalize(field, row.get("final_{}".format(field)))
            for field in FIELD_NAMES
        )
    ]


def run_target(
    name: str,
    url: str,
    rows: List[Dict[str, str]],
    images_dir: Path,
    output_dir: Path,
    timeout: float,
) -> Dict[str, object]:
    if rows:
        request_ocr(url, images_dir / rows[0]["image_file"], timeout)

    durations: List[float] = []
    correct = {field: 0 for field in FIELD_NAMES}
    all_fields_correct = 0
    failures = []
    attempted = {field: 0 for field in ("name", "birthday")}
    recovered = {field: 0 for field in ("name", "birthday")}

    for index, row in enumerate(rows, start=1):
        image_path = images_dir / (row.get("image_file") or "")
        try:
            actual, duration, request_id = request_ocr(url, image_path, timeout)
            durations.append(duration)
            matches = field_matches(actual, row)
            for field, matched in matches.items():
                if matched:
                    correct[field] += 1
            if all(matches.values()):
                all_fields_correct += 1

            metadata_path = output_dir / request_id / "field_roi_recovery.json"
            if metadata_path.is_file():
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                for field in metadata.get("attempted_fields", []):
                    if field in attempted:
                        attempted[field] += 1
                for field in metadata.get("recovered_fields", []):
                    if field in recovered:
                        recovered[field] += 1
        except Exception as exc:
            failures.append({"image": row.get("image_file", ""), "error": type(exc).__name__})
        if index % 10 == 0 or index == len(rows):
            print("{} [{}/{}]".format(name, index, len(rows)), flush=True)

    successful = len(durations)
    return {
        "name": name,
        "samples": len(rows),
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
        "latency_seconds": {
            "average": round(statistics.mean(durations), 4) if durations else None,
            "p50": round(percentile(durations, 0.50), 4) if durations else None,
            "p95": round(percentile(durations, 0.95), 4) if durations else None,
            "max": round(max(durations), 4) if durations else None,
        },
        "roi_attempted": attempted,
        "roi_recovered": recovered,
        "failures": failures,
    }


def render_markdown(report: Dict[str, object]) -> str:
    lines = [
        "# ID Front Field ROI A/B Report",
        "",
        "This report contains aggregate accuracy and latency only. No document values are included.",
        "",
        "| Configuration | Samples | Successful | Exact all-fields rate | P50 | P95 | Name ROI attempted/recovered | Birthday ROI attempted/recovered |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for target in report["targets"]:
        lines.append(
            "| {name} | {samples} | {successful_requests} | {all_fields_exact_rate}% | {p50}s | {p95}s | {name_attempted}/{name_recovered} | {birthday_attempted}/{birthday_recovered} |".format(
                name=target["name"],
                samples=target["samples"],
                successful_requests=target["successful_requests"],
                all_fields_exact_rate=target["all_fields_exact_rate"],
                p50=target["latency_seconds"]["p50"],
                p95=target["latency_seconds"]["p95"],
                name_attempted=target["roi_attempted"]["name"],
                name_recovered=target["roi_recovered"]["name"],
                birthday_attempted=target["roi_attempted"]["birthday"],
                birthday_recovered=target["roi_recovered"]["birthday"],
            )
        )
        lines.extend(["", "## {} Field Accuracy".format(target["name"]), "", "| Field | Correct | Total | Accuracy |", "| --- | ---: | ---: | ---: |"])
        for field in FIELD_NAMES:
            metric = target["field_accuracy"][field]
            lines.append("| {} | {} | {} | {}% |".format(field, metric["correct"], metric["total"], metric["accuracy_percent"]))
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="A/B test ID-front field ROI recovery")
    parser.add_argument("--input-csv", required=True, type=Path)
    parser.add_argument("--images-dir", required=True, type=Path)
    parser.add_argument("--url-off", required=True)
    parser.add_argument("--url-on", required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("data/outputs"))
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--all-reviewed", action="store_true")
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-markdown", required=True, type=Path)
    args = parser.parse_args()

    rows = select_rows(read_review_rows(args.input_csv), args.all_reviewed)
    if not rows:
        parser.error("no reviewed rows selected")
    if not args.images_dir.is_dir():
        parser.error("images directory does not exist")

    report = {
        "dataset": str(args.input_csv),
        "images_dir": str(args.images_dir),
        "selected_samples": len(rows),
        "selection": "all reviewed" if args.all_reviewed else "reviewed corrected rows",
        "targets": [
            run_target("roi_off", args.url_off, rows, args.images_dir, args.output_dir, args.timeout),
            run_target("roi_on", args.url_on, rows, args.images_dir, args.output_dir, args.timeout),
        ],
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output_markdown.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all(not target["failures"] for target in report["targets"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
