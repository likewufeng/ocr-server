import asyncio
import json
import unittest
from concurrent.futures import Future
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import cv2
import numpy as np

from app.api.stamp import recognize_document_stamps
from app.services.stamp_service import StampOCRService, StampServiceUnavailable


class StampShapeTest(unittest.TestCase):
    def setUp(self):
        self.service = StampOCRService()

    @staticmethod
    def _canvas():
        return np.full((400, 400, 3), 255, dtype=np.uint8)

    def test_circle_is_detected(self):
        image = self._canvas()
        cv2.circle(image, (200, 200), 150, (0, 0, 220), 8)
        result = self.service.analyze_shape(image)
        self.assertEqual(result["shape"], "circle")
        self.assertGreater(result["shape_confidence"], 0.7)

    def test_ellipse_is_detected(self):
        image = self._canvas()
        cv2.ellipse(image, (200, 200), (170, 110), 0, 0, 360, (0, 0, 220), 8)
        self.assertEqual(self.service.analyze_shape(image)["shape"], "ellipse")

    def test_square_is_detected_before_circularity_rule(self):
        image = self._canvas()
        cv2.rectangle(image, (60, 60), (340, 340), (0, 0, 220), 8)
        self.assertEqual(self.service.analyze_shape(image)["shape"], "square")

    def test_transparent_png_uses_alpha_foreground(self):
        image = np.zeros((200, 200, 4), dtype=np.uint8)
        cv2.circle(image, (100, 100), 70, (0, 0, 255, 255), -1)
        result = self.service.analyze_shape(image)
        self.assertGreater(cv2.countNonZero(result["mask"]), 10000)
        self.assertEqual(result["shape"], "circle")


class StampOCRTest(unittest.TestCase):
    def test_single_route_returns_unified_success_response(self):
        from app.api.stamp import recognize_stamp

        class DummyFile:
            filename = "stamp.png"
            content_type = "image/png"

            async def close(self):
                return None

        with TemporaryDirectory() as directory:
            async def save_upload(file, request_id):
                output = Path(directory) / request_id
                output.mkdir(parents=True, exist_ok=True)
                return output / "stamp.png"

            async def recognize(*args):
                return {
                    "shape": "circle", "shape_confidence": 0.9, "text": "某某公司",
                    "confidence": 0.91, "words": [], "artifacts": {},
                }

            with patch("app.api.stamp.OUTPUT_DIR", Path(directory)), patch(
                "app.api.stamp._save_upload", side_effect=save_upload
            ), patch("app.api.stamp._recognize_stamp", side_effect=recognize):
                response = asyncio.run(recognize_stamp(DummyFile(), False))
        self.assertEqual(response["code"], 0)
        self.assertTrue(response["request_id"])
        self.assertEqual(response["data"]["type"], "stamp")
        self.assertEqual(response["data"]["text"], "某某公司")

    def test_single_route_returns_4001_when_ocr_is_empty(self):
        from app.api.stamp import recognize_stamp

        class DummyFile:
            filename = "stamp.png"
            content_type = "image/png"

            async def close(self):
                return None

        async def save_upload(*args):
            return Path("stamp.png")

        async def recognize(*args):
            return {"shape": "unknown", "shape_confidence": 0.1, "text": "", "confidence": 0.0, "words": []}

        with patch("app.api.stamp._save_upload", side_effect=save_upload), patch(
            "app.api.stamp._recognize_stamp", side_effect=recognize
        ):
            response = asyncio.run(recognize_stamp(DummyFile(), False))
        self.assertEqual(response["code"], 4001)
        self.assertIsNone(response["data"])

    def test_debug_saves_unwrapped_image_and_empty_result_is_observable(self):
        service = StampOCRService()
        image = np.full((300, 300, 3), 255, dtype=np.uint8)
        cv2.circle(image, (150, 150), 110, (0, 0, 220), 6)
        future = Future()
        future.set_result({"texts": [], "scores": [], "boxes": []})
        with TemporaryDirectory() as directory, patch(
            "app.services.stamp_service.ocr_service.submit_recognize", return_value=future
        ):
            result = service.recognize_image(image, "request-1", Path(directory), True)
            self.assertEqual(result["text"], "")
            self.assertTrue((Path(directory) / "stamp_ocr.png").exists())
            self.assertTrue((Path(directory) / "stamp_unwrapped.jpg").exists())
            self.assertTrue((Path(directory) / "stamp_mask.png").exists())

    def test_unknown_shape_does_not_unwrap(self):
        service = StampOCRService()
        image = np.full((100, 100, 3), 255, dtype=np.uint8)
        future = Future()
        future.set_result({"texts": ["方印"], "scores": [0.9], "boxes": [[1, 2, 30, 20]]})
        with TemporaryDirectory() as directory, patch.object(
            service, "analyze_shape", return_value={"shape": "unknown", "shape_confidence": 0.2}
        ), patch.object(service, "unwrap_seal") as unwrap, patch(
            "app.services.stamp_service.ocr_service.submit_recognize", return_value=future
        ):
            result = service.recognize_image(image, "request-1", Path(directory))
            unwrap.assert_not_called()
            self.assertEqual(result["text"], "方印")


    def test_seal_polygon_fills_missing_box(self):
        words = StampOCRService._words_from_result({
            "texts": ["鍗扮珷"],
            "scores": [0.9],
            "boxes": [],
            "polys": [[[2, 3], [20, 3], [20, 15], [2, 15]]],
        })
        self.assertEqual(words[0]["box"], [2, 3, 20, 15])

    def test_low_quality_rest_candidate_does_not_replace_baseline(self):
        baseline = {"words": [{"text": "河南省吉米特", "confidence": 0.80}]}
        rest = {"words": [
            {"text": "A", "confidence": 0.70},
            {"text": "R", "confidence": 0.35},
        ]}
        self.assertLess(
            StampOCRService._candidate_quality(rest),
            StampOCRService._candidate_quality(baseline) + 0.08,
        )


class StampDependencyTest(unittest.TestCase):
    def test_remote_payload_supports_base64_stamps(self):
        payload = {"data": {"stamps": [{"base64": "aGVsbG8=", "box": {"x1": 1, "y1": 2, "x2": 4, "y2": 6}}]}}
        result = StampOCRService._parse_remote_stamps(payload)
        self.assertEqual(result[0]["image"], b"hello")
        self.assertEqual(result[0]["box"]["w"], 3)
        self.assertEqual(result[0]["box"]["h"], 4)

    def test_remote_failure_is_explicit(self):
        service = StampOCRService()
        with patch.object(service, "extract_remote", side_effect=StampServiceUnavailable("连接超时")):
            self.assertRaises(StampServiceUnavailable, service.extract_remote, Path("missing.jpg"))

    def test_document_route_keeps_dependency_error_code(self):
        class DummyFile:
            filename = "page.jpg"
            content_type = "image/jpeg"

            async def close(self):
                return None

        async def save_upload(*args):
            return Path("page.jpg")

        with patch("app.api.stamp._save_upload", side_effect=save_upload), patch(
            "app.api.stamp.stamp_service.extract_remote",
            side_effect=StampServiceUnavailable("连接超时"),
        ):
            response = asyncio.run(recognize_document_stamps(DummyFile(), False))
        self.assertEqual(response["code"], 5021)
        self.assertIsNone(response["data"])
        self.assertTrue(response["request_id"])


if __name__ == "__main__":
    unittest.main()
