"""Generate deterministic robustness variants from a reviewed ID-front gold set."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Tuple

import cv2
import numpy as np

from report_id_front_review_accuracy import COUNTED_STATUSES, read_review_rows


ScenarioFunc = Callable[[np.ndarray, np.random.RandomState], np.ndarray]


def stable_rng(seed: int, source_name: str, scenario: str) -> np.random.RandomState:
    material = "{}:{}:{}".format(seed, source_name, scenario).encode("utf-8")
    value = int(hashlib.sha256(material).hexdigest()[:8], 16)
    return np.random.RandomState(value)


def motion_blur(image: np.ndarray, rng: np.random.RandomState) -> np.ndarray:
    length = int(rng.choice([9, 11, 13]))
    kernel = np.zeros((length, length), dtype=np.float32)
    cv2.line(kernel, (0, length // 2), (length - 1, length // 2), 1, 1)
    matrix = cv2.getRotationMatrix2D((length / 2.0, length / 2.0), rng.uniform(0, 180), 1)
    kernel = cv2.warpAffine(kernel, matrix, (length, length))
    kernel /= max(float(kernel.sum()), 1.0)
    return cv2.filter2D(image, -1, kernel)


def low_resolution(image: np.ndarray, rng: np.random.RandomState) -> np.ndarray:
    scale = float(rng.uniform(0.30, 0.45))
    height, width = image.shape[:2]
    small = cv2.resize(image, (max(1, int(width * scale)), max(1, int(height * scale))), interpolation=cv2.INTER_AREA)
    return cv2.resize(small, (width, height), interpolation=cv2.INTER_LINEAR)


def gaussian_noise(image: np.ndarray, rng: np.random.RandomState) -> np.ndarray:
    noise = rng.normal(0, rng.uniform(9, 16), image.shape).astype(np.float32)
    return np.clip(image.astype(np.float32) + noise, 0, 255).astype(np.uint8)


def rotation(image: np.ndarray, rng: np.random.RandomState) -> np.ndarray:
    height, width = image.shape[:2]
    angle = float(rng.choice([-1, 1]) * rng.uniform(4, 12))
    matrix = cv2.getRotationMatrix2D((width / 2.0, height / 2.0), angle, 1.0)
    return cv2.warpAffine(image, matrix, (width, height), borderMode=cv2.BORDER_CONSTANT, borderValue=(245, 245, 245))


def perspective(image: np.ndarray, rng: np.random.RandomState) -> np.ndarray:
    height, width = image.shape[:2]
    source = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
    jitter_x = width * rng.uniform(0.025, 0.055)
    jitter_y = height * rng.uniform(0.025, 0.055)
    destination = source + rng.uniform(
        low=[-jitter_x, -jitter_y], high=[jitter_x, jitter_y], size=(4, 2)
    ).astype(np.float32)
    transform = cv2.getPerspectiveTransform(source, destination)
    return cv2.warpPerspective(image, transform, (width, height), borderMode=cv2.BORDER_CONSTANT, borderValue=(245, 245, 245))


def aspect_warp(image: np.ndarray, rng: np.random.RandomState) -> np.ndarray:
    height, width = image.shape[:2]
    scale_x = float(rng.choice([rng.uniform(0.91, 0.96), rng.uniform(1.04, 1.09)]))
    warped = cv2.resize(image, (max(1, int(width * scale_x)), height), interpolation=cv2.INTER_CUBIC)
    return cv2.resize(warped, (width, height), interpolation=cv2.INTER_CUBIC)


def illumination(image: np.ndarray, rng: np.random.RandomState) -> np.ndarray:
    gamma = float(rng.choice([rng.uniform(0.48, 0.72), rng.uniform(1.25, 1.55)]))
    normalized = image.astype(np.float32) / 255.0
    return np.clip(np.power(normalized, gamma) * 255.0, 0, 255).astype(np.uint8)


def jpeg_compression(image: np.ndarray, rng: np.random.RandomState) -> np.ndarray:
    quality = int(rng.choice([25, 30, 35]))
    success, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not success:
        raise RuntimeError("JPEG encoding failed")
    return cv2.imdecode(encoded, cv2.IMREAD_COLOR)


def background(image: np.ndarray, rng: np.random.RandomState) -> np.ndarray:
    height, width = image.shape[:2]
    canvas_height, canvas_width = int(height * 1.25), int(width * 1.25)
    background_noise = rng.normal(185, 20, (canvas_height, canvas_width, 3))
    canvas = np.clip(background_noise, 90, 230).astype(np.uint8)
    for y in range(0, canvas_height, max(24, canvas_height // 12)):
        cv2.line(canvas, (0, y), (canvas_width, y), (150, 150, 150), 1)

    margin_x, margin_y = int(width * 0.12), int(height * 0.12)
    source = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
    base = np.float32(
        [
            [margin_x, margin_y],
            [canvas_width - margin_x - 1, margin_y],
            [canvas_width - margin_x - 1, canvas_height - margin_y - 1],
            [margin_x, canvas_height - margin_y - 1],
        ]
    )
    jitter = np.array([[width * 0.025, height * 0.025]], dtype=np.float32)
    destination = base + rng.uniform(-jitter, jitter, size=(4, 2)).astype(np.float32)
    transform = cv2.getPerspectiveTransform(source, destination)
    warped = cv2.warpPerspective(image, transform, (canvas_width, canvas_height))
    mask = cv2.warpPerspective(np.full((height, width), 255, dtype=np.uint8), transform, (canvas_width, canvas_height))
    canvas[mask > 0] = warped[mask > 0]
    return canvas


def glare(image: np.ndarray, rng: np.random.RandomState) -> np.ndarray:
    height, width = image.shape[:2]
    center_x = rng.uniform(width * 0.25, width * 0.75)
    center_y = rng.uniform(height * 0.2, height * 0.8)
    y, x = np.ogrid[:height, :width]
    distance = ((x - center_x) / (width * 0.22)) ** 2 + ((y - center_y) / (height * 0.18)) ** 2
    alpha = np.exp(-distance * 2.5)[:, :, None] * rng.uniform(0.55, 0.8)
    return np.clip(image.astype(np.float32) * (1.0 - alpha) + 255.0 * alpha, 0, 255).astype(np.uint8)


def shadow(image: np.ndarray, rng: np.random.RandomState) -> np.ndarray:
    height, width = image.shape[:2]
    center_x = rng.uniform(0, width)
    center_y = rng.uniform(0, height)
    y, x = np.ogrid[:height, :width]
    distance = ((x - center_x) / (width * 0.55)) ** 2 + ((y - center_y) / (height * 0.55)) ** 2
    factor = 1.0 - np.exp(-distance * 1.8) * rng.uniform(0.45, 0.65)
    return np.clip(image.astype(np.float32) * factor[:, :, None], 0, 255).astype(np.uint8)


def edge_crop(image: np.ndarray, rng: np.random.RandomState) -> np.ndarray:
    height, width = image.shape[:2]
    side = int(rng.choice([0, 1, 2, 3]))
    ratio = float(rng.uniform(0.06, 0.12))
    left, top, right, bottom = 0, 0, width, height
    if side == 0:
        left = int(width * ratio)
    elif side == 1:
        right = width - int(width * ratio)
    elif side == 2:
        top = int(height * ratio)
    else:
        bottom = height - int(height * ratio)
    cropped = image[top:bottom, left:right]
    return cv2.resize(cropped, (width, height), interpolation=cv2.INTER_CUBIC)


def occlusion(image: np.ndarray, rng: np.random.RandomState) -> np.ndarray:
    result = image.copy()
    height, width = result.shape[:2]
    rectangle_width = int(width * rng.uniform(0.14, 0.24))
    rectangle_height = int(height * rng.uniform(0.10, 0.20))
    x = int(rng.uniform(0, max(1, width - rectangle_width)))
    y = int(rng.uniform(0, max(1, height - rectangle_height)))
    color = int(rng.uniform(35, 90))
    cv2.rectangle(result, (x, y), (x + rectangle_width, y + rectangle_height), (color, color, color), -1)
    return result


def screen_rephoto(image: np.ndarray, rng: np.random.RandomState) -> np.ndarray:
    height, width = image.shape[:2]
    margin = max(18, int(min(width, height) * 0.06))
    canvas = np.full((height + margin * 2, width + margin * 2, 3), 18, dtype=np.uint8)
    canvas[margin : margin + height, margin : margin + width] = image
    y, x = np.ogrid[:height, :width]
    pattern = (np.sin(x * rng.uniform(0.18, 0.28)) + np.sin(y * rng.uniform(0.18, 0.28))) * 5.0
    region = canvas[margin : margin + height, margin : margin + width].astype(np.float32)
    canvas[margin : margin + height, margin : margin + width] = np.clip(region + pattern[:, :, None], 0, 255).astype(np.uint8)
    return canvas


SCENARIOS: Dict[str, Tuple[str, str, ScenarioFunc]] = {
    "gaussian_blur": ("quality", "scored", lambda image, rng: cv2.GaussianBlur(image, (5, 5), 1.4)),
    "motion_blur": ("quality", "scored", motion_blur),
    "low_resolution": ("quality", "scored", low_resolution),
    "gaussian_noise": ("quality", "scored", gaussian_noise),
    "rotation": ("geometry", "scored", rotation),
    "perspective": ("geometry", "scored", perspective),
    "aspect_warp": ("geometry", "scored", aspect_warp),
    "illumination": ("lighting", "scored", illumination),
    "jpeg_compression": ("quality", "scored", jpeg_compression),
    "background": ("background", "scored", background),
    "glare": ("lighting", "diagnostic", glare),
    "shadow": ("lighting", "diagnostic", shadow),
    "edge_crop": ("occlusion", "diagnostic", edge_crop),
    "occlusion": ("occlusion", "diagnostic", occlusion),
    "screen_rephoto": ("media", "diagnostic", screen_rephoto),
}


def parse_scenarios(value: str, include_diagnostic: bool) -> List[str]:
    if value:
        names = [item.strip() for item in value.split(",") if item.strip()]
    else:
        names = [name for name, (_, mode, _) in SCENARIOS.items() if mode == "scored"]
        if include_diagnostic:
            names.extend(name for name, (_, mode, _) in SCENARIOS.items() if mode == "diagnostic")
    unknown = [name for name in names if name not in SCENARIOS]
    if unknown:
        raise ValueError("Unknown scenarios: {}".format(", ".join(unknown)))
    return names


def read_image(path: Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Unable to decode image: {}".format(path))
    return image


def write_image(path: Path, image: np.ndarray, quality: int) -> None:
    success, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not success:
        raise RuntimeError("Unable to encode image: {}".format(path))
    encoded.tofile(str(path))


def reviewed_rows(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    return [
        row
        for row in rows
        if (row.get("review_status") or "").strip().lower() in COUNTED_STATUSES
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate deterministic ID-front robustness variants")
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=20260807)
    parser.add_argument("--scenarios", default="", help="Comma-separated scenario names")
    parser.add_argument("--include-diagnostic", action="store_true")
    parser.add_argument("--jpeg-quality", type=int, default=92)
    args = parser.parse_args()

    if not args.source_dir.is_dir():
        parser.error("source-dir does not exist: {}".format(args.source_dir))
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error("output-dir must be empty: {}".format(args.output_dir))
    if not 1 <= args.jpeg_quality <= 100:
        parser.error("jpeg-quality must be between 1 and 100")

    source_csv = args.source_dir / "annotation_template.csv"
    source_images = args.source_dir / "images"
    rows = reviewed_rows(read_review_rows(source_csv))
    if not rows:
        parser.error("no confirmed or corrected rows found in {}".format(source_csv))
    scenarios = parse_scenarios(args.scenarios, args.include_diagnostic)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_images = args.output_dir / "images"
    output_images.mkdir()
    manifest_rows = []
    failures = []
    for source_index, row in enumerate(rows, start=1):
        source_name = row.get("image_file") or ""
        source_path = source_images / source_name
        try:
            image = read_image(source_path)
        except Exception as exc:
            failures.append({"source_image": source_name, "error": type(exc).__name__})
            continue
        stem = Path(source_name).stem
        for scenario in scenarios:
            category, mode, transform = SCENARIOS[scenario]
            variant_name = "{}__{}.jpg".format(stem, scenario)
            try:
                variant = transform(image, stable_rng(args.seed, source_name, scenario))
                write_image(output_images / variant_name, variant, args.jpeg_quality)
            except Exception as exc:
                failures.append(
                    {"source_image": source_name, "scenario": scenario, "error": type(exc).__name__}
                )
                continue
            manifest_rows.append(
                {
                    "variant_file": variant_name,
                    "source_image": source_name,
                    "scenario": scenario,
                    "category": category,
                    "evaluation_mode": mode,
                }
            )
        if source_index % 25 == 0 or source_index == len(rows):
            print("generated [{}/{}]".format(source_index, len(rows)), flush=True)

    manifest_path = args.output_dir / "manifest.csv"
    with manifest_path.open("w", encoding="utf-8-sig", newline="") as output_file:
        writer = csv.DictWriter(
            output_file,
            fieldnames=("variant_file", "source_image", "scenario", "category", "evaluation_mode"),
        )
        writer.writeheader()
        writer.writerows(manifest_rows)
    summary = {
        "source_dir": str(args.source_dir),
        "source_samples": len(rows),
        "seed": args.seed,
        "scenarios": scenarios,
        "generated_variants": len(manifest_rows),
        "failures": failures,
    }
    (args.output_dir / "generation_manifest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
