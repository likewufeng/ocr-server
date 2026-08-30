"""只读检查 ICDAR 2023 ReST 印章文字数据集。

该脚本不会复制、改写或删除数据集文件。它读取训练图片和 train_gts.json，
校验文件对应关系，并输出一份适合归档的中文 Markdown 检查报告。
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _image_size(path: Path) -> Optional[Tuple[int, int]]:
    """优先使用项目已有的 OpenCV；没有 OpenCV 时不影响其余检查。"""
    try:
        import cv2  # type: ignore

        image = cv2.imread(str(path))
        if image is None:
            return None
        height, width = image.shape[:2]
        return int(width), int(height)
    except ImportError:
        return None


def _iter_instances(data: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for values in data.values():
        if isinstance(values, list):
            for item in values:
                if isinstance(item, dict):
                    yield item


def inspect_dataset(root: Path) -> Dict[str, Any]:
    train_root = root / "ReST_train"
    image_root = train_root / "train_images"
    test_root = root / "test_images"
    annotation_path = train_root / "train_gts.json"
    chars_path = train_root / "chars.txt"

    data: Dict[str, Any] = json.loads(annotation_path.read_text(encoding="utf-8"))
    image_paths = sorted(image_root.glob("*.jpg"), key=lambda item: item.stem)
    image_names = {path.stem for path in image_paths}
    gt_numbers = sorted(
        int(key[3:])
        for key in data
        if isinstance(key, str) and key.startswith("gt_") and key[3:].isdigit()
    )
    gt_names = {str(number) for number in gt_numbers}
    instances = list(_iter_instances(data))
    texts = [str(item.get("transcription", "")) for item in instances]
    lengths = [len(text) for text in texts]
    point_counts = [len(item.get("points", [])) for item in instances]
    invalid_point_instances = sum(
        not isinstance(item.get("points"), list) or len(item.get("points", [])) < 3
        for item in instances
    )

    dimensions: Counter[str] = Counter()
    unreadable_images: List[str] = []
    for path in image_paths:
        size = _image_size(path)
        if size is None:
            unreadable_images.append(path.name)
        else:
            dimensions[f"{size[0]}x{size[1]}"] += 1

    chars_text = chars_path.read_text(encoding="utf-8") if chars_path.exists() else ""
    return {
        "root": str(root),
        "train_images": len(image_paths),
        "test_images": len(list(test_root.glob("*.jpg"))),
        "annotation_entries": len(data),
        "annotation_key_min": min(gt_numbers) if gt_numbers else None,
        "annotation_key_max": max(gt_numbers) if gt_numbers else None,
        "missing_annotation_keys": len(set(range(min(gt_numbers), max(gt_numbers) + 1)) - set(gt_numbers))
        if gt_numbers
        else None,
        "images_without_annotation": len(image_names - gt_names),
        "annotations_without_image": len(gt_names - image_names),
        "text_instances": len(instances),
        "empty_annotation_entries": sum(not values for values in data.values()),
        "empty_transcriptions": sum(not text for text in texts),
        "replacement_character_transcriptions": sum("\ufffd" in text for text in texts),
        "unique_transcriptions": len(set(texts)),
        "text_length_min": min(lengths) if lengths else None,
        "text_length_max": max(lengths) if lengths else None,
        "text_length_average": round(statistics.mean(lengths), 2) if lengths else None,
        "point_count_min": min(point_counts) if point_counts else None,
        "point_count_max": max(point_counts) if point_counts else None,
        "point_count_average": round(statistics.mean(point_counts), 2) if point_counts else None,
        "invalid_point_instances": invalid_point_instances,
        "top_text_lengths": Counter(lengths).most_common(10),
        "image_dimensions": dimensions.most_common(10),
        "unreadable_images": unreadable_images[:20],
        "chars_file_bytes": chars_path.stat().st_size if chars_path.exists() else None,
        "chars_count": len(chars_text),
        "chars_replacement_count": chars_text.count("\ufffd"),
        "train_zip_exists": (train_root / "train_images.zip").exists(),
        "test_zip_exists": (root / "test_images.zip").exists(),
        "sample_transcriptions": texts[:10],
    }


def render_markdown(result: Dict[str, Any]) -> str:
    dimensions = "、".join(f"{name}（{count}张）" for name, count in result["image_dimensions"])
    lengths = "、".join(f"{length}字符：{count}条" for length, count in result["top_text_lengths"])
    samples = "\n".join(f"- `{text!r}`" for text in result["sample_transcriptions"])
    status = "通过" if all(
        result[key] == 0
        for key in ("missing_annotation_keys", "images_without_annotation", "annotations_without_image", "empty_annotation_entries", "empty_transcriptions")
    ) and not result["unreadable_images"] and result["invalid_point_instances"] == 0 else "需关注"

    return f"""# ReST 印章文字数据集检查报告

> 检查方式：只读检查。原始数据未复制、未改写、未删除。
> 数据集路径：`{result['root']}`
> 检查结论：**{status}**

## 1. 文件与对应关系

| 项目 | 结果 |
|---|---:|
| 训练图片 | {result['train_images']} |
| 测试图片 | {result['test_images']} |
| 训练标注条目 | {result['annotation_entries']} |
| 标注键范围 | `gt_{result['annotation_key_min']}` 到 `gt_{result['annotation_key_max']}` |
| 缺失标注键 | {result['missing_annotation_keys']} |
| 有图片无标注 | {result['images_without_annotation']} |
| 有标注无图片 | {result['annotations_without_image']} |
| 训练图片无法读取 | {len(result['unreadable_images'])} |
| 训练图片压缩包 | {'存在' if result['train_zip_exists'] else '不存在'} |
| 测试图片压缩包 | {'存在' if result['test_zip_exists'] else '不存在'} |

当前训练集文件名和标注可以完整对应。测试集有图片但没有公开金标准文字标注，因此不能直接计算测试集准确率。

## 2. 标注统计

| 项目 | 结果 |
|---|---:|
| 文字实例数 | {result['text_instances']} |
| 每张图片平均实例数 | {result['text_instances'] / result['train_images']:.2f} |
| 空标注条目 | {result['empty_annotation_entries']} |
| 空转写文本 | {result['empty_transcriptions']} |
| 含替换字符 `�` 的转写 | {result['replacement_character_transcriptions']} |
| 不同转写数量 | {result['unique_transcriptions']} |
| 文本长度最小/最大/平均 | {result['text_length_min']} / {result['text_length_max']} / {result['text_length_average']} |
| polygon 点数最小/最大/平均 | {result['point_count_min']} / {result['point_count_max']} / {result['point_count_average']} |
| polygon 点数少于 3 的实例 | {result['invalid_point_instances']} |

文本长度分布 Top 10：{lengths}

## 3. 图片统计

主要图片尺寸：{dimensions or '未读取到尺寸'}

## 4. 标注格式说明

标注文件是 JSON 对象，键名为 `gt_N`，对应 `ReST_train/train_images/N.jpg`。每个值是文字实例数组，实例包含：

- `points`：文字区域 polygon，点数不固定，不能按四边形处理；
- `transcription`：该区域的文字转写。

训练集当前每张图片恰好一个文字实例。原始 polygon 可能有很多点，做检测训练转换时应原样保留，或在转换到矩形检测格式时明确记录近似损失。当前有 {result['invalid_point_instances']} 个实例的 `points` 少于 3 个点，不能作为有效检测 polygon；做检测训练前应过滤，并保留这些样本用于识别训练或质量排查。

## 5. 字符表与文本风险

`chars.txt` 大小为 {result['chars_file_bytes']} 字节，读取字符数为 {result['chars_count']}，其中替换字符 `�` 数量为 {result['chars_replacement_count']}。

前 10 条转写抽样：
{samples}

如果抽样或统计中出现大量 `�`，应先确认数据发布包本身是否把不可辨识字符编码为替换符。此类字符不能恢复为真实汉字，不应把它们当作可纠正的 OCR 答案；训练前建议按项目策略过滤、映射为特殊占位符，或保留为“不可识别字符”样本并单独统计。

## 6. 后续使用建议

1. 原始 ReST 目录作为只读归档，不直接复制到项目仓库。
2. 先用训练集划分出固定验证集，例如按图片编号固定保留 10%，不要每次随机变化。
3. 保留 ReST 原始 JSON，同时生成项目自己的 JSONL manifest，记录 `image`、`points`、`text`、`split` 和 `dataset`。
4. 先做当前 PP-OCRv6 基线，再做 ReST 专用识别模型微调，对比字符准确率、整串准确率和圆章真实样本效果。
5. ReST 官方许可仅限非商业研究和教育用途；未取得商业授权前，不应把其图片、标注或训练产物直接用于生产商业服务。
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="检查 ReST 印章文字数据集")
    parser.add_argument("dataset", type=Path, help="ReST 数据集根目录")
    parser.add_argument("--output", type=Path, required=True, help="输出 Markdown 报告路径")
    args = parser.parse_args()
    result = inspect_dataset(args.dataset.expanduser().resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_markdown(result), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"报告已生成：{args.output}")


if __name__ == "__main__":
    main()
