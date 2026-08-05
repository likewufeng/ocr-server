import os
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, DefaultDict, Dict, Iterable, List, Tuple

from app.config import (
    INSTANCE_NAME,
    METRICS_ENABLED,
    OCR_DEVICE,
    OCR_INFERENCE_BACKEND,
    OCR_CPU_THREADS,
    OCR_MAX_CONCURRENT_REQUESTS,
    OCR_MODEL_ENGINE,
    OCR_MODEL_PROFILE,
    OCR_MODEL_VERSION,
    OCR_TEXT_RECOGNITION_BATCH_SIZE,
    OCR_USE_FINE_TUNED_MODEL,
)


HTTP_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300)
OCR_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300)


def _escape_label(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _label_text(labels: Iterable[Tuple[str, object]]) -> str:
    values = [("instance_name", INSTANCE_NAME), *labels]
    return "{" + ",".join(
        '{}="{}"'.format(name, _escape_label(value)) for name, value in values
    ) + "}"


def _resident_memory_bytes():
    try:
        statm = Path("/proc/self/statm").read_text(encoding="ascii").split()
        return int(statm[1]) * os.sysconf("SC_PAGE_SIZE")
    except (AttributeError, IndexError, OSError, ValueError):
        return None


class Histogram:
    def __init__(self, buckets: Tuple[float, ...]):
        self.buckets = buckets
        self.count = 0
        self.total = 0.0
        self.bucket_counts = [0] * len(buckets)

    def observe(self, value: float) -> None:
        self.count += 1
        self.total += value
        for index, boundary in enumerate(self.buckets):
            if value <= boundary:
                self.bucket_counts[index] += 1


class MetricsCollector:
    def __init__(self, enabled: bool = METRICS_ENABLED):
        self.enabled = enabled
        self.started_at = time.time()
        self._lock = threading.Lock()
        self._http_requests: DefaultDict[Tuple[str, str, str], int] = defaultdict(int)
        self._http_durations: Dict[Tuple[str, str], Histogram] = {}
        self._ocr_requests: DefaultDict[Tuple[str, str, str], int] = defaultdict(int)
        self._cache_requests: DefaultDict[str, int] = defaultdict(int)
        self._queue_waits: Dict[str, Histogram] = {}
        self._prediction_durations: Dict[str, Histogram] = {}
        self._active_http = 0
        self._queue_depth = 0
        self._active_inference = 0
        self._model_ready = False

    def set_model_ready(self, ready: bool) -> None:
        with self._lock:
            self._model_ready = ready

    def http_started(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._active_http += 1

    def http_completed(
        self, method: str, path: str, status_code: int, duration_seconds: float
    ) -> None:
        if not self.enabled:
            return
        key = (method, path)
        with self._lock:
            self._active_http = max(0, self._active_http - 1)
            self._http_requests[(method, path, str(status_code))] += 1
            histogram = self._http_durations.setdefault(
                key, Histogram(HTTP_BUCKETS)
            )
            histogram.observe(duration_seconds)

    def queue_started(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._queue_depth += 1

    def queue_acquired(self, document_type: str, wait_seconds: float) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._queue_depth = max(0, self._queue_depth - 1)
            histogram = self._queue_waits.setdefault(
                document_type, Histogram(OCR_BUCKETS)
            )
            histogram.observe(wait_seconds)

    def queue_abandoned(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._queue_depth = max(0, self._queue_depth - 1)

    def inference_started(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._active_inference += 1

    def inference_completed(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._active_inference = max(0, self._active_inference - 1)

    def observe_prediction(self, document_type: str, duration_seconds: float) -> None:
        if not self.enabled:
            return
        with self._lock:
            histogram = self._prediction_durations.setdefault(
                document_type, Histogram(OCR_BUCKETS)
            )
            histogram.observe(duration_seconds)

    def record_cache(self, status: str) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._cache_requests[status] += 1

    def record_ocr_request(
        self, document_type: str, cache_status: str, result: str
    ) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._ocr_requests[(document_type, cache_status, result)] += 1

    @staticmethod
    def _histogram_json(histogram: Histogram) -> Dict[str, Any]:
        average = histogram.total / histogram.count if histogram.count else 0.0
        return {
            "count": histogram.count,
            "sum_seconds": round(histogram.total, 6),
            "average_seconds": round(average, 6),
        }

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            cache_hits = self._cache_requests.get("hit", 0)
            cache_misses = self._cache_requests.get("miss", 0)
            cache_total = cache_hits + cache_misses
            return {
                "enabled": self.enabled,
                "instance_name": INSTANCE_NAME,
                "uptime_seconds": round(time.time() - self.started_at, 3),
                "process": {
                    "cpu_seconds": round(time.process_time(), 6),
                    "resident_memory_bytes": _resident_memory_bytes(),
                },
                "model": {
                    "device": OCR_DEVICE,
                    "inference_backend": OCR_INFERENCE_BACKEND,
                    "version": OCR_MODEL_VERSION,
                    "profile": OCR_MODEL_PROFILE,
                    "engine": OCR_MODEL_ENGINE,
                    "fine_tuned_detector": OCR_USE_FINE_TUNED_MODEL,
                    "cpu_threads": OCR_CPU_THREADS,
                    "recognition_batch_size": OCR_TEXT_RECOGNITION_BATCH_SIZE,
                    "max_concurrent_requests": OCR_MAX_CONCURRENT_REQUESTS,
                },
                "gauges": {
                    "active_http_requests": self._active_http,
                    "ocr_queue_depth": self._queue_depth,
                    "active_ocr_inference": self._active_inference,
                    "model_ready": self._model_ready,
                },
                "cache": {
                    "hits": cache_hits,
                    "misses": cache_misses,
                    "hit_ratio": round(cache_hits / cache_total, 6) if cache_total else 0.0,
                },
                "http_requests": [
                    {
                        "method": method,
                        "path": path,
                        "status": status,
                        "count": count,
                    }
                    for (method, path, status), count in sorted(self._http_requests.items())
                ],
                "ocr_requests": [
                    {
                        "document_type": document_type,
                        "cache_status": cache_status,
                        "result": result,
                        "count": count,
                    }
                    for (document_type, cache_status, result), count in sorted(
                        self._ocr_requests.items()
                    )
                ],
                "queue_wait": {
                    key: self._histogram_json(value)
                    for key, value in sorted(self._queue_waits.items())
                },
                "prediction": {
                    key: self._histogram_json(value)
                    for key, value in sorted(self._prediction_durations.items())
                },
            }

    @staticmethod
    def _render_histograms(
        lines: List[str], name: str, help_text: str, values: Dict[Any, Histogram],
        label_names: Tuple[str, ...]
    ) -> None:
        lines.extend(("# HELP {} {}".format(name, help_text), "# TYPE {} histogram".format(name)))
        for key, histogram in sorted(values.items()):
            key_values = key if isinstance(key, tuple) else (key,)
            labels = tuple(zip(label_names, key_values))
            for boundary, count in zip(histogram.buckets, histogram.bucket_counts):
                bucket_labels = (*labels, ("le", boundary))
                lines.append("{}_bucket{} {}".format(name, _label_text(bucket_labels), count))
            lines.append("{}_bucket{} {}".format(name, _label_text((*labels, ("le", "+Inf"))), histogram.count))
            lines.append("{}_sum{} {}".format(name, _label_text(labels), histogram.total))
            lines.append("{}_count{} {}".format(name, _label_text(labels), histogram.count))

    def render_prometheus(self) -> str:
        with self._lock:
            lines = [
                "# HELP ocr_server_info Static OCR server instance information.",
                "# TYPE ocr_server_info gauge",
                "ocr_server_info{} 1".format(
                    _label_text((
                        ("device", OCR_DEVICE),
                        ("inference_backend", OCR_INFERENCE_BACKEND),
                        ("model_version", OCR_MODEL_VERSION),
                        ("model_profile", OCR_MODEL_PROFILE),
                        ("model_engine", OCR_MODEL_ENGINE),
                        ("fine_tuned_detector", str(OCR_USE_FINE_TUNED_MODEL).lower()),
                        ("cpu_threads", OCR_CPU_THREADS),
                        ("max_concurrent_requests", OCR_MAX_CONCURRENT_REQUESTS),
                    ))
                ),
                "# HELP ocr_process_uptime_seconds Process uptime in seconds.",
                "# TYPE ocr_process_uptime_seconds gauge",
                "ocr_process_uptime_seconds{} {}".format(
                    _label_text(()), time.time() - self.started_at
                ),
                "# HELP ocr_process_cpu_seconds_total Total process CPU time in seconds.",
                "# TYPE ocr_process_cpu_seconds_total counter",
                "ocr_process_cpu_seconds_total{} {}".format(
                    _label_text(()), time.process_time()
                ),
                "# HELP ocr_http_active_requests Current active HTTP requests.",
                "# TYPE ocr_http_active_requests gauge",
                "ocr_http_active_requests{} {}".format(_label_text(()), self._active_http),
                "# HELP ocr_queue_depth Current requests waiting for an OCR slot.",
                "# TYPE ocr_queue_depth gauge",
                "ocr_queue_depth{} {}".format(_label_text(()), self._queue_depth),
                "# HELP ocr_inference_active Current active OCR inference calls.",
                "# TYPE ocr_inference_active gauge",
                "ocr_inference_active{} {}".format(_label_text(()), self._active_inference),
                "# HELP ocr_model_ready Whether the OCR model initialized successfully.",
                "# TYPE ocr_model_ready gauge",
                "ocr_model_ready{} {}".format(_label_text(()), int(self._model_ready)),
                "# HELP ocr_http_requests_total HTTP requests by route and status.",
                "# TYPE ocr_http_requests_total counter",
            ]
            resident_memory = _resident_memory_bytes()
            if resident_memory is not None:
                lines.extend((
                    "# HELP ocr_process_resident_memory_bytes Resident memory in bytes.",
                    "# TYPE ocr_process_resident_memory_bytes gauge",
                    "ocr_process_resident_memory_bytes{} {}".format(
                        _label_text(()), resident_memory
                    ),
                ))
            for (method, path, status), count in sorted(self._http_requests.items()):
                lines.append(
                    "ocr_http_requests_total{} {}".format(
                        _label_text((("method", method), ("path", path), ("status", status))),
                        count,
                    )
                )

            self._render_histograms(
                lines, "ocr_http_request_duration_seconds", "HTTP request duration.",
                self._http_durations, ("method", "path")
            )
            lines.extend((
                "# HELP ocr_requests_total OCR requests by type, cache status and result.",
                "# TYPE ocr_requests_total counter",
            ))
            for (document_type, cache_status, result), count in sorted(self._ocr_requests.items()):
                lines.append(
                    "ocr_requests_total{} {}".format(
                        _label_text((("document_type", document_type), ("cache_status", cache_status), ("result", result))),
                        count,
                    )
                )
            lines.extend((
                "# HELP ocr_cache_requests_total OCR cache lookups by final status.",
                "# TYPE ocr_cache_requests_total counter",
            ))
            for status, count in sorted(self._cache_requests.items()):
                lines.append("ocr_cache_requests_total{} {}".format(_label_text((("status", status),)), count))

            self._render_histograms(
                lines, "ocr_queue_wait_seconds", "Time waiting for an OCR execution slot.",
                self._queue_waits, ("document_type",)
            )
            self._render_histograms(
                lines, "ocr_prediction_duration_seconds", "PaddleX prediction duration.",
                self._prediction_durations, ("document_type",)
            )
            return "\n".join(lines) + "\n"


metrics = MetricsCollector()
