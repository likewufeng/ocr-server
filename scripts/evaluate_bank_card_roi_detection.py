"""Evaluate ONNX bank-card ROI detection against a YOLO-format test split."""
import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2

# Allow the evaluator to run directly from any working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.bank_card_roi import BankCardROILocalizer


CLASS_NAMES = ("card_number", "date", "union_pay")


def intersection_over_union(a, b) -> float:
    left = max(a[0], b[0])
    top = max(a[1], b[1])
    right = min(a[2], b[2])
    bottom = min(a[3], b[3])
    intersection = max(0, right - left) * max(0, bottom - top)
    if not intersection:
        return 0.0
    area_a = max(0, a[2] - a[0]) * max(0, a[3] - a[1])
    area_b = max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    return intersection / max(1, area_a + area_b - intersection)


def load_labels(label_path: Path, image_width: int, image_height: int):
    labels = []
    if not label_path.is_file():
        return labels
    for line in label_path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) != 5:
            continue
        class_id, center_x, center_y, width, height = map(float, parts)
        class_id = int(class_id)
        left = int((center_x - width / 2) * image_width)
        top = int((center_y - height / 2) * image_height)
        right = int((center_x + width / 2) * image_width)
        bottom = int((center_y + height / 2) * image_height)
        labels.append((class_id, (left, top, right, bottom)))
    return labels


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate card field detector recall")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True, help="detection split root")
    parser.add_argument("--split", choices=("test", "valid", "train"), default="test")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confidence", type=float, default=0.45)
    parser.add_argument("--iou", type=float, default=0.5)
    args = parser.parse_args()

    localizer = BankCardROILocalizer(args.model, confidence_threshold=args.confidence)
    image_dir = args.dataset / args.split / "images"
    label_dir = args.dataset / args.split / "labels"
    if not image_dir.is_dir() or not label_dir.is_dir():
        raise SystemExit("dataset must contain <split>/images and <split>/labels")

    counts = defaultdict(Counter)
    rows = []
    for image_path in sorted(image_dir.iterdir()):
        image = cv2.imread(str(image_path))
        if image is None:
            continue
        height, width = image.shape[:2]
        labels = load_labels(label_dir / (image_path.stem + ".txt"), width, height)
        predictions = localizer.detect(image)
        used_prediction_indexes = set()
        for class_id, expected_box in labels:
            label = CLASS_NAMES[class_id]
            candidates = [
                (index, intersection_over_union(expected_box, (item.left, item.top, item.right, item.bottom)))
                for index, item in enumerate(predictions)
                if item.label == label and index not in used_prediction_indexes
            ]
            best_index, best_iou = max(candidates, key=lambda item: item[1], default=(-1, 0.0))
            matched = best_iou >= args.iou
            counts[label]["ground_truth"] += 1
            counts[label]["true_positive"] += int(matched)
            if matched:
                used_prediction_indexes.add(best_index)
            rows.append(
                {
                    "image": image_path.name,
                    "field": label,
                    "matched": matched,
                    "best_iou": round(best_iou, 4),
                }
            )
        for index, prediction in enumerate(predictions):
            if index not in used_prediction_indexes:
                counts[prediction.label]["false_positive"] += 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.with_suffix(".csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=("image", "field", "matched", "best_iou"))
        writer.writeheader()
        writer.writerows(rows)

    report = [
        "# 银行卡区域定位评测报告",
        "",
        "| 字段 | 标注框数 | IoU >= {:.2f} 命中数 | 召回率 | 误检数 |".format(args.iou),
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for label in CLASS_NAMES:
        ground_truth = counts[label]["ground_truth"]
        true_positive = counts[label]["true_positive"]
        report.append(
            "| {} | {} | {} | {:.2%} | {} |".format(
                label,
                ground_truth,
                true_positive,
                true_positive / ground_truth if ground_truth else 0,
                counts[label]["false_positive"],
            )
        )
    report.append("")
    report.append("明细见同目录 CSV。该指标只衡量区域定位，不能代替卡号和有效期文字准确率。")
    args.output.with_suffix(".md").write_text("\n".join(report) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
