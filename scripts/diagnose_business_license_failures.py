"""Classify business-license regression failures from retained OCR artifacts.

The generated report intentionally contains no document text. It links each
failure to its locally retained original image and OCR artifact so engineers can
separate parser defects from underlying OCR recognition defects.
"""

import argparse
import csv
import hashlib
import io
import json
import re
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable

try:
    from scripts.prepare_business_license_gold_set import FIELD_NAMES
    from scripts.report_business_license_accuracy import FIELD_LABELS, normalize, read_csv
except ModuleNotFoundError:
    from prepare_business_license_gold_set import FIELD_NAMES
    from report_business_license_accuracy import FIELD_LABELS, normalize, read_csv


PUNCTUATION = re.compile(r"[\s,，;；:：、.。()（）\[\]【】'\"]")
FIELD_LABEL_TOKENS = {
    "credit_code": ("统一社会信用代码", "社会信用代码", "信用代码", "注册号"),
    "name": ("名称", "名", "称"),
    "type_name": ("类型", "类", "型"),
    "legal_person": ("法定代表人", "负责人"),
    "capital": ("注册资本", "注册资金"),
    "establish_date": ("成立日期", "注册日期", "设立日期"),
    "address": ("住所", "营业场所", "经营场所", "注册地址", "住", "所"),
    "business_scope": ("经营范围",),
}


def compact(value: object) -> str:
    return PUNCTUATION.sub("", str(value or ""))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Dict[str, object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def artifact_index(outputs_dir: Path) -> Dict[str, Path]:
    """Map original upload hashes to their most recently written artifact dir."""
    indexed: Dict[str, Path] = {}
    for candidate in outputs_dir.iterdir():
        if not candidate.is_dir():
            continue
        upload_info = load_json(candidate / "upload_info.json")
        digest = upload_info.get("sha256")
        if not isinstance(digest, str) or not digest:
            continue
        previous = indexed.get(digest)
        if previous is None or candidate.stat().st_mtime > previous.stat().st_mtime:
            indexed[digest] = candidate
    return indexed


def failed_fields(report: Dict[str, object]) -> Iterable[tuple[str, str]]:
    for sample in report.get("failure_details") or []:
        image_name = sample.get("image_file") or ""
        for detail in sample.get("failed_fields") or []:
            field = detail.get("field") or ""
            if image_name and field in FIELD_NAMES:
                yield image_name, field


def classify(field: str, gold: object, prediction: object, ocr: Dict[str, object]) -> str:
    texts = [str(item or "") for item in ocr.get("texts") or []]
    joined = "".join(texts)
    normalized_gold = normalize(field, gold)
    normalized_prediction = normalize(field, prediction)
    compact_gold = compact(gold)
    compact_ocr = compact(joined)
    has_label = any(token in joined for token in FIELD_LABEL_TOKENS[field])

    if normalized_gold and normalized_gold in joined:
        return "原始OCR包含完整金标，优先排查解析或格式化边界"
    if compact_gold and compact_gold in compact_ocr:
        return "原始OCR包含等价文本，优先排查标点或格式归一化"
    if not normalized_prediction and has_label:
        return "标签已识别但字段为空，优先排查版面解析或字段ROI"
    if not normalized_prediction:
        return "字段为空且标签不完整，属于OCR漏检或版面异常"
    return "原始OCR与金标不一致，优先排查模型识别或保守纠错规则"


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose business-license regression failures")
    parser.add_argument("--input-csv", required=True, type=Path)
    parser.add_argument("--report-json", required=True, type=Path)
    parser.add_argument("--images-dir", required=True, type=Path)
    parser.add_argument("--outputs-dir", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-markdown", required=True, type=Path)
    args = parser.parse_args()

    rows, _ = read_csv(args.input_csv)
    rows_by_image = {row.get("image_file") or "": row for row in rows}
    report = load_json(args.report_json)
    artifacts = artifact_index(args.outputs_dir)
    details = []
    summary = Counter()

    for image_name, field in failed_fields(report):
        image_path = args.images_dir / image_name
        row = rows_by_image.get(image_name, {})
        artifact_dir = artifacts.get(sha256_file(image_path)) if image_path.is_file() else None
        parsed = load_json(artifact_dir / "parsed_result.json") if artifact_dir else {}
        ocr = load_json(artifact_dir / "ocr_result.json") if artifact_dir else {}
        diagnosis = (
            classify(field, row.get("final_{}".format(field)), parsed.get(field), ocr)
            if artifact_dir else "未找到对应缓存产物，需重新请求并保留request_id"
        )
        summary[diagnosis] += 1
        details.append({
            "image_file": image_name,
            "field": field,
            "field_label": FIELD_LABELS[field],
            "diagnosis": diagnosis,
            "artifact_dir": str(artifact_dir) if artifact_dir else "",
        })

    payload = {
        "failure_field_count": len(details),
        "diagnosis_summary": dict(summary),
        "details": details,
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 营业执照失败项倒查分类",
        "",
        "本报告不保存证照原文、金标值或识别值；每一项仅关联本地动态产物目录。",
        "",
        "| 诊断结论 | 字段数 |",
        "| --- | ---: |",
    ]
    lines.extend("| {} | {} |".format(key, value) for key, value in summary.most_common())
    lines.extend([
        "",
        "## 逐项清单",
        "",
        "| 图片 | 字段 | 诊断结论 | 本地产物目录 |",
        "| --- | --- | --- | --- |",
    ])
    lines.extend(
        "| {image_file} | {field_label} | {diagnosis} | `{artifact_dir}` |".format(**item)
        for item in details
    )
    args.output_markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"failure_field_count": len(details), "diagnosis_summary": dict(summary)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
