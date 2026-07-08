from paddlex import create_pipeline


class OCRService:

    def __init__(self):
        self.pipeline = None

    def initialize(self):

        if self.pipeline is None:
            self.pipeline = create_pipeline("OCR")

    def recognize(self, image_path):

        for result in self.pipeline.predict(image_path):

            return {
                "texts": result["rec_texts"],
                "scores": result["rec_scores"],
                "boxes": result["rec_boxes"]
            }

        return {
            "texts": [],
            "scores": [],
            "boxes": []
        }


ocr_service = OCRService()