"""Build a business-license review set from a JSONL detection annotation file."""

import argparse
import csv
import json
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import mimetypes
import uuid


FIELD_NAMES = (
    "credit_code",
    "name",
    "type_name",
    "legal_person",
    "capital",
    "establish_date",
    "address",
    "business_scope",
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
ANSWER_FIELDS = {
    "answer_1": "credit_code",
    "answer_2": "name",
    "answer_3": "type_name",
    "answer_4": "address",
    "answer_5": "legal_person",
    "answer_6": "capital",
    "answer_7": "establish_date",
    "answer_9": "business_scope",
}


def multipart_body(image_path: Path) -> Tuple[bytes, str]:
    boundary = "----ocr-business-gold-{}".format(uuid.uuid4().hex)
    content_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    prefix = (
        "--{0}\r\n"
        'Content-Disposition: form-data; name="file"; filename="{1}"\r\n'
        "Content-Type: {2}\r\n\r\n"
    ).format(boundary, image_path.name, content_type).encode("utf-8")
    suffix = "\r\n--{}--\r\n".format(boundary).encode("ascii")
    return prefix + image_path.read_bytes() + suffix, boundary


def call_ocr(url: str, image_path: Path, timeout: float) -> Dict[str, object]:
    query = urlencode({"document_type": "business_license", "auto_orientation": "true"})
    body, boundary = multipart_body(image_path)
    request = Request(
        "{}/ocr?{}".format(url.rstrip("/"), query),
        data=body,
        method="POST",
        headers={"Content-Type": "multipart/form-data; boundary={}".format(boundary)},
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("code") != 0:
        raise RuntimeError("OCR API returned code {}".format(payload.get("code")))
    return payload.get("data") or {}


def read_val_jsonl(path: Path) -> Dict[str, List[Dict[str, object]]]:
    records: Dict[str, List[Dict[str, object]]] = {}
    with path.open("r", encoding="utf-8") as source_file:
        for line_number, line in enumerate(source_file, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                image_name, payload = line.split("\t", 1)
                annotations = json.loads(payload)
            except (ValueError, json.JSONDecodeError) as exc:
                raise ValueError("Invalid annotation at line {}".format(line_number)) from exc
            records[Path(image_name).name] = annotations
    return records


def answer_sort_key(key: str) -> Tuple[int, int]:
    suffix = key.rsplit("_", 1)[-1]
    return (0 if suffix.isdigit() else 1, int(suffix) if suffix.isdigit() else 0)


def structured_gold(annotations: List[Dict[str, object]]) -> Dict[str, str]:
    grouped: Dict[str, List[Tuple[str, str]]] = {field: [] for field in FIELD_NAMES}
    for item in annotations:
        key = str(item.get("key_cls") or "")
        match = re.fullmatch(r"(answer_\d+)(?:_(\d+))?", key)
        if not match:
            continue
        base_key, part = match.groups()
        field = ANSWER_FIELDS.get(base_key)
        text = str(item.get("transcription") or "").strip()
        if field and text:
            grouped[field].append((part or "0", text))

    result = {}
    for field in FIELD_NAMES:
        values = sorted(grouped[field], key=lambda value: answer_sort_key(value[0]))
        result[field] = "".join(value for _, value in values)
    return result


def write_template(path: Path, records: List[Dict[str, str]]) -> None:
    fieldnames = ["image_file"]
    fieldnames.extend("pre_{}".format(field) for field in FIELD_NAMES)
    fieldnames.extend("final_{}".format(field) for field in FIELD_NAMES)
    fieldnames.extend(("review_status", "reviewer", "reviewed_at", "notes"))
    with path.open("w", encoding="utf-8-sig", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def normalize(field: str, value: object) -> str:
    text = re.sub(r"\s+", "", str(value or "")).replace("：", ":")
    if field == "credit_code":
        return re.sub(r"[^0-9A-Za-z]", "", text).upper()
    if field == "establish_date":
        match = re.search(r"(\d{4})\D*(\d{1,2})\D*(\d{1,2})", text)
        if match:
            return "{}年{:02d}月{:02d}日".format(
                match.group(1), int(match.group(2)), int(match.group(3))
            )
    return text


def build_report(records: List[Dict[str, str]], failures: int) -> Dict[str, object]:
    correct = Counter()
    totals = Counter()
    all_correct = 0
    all_total = 0
    for record in records:
        annotated_fields = [
            field for field in FIELD_NAMES if normalize(field, record["final_{}".format(field)])
        ]
        if not annotated_fields:
            continue
        row_correct = True
        for field in annotated_fields:
            totals[field] += 1
            matched = normalize(field, record["pre_{}".format(field)]) == normalize(
                field, record["final_{}".format(field)]
            )
            if matched:
                correct[field] += 1
            else:
                row_correct = False
        if row_correct:
            all_correct += 1

        all_total += 1
    return {
        "dataset_type": "business_license",
        "samples": len(records),
        "samples_with_annotations": all_total,
        "ocr_failures": failures,
        "all_fields_exact_correct": all_correct,
        "all_fields_exact_rate": round(all_correct * 100.0 / all_total, 2) if all_total else None,
        "field_accuracy": {
            field: {
                "correct": correct[field],
                "total": totals[field],
                "accuracy_percent": round(correct[field] * 100.0 / totals[field], 2) if totals[field] else None,
            }
            for field in FIELD_NAMES
        },
        "gold_source": "yyzz/val.json answer_* annotations; requires human confirmation before production claims",
    }


def render_markdown(report: Dict[str, object]) -> str:
    lines = [
        "# 营业执照 OCR 基线准确率",
        "",
        "期望字段由 `val.json` 中的 `answer_*` 标注整理而来。用于生产准确率结论前，仍应人工复核 CSV 中的字段归并。",
        "",
        "| 指标 | 结果 |",
        "| --- | ---: |",
        "| 样本总数 | {} |".format(report["samples"]),
        "| 有结构化源标注的样本数 | {} |".format(report["samples_with_annotations"]),
        "| OCR 接口失败数 | {} |".format(report["ocr_failures"]),
        "| 全字段完全正确率 | {}% |".format(report["all_fields_exact_rate"]),
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
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare and baseline business-license OCR gold data")
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    source_annotations = args.source_dir / "val.json"
    if not args.source_dir.is_dir() or not source_annotations.is_file():
        parser.error("source-dir must contain val.json")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error("output-dir must be empty or absent")

    annotations_by_image = read_val_jsonl(source_annotations)
    image_output_dir = args.output_dir / "images"
    image_output_dir.mkdir(parents=True, exist_ok=True)
    records = []
    failures = []
    for index, image_name in enumerate(sorted(annotations_by_image), start=1):
        source_image = args.source_dir / image_name
        if not source_image.is_file():
            failures.append({"image": image_name, "error": "image_missing"})
            continue
        shutil.copy2(source_image, image_output_dir / image_name)
        try:
            pre = call_ocr(args.url, source_image, args.timeout)
        except Exception as exc:
            failures.append({"image": image_name, "error": type(exc).__name__})
            pre = {field: "" for field in FIELD_NAMES}
        gold = structured_gold(annotations_by_image[image_name])
        has_structured_gold = any(gold.values())
        record = {"image_file": image_name}
        for field in FIELD_NAMES:
            record["pre_{}".format(field)] = str(pre.get(field) or "")
            record["final_{}".format(field)] = gold[field]
        record.update({
            "review_status": "confirmed" if has_structured_gold else "pending",
            "reviewer": "source_val_json" if has_structured_gold else "",
            "reviewed_at": "",
            "notes": (
                "由 val.json 的 answer_* 标注整理，需人工复核字段归并。"
                if has_structured_gold
                else "源文件只有 OCR 文本标注，没有 answer_* 结构化字段，需要人工校对。"
            ),
        })
        records.append(record)
        if index % 10 == 0 or index == len(annotations_by_image):
            print("processed [{}/{}]".format(index, len(annotations_by_image)), flush=True)

    report = build_report(records, len(failures))
    report["failure_details"] = failures
    report["source_count"] = len(annotations_by_image)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_annotations, args.output_dir / "source_val.json")
    write_template(args.output_dir / "annotation_template.csv", records)
    (args.output_dir / "baseline_accuracy_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.output_dir / "baseline_accuracy_report.md").write_text(
        render_markdown(report), encoding="utf-8"
    )
    (args.output_dir / "README.md").write_text(
        "# 营业执照金标数据集\n\n"
        "本数据集包含从 `docs/yyzz` 整合的 63 张图片。结构化金标字段由 `val.json` 中的 `answer_*` 标注整理。\n\n"
        "`annotation_template.csv` 中，`pre_*` 是当前 `/ocr` 接口的预标注，`final_*` 是从源标注整理的期望值。没有 `answer_*` 结构化字段的样例状态为 `pending`，需要人工校对后才能纳入正式准确率统计。\n\n"
        "人工校对完成后，运行 `scripts/report_business_license_accuracy.py` 可重新生成不含证件原文的准确率报告。\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
