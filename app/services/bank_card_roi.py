"""ONNX bank-card field localizer.

The model is an optional YOLO detector with three classes from CreditCard-OCR:
card_number, date, and union_pay. It deliberately uses OpenCV DNN so the main
service does not need PyTorch or Ultralytics at runtime.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence, Union

import cv2
import numpy as np


CLASS_NAMES = ("card_number", "date", "union_pay")


@dataclass(frozen=True)
class ROIDetection:
    """One card-field rectangle in original-image coordinates."""

    label: str
    confidence: float
    left: int
    top: int
    right: int
    bottom: int

    @property
    def area(self) -> int:
        return max(0, self.right - self.left) * max(0, self.bottom - self.top)


class BankCardROILocalizer:
    """Run a YOLO ONNX card-field detector through OpenCV DNN."""

    def __init__(
        self,
        model_path: Path,
        input_size: int = 640,
        confidence_threshold: float = 0.45,
        nms_threshold: float = 0.45,
    ) -> None:
        self.model_path = Path(model_path)
        self.input_size = input_size
        self.confidence_threshold = confidence_threshold
        self.nms_threshold = nms_threshold
        self.net = None

    def load(self) -> None:
        if self.net is not None:
            return
        if not self.model_path.is_file():
            raise FileNotFoundError(
                "Bank-card ROI ONNX model does not exist: {}".format(self.model_path)
            )
        self.net = cv2.dnn.readNetFromONNX(str(self.model_path))

    def detect(self, image: np.ndarray) -> List[ROIDetection]:
        """Detect card fields from a BGR image."""
        if image is None or image.size == 0:
            return []
        self.load()

        padded, scale, left_pad, top_pad = self._letterbox(image)
        blob = cv2.dnn.blobFromImage(
            padded,
            scalefactor=1.0 / 255.0,
            size=(self.input_size, self.input_size),
            swapRB=True,
            crop=False,
        )
        self.net.setInput(blob)
        return self._decode_outputs(
            self.net.forward(),
            image.shape[1],
            image.shape[0],
            scale,
            left_pad,
            top_pad,
        )

    def _letterbox(self, image: np.ndarray) -> tuple[np.ndarray, float, int, int]:
        height, width = image.shape[:2]
        scale = min(self.input_size / width, self.input_size / height)
        resized_width = max(1, int(round(width * scale)))
        resized_height = max(1, int(round(height * scale)))
        resized = cv2.resize(image, (resized_width, resized_height))
        left = (self.input_size - resized_width) // 2
        top = (self.input_size - resized_height) // 2
        padded = cv2.copyMakeBorder(
            resized,
            top,
            self.input_size - resized_height - top,
            left,
            self.input_size - resized_width - left,
            cv2.BORDER_CONSTANT,
            value=(114, 114, 114),
        )
        return padded, scale, left, top

    def _decode_outputs(
        self,
        outputs: Union[np.ndarray, Sequence[np.ndarray]],
        original_width: int,
        original_height: int,
        scale: float,
        left_pad: int,
        top_pad: int,
    ) -> List[ROIDetection]:
        """Decode standard YOLOv8 ONNX output shaped [1, 4 + classes, N]."""
        if isinstance(outputs, (list, tuple)):
            if not outputs:
                return []
            outputs = outputs[0]
        rows = np.asarray(outputs)
        rows = np.squeeze(rows)
        if rows.ndim != 2:
            return []
        # Ultralytics YOLOv8 export is [4 + class_count, prediction_count].
        if rows.shape[0] <= 4 + len(CLASS_NAMES) and rows.shape[1] > rows.shape[0]:
            rows = rows.T
        if rows.shape[1] < 4 + len(CLASS_NAMES):
            return []

        boxes_by_class: dict[int, list[list[int]]] = {}
        scores_by_class: dict[int, list[float]] = {}
        for row in rows:
            class_scores = row[4 : 4 + len(CLASS_NAMES)]
            class_id = int(np.argmax(class_scores))
            confidence = float(class_scores[class_id])
            if confidence < self.confidence_threshold:
                continue

            center_x, center_y, width, height = (float(value) for value in row[:4])
            x1 = int(round((center_x - width / 2 - left_pad) / scale))
            y1 = int(round((center_y - height / 2 - top_pad) / scale))
            x2 = int(round((center_x + width / 2 - left_pad) / scale))
            y2 = int(round((center_y + height / 2 - top_pad) / scale))
            x1 = max(0, min(x1, original_width - 1))
            y1 = max(0, min(y1, original_height - 1))
            x2 = max(x1 + 1, min(x2, original_width))
            y2 = max(y1 + 1, min(y2, original_height))
            boxes_by_class.setdefault(class_id, []).append([x1, y1, x2 - x1, y2 - y1])
            scores_by_class.setdefault(class_id, []).append(confidence)

        detections = []
        for class_id, boxes in boxes_by_class.items():
            scores = scores_by_class[class_id]
            kept = cv2.dnn.NMSBoxes(boxes, scores, self.confidence_threshold, self.nms_threshold)
            for index in np.asarray(kept).reshape(-1):
                left, top, width, height = boxes[int(index)]
                detections.append(
                    ROIDetection(
                        label=CLASS_NAMES[class_id],
                        confidence=round(float(scores[int(index)]), 4),
                        left=left,
                        top=top,
                        right=left + width,
                        bottom=top + height,
                    )
                )
        return sorted(detections, key=lambda item: (item.label, -item.confidence))

    @staticmethod
    def crop(
        image: np.ndarray, detection: ROIDetection, padding_ratio: float
    ) -> tuple[np.ndarray, tuple[int, int, int, int]]:
        """Crop a detected field with bounded padding and return its origin box."""
        height, width = image.shape[:2]
        padding_x = int(round((detection.right - detection.left) * padding_ratio))
        padding_y = int(round((detection.bottom - detection.top) * padding_ratio))
        left = max(0, detection.left - padding_x)
        top = max(0, detection.top - padding_y)
        right = min(width, detection.right + padding_x)
        bottom = min(height, detection.bottom + padding_y)
        return image[top:bottom, left:right], (left, top, right, bottom)


def select_field_detections(
    detections: Iterable[ROIDetection], max_dates: int = 2
) -> List[ROIDetection]:
    """Keep the strongest card-number and date areas; logo is not OCR input."""
    grouped: dict[str, list[ROIDetection]] = {"card_number": [], "date": []}
    for detection in detections:
        if detection.label in grouped:
            grouped[detection.label].append(detection)
    selected = []
    if grouped["card_number"]:
        selected.append(max(grouped["card_number"], key=lambda item: (item.confidence, item.area)))
    selected.extend(
        sorted(grouped["date"], key=lambda item: (item.confidence, item.area), reverse=True)[:max_dates]
    )
    return selected
