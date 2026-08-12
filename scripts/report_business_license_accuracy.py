"""Generate a privacy-safe accuracy report from reviewed business-license CSV."""

import argparse
import csv
import io
import json
import re
from collections import Counter
from pathlib import Path


FIELDS = (
    "credit_code", "name", "type_name", "legal_person", "capital",
    "establish_date", "address", "business_scope",
)
FIELD_LABELS = {
    "credit_code": "统一社会信用代码",
    "name": "名称",
    "type_name": "类型",
    "legal_person": "法定代表人",
    "capital": "注册资本",
    "establish_date": "成立日期",
    "address": "住所",
    "business_scope": "经营范围",
}


def normalize(field: str, value: object) -> str:
    text = re.sub(r"\s+", "", str(value or ""))
    if field == "credit_code":
        return re.sub(r"[^0-9A-Za-z]", "", text).upper()
    if field == "type_name":
        return text.translate(str.maketrans({"\uFF08": "(", "\uFF09": ")"}))
    if field == "establish_date":
        match = re.search(r"(\d{4})\D*(\d{1,2})\D*(\d{1,2})", text)
        if match:
            return "{}年{:02d}月{:02d}日".format(match.group(1), int(match.group(2)), int(match.group(3)))
    return text


def read_csv(path: Path):
    raw = path.read_bytes()
    last_error = None
    for encoding in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            rows = list(csv.DictReader(io.StringIO(raw.decode(encoding))))
            if rows and "review_status" in rows[0]:
                return rows, encoding
            last_error = ValueError("expected CSV columns are missing")
        except (UnicodeDecodeError, UnicodeError, csv.Error, ValueError) as exc:
            last_error = exc
    raise ValueError("Cannot read CSV: {}".format(last_error))


def main() -> int:
    parser = argparse.ArgumentParser(description="Report business-license OCR accuracy")
    parser.add_argument("--input-csv", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-markdown", required=True, type=Path)
    args = parser.parse_args()

    rows, source_encoding = read_csv(args.input_csv)
    counted = [row for row in rows if (row.get("review_status") or "").lower() in {"confirmed", "corrected"}]
    correct = Counter()
    totals = Counter()
    all_correct = 0
    all_total = 0
    for row in counted:
        annotated_fields = [
            field for field in FIELDS if normalize(field, row.get("final_{}".format(field)))
        ]
        if not annotated_fields:
            continue
        row_correct = True
        for field in annotated_fields:
            totals[field] += 1
            matched = normalize(field, row.get("pre_{}".format(field))) == normalize(field, row.get("final_{}".format(field)))
            if matched:
                correct[field] += 1
            else:
                row_correct = False
        if row_correct:
            all_correct += 1
        all_total += 1
    report = {
        "samples": len(counted),
        "source_encoding": source_encoding,
        "samples_with_annotations": all_total,
        "all_fields_exact_rate": round(all_correct * 100.0 / all_total, 2) if all_total else None,
        "field_accuracy": {
            field: {
                "correct": correct[field],
                "total": totals[field],
                "accuracy_percent": round(correct[field] * 100.0 / totals[field], 2) if totals[field] else None,
            } for field in FIELDS
        },
    }
    args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 营业执照 OCR 准确率报告", "", "| 字段 | 正确数 | 纳入统计数 | 准确率 |", "| --- | ---: | ---: | ---: |"]
    for field in FIELDS:
        item = report["field_accuracy"][field]
        lines.append("| {} | {} | {} | {}% |".format(FIELD_LABELS[field], item["correct"], item["total"], item["accuracy_percent"]))
    lines.extend(["", "全字段完全正确率：{}%".format(report["all_fields_exact_rate"])])
    args.output_markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
