from typing import Any
import re
import os
import cv2
import numpy as np

from paddlex import create_pipeline

from app.utils.logger import logger


class OCRService:

    def __init__(self):
        self.pipeline = None
        self.layout_pipeline = None

    def initialize(self):
        if self.pipeline is not None:
            return

        logger.info("Initializing PaddleX OCR Pipeline...")

        # 使用优化参数创建 pipeline
        self.pipeline = create_pipeline(
            "OCR",
            det_db_unclip_ratio=2.0,         # 检测框扩展比例，更好地包含文本
            det_db_score_mode="slow",       # 更精确的分数计算模式
        )

        logger.info("PaddleX OCR Pipeline Ready.")

    def initialize_layout_pipeline(self):
        """初始化布局分析 pipeline"""
        if self.layout_pipeline is not None:
            return

        logger.info("Initializing PaddleX OCR Layout Pipeline...")

        # 布局分析 pipeline 配置
        self.layout_pipeline = create_pipeline(
            "OCR",
            use_layout_detection=True,    # 启用布局检测
            use_seal_recognition=True,      # 启用印章识别
            use_doc_preprocessor=False,     # 不使用文档预处理器
            return_layout_polygon_points=True,  # 返回多边形点
            format_block_content=True,     # 格式化块内容
            merge_layout_blocks=True,      # 合并布局块
            det_db_unclip_ratio=2.0,       # 检测框扩展比例
            det_db_score_mode="slow",     # 更精确的分数计算模式
        )

        logger.info("PaddleX OCR Layout Pipeline Ready.")

    def preprocess_image(self, image_path: str) -> str:
        """
        图片预处理：自动增强图片质量
        返回预处理后的临时文件路径
        """
        img = cv2.imread(image_path)
        if img is None:
            raise ValueError(f"无法读取图片文件: {image_path}")

        # 转换为灰度图
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # CLAHE 自适应直方图均衡化 - 提升对比度
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)

        # 锐化处理 - 使文字更清晰
        kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
        sharpened = cv2.filter2D(enhanced, -1, kernel)

        # 自动对比度调整
        sharpened = cv2.convertScaleAbs(sharpened, alpha=1.2, beta=30)

        # 保存临时文件
        temp_dir = os.path.join(os.path.dirname(image_path), "temp_preprocessed")
        os.makedirs(temp_dir, exist_ok=True)
        temp_path = os.path.join(temp_dir, f"enhanced_{os.path.basename(image_path)}")
        cv2.imwrite(temp_path, sharpened)

        return temp_path

    def postprocess_texts(self, texts: list[str]) -> list[str]:
        """
        文本后处理：修正常见 OCR 错误
        
        修正策略：
        1. 对单个字符进行常见字符修正（OCR 最容易出错的地方）
        2. 修正中文符号为英文符号
        3. 清理空格和引号
        """
        # 单个字符修正：OCR 最容易将数字误识别为字母
        single_char_corrections = {
            'O': '0', 'o': '0',  # 字母 O/o → 数字 0
            'l': '1', 'I': '1', '|': '1',  # 字母 l/I/| → 数字 1
            'B': '8', 'b': '8',  # 字母 B/b → 数字 8
            'S': '5', 's': '5',  # 字母 S/s → 数字 5
            'Z': '2', 'z': '2',  # 字母 Z/z → 数字 2
        }
        
        # 符号修正
        symbol_corrections = {
            '：': ':', '；': ';', '。': '.',
            '（': '(', '）': ')', '【': '[', '】': ']',
            '「': '(', '」': ')', '、': ',', '·': '.',
            '‘': "'", '’': "'", '“': '"', '”': '"',
        }

        processed = []
        for text in texts:
            if not text or not isinstance(text, str):
                processed.append("")
                continue
            
            # 策略1：单个字符进行字符修正
            if len(text) == 1 and text in single_char_corrections:
                text = single_char_corrections[text]
            
            # 策略2：修正符号
            for wrong, right in symbol_corrections.items():
                text = text.replace(wrong, right)

            # 策略3：清理空格和引号
            text = re.sub(r'\s+', ' ', text).strip()
            text = text.strip('"').strip("'").strip()

            processed.append(text)

        return processed

    def recognize(self, image_path: str, min_score: float = 0.7) -> dict[str, Any]:
        """
        OCR 识别接口（带优化）
        
        Args:
            image_path: 图片路径
            min_score: 最低置信度阈值（默认 0.7，范围 0-1）
        
        Returns:
            识别结果字典，包含 texts, scores, boxes, polys, angle
        """
        if self.pipeline is None:
            # 延迟初始化：如果 pipeline 未初始化，自动初始化
            self.initialize()

        # 图片预处理
        temp_path = None
        try:
            temp_path = self.preprocess_image(image_path)

            # OCR 识别
            for result in self.pipeline.predict(temp_path):

                # 置信度过滤
                texts = []
                scores = []
                boxes = []
                polys = []

                for i, score in enumerate(result["rec_scores"]):
                    if score >= min_score:
                        texts.append(result["rec_texts"][i])
                        scores.append(float(score))
                        boxes.append(result["rec_boxes"][i].tolist())
                        polys.append(result["dt_polys"][i].tolist())

                # 文本后处理
                texts = self.postprocess_texts(texts)

                return {
                    "texts": texts,
                    "scores": scores,
                    "boxes": boxes,
                    "polys": polys,
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

        finally:
            # 清理临时文件
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception as e:
                    logger.warning(f"清理临时文件失败: {e}")


    def recognize_with_layout(self, image_path: str) -> list[dict[str, Any]]:
        """
        布局分析 OCR 识别接口
        
        使用布局分析 pipeline 处理文档，返回结构化结果
        
        Args:
            image_path: 图片或 PDF 文件路径
        
        Returns:
            布局分析结果列表，每个元素代表一页的分析结果
        """
        if self.layout_pipeline is None:
            self.initialize_layout_pipeline()

        def convert_to_serializable(obj):
            """递归将 numpy 数组和其他非序列化对象转换为可序列化格式"""
            if isinstance(obj, dict):
                return {k: convert_to_serializable(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_to_serializable(item) for item in obj]
            elif isinstance(obj, tuple):
                return tuple(convert_to_serializable(item) for item in obj)
            elif isinstance(obj, np.ndarray):
                return obj.tolist()
            elif isinstance(obj, np.integer):
                return int(obj)
            elif isinstance(obj, np.floating):
                return float(obj)
            elif isinstance(obj, np.bool_):
                return bool(obj)
            else:
                return obj

        # 执行布局分析
        layout_results = []
        for result in self.layout_pipeline.predict(image_path):
            # 转换为可序列化格式
            serializable_result = convert_to_serializable(result)
            layout_results.append(serializable_result)

        return layout_results


ocr_service = OCRService()