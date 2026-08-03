import argparse
import json
import math
import mimetypes
import statistics
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def percentile(values: List[float], percent: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * percent) - 1)
    return ordered[index]


def parse_case(value: str) -> Tuple[Path, str]:
    try:
        path_text, document_type = value.rsplit("|", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "图片参数格式必须为：图片路径|document_type"
        ) from exc

    path = Path(path_text)
    if not path.is_file():
        raise argparse.ArgumentTypeError("图片不存在: {}".format(path))
    return path, document_type


def multipart_body(
    image_path: Path, payload_suffix: bytes
) -> Tuple[bytes, str]:
    boundary = "----ocr-mixed-benchmark-{}".format(uuid.uuid4().hex)
    content_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    prefix = (
        "--{0}\r\n"
        'Content-Disposition: form-data; name="file"; filename="{1}"\r\n'
        "Content-Type: {2}\r\n\r\n"
    ).format(boundary, image_path.name.replace('"', ""), content_type).encode("utf-8")
    suffix = "\r\n--{}--\r\n".format(boundary).encode("ascii")
    return prefix + image_path.read_bytes() + payload_suffix + suffix, boundary


def invoke(
    url: str,
    case: Tuple[Path, str],
    request_number: int,
    timeout: float,
) -> Dict[str, object]:
    image_path, document_type = case
    query = urlencode({"document_type": document_type})
    endpoint = url.rstrip("/") + "/ocr?" + query
    # JPEG/PNG decoders ignore trailing bytes, while the API hash changes per request.
    payload_suffix = "\nocr-mixed-benchmark-{}-{}\n".format(
        request_number, uuid.uuid4().hex
    ).encode("ascii")
    body, boundary = multipart_body(image_path, payload_suffix)
    request = Request(
        endpoint,
        data=body,
        method="POST",
        headers={"Content-Type": "multipart/form-data; boundary={}".format(boundary)},
    )
    started_at = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return {
                "ok": response.status == 200 and payload.get("code") == 0,
                "status": response.status,
                "document_type": document_type,
                "duration_seconds": time.perf_counter() - started_at,
                "cache": response.headers.get("X-OCR-Cache", "UNKNOWN"),
            }
    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "document_type": document_type,
            "duration_seconds": time.perf_counter() - started_at,
            "cache": "UNKNOWN",
            "error": str(exc),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="OCR 三类图片混合并发压测工具")
    parser.add_argument("--url", required=True, help="服务根地址，如 http://127.0.0.1:18081")
    parser.add_argument(
        "--case",
        required=True,
        action="append",
        type=parse_case,
        help="图片与类型，格式：图片路径|document_type，可重复传入",
    )
    parser.add_argument("--requests", type=int, default=24)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()

    if args.requests < 1 or args.concurrency < 1:
        parser.error("requests 和 concurrency 必须大于 0")

    started_at = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [
            executor.submit(
                invoke,
                args.url,
                args.case[index % len(args.case)],
                index,
                args.timeout,
            )
            for index in range(args.requests)
        ]
        results = [future.result() for future in as_completed(futures)]

    wall_seconds = time.perf_counter() - started_at
    durations = [float(item["duration_seconds"]) for item in results]
    successes = sum(bool(item["ok"]) for item in results)
    cache_hits = sum(item["cache"] == "HIT" for item in results)
    by_type = {}
    for item in results:
        by_type.setdefault(item["document_type"], []).append(item)

    report = {
        "url": args.url,
        "requests": args.requests,
        "concurrency": args.concurrency,
        "cases": [
            {"image": str(path), "document_type": document_type}
            for path, document_type in args.case
        ],
        "successes": successes,
        "failures": args.requests - successes,
        "cache_hits": cache_hits,
        "wall_seconds": round(wall_seconds, 4),
        "throughput_requests_per_second": round(args.requests / wall_seconds, 4),
        "latency_seconds": {
            "average": round(statistics.mean(durations), 4),
            "p50": round(percentile(durations, 0.50), 4),
            "p95": round(percentile(durations, 0.95), 4),
            "max": round(max(durations), 4),
        },
        "by_document_type": {
            document_type: {
                "requests": len(items),
                "successes": sum(bool(item["ok"]) for item in items),
                "average_seconds": round(
                    statistics.mean(float(item["duration_seconds"]) for item in items), 4
                ),
                "p95_seconds": round(
                    percentile(
                        [float(item["duration_seconds"]) for item in items], 0.95
                    ),
                    4,
                ),
            }
            for document_type, items in sorted(by_type.items())
        },
        "errors": [item.get("error") for item in results if item.get("error")],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if cache_hits:
        print("警告：检测到 {} 次缓存命中，本次数据不能代表真实 OCR 吞吐。".format(cache_hits))
    return 0 if successes == args.requests and cache_hits == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
