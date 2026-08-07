"""Generate a privacy-safe accuracy report from a reviewed ID-front CSV file."""

import argparse
import csv
import io
import json
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional


FIELDS = ("name", "gender", "nation", "birthday", "address", "id_number")
COUNTED_STATUSES = {"confirmed", "corrected"}


def normalize(field: str, value: object) -> str:
    text = re.sub(r"\s+", "", str(value or "")).replace("：", ":")
    if field == "id_number":
        return re.sub(r"[^0-9Xx]", "", text).upper()
    if field == "birthday":
        match = re.search(r"(\d{4})\D*(\d{1,2})\D*(\d{1,2})", text)
        if match:
            return "{}年{}月{}日".format(
                match.group(1), int(match.group(2)), int(match.group(3))
            )
    return text


def rate(correct: int, total: int) -> Optional[float]:
    return round(correct * 100.0 / total, 2) if total else None


def read_review_rows(input_path: Path) -> List[Dict[str, str]]:
    """Accept CSV files saved by Excel in UTF-8, UTF-16, or GBK-compatible encodings."""
    raw = input_path.read_bytes()
    last_error = None
    for encoding in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            text = raw.decode(encoding)
            reader = csv.DictReader(io.StringIO(text))
            rows = list(reader)
            if reader.fieldnames and "review_status" in reader.fieldnames:
                return rows
            last_error = ValueError("review_status column not found with {}".format(encoding))
        except (UnicodeDecodeError, UnicodeError, csv.Error, ValueError) as exc:
            last_error = exc
    raise ValueError("Unable to read review CSV: {}".format(last_error))


def render_markdown(report: Dict[str, object]) -> str:
    lines = [
        "# 身份证正面 OCR 准确率报告",
        "",
        "本报告从人工校对后的 CSV 汇总生成，不包含姓名、地址、身份证号等字段原文。",
        "",
        "| 指标 | 结果 |",
        "| --- | ---: |",
        "| 模板总样本数 | {} |".format(report["total_rows"]),
        "| 已纳入统计样本数 | {} |".format(report["reviewed_rows"]),
        "| 待校对样本数 | {} |".format(report["pending_rows"]),
        "| 不可判读样本数 | {} |".format(report["unreadable_rows"]),
        "| 全字段完全正确率 | {}% |".format(report["all_fields_exact_rate"]),
        "",
        "## 字段准确率",
        "",
        "| 字段 | 正确数 | 纳入统计数 | 完全正确率 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for field in FIELDS:
        item = report["field_accuracy"][field]
        value = "-" if item["accuracy_percent"] is None else "{}%".format(item["accuracy_percent"])
        lines.append("| {} | {} | {} | {} |".format(field, item["correct"], item["total"], value))
    lines.extend(
        [
            "",
            "## 统计口径",
            "",
            "- 只有 `review_status=confirmed` 或 `corrected` 的行纳入统计。",
            "- `unreadable` 样本单独计数，不参与准确率分母。",
            "- 预标注 `pre_*` 与人工确认值 `final_*` 按字段规范化后完全匹配才记为正确。",
            "- 未填写 `final_*` 默认为该字段的人工确认值为空；请勿用空白代替未校对。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Report structured OCR accuracy from reviewed CSV")
    parser.add_argument("--input-csv", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-markdown", required=True, type=Path)
    args = parser.parse_args()

    rows = read_review_rows(args.input_csv)
    required = {"review_status"}
    required.update("pre_{}".format(field) for field in FIELDS)
    required.update("final_{}".format(field) for field in FIELDS)
    missing = sorted(required.difference(rows[0] if rows else {}))
    if missing:
        parser.error("CSV missing required columns: {}".format(", ".join(missing)))

    correct = Counter()
    reviewed = 0
    unreadable = 0
    pending = 0
    all_fields_correct = 0
    statuses = Counter()
    for row in rows:
        status = (row.get("review_status") or "").strip().lower()
        statuses[status or "blank"] += 1
        if status == "unreadable":
            unreadable += 1
            continue
        if status not in COUNTED_STATUSES:
            pending += 1
            continue
        reviewed += 1
        row_all_correct = True
        for field in FIELDS:
            matches = normalize(field, row.get("pre_{}".format(field))) == normalize(
                field, row.get("final_{}".format(field))
            )
            if matches:
                correct[field] += 1
            else:
                row_all_correct = False
        if row_all_correct:
            all_fields_correct += 1

    report = {
        "total_rows": len(rows),
        "reviewed_rows": reviewed,
        "pending_rows": pending,
        "unreadable_rows": unreadable,
        "status_counts": dict(sorted(statuses.items())),
        "all_fields_exact_correct": all_fields_correct,
        "all_fields_exact_rate": rate(all_fields_correct, reviewed),
        "field_accuracy": {
            field: {
                "correct": correct[field],
                "total": reviewed,
                "accuracy_percent": rate(correct[field], reviewed),
            }
            for field in FIELDS
        },
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output_markdown.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
