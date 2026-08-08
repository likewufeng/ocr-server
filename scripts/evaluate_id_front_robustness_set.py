"""Evaluate ID-front robustness variants against a reviewed source gold set."""

import argparse
import csv
import json
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from prepare_id_front_review_set import FIELD_NAMES, call_ocr
from report_id_front_review_accuracy import COUNTED_STATUSES, normalize, rate, read_review_rows


SCENARIO_DESCRIPTIONS = {
    "aspect_warp": ("轻微比例扭曲", "模拟证件被挤压或拉伸后的长宽比例变化"),
    "background": ("复杂背景", "模拟证件放在杂乱桌面或非纯色背景上拍摄"),
    "edge_crop": ("边缘缺失", "模拟拍摄不全，证件边缘被裁掉"),
    "gaussian_blur": ("失焦模糊", "模拟对焦不准造成的整体模糊"),
    "gaussian_noise": ("画面噪点", "模拟暗光高感光度拍摄产生的噪点"),
    "glare": ("局部强反光", "模拟闪光灯或灯光反射覆盖局部文字"),
    "illumination": ("整体过亮或过暗", "模拟曝光异常或光照不足"),
    "jpeg_compression": ("高压缩失真", "模拟微信转发等 JPEG 多次压缩后的细节损失"),
    "low_resolution": ("低分辨率", "模拟低像素设备或图片被大幅缩小后的效果"),
    "motion_blur": ("运动模糊", "模拟拍摄时手抖或证件移动造成的拖影"),
    "occlusion": ("内容遮挡", "模拟手指、物体等遮住证件局部信息"),
    "perspective": ("透视畸变", "模拟从侧上方或斜角拍摄导致的梯形变形"),
    "rotation": ("图片倾斜", "模拟证件未摆正或拍摄角度倾斜"),
    "screen_rephoto": ("屏幕翻拍", "模拟对手机或显示器上的证件图片再次拍摄"),
    "shadow": ("局部阴影", "模拟背光或遮挡光源导致的暗部区域"),
}

CATEGORY_LABELS = {
    "quality": "图像质量",
    "geometry": "几何与角度",
    "lighting": "光照",
    "occlusion": "遮挡与缺失",
    "background": "背景",
    "media": "介质",
}

MODE_LABELS = {
    "scored": "纳入总分",
    "diagnostic": "仅诊断，不纳入总分",
}


def request_with_retry(url: str, image_path: Path, timeout: float) -> Dict[str, object]:
    error = None
    for attempt in range(3):
        try:
            return call_ocr(url, "ocr", image_path, timeout)
        except Exception as exc:
            error = exc
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    raise error


def read_manifest(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as input_file:
        rows = list(csv.DictReader(input_file))
    required = {"variant_file", "source_image", "scenario", "category", "evaluation_mode"}
    missing = required.difference(rows[0] if rows else {})
    if missing:
        raise ValueError("manifest missing columns: {}".format(", ".join(sorted(missing))))
    return rows


def counter_report(counter: Counter, successful: int) -> Dict[str, object]:
    return {
        "successful_requests": successful,
        "all_fields_exact_correct": counter["all_fields"],
        "all_fields_exact_rate": rate(counter["all_fields"], successful),
        "field_accuracy": {
            field: {
                "correct": counter[field],
                "total": successful,
                "accuracy_percent": rate(counter[field], successful),
            }
            for field in FIELD_NAMES
        },
    }


def evaluate_variant(args: Tuple[Dict[str, str], Dict[str, str], Path, str, float]) -> Dict[str, object]:
    variant, gold, images_dir, url, timeout = args
    try:
        actual = request_with_retry(url, images_dir / variant["variant_file"], timeout)
    except Exception as exc:
        return {"variant": variant, "error": type(exc).__name__}
    matches = {}
    for field in FIELD_NAMES:
        matches[field] = normalize(field, actual.get(field)) == normalize(
            field, gold.get("final_{}".format(field))
        )
    return {"variant": variant, "matches": matches}


def render_markdown(report: Dict[str, object]) -> str:
    lines = [
        "# 身份证正面 OCR 鲁棒性报告",
        "",
        "本报告比较当前 `/ocr` 接口结果与人工校对后的金标，不包含任何证件字段原文或源图片名称。",
        "",
        "| 指标 | 结果 |",
        "| --- | ---: |",
        "| 测试图片总数 | {} |".format(report["total_variants"]),
        "| 接口成功数 | {} |".format(report["successful_requests"]),
        "| 接口失败数 | {} |".format(report["failed_requests"]),
        "| 纳入总分的图片数 | {} |".format(report["scored_variants"]),
        "| 纳入总分的全字段完全正确率 | {}% |".format(
            report["scored_overall"]["all_fields_exact_rate"]
        ),
        "",
        "## 各场景结果",
        "",
        "| 测试场景 | 英文标识 | 中文解释 | 场景类别 | 统计口径 | 成功请求 | 全字段完全正确率 |",
        "| --- | --- | --- | --- | --- | ---: | ---: |",
    ]
    for name, item in report["scenarios"].items():
        value = item["result"]["all_fields_exact_rate"]
        rate_text = "-" if value is None else "{}%".format(value)
        display_name, description = SCENARIO_DESCRIPTIONS.get(name, (name, "未配置中文说明"))
        lines.append(
            "| {} | `{}` | {} | {} | {} | {} | {} |".format(
                display_name,
                name,
                description,
                CATEGORY_LABELS.get(item["category"], item["category"]),
                MODE_LABELS.get(item["evaluation_mode"], item["evaluation_mode"]),
                item["result"]["successful_requests"],
                rate_text,
            )
        )
    lines.extend(
        [
            "",
            "## 怎么看结果",
            "",
            "- “纳入总分”表示证件信息仍完整，结果会计入鲁棒性主指标。",
            "- “仅诊断，不纳入总分”表示图片故意模拟反光、遮挡、缺边或翻拍，结果仅用于观察系统边界。",
            "- 屏幕翻拍要实现自动判定通过或不通过，接口还需要单独返回风险标记字段。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate generated ID-front robustness variants")
    parser.add_argument("--source-csv", type=Path)
    parser.add_argument("--images-dir", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-markdown", required=True, type=Path)
    parser.add_argument(
        "--render-report-json",
        type=Path,
        help="Render Markdown from an existing JSON report without calling the OCR API",
    )
    args = parser.parse_args()
    if args.render_report_json:
        report = json.loads(args.render_report_json.read_text(encoding="utf-8"))
        args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
        args.output_markdown.write_text(render_markdown(report), encoding="utf-8-sig")
        print("rendered {}".format(args.output_markdown))
        return 0
    if not args.source_csv or not args.images_dir or not args.manifest or not args.output_json:
        parser.error(
            "--source-csv, --images-dir, --manifest, and --output-json are required for evaluation"
        )
    if args.concurrency < 1:
        parser.error("concurrency must be positive")

    gold_rows = {
        row.get("image_file"): row
        for row in read_review_rows(args.source_csv)
        if (row.get("review_status") or "").strip().lower() in COUNTED_STATUSES
    }
    manifest_rows = read_manifest(args.manifest)
    work = []
    skipped = []
    for variant in manifest_rows:
        gold = gold_rows.get(variant["source_image"])
        if gold is None:
            skipped.append(variant["variant_file"])
            continue
        work.append((variant, gold, args.images_dir, args.url, args.timeout))

    counters = defaultdict(Counter)
    scenario_meta = {}
    failures = []
    started_at = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        for index, result in enumerate(executor.map(evaluate_variant, work), start=1):
            variant = result["variant"]
            name = variant["scenario"]
            scenario_meta[name] = {
                "category": variant["category"],
                "evaluation_mode": variant["evaluation_mode"],
            }
            if "error" in result:
                failures.append({"scenario": name, "error": result["error"]})
            else:
                counter = counters[name]
                counter["successful"] += 1
                all_correct = True
                for field, matched in result["matches"].items():
                    if matched:
                        counter[field] += 1
                    else:
                        all_correct = False
                if all_correct:
                    counter["all_fields"] += 1
            if index % 50 == 0 or index == len(work):
                print("evaluated [{}/{}]".format(index, len(work)), flush=True)

    scored_counter = Counter()
    scenario_reports = {}
    for name in sorted(scenario_meta):
        meta = scenario_meta[name]
        counter = counters[name]
        successful = counter["successful"]
        scenario_reports[name] = {
            "category": meta["category"],
            "evaluation_mode": meta["evaluation_mode"],
            "result": counter_report(counter, successful),
        }
        if meta["evaluation_mode"] == "scored":
            scored_counter.update(counter)

    successful = len(work) - len(failures)
    report = {
        "total_variants": len(work),
        "successful_requests": successful,
        "failed_requests": len(failures),
        "skipped_variants": len(skipped),
        "scored_variants": scored_counter["successful"],
        "scored_overall": counter_report(scored_counter, scored_counter["successful"]),
        "scenarios": scenario_reports,
        "duration_seconds": round(time.monotonic() - started_at, 2),
        "failures_by_scenario": dict(sorted(Counter(item["scenario"] for item in failures).items())),
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output_markdown.write_text(render_markdown(report), encoding="utf-8-sig")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
