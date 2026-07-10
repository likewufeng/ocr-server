from app.utils.layout import Layout
from app.parsers.detector import DocumentDetector
from app.parsers.id_front import IDFrontParser
from app.parsers.id_back import IDBackParser
from app.parsers.business import BusinessParser

class OCRParser:
    def __init__(self):
        self.detector = DocumentDetector()
        self.parsers = {
            "id_front": IDFrontParser(),
            "id_back": IDBackParser(),
            "business_license": BusinessParser()
        }

    def parse(self, layout: Layout):
        # 1. 自动检测类型
        doc_type = self.detector.detect(layout)
        
        # 2. 选择对应的解析器
        parser = self.parsers.get(doc_type)
        
        if not parser:
            return {
                "type": "unknown",
                "error": "未能识别证件类型",
                "raw_texts": layout.texts()
            }
        
        # 3. 执行解析
        try:
            result = parser.parse(layout)
            return result
        except Exception as e:
            return {
                "type": doc_type,
                "error": f"解析失败: {str(e)}"
            }