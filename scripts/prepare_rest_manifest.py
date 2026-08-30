"""为 ReST 数据集生成项目侧 JSONL manifest。

只写入项目目录中的 manifest，不复制或修改 ReST 原始图片、标注和压缩包。
生成的 image 路径相对于 ReST 数据集根目录，便于在不同机器上通过参数复用。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def load_annotations(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("train_gts.json 顶层必须是 JSON 对象")
    return value


def build_records(dataset_root: Path, validation_ratio: float) -> List[Dict[str, Any]]:
    train_root = dataset_root / "ReST_train"
    annotations = load_annotations(train_root / "train_gts.json")
    records: List[Dict[str, Any]] = []
    image_numbers = sorted(
        int(key[3:])
        for key in annotations
        if key.startswith("gt_") and key[3:].isdigit()
    )
    validation_count = round(len(image_numbers) * validation_ratio)
    validation_start = len(image_numbers) - validation_count

    for index, number in enumerate(image_numbers):
        values = annotations[f"gt_{number}"]
        if not isinstance(values, list):
            continue
        for instance_index, item in enumerate(values):
            if not isinstance(item, dict):
                continue
            points = item.get("points", [])
            records.append(
                {
                    "dataset": "ReST",
                    "image": (Path("ReST_train") / "train_images" / f"{number}.jpg").as_posix(),
                    "image_id": number,
                    "instance_id": instance_index,
                    "split": "val" if index >= validation_start else "train",
                    "points": points,
                    "text": str(item.get("transcription", "")),
                    "valid_polygon": isinstance(points, list) and len(points) >= 3,
                    "source_annotation": f"gt_{number}",
                }
            )
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 ReST 项目侧 JSONL manifest")
    parser.add_argument("dataset", type=Path, help="ReST 数据集根目录")
    parser.add_argument("--output", type=Path, required=True, help="输出 JSONL 文件")
    parser.add_argument("--validation-ratio", type=float, default=0.1, help="验证集比例，默认 0.1")
    args = parser.parse_args()
    if not 0 < args.validation_ratio < 1:
        raise ValueError("--validation-ratio 必须在 0 和 1 之间")

    records = build_records(args.dataset.expanduser().resolve(), args.validation_ratio)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"已生成 {len(records)} 条记录：{args.output}")


if __name__ == "__main__":
    main()
