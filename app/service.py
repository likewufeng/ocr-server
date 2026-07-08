from paddlex import create_pipeline

pipeline = create_pipeline("OCR")


def recognize(image_path: str):
    for result in pipeline.predict(image_path):
        return result["rec_texts"]
    return []