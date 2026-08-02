import argparse
import json
import math
import mimetypes
import statistics
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def percentile(values: List[float], percent: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * percent) - 1)
    return ordered[index]


def multipart_body(image_path: Path) -> tuple:
    boundary = "----ocr-benchmark-{}".format(uuid.uuid4().hex)
    content_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    prefix = (
        "--{0}\r\n"
        'Content-Disposition: form-data; name="file"; filename="{1}"\r\n'
        "Content-Type: {2}\r\n\r\n"
    ).format(boundary, image_path.name.replace('"', ""), content_type).encode("utf-8")
    suffix = "\r\n--{}--\r\n".format(boundary).encode("ascii")
    return prefix + image_path.read_bytes() + suffix, boundary


def invoke(
    url: str,
    image_path: Path,
    document_type: Optional[str],
    auto_orientation: Optional[bool],
    timeout: float,
) -> Dict[str, object]:
    query = {}
    if document_type:
        query["document_type"] = document_type
    if auto_orientation is not None:
        query["auto_orientation"] = str(auto_orientation).lower()
    endpoint = url.rstrip("/") + "/ocr"
    if query:
        endpoint += "?" + urlencode(query)

    body, boundary = multipart_body(image_path)
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
                "duration_seconds": time.perf_counter() - started_at,
                "cache": response.headers.get("X-OCR-Cache", "UNKNOWN"),
                "request_id": payload.get("request_id"),
            }
    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "duration_seconds": time.perf_counter() - started_at,
            "cache": "UNKNOWN",
            "error": str(exc),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="OCR HTTP 并发吞吐基准工具")
    parser.add_argument("--url", required=True, help="服务根地址，如 http://127.0.0.1:8000")
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--document-type")
    parser.add_argument("--requests", type=int, default=8)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=300)
    orientation = parser.add_mutually_exclusive_group()
    orientation.add_argument("--auto-orientation", action="store_true", dest="auto_orientation")
    orientation.add_argument("--no-auto-orientation", action="store_false", dest="auto_orientation")
    parser.set_defaults(auto_orientation=None)
    args = parser.parse_args()

    if not args.image.is_file():
        parser.error("图片不存在: {}".format(args.image))
    if args.requests < 1 or args.concurrency < 1:
        parser.error("requests 和 concurrency 必须大于 0")

    started_at = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [
            executor.submit(
                invoke,
                args.url,
                args.image,
                args.document_type,
                args.auto_orientation,
                args.timeout,
            )
            for _ in range(args.requests)
        ]
        results = [future.result() for future in as_completed(futures)]
    wall_seconds = time.perf_counter() - started_at

    durations = [float(item["duration_seconds"]) for item in results]
    successes = sum(bool(item["ok"]) for item in results)
    cache_hits = sum(item["cache"] == "HIT" for item in results)
    report = {
        "url": args.url,
        "requests": args.requests,
        "concurrency": args.concurrency,
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
        "errors": [item.get("error") for item in results if item.get("error")],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if cache_hits:
        print("警告：检测到 {} 次缓存命中，本次数据不能代表真实 OCR 吞吐。".format(cache_hits))
    return 0 if successes == args.requests and cache_hits == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
