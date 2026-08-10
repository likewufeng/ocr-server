"""Evaluate the live OCR endpoint against a manually reviewed business-license set."""

import argparse
import json
import time
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Dict, List, Tuple

try:
    from scripts.prepare_business_license_gold_set import FIELD_NAMES, call_ocr
    from scripts.report_business_license_accuracy import FIELD_LABELS, normalize, read_csv
except ModuleNotFoundError:
    from prepare_business_license_gold_set import FIELD_NAMES, call_ocr
    from report_business_license_accuracy import FIELD_LABELS, normalize, read_csv


def percentile(values: List[float], percent: float):
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * percent)))
    return round(ordered[index], 3)


def comparison_kind(field: str, prediction: object, gold: object) -> str:
    normalized_prediction = normalize(field, prediction)
    normalized_gold = normalize(field, gold)
    if normalized_prediction == normalized_gold:
        return "完全一致"
    if not normalized_prediction:
        return "结果为空"
    if normalized_prediction in normalized_gold:
        return "结果过短"
    if normalized_gold in normalized_prediction:
        return "结果过长"
    return "内容不同"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate /ocr against manually reviewed business-license gold data"
    )
    parser.add_argument("--input-csv", required=True, type=Path)
    parser.add_argument("--images-dir", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-markdown", required=True, type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--retries", type=int, default=1, help="单张图片失败后的重试次数")
    args = parser.parse_args()

    rows, source_encoding = read_csv(args.input_csv)
    reviewed_rows = [
        row for row in rows
        if (row.get("review_status") or "").lower() in {"confirmed", "corrected"}
    ]
    correct = Counter()
    totals = Counter()
    comparison_summary = {field: Counter() for field in FIELD_NAMES}
    all_correct = 0
    all_total = 0
    failures = 0
    retry_recovered = 0
    latencies = []

    for index, row in enumerate(reviewed_rows, start=1):
        image_name = row.get("image_file") or ""
        image_path = args.images_dir / image_name
        annotated_fields = [
            field for field in FIELD_NAMES if normalize(field, row.get("final_{}".format(field)))
        ]
        if not image_path.is_file() or not annotated_fields:
            failures += 1
            continue

        started = time.perf_counter()
        prediction = {}
        succeeded = False
        for attempt in range(max(0, args.retries) + 1):
            try:
                prediction = call_ocr(args.url, image_path, args.timeout)
                succeeded = True
                if attempt:
                    retry_recovered += 1
                break
            except Exception:
                continue
        if not succeeded:
            failures += 1
        latencies.append((time.perf_counter() - started) * 1000.0)

        row_correct = True
        for field in annotated_fields:
            totals[field] += 1
            relation = comparison_kind(field, prediction.get(field), row.get("final_{}".format(field)))
            comparison_summary[field][relation] += 1
            matched = relation == "完全一致"
            if matched:
                correct[field] += 1
            else:
                row_correct = False
        if row_correct:
            all_correct += 1
        all_total += 1

        if index % 10 == 0 or index == len(reviewed_rows):
            print("processed [{}/{}]".format(index, len(reviewed_rows)), flush=True)

    report = {
        "dataset_type": "business_license",
        "samples": len(reviewed_rows),
        "samples_with_annotations": all_total,
        "request_failures": failures,
        "retry_recovered": retry_recovered,
        "source_encoding": source_encoding,
        "all_fields_exact_correct": all_correct,
        "all_fields_exact_rate": round(all_correct * 100.0 / all_total, 2) if all_total else None,
        "field_accuracy": {
            field: {
                "correct": correct[field],
                "total": totals[field],
                "accuracy_percent": round(correct[field] * 100.0 / totals[field], 2)
                if totals[field] else None,
            }
            for field in FIELD_NAMES
        },
        "comparison_summary": {
            field: dict(comparison_summary[field]) for field in FIELD_NAMES
        },
        "latency_ms": {
            "count": len(latencies),
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "max": round(max(latencies), 3) if latencies else None,
        },
    }

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 营业执照 OCR 回归准确率报告",
        "",
        "本报告基于人工复核后的金标数据集生成，仅包含汇总指标，不输出证照原文或识别结果。",
        "",
        "| 指标 | 结果 |",
        "| --- | ---: |",
        "| 已评测样本数 | {} |".format(report["samples_with_annotations"]),
        "| 接口失败数 | {} |".format(report["request_failures"]),
        "| 重试恢复数 | {} |".format(report["retry_recovered"]),
        "| 全字段完全正确率 | {}% |".format(report["all_fields_exact_rate"]),
        "| P50 响应时间 | {} ms |".format(report["latency_ms"]["p50"]),
        "| P95 响应时间 | {} ms |".format(report["latency_ms"]["p95"]),
        "",
        "| 字段 | 正确数 | 纳入统计数 | 准确率 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for field in FIELD_NAMES:
        metric = report["field_accuracy"][field]
        lines.append(
            "| {} | {} | {} | {}% |".format(
                FIELD_LABELS[field], metric["correct"], metric["total"], metric["accuracy_percent"]
            )
        )
    lines.extend([
        "",
        "## 差异类型汇总",
        "",
        "| 字段 | 完全一致 | 结果为空 | 结果过短 | 结果过长 | 内容不同 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ])
    for field in FIELD_NAMES:
        summary = report["comparison_summary"][field]
        lines.append(
            "| {} | {} | {} | {} | {} | {} |".format(
                FIELD_LABELS[field],
                summary.get("完全一致", 0),
                summary.get("结果为空", 0),
                summary.get("结果过短", 0),
                summary.get("结果过长", 0),
                summary.get("内容不同", 0),
            )
        )
    args.output_markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
