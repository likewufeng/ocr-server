"""Compare ID-front quality retry off/on on a reviewed gold set."""

import argparse
import json
import math
import statistics
import time
from pathlib import Path
from typing import Dict, List, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from prepare_id_front_review_set import FIELD_NAMES, multipart_body
from report_id_front_review_accuracy import COUNTED_STATUSES, normalize, read_review_rows, rate


def percentile(values: List[float], percent: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[max(0, math.ceil(len(ordered) * percent) - 1)]


def request_ocr(url: str, image_path: Path, timeout: float) -> Tuple[Dict[str, object], float, str]:
    query = urlencode({"document_type": "id_front", "auto_orientation": "true"})
    body, boundary = multipart_body(image_path)
    request = Request(
        "{}/ocr?{}".format(url.rstrip("/"), query),
        data=body,
        method="POST",
        headers={"Content-Type": "multipart/form-data; boundary={}".format(boundary)},
    )
    started_at = time.perf_counter()
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    duration = time.perf_counter() - started_at
    if payload.get("code") != 0:
        raise RuntimeError("OCR API returned code {}".format(payload.get("code")))
    return payload.get("data") or {}, duration, str(payload.get("request_id") or "")


def field_matches(actual: Dict[str, object], gold: Dict[str, str]) -> Dict[str, bool]:
    return {
        field: normalize(field, actual.get(field))
        == normalize(field, gold.get("final_{}".format(field)))
        for field in FIELD_NAMES
    }


def select_rows(rows: List[Dict[str, str]], all_reviewed: bool) -> List[Dict[str, str]]:
    selected = [
        row
        for row in rows
        if (row.get("review_status") or "").strip().lower() in COUNTED_STATUSES
    ]
    if all_reviewed:
        return selected
    return [
        row
        for row in selected
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
    timeout: float,
    warmup: bool,
) -> Dict[str, object]:
    if warmup and rows:
        request_ocr(url, images_dir / rows[0]["image_file"], timeout)

    durations: List[float] = []
    correct = {field: 0 for field in FIELD_NAMES}
    all_fields_correct = 0
    failures = []
    retry_triggered = 0
    selected_retry = 0
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

            quality_path = Path("data/outputs") / request_id / "quality_info.json"
            if quality_path.is_file():
                try:
                    quality = json.loads(quality_path.read_text(encoding="utf-8"))
                    if quality.get("retry_triggered"):
                        retry_triggered += 1
                    if quality.get("selected_pass") == "retry":
                        selected_retry += 1
                except (OSError, ValueError):
                    pass
        except Exception as exc:
            failures.append({"image": row.get("image_file", ""), "error": type(exc).__name__})
        if index % 10 == 0 or index == len(rows):
            print("{} [{}/{}]".format(name, index, len(rows)), flush=True)

    successful = len(durations)
    return {
        "name": name,
        "url": url,
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
        "throughput_requests_per_second": round(sum(1 for _ in durations) / sum(durations), 4)
        if durations and sum(durations) > 0
        else None,
        "retry_triggered": retry_triggered,
        "selected_retry": selected_retry,
        "failures": failures,
    }


def render_markdown(report: Dict[str, object]) -> str:
    lines = [
        "# ID Front Quality Retry A/B Report",
        "",
        "本报告使用人工确认过的真实失败样本，比较身份证正面条件二次 OCR 开启与关闭。",
        "报告不包含身份证字段原文。",
        "",
        "| 配置 | 样本 | 成功 | 全字段准确率 | P50 | P95 | 平均吞吐 | 重试触发 | 重试被采用 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in report["targets"]:
        if lines[-1] != "":
            lines.append("")
        lines.append(
            "| {name} | {samples} | {successful_requests} | {all_fields_exact_rate}% | {p50}s | {p95}s | {throughput_requests_per_second} req/s | {retry_triggered} | {selected_retry} |".format(
                name=item["name"],
                samples=item["samples"],
                successful_requests=item["successful_requests"],
                all_fields_exact_rate=item["all_fields_exact_rate"],
                p50=item["latency_seconds"]["p50"],
                p95=item["latency_seconds"]["p95"],
                throughput_requests_per_second=item["throughput_requests_per_second"],
                retry_triggered=item["retry_triggered"],
                selected_retry=item["selected_retry"],
            )
        )
        lines.extend(["", "## {} 字段准确率".format(item["name"]), "", "| 字段 | 正确 | 总数 | 准确率 |", "| --- | ---: | ---: | ---: |"])
        for field in FIELD_NAMES:
            metric = item["field_accuracy"][field]
            lines.append("| {} | {} | {} | {}% |".format(field, metric["correct"], metric["total"], metric["accuracy_percent"]))
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="A/B test ID-front quality retry")
    parser.add_argument("--input-csv", required=True, type=Path)
    parser.add_argument("--images-dir", required=True, type=Path)
    parser.add_argument("--url-off", required=True)
    parser.add_argument("--url-on", required=True)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--all-reviewed", action="store_true")
    parser.add_argument("--no-warmup", action="store_true")
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-markdown", required=True, type=Path)
    args = parser.parse_args()

    rows = select_rows(read_review_rows(args.input_csv), args.all_reviewed)
    if not rows:
        parser.error("no reviewed rows selected")
    if not args.images_dir.is_dir():
        parser.error("images directory does not exist: {}".format(args.images_dir))

    targets = [
        run_target("retry_off", args.url_off, rows, args.images_dir, args.timeout, not args.no_warmup),
        run_target("retry_on", args.url_on, rows, args.images_dir, args.timeout, not args.no_warmup),
    ]

    report = {
        "dataset": str(args.input_csv),
        "images_dir": str(args.images_dir),
        "selected_samples": len(rows),
        "selection": "all reviewed" if args.all_reviewed else "reviewed rows with at least one corrected field",
        "targets": targets,
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output_markdown.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all(not item["failures"] for item in targets) else 1


if __name__ == "__main__":
    raise SystemExit(main())
