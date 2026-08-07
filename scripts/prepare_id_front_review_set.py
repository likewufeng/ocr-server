"""Create a review-ready ID-front sample set from an unlabelled image directory."""

import argparse
import csv
import json
import mimetypes
import random
import shutil
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen


FIELD_NAMES = ("name", "gender", "nation", "birthday", "address", "id_number")
INVALID_GENDER_MARKERS = ("机器人", "未知")


def multipart_body(image_path: Path) -> Tuple[bytes, str]:
    boundary = "----ocr-review-set-{}".format(uuid.uuid4().hex)
    content_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    prefix = (
        "--{0}\r\n"
        'Content-Disposition: form-data; name="file"; filename="{1}"\r\n'
        "Content-Type: {2}\r\n\r\n"
    ).format(boundary, image_path.name.replace('"', ""), content_type).encode("utf-8")
    suffix = "\r\n--{}--\r\n".format(boundary).encode("ascii")
    return prefix + image_path.read_bytes() + suffix, boundary


def call_ocr(
    url: str, endpoint: str, image_path: Path, timeout: float
) -> Dict[str, object]:
    query = urlencode({"document_type": "id_front", "auto_orientation": "true"})
    body, boundary = multipart_body(image_path)
    request = Request(
        "{}/{}?{}".format(url.rstrip("/"), endpoint, query),
        data=body,
        method="POST",
        headers={"Content-Type": "multipart/form-data; boundary={}".format(boundary)},
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("code") != 0:
        raise RuntimeError("OCR API returned code {}".format(payload.get("code")))
    return payload.get("data") or {}


def scan_raw(
    args: Tuple[str, Path, float]
) -> Tuple[Path, Optional[str], Optional[str]]:
    url, image_path, timeout = args
    try:
        raw_result = call_ocr(url, "ocr/raw", image_path, timeout)
    except Exception as exc:
        return image_path, None, type(exc).__name__

    text = "".join(str(value) for value in raw_result.get("texts", []))
    marker = next((item for item in INVALID_GENDER_MARKERS if item in text), None)
    return image_path, marker, None


def chunks(values: List[Path], size: int) -> Iterable[List[Path]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def markdown_text(manifest: Dict[str, object]) -> str:
    return """# 身份证正面人工校对集

本目录由 `scripts/prepare_id_front_review_set.py` 生成。图片副本位于 `images/`，预标注和人工校对模板为 `annotation_template.csv`。

## 校对方式

1. 使用 Excel 打开 `annotation_template.csv`。
2. 对照 `images/<image_file>`，将正确字段填写到 `final_*` 列。
3. 将 `review_status` 设置为 `confirmed`、`corrected` 或 `unreadable`。
4. 有遮挡、图片本身不存在字段或无法确认的样本，请保留空白字段并在 `notes` 说明原因。

`pre_*` 列为当前 OCR 的预标注，只用于减少录入工作；准确率计算应只使用 `final_*` 列。不要把本目录、CSV 或图片提交到 Git、网盘或公开文件系统。

## 抽样信息

- 源目录图片数：{source_count}
- 扫描候选数：{scanned_count}
- 因原始 OCR 文本含“机器人”或“未知”排除：{excluded_invalid_gender}
- OCR 扫描失败：{scan_failures}
- 入选数量：{selected_count}
- 随机种子：{seed}
- 当前服务：{url}

筛选依赖当前 OCR 原始文本，因此无法替代人工校对；它的目的只是排除已知不符合本次身份证性别字段验证范围的样本。
""".format(**manifest)


def write_csv(output_path: Path, records: List[Dict[str, str]]) -> None:
    fieldnames = ["image_file"]
    fieldnames.extend("pre_{}".format(field) for field in FIELD_NAMES)
    fieldnames.extend("final_{}".format(field) for field in FIELD_NAMES)
    fieldnames.extend(("review_status", "reviewer", "reviewed_at", "notes"))
    with output_path.open("w", encoding="utf-8-sig", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a pre-labelled ID-front review sample from unlabelled images"
    )
    parser.add_argument("--dataset-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--sample-size", type=int, default=400)
    parser.add_argument("--seed", type=int, default=20260807)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    if args.sample_size < 1:
        parser.error("sample-size must be positive")
    if args.concurrency < 1:
        parser.error("concurrency must be positive")
    if not args.dataset_dir.is_dir():
        parser.error("dataset-dir does not exist: {}".format(args.dataset_dir))
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error("output-dir is not empty: {}".format(args.output_dir))

    images = sorted(
        path
        for path in args.dataset_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )
    random.Random(args.seed).shuffle(images)
    selected: List[Path] = []
    excluded_invalid_gender = 0
    scan_failures: List[Dict[str, str]] = []
    scanned_count = 0

    # Preserve the randomized ordering while keeping two HTTP requests in flight.
    for batch in chunks(images, max(args.concurrency * 25, args.concurrency)):
        scan_args = [(args.url, image, args.timeout) for image in batch]
        with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            results = list(executor.map(scan_raw, scan_args))
        for image_path, marker, error in results:
            scanned_count += 1
            if error:
                scan_failures.append({"image": image_path.name, "error": error})
                continue
            if marker:
                excluded_invalid_gender += 1
                continue
            selected.append(image_path)
            if len(selected) >= args.sample_size:
                break
        print(
            "scanned={}, eligible={}, excluded_invalid_gender={}, failures={}".format(
                scanned_count, len(selected), excluded_invalid_gender, len(scan_failures)
            ),
            flush=True,
        )
        if len(selected) >= args.sample_size:
            break

    if len(selected) < args.sample_size:
        raise RuntimeError(
            "Only {} eligible images found; expected {}".format(
                len(selected), args.sample_size
            )
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    image_output_dir = args.output_dir / "images"
    image_output_dir.mkdir()
    records = []
    prelabel_failures = []
    for index, image_path in enumerate(selected, start=1):
        try:
            parsed = call_ocr(args.url, "ocr", image_path, args.timeout)
        except Exception as exc:
            prelabel_failures.append({"image": image_path.name, "error": type(exc).__name__})
            continue

        shutil.copy2(image_path, image_output_dir / image_path.name)
        record = {"image_file": image_path.name}
        for field in FIELD_NAMES:
            value = str(parsed.get(field) or "")
            record["pre_{}".format(field)] = value
            # The reviewer edits only incorrect values, then records the review state.
            record["final_{}".format(field)] = value
        record.update(
            {"review_status": "pending", "reviewer": "", "reviewed_at": "", "notes": ""}
        )
        records.append(record)
        if index % 25 == 0 or index == len(selected):
            print("prelabelled [{}/{}]".format(index, len(selected)), flush=True)

    manifest = {
        "source_count": len(images),
        "scanned_count": scanned_count,
        "excluded_invalid_gender": excluded_invalid_gender,
        "scan_failures": len(scan_failures),
        "prelabel_failures": len(prelabel_failures),
        "selected_count": len(records),
        "seed": args.seed,
        "url": args.url,
        "invalid_gender_markers": list(INVALID_GENDER_MARKERS),
        "selection_files": [record["image_file"] for record in records],
        "scan_failure_details": scan_failures,
        "prelabel_failure_details": prelabel_failures,
    }
    write_csv(args.output_dir / "annotation_template.csv", records)
    (args.output_dir / "selection_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.output_dir / "README.md").write_text(markdown_text(manifest), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if len(records) == args.sample_size else 1


if __name__ == "__main__":
    raise SystemExit(main())
