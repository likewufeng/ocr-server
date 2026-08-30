"""印章形状分析、环形文字展开和 PaddleOCR 编排。

整页印章的检测与裁切属于 stamp-ai-service，本模块不包含检测模型，只处理已经
得到的单印章图片，或远程服务返回的印章裁切图。
"""

import base64
import binascii
import json
import math
import mimetypes
import socket
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from app.config import (
    STAMP_RECOGNITION_ENABLED,
    STAMP_SERVICE_API_KEY,
    STAMP_SERVICE_TIMEOUT_SECONDS,
    STAMP_SERVICE_URL,
)
from app.services.ocr_service import ocr_service


class StampServiceUnavailable(Exception):
    """stamp-ai-service 连接失败、超时或返回无效结果。"""


class StampServiceTimeout(StampServiceUnavailable):
    """stamp-ai-service 在配置的时间内未完成响应。"""


class StampOCRService:
    """单印章视觉处理服务。PaddleOCR 仍由项目现有单例统一管理。"""

    SHAPES = ("circle", "ellipse", "square", "unknown")

    @staticmethod
    def decode_image(content: bytes) -> np.ndarray:
        image = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if image is None or image.size == 0:
            raise ValueError("图片无法读取")
        if len(image.shape) == 2:
            return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        if image.shape[2] not in (3, 4):
            raise ValueError("图片通道数不支持")
        return image

    @staticmethod
    def _foreground_mask(image: np.ndarray) -> np.ndarray:
        """生成印章前景 mask：有意义的 Alpha 优先，否则综合颜色和灰度。"""
        if image.shape[2] == 4:
            alpha = image[:, :, 3]
            if int(alpha.min()) < 250:
                mask = np.where(alpha > 20, 255, 0).astype(np.uint8)
                if cv2.countNonZero(mask) > 20:
                    return StampOCRService._clean_mask(mask)

        bgr = image[:, :, :3]
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        # 红章常见的两个 Hue 区间；同时保留高饱和度彩色印章。
        red = cv2.inRange(hsv, np.array([0, 35, 35]), np.array([15, 255, 255]))
        red |= cv2.inRange(hsv, np.array([165, 35, 35]), np.array([179, 255, 255]))
        colored = cv2.inRange(hsv, np.array([0, 45, 30]), np.array([179, 255, 255]))
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        dark = cv2.inRange(gray, 0, 170)
        mask = cv2.bitwise_or(red, cv2.bitwise_and(colored, dark))
        return StampOCRService._clean_mask(mask)

    @staticmethod
    def _clean_mask(mask: np.ndarray) -> np.ndarray:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        return mask

    @staticmethod
    def _quad_angle(point_a: np.ndarray, point_b: np.ndarray, point_c: np.ndarray) -> float:
        first = point_a - point_b
        second = point_c - point_b
        denominator = np.linalg.norm(first) * np.linalg.norm(second)
        if denominator == 0:
            return 0.0
        cosine = float(np.dot(first, second) / denominator)
        return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))

    def analyze_shape(self, image: np.ndarray) -> Dict[str, Any]:
        mask = self._foreground_mask(image)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return {"shape": "unknown", "shape_confidence": 0.0, "mask": mask}
        contour = max(contours, key=cv2.contourArea)
        area = float(cv2.contourArea(contour))
        perimeter = float(cv2.arcLength(contour, True))
        x, y, width, height = cv2.boundingRect(contour)
        if area < 100 or perimeter <= 0 or width <= 0 or height <= 0:
            return {"shape": "unknown", "shape_confidence": 0.1, "mask": mask}

        aspect = min(width, height) / max(width, height)
        circularity = 4.0 * math.pi * area / (perimeter * perimeter)
        fill_ratio = area / float(width * height)
        polygon = cv2.approxPolyDP(contour, 0.04 * perimeter, True)
        quad_score = 0.0
        if len(polygon) == 4:
            points = polygon.reshape(4, 2).astype(np.float32)
            angles = [
                self._quad_angle(points[(i - 1) % 4], points[i], points[(i + 1) % 4])
                for i in range(4)
            ]
            quad_score = max(0.0, 1.0 - sum(abs(angle - 90.0) for angle in angles) / 180.0)

        ellipse_ratio = 0.0
        ellipse_error = 1.0
        ellipse = None
        if len(contour) >= 5:
            ellipse = cv2.fitEllipse(contour)
            raw_axes = tuple(float(axis) for axis in ellipse[1])
            axes = sorted(raw_axes, reverse=True)
            if axes[0] > 0:
                ellipse_ratio = axes[1] / axes[0]
                distances = []
                center = np.asarray(ellipse[0], dtype=np.float32)
                # OpenCV 的角度对应 size[0] 轴；若交换长短轴，角度也要转 90 度。
                angle_degrees = float(ellipse[2])
                if raw_axes[0] < raw_axes[1]:
                    angle_degrees += 90.0
                angle = math.radians(angle_degrees)
                major = axes[0] / 2.0
                minor = axes[1] / 2.0
                cos_a, sin_a = math.cos(angle), math.sin(angle)
                for point in contour.reshape(-1, 2).astype(np.float32):
                    dx, dy = point - center
                    ex = (dx * cos_a + dy * sin_a) / max(major, 1.0)
                    ey = (-dx * sin_a + dy * cos_a) / max(minor, 1.0)
                    distances.append(abs(math.sqrt(ex * ex + ey * ey) - 1.0))
                ellipse_error = min(1.0, float(np.mean(distances)) * 2.0)

        # 拍照透视会改变宽高比，因此圆章同时看圆度和椭圆拟合误差。
        circle_score = max(
            0.0,
            min(1.0, 0.35 * circularity + 0.30 * aspect + 0.35 * (1.0 - ellipse_error)),
        )
        ellipse_score = max(
            0.0,
            min(1.0, 0.45 * (1.0 - ellipse_error) + 0.35 * (1.0 - ellipse_ratio) + 0.20 * circularity),
        )
        square_score = max(0.0, min(1.0, 0.55 * quad_score + 0.45 * fill_ratio))

        scores = {"circle": circle_score, "ellipse": ellipse_score, "square": square_score}
        shape = max(scores, key=scores.get)
        confidence = float(scores[shape])
        # 接近圆形的轮廓优先判圆；只有明显拉长才判椭圆。
        if len(polygon) == 4 and quad_score >= 0.60 and fill_ratio >= 0.50:
            shape, confidence = "square", square_score
        elif circle_score >= 0.70 and aspect >= 0.78 and circularity >= 0.62:
            shape, confidence = "circle", circle_score
        elif ellipse is not None and ellipse_error <= 0.22 and ellipse_ratio < 0.82:
            shape, confidence = "ellipse", ellipse_score
        elif confidence < 0.55:
            shape, confidence = "unknown", max(0.0, confidence * 0.7)

        return {
            "shape": shape,
            "shape_confidence": round(min(1.0, confidence), 4),
            "mask": mask,
            "contour_box": [int(x), int(y), int(width), int(height)],
            "features": {
                "aspect_ratio": round(aspect, 4),
                "circularity": round(circularity, 4),
                "ellipse_error": round(ellipse_error, 4),
                "ellipse_axis_ratio": round(ellipse_ratio, 4),
                "polygon_vertices": int(len(polygon)),
                "quadrilateral_score": round(quad_score, 4),
                "fill_ratio": round(fill_ratio, 4),
            },
            "ellipse": ellipse,
            "contour": contour,
        }

    @staticmethod
    def _white_background_like(image: np.ndarray, mask: np.ndarray) -> np.ndarray:
        result = image[:, :, :3].copy()
        result[mask == 0] = (255, 255, 255)
        return result

    def unwrap_seal(self, image: np.ndarray, analysis: Dict[str, Any]) -> np.ndarray:
        """把圆/椭圆章环形文字展开为水平文字带，供通用 OCR 使用。"""
        contour = analysis["contour"]
        mask = analysis["mask"]
        if analysis["shape"] not in ("circle", "ellipse"):
            return image[:, :, :3].copy()
        if analysis.get("ellipse") is not None:
            center = tuple(float(v) for v in analysis["ellipse"][0])
            raw_axes = tuple(float(axis) for axis in analysis["ellipse"][1])
            axes = sorted(raw_axes, reverse=True)
            angle_degrees = float(analysis["ellipse"][2])
            if raw_axes[0] < raw_axes[1]:
                angle_degrees += 90.0
            angle = math.radians(angle_degrees)
            major, minor = axes[0] / 2.0, axes[1] / 2.0
        else:
            moments = cv2.moments(contour)
            center = (
                moments["m10"] / moments["m00"] if moments["m00"] else image.shape[1] / 2.0,
                moments["m01"] / moments["m00"] if moments["m00"] else image.shape[0] / 2.0,
            )
            radius = max(cv2.boundingRect(contour)[2:]) / 2.0
            major = minor = radius
            angle = 0.0

        source = self._white_background_like(image, mask)
        # 直接按椭圆的长短轴采样环带，避免把章心图案和五角星展开成横线。
        radial_samples = max(96, int(minor * 0.62))
        angular_width = max(720, int(2.0 * math.pi * major))
        # 文字通常位于外轮廓内侧，最外侧约 8% 多为圆边；排除它可避免
        # 圆边在展开后变成贯穿整行的伪文字。
        rho = np.linspace(0.46, 0.88, radial_samples, dtype=np.float32)
        theta = np.linspace(0.0, 2.0 * math.pi, angular_width, endpoint=False, dtype=np.float32)
        rho_grid, theta_grid = np.meshgrid(rho, theta, indexing="ij")
        cos_angle, sin_angle = math.cos(angle), math.sin(angle)
        local_x = major * rho_grid * np.cos(theta_grid)
        local_y = minor * rho_grid * np.sin(theta_grid)
        map_x = center[0] + local_x * cos_angle - local_y * sin_angle
        map_y = center[1] + local_x * sin_angle + local_y * cos_angle
        polar = cv2.remap(
            source, map_x.astype(np.float32), map_y.astype(np.float32),
            cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
            borderValue=(255, 255, 255),
        )
        # 列是角度。上下半圈各保留约 30 度重叠，避免公司名首尾字符恰好
        # 落在 180/360 度切点而被截断；下半圈再旋转 180 度恢复正向。
        def angular_slice(start_degrees: int, span_degrees: int) -> np.ndarray:
            start = int(angular_width * (start_degrees % 360) / 360)
            width = int(angular_width * span_degrees / 360)
            tiled = np.concatenate([polar, polar], axis=1)
            return tiled[:, start: start + width]

        top = angular_slice(150, 240)
        bottom = cv2.rotate(angular_slice(330, 240), cv2.ROTATE_180)
        padding = max(12, radial_samples // 10)
        height = max(top.shape[0], bottom.shape[0])
        width = max(top.shape[1], bottom.shape[1])
        canvas = np.full(
            (height * 2 + padding * 2 + 16, width + 16, 3), 255, dtype=np.uint8
        )
        canvas[padding: padding + top.shape[0], 8: 8 + top.shape[1]] = top
        bottom_y = height + padding + 16
        canvas[bottom_y: bottom_y + bottom.shape[0], 8: 8 + bottom.shape[1]] = bottom
        return canvas

    @staticmethod
    def _words_from_result(result: Dict[str, Any]) -> List[Dict[str, Any]]:
        texts = result.get("texts") or []
        scores = result.get("scores") or []
        boxes = result.get("boxes") or []
        polys = result.get("polys") or []
        words = []
        for index, text in enumerate(texts):
            box = boxes[index] if index < len(boxes) else []
            if not box and index < len(polys) and polys[index]:
                points = np.asarray(polys[index], dtype=np.float32).reshape(-1, 2)
                if len(points):
                    box = [
                        int(points[:, 0].min()), int(points[:, 1].min()),
                        int(points[:, 0].max()), int(points[:, 1].max()),
                    ]
            words.append({
                "text": str(text),
                "confidence": float(scores[index]) if index < len(scores) else 0.0,
                "box": box,
            })
        return words

    def recognize_image(
        self, image: np.ndarray, request_id: str, output_dir: Path,
        debug: bool = False, artifact_prefix: str = "stamp",
    ) -> Dict[str, Any]:
        analysis = self.analyze_shape(image)
        shape = analysis["shape"]
        ocr_image = self.unwrap_seal(image, analysis) if shape in ("circle", "ellipse") else image[:, :, :3]
        artifact_path = output_dir / (artifact_prefix + "_unwrapped.jpg")
        if debug and shape in ("circle", "ellipse"):
            cv2.imwrite(str(artifact_path), ocr_image)
            cv2.imwrite(str(output_dir / (artifact_prefix + "_mask.png")), analysis["mask"])
        # 印章 PNG 常带 Alpha 或细小镂空，OCR 中间图使用无损 PNG，避免 JPEG
        # 压缩把透明边缘变成黑色伪影。
        input_path = output_dir / (artifact_prefix + "_ocr.png")
        if not cv2.imwrite(str(input_path), ocr_image):
            raise ValueError("印章预处理图片保存失败")
        # 姣忔鍏堣窇宸茬粡楠岃瘉鐨勫渾绔犲睍寮€ OCR锛岀‘淇濆熀绾垮彲鐢ㄣ€?
        result = None
        recognition_source = "baseline"
        source_path = output_dir / (artifact_prefix + "_source.png")
        if STAMP_RECOGNITION_ENABLED and cv2.imwrite(str(source_path), image[:, :, :3]):
            try:
                official_result = ocr_service.submit_recognize_stamp_with_official_model(
                    str(source_path)
                ).result()
                if official_result and official_result.get("texts"):
                    result = official_result
                    recognition_source = "official_seal_recognition"
            except Exception:
                # 专用模型缺失或加载失败时回退现有 OCR。
                pass

        if result is None:
            result = ocr_service.submit_recognize(
                str(input_path), request_id=request_id, output_dir=output_dir,
                document_type=None, auto_orientation=False, min_score=0.35,
            ).result()
        words = self._words_from_result(result or {})
        text = " ".join(item["text"] for item in words if item["text"]).strip()
        confidence = max((item["confidence"] for item in words), default=0.0)
        return {
            "shape": shape,
            "shape_confidence": analysis["shape_confidence"],
            "text": text,
            "confidence": round(float(confidence), 4),
            "words": words,
            "artifacts": {
                "ocr_image": input_path.name,
                "unwrapped_image": artifact_path.name if debug and shape in ("circle", "ellipse") else None,
                "recognition_source": recognition_source,
            },
        }

    @staticmethod
    def _multipart(file_path: Path, fields: Dict[str, str]) -> Tuple[bytes, str]:
        boundary = "----ocrserver-" + uuid.uuid4().hex
        chunks = []
        for key, value in fields.items():
            chunks.append(("--" + boundary + "\r\n" +
                           'Content-Disposition: form-data; name="' + key + '"\r\n\r\n' +
                           str(value) + "\r\n").encode("utf-8"))
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        chunks.append(("--" + boundary + "\r\n" +
                       'Content-Disposition: form-data; name="file"; filename="' +
                       file_path.name + '"\r\nContent-Type: ' + content_type + "\r\n\r\n").encode("utf-8"))
        chunks.append(file_path.read_bytes())
        chunks.append(("\r\n--" + boundary + "--\r\n").encode("ascii"))
        return b"".join(chunks), "multipart/form-data; boundary=" + boundary

    def extract_remote(self, file_path: Path) -> List[Dict[str, Any]]:
        body, content_type = self._multipart(
            file_path, {"return_type": "base64", "strategy": "MODEL", "debug": "false"}
        )
        headers = {"Content-Type": content_type, "Accept": "application/json"}
        if STAMP_SERVICE_API_KEY:
            headers["Authorization"] = "Bearer " + STAMP_SERVICE_API_KEY
        request = urllib.request.Request(
            STAMP_SERVICE_URL + "/api/stamp/extract", data=body, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=STAMP_SERVICE_TIMEOUT_SECONDS) as response:
                if response.status < 200 or response.status >= 300:
                    raise StampServiceUnavailable("stamp-ai-service 返回 HTTP {}".format(response.status))
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise StampServiceUnavailable("stamp-ai-service 返回 HTTP {}".format(exc.code))
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise StampServiceTimeout("stamp-ai-service 请求超时")
            raise StampServiceUnavailable("stamp-ai-service 请求失败: {}".format(exc))
        except (TimeoutError, socket.timeout) as exc:
            raise StampServiceTimeout("stamp-ai-service 请求超时: {}".format(exc))
        except (ValueError, json.JSONDecodeError) as exc:
            raise StampServiceUnavailable("stamp-ai-service 请求失败: {}".format(exc))
        if isinstance(payload, dict) and payload.get("code") not in (None, 0, "0"):
            raise StampServiceUnavailable(
                "stamp-ai-service 返回错误: {}".format(payload.get("msg") or payload.get("message") or payload.get("code"))
            )
        return self._parse_remote_stamps(payload)

    @staticmethod
    def _parse_remote_stamps(payload: Any) -> List[Dict[str, Any]]:
        data = payload.get("data", payload) if isinstance(payload, dict) else payload
        if isinstance(data, dict):
            items = data.get("stamps") or data.get("results") or data.get("items") or data.get("images") or []
        else:
            items = data
        if not isinstance(items, list):
            raise StampServiceUnavailable("stamp-ai-service 返回缺少 stamps 列表")
        parsed = []
        for item in items:
            if not isinstance(item, dict):
                continue
            encoded = (
                item.get("base64") or item.get("image_base64") or item.get("image")
                or item.get("crop") or item.get("crop_image") or item.get("stamp_image")
            )
            if isinstance(encoded, str) and encoded.startswith("data:"):
                encoded = encoded.split(",", 1)[-1]
            if not encoded:
                continue
            try:
                image_bytes = base64.b64decode(encoded, validate=False)
            except (ValueError, binascii.Error) as exc:
                raise StampServiceUnavailable("stamp-ai-service 印章图片 base64 无效: {}".format(exc))
            box = item.get("box") or item.get("bbox") or {}
            if isinstance(box, (list, tuple)) and len(box) >= 4:
                box = {"x": int(box[0]), "y": int(box[1]), "w": int(box[2]), "h": int(box[3])}
            elif isinstance(box, dict):
                if all(key in box for key in ("x1", "y1", "x2", "y2")):
                    box = {
                        "x": int(box["x1"]), "y": int(box["y1"]),
                        "w": int(box["x2"] - box["x1"]), "h": int(box["y2"] - box["y1"]),
                    }
                elif all(key in box for key in ("left", "top", "right", "bottom")):
                    box = {
                        "x": int(box["left"]), "y": int(box["top"]),
                        "w": int(box["right"] - box["left"]),
                        "h": int(box["bottom"] - box["top"]),
                    }
            parsed.append({"image": image_bytes, "box": box})
        return parsed


stamp_service = StampOCRService()
