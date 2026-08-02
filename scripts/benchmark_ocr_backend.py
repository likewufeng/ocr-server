import argparse
import difflib
import json
import os
import statistics
import subprocess
import sys
import time
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Dict, List


RESULT_PREFIX = "OCR_BACKEND_RESULT="
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def run_worker(args: argparse.Namespace) -> int:
    os.environ["OCR_INFERENCE_BACKEND"] = args.backend
    os.environ["OCR_CACHE_ENABLED"] = "false"
    os.environ["OCR_SAVE_PREPROCESSED_IMAGE"] = "false"
    os.environ["OCR_USE_FINE_TUNED_MODEL"] = "false"
    os.environ["OCR_CPU_THREADS"] = str(args.cpu_threads)

    try:
        from app.parsers.parser import OCRParser
        from app.services.ocr_service import ocr_service
        from app.utils.layout import build_layout

        ocr_service.initialize()
        parser = OCRParser()
        timings: List[float] = []
        samples: List[Dict[str, Any]] = []
        for image_path in args.images:
            result = None
            for index in range(args.warmup + args.repeats):
                started_at = time.perf_counter()
                result = ocr_service.recognize(
                    str(image_path),
                    document_type=args.document_type,
                    auto_orientation=args.auto_orientation,
                )
                duration = time.perf_counter() - started_at
                if index >= args.warmup:
                    timings.append(duration)
            parsed = parser.parse(build_layout(result), document_type=args.document_type)
            samples.append(
                {
                    "image": image_path.name,
                    "texts": result.get("texts", []),
                    "parsed": parsed,
                }
            )
        report = {
            "status": "ok",
            "backend": args.backend,
            "cpu_threads": args.cpu_threads,
            "measurement_count": len(timings),
            "latency_seconds": {
                "average": round(statistics.mean(timings), 6),
                "median": round(statistics.median(timings), 6),
                "min": round(min(timings), 6),
                "max": round(max(timings), 6),
            },
            "samples": samples,
        }
    except Exception as exc:
        report = {
            "status": "unsupported" if args.backend == "openvino" else "error",
            "backend": args.backend,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "dependencies": {
                "ultra_infer": find_spec("ultra_infer") is not None,
                "paddle2onnx": find_spec("paddle2onnx") is not None,
            },
        }
    print(RESULT_PREFIX + json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "ok" else 2


def execute_backend(args: argparse.Namespace, backend: str) -> Dict[str, Any]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--backend",
        backend,
        "--repeats",
        str(args.repeats),
        "--warmup",
        str(args.warmup),
        "--cpu-threads",
        str(args.cpu_threads),
    ]
    if args.document_type:
        command.extend(("--document-type", args.document_type))
    if args.auto_orientation:
        command.append("--auto-orientation")
    else:
        command.append("--no-auto-orientation")
    for image_path in args.images:
        command.extend(("--image", str(image_path)))

    completed = subprocess.run(command, capture_output=True, text=True)
    for line in reversed(completed.stdout.splitlines()):
        if line.startswith(RESULT_PREFIX):
            return json.loads(line[len(RESULT_PREFIX):])
    return {
        "status": "error",
        "backend": backend,
        "error": completed.stderr.strip() or "worker did not return a result",
    }


def compare_quality(baseline: Dict[str, Any], candidate: Dict[str, Any]) -> List[Dict[str, Any]]:
    comparisons = []
    for left, right in zip(baseline.get("samples", []), candidate.get("samples", [])):
        left_text = "".join(left.get("texts", []))
        right_text = "".join(right.get("texts", []))
        comparisons.append(
            {
                "image": left.get("image"),
                "text_similarity": round(
                    difflib.SequenceMatcher(None, left_text, right_text).ratio(), 6
                ),
                "parsed_fields_equal": left.get("parsed") == right.get("parsed"),
                "paddle_parsed": left.get("parsed"),
                "openvino_parsed": right.get("parsed"),
            }
        )
    return comparisons


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Paddle/MKLDNN 与 OpenVINO OCR 对照实验")
    parser.add_argument("--image", action="append", dest="images", type=Path, required=True)
    parser.add_argument("--document-type")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--cpu-threads", type=int, default=8)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--backend", choices=("paddle", "openvino"), help=argparse.SUPPRESS)
    orientation = parser.add_mutually_exclusive_group()
    orientation.add_argument("--auto-orientation", action="store_true", dest="auto_orientation")
    orientation.add_argument("--no-auto-orientation", action="store_false", dest="auto_orientation")
    parser.set_defaults(auto_orientation=True)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    for image_path in args.images:
        if not image_path.is_file():
            parser.error("图片不存在: {}".format(image_path))
    if args.repeats < 1 or args.warmup < 0 or args.cpu_threads < 1:
        parser.error("repeats/cpu-threads 必须大于 0，warmup 不能小于 0")
    if args.worker:
        if not args.backend:
            parser.error("worker 模式必须指定 backend")
        return run_worker(args)

    baseline = execute_backend(args, "paddle")
    openvino = execute_backend(args, "openvino")
    report: Dict[str, Any] = {"paddle": baseline, "openvino": openvino}
    if baseline.get("status") == "ok" and openvino.get("status") == "ok":
        paddle_average = baseline["latency_seconds"]["average"]
        openvino_average = openvino["latency_seconds"]["average"]
        report["comparison"] = {
            "openvino_speedup": round(paddle_average / openvino_average, 4),
            "quality": compare_quality(baseline, openvino),
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if baseline.get("status") == "ok" and openvino.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
