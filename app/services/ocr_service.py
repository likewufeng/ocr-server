from typing import Any

from paddlex import create_pipeline

from app.utils.logger import logger


class OCRService:

    def __init__(self):

        self.pipeline = None

    def initialize(self):

        if self.pipeline is not None:
            return

        logger.info("Initializing PaddleX OCR Pipeline...")

        self.pipeline = create_pipeline("OCR")

        logger.info("PaddleX OCR Pipeline Ready.")

    def recognize(self, image_path: str) -> dict[str, Any]:

        if self.pipeline is None:
            raise RuntimeError("OCR pipeline is not initialized.")

        for result in self.pipeline.predict(image_path):

            return {
                "texts": result["rec_texts"],
                "scores": result["rec_scores"],
                "boxes": result["rec_boxes"].tolist(),
                "polys": [p.tolist() for p in result["dt_polys"]],
                "angle": result["doc_preprocessor_res"]["angle"]
            }

        return {
            "texts": [],
            "scores": [],
            "boxes": [],
            "polys": [],
            "angle": 0,
            "raw": None
        }


ocr_service = OCRService()