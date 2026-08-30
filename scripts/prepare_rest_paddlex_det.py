"""把 ReST 训练标注转换为 PaddleX TextDetDataset。

ReST 原始目录保持只读。本脚本默认将图片复制到项目训练目录，避免训练时依赖
外部路径；原始 train_gts.json 不会被修改。少于 3 个点的 polygon 会被过滤，
但对应图片仍保留为空标注样本，便于模型学习背景和异常输入。
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import cv2
import numpy as np


def _instances(value: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                yield item


def _valid_points(points: Any) -> bool:
    return isinstance(points, list) and len(points) >= 3 and all(
        isinstance(point, (list, tuple)) and len(point) == 2 for point in points
    )


def _simplify_points(points: Any, epsilon: float) -> Tuple[Any, bool]:
    """压缩 ReST 的密集边界点，保留曲线形状并降低 DB 标注栅格化成本。"""
    if not _valid_points(points) or epsilon <= 0:
        return points, False
    contour = np.asarray(points, dtype=np.float32).reshape(-1, 1, 2)
    simplified = cv2.approxPolyDP(contour, epsilon, True).reshape(-1, 2)
    if len(simplified) < 3:
        return points, False
    return [[round(float(x), 2), round(float(y), 2)] for x, y in simplified], True


def prepare(
    dataset_root: Path,
    output_root: Path,
    validation_ratio: float,
    copy_images: bool,
    polygon_epsilon: float,
    max_images: int = 0,
) -> Tuple[int, int, int, int, int]:
    train_root = dataset_root / "ReST_train"
    source_images = train_root / "train_images"
    annotations_path = train_root / "train_gts.json"
    target_images = output_root / "images"
    output_root.mkdir(parents=True, exist_ok=True)
    target_images.mkdir(parents=True, exist_ok=True)

    with annotations_path.open("r", encoding="utf-8") as handle:
        annotations: Dict[str, Any] = json.load(handle)
    image_numbers = sorted(
        int(key[3:])
        for key in annotations
        if isinstance(key, str) and key.startswith("gt_") and key[3:].isdigit()
    )
    if max_images > 0:
        image_numbers = image_numbers[:max_images]
    validation_count = round(len(image_numbers) * validation_ratio)
    validation_start = len(image_numbers) - validation_count
    lines = {"train": [], "val": []}
    invalid_polygons = 0
    simplified_polygons = 0
    original_points = 0
    output_points = 0
    image_count = 0

    for index, number in enumerate(image_numbers):
        source = source_images / f"{number}.jpg"
        if not source.is_file():
            raise FileNotFoundError(source)
        if copy_images:
            shutil.copy2(source, target_images / source.name)
        label_items: List[Dict[str, Any]] = []
        for item in _instances(annotations[f"gt_{number}"]):
            points = item.get("points")
            if not _valid_points(points):
                invalid_polygons += 1
                continue
            original_points += len(points)
            points, simplified = _simplify_points(points, polygon_epsilon)
            if simplified:
                simplified_polygons += 1
            output_points += len(points)
            label_items.append({"points": points, "transcription": str(item.get("transcription", ""))})
        split = "val" if index >= validation_start else "train"
        lines[split].append(
            f"images/{source.name}\t{json.dumps(label_items, ensure_ascii=False, separators=(',', ':'))}\n"
        )
        image_count += 1

    for split, split_lines in lines.items():
        (output_root / f"{split}.txt").write_text("".join(split_lines), encoding="utf-8")
    metadata = {
        "dataset": "ReST",
        "source": str(dataset_root),
        "image_count": image_count,
        "train_count": len(lines["train"]),
        "val_count": len(lines["val"]),
        "invalid_polygons_filtered": invalid_polygons,
        "polygon_epsilon": polygon_epsilon,
        "simplified_polygons": simplified_polygons,
        "original_points": original_points,
        "output_points": output_points,
        "average_points_before": round(original_points / max(simplified_polygons + (image_count - invalid_polygons - simplified_polygons), 1), 2),
        "average_points_after": round(output_points / max(image_count - invalid_polygons, 1), 2),
        "max_images": max_images,
        "validation_ratio": validation_ratio,
        "copied_images": copy_images,
        "notes": "原始 points 少于 3 的实例未进入检测标注；对应图片保留为空标注样本。",
    }
    (output_root / "dataset_meta.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return image_count, len(lines["train"]), invalid_polygons, original_points, output_points


def main() -> None:
    parser = argparse.ArgumentParser(description="准备 ReST 的 PaddleX 印章文字检测数据")
    parser.add_argument("dataset", type=Path, help="ReST 数据集根目录")
    parser.add_argument("--output", type=Path, required=True, help="PaddleX 数据集输出目录")
    parser.add_argument("--validation-ratio", type=float, default=0.1)
    parser.add_argument("--polygon-epsilon", type=float, default=1.5, help="polygon 近似误差像素，0 表示保留原始点")
    parser.add_argument("--max-images", type=int, default=0, help="仅准备前 N 张图片，用于冒烟测试；0 表示全部")
    parser.add_argument("--no-copy-images", action="store_true", help="仅生成标注，不复制图片")
    args = parser.parse_args()
    if not 0 < args.validation_ratio < 1:
        raise ValueError("--validation-ratio 必须在 0 和 1 之间")
    result = prepare(
        args.dataset.expanduser().resolve(), args.output.expanduser().resolve(),
        args.validation_ratio, not args.no_copy_images, args.polygon_epsilon, args.max_images,
    )
    print(
        f"图片 {result[0]} 张，训练 {result[1]} 张，过滤无效 polygon {result[2]} 个，"
        f"polygon 点数 {result[3]} -> {result[4]}"
    )


if __name__ == "__main__":
    main()
