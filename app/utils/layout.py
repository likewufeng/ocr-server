from dataclasses import dataclass
from typing import List, Optional

from app.utils.logger import logger
import json


@dataclass
class OCRLine:
    """
    一行 OCR 数据
    """

    text: str

    left: int
    top: int
    right: int
    bottom: int

    score: float

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def center_x(self) -> float:
        return (self.left + self.right) / 2

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2


class Layout:

    def __init__(self, lines: List[OCRLine]):

        self.lines = sorted(
            lines,
            key=lambda x: (x.top, x.left)
        )

    def all(self) -> List[OCRLine]:
        return self.lines

    def texts(self) -> List[str]:
        return [i.text for i in self.lines]

    def find(self, keyword: str) -> Optional[OCRLine]:
        """
        找包含关键字的一行
        """

        for line in self.lines:

            if keyword in line.text:
                return line

        return None
    
    def find_any(self, *keywords) -> Optional[OCRLine]:
        """
        查找任意关键字，返回第一个匹配项

        layout.find_any(
            "名称",
            "名 称",
            "称"
        )
        """

        for keyword in keywords:

            line = self.find(keyword)

            if line:
                return line

        return None

    def find_all(self, keyword: str) -> List[OCRLine]:
        """
        找所有包含关键字的行
        """

        result = []

        for line in self.lines:

            if keyword in line.text:
                result.append(line)

        return result

    def same_row(
            self,
            line: OCRLine,
            tolerance: int = 20
    ) -> List[OCRLine]:
        """
        找同一行
        """

        result = []

        for item in self.lines:

            if abs(
                    item.center_y - line.center_y
            ) <= tolerance:

                result.append(item)

        result.sort(
            key=lambda x: x.left
        )

        return result

    def right_of(
            self,
            line: OCRLine,
            tolerance: int = 20
    ) -> List[OCRLine]:
        """
        找右边内容
        """

        result = []

        for item in self.lines:

            if item.left <= line.right:
                continue

            if abs(
                    item.center_y - line.center_y
            ) <= tolerance:

                result.append(item)

        result.sort(
            key=lambda x: x.left
        )

        return result

    def left_of(
            self,
            line: OCRLine,
            tolerance: int = 20
    ) -> List[OCRLine]:
        """
        找左边内容
        """

        result = []

        for item in self.lines:

            if item.right >= line.left:
                continue

            if abs(
                    item.center_y - line.center_y
            ) <= tolerance:

                result.append(item)

        result.sort(
            key=lambda x: x.left
        )

        return result

    def below(
            self,
            line: OCRLine
    ) -> List[OCRLine]:
        """
        找下面所有行
        """

        result = []

        for item in self.lines:

            if item.top > line.bottom:
                result.append(item)

        result.sort(
            key=lambda x: x.top
        )

        return result

    def above(
            self,
            line: OCRLine
    ) -> List[OCRLine]:
        """
        找上面所有行
        """

        result = []

        for item in self.lines:

            if item.bottom < line.top:
                result.append(item)

        result.sort(
            key=lambda x: x.top
        )

        return result

    def nearest_below(
        self,
        line: OCRLine
    ) -> Optional[OCRLine]:

        items = []

        for item in self.lines:

            if item.top <= line.bottom:
                continue

            items.append(item)

        if not items:
            return None

        return min(
            items,
            key=lambda x: (
                x.top - line.bottom,
                abs(x.left - line.left)
            )
        )

    def nearest_above(
        self,
        line: OCRLine
    ) -> Optional[OCRLine]:
        """
        返回最近的上方 OCRLine
        """

        items = []

        for item in self.lines:

            if item.bottom >= line.top:
                continue

            items.append(item)

        if not items:
            return None

        return min(
            items,
            key=lambda x: (
                line.top - x.bottom,
                abs(x.left - line.left)
            )
        )

    # def nearest_right(
    #         self,
    #         line: OCRLine
    # ) -> Optional[OCRLine]:
    #     """
    #     最近右边
    #     """

    #     items = self.right_of(line)

    #     if len(items) == 0:
    #         return None

    #     return items[0]
    
    def nearest_right(
        self,
        line: OCRLine,
        tolerance: int = None
    ) -> Optional[OCRLine]:
        """
        返回同行最近的右侧 OCRLine
        """

        items = self.right_of(line, tolerance)

        if not items:
            return None

        return min(
            items,
            key=lambda x: x.left
        )


def build_layout(
    ocr_result,
    min_score: float = 0.2
) -> Layout:
    # logger.info("🚀 ~ build_layout ~ ocr_result: {}", json.dumps(ocr_result, indent=2, ensure_ascii=False))
    """
    PaddleX OCR
        ↓
    Layout

    自动过滤：
    - 空文本
    - 低置信度
    """

    texts = ocr_result["texts"]

    boxes = ocr_result["boxes"]

    scores = ocr_result["scores"]

    lines = []

    for text, box, score in zip(
            texts,
            boxes,
            scores
    ):

        # ---------- 清洗 ----------

        if text is None:
            continue

        text = str(text).strip()

        if text == "":
            continue

        if score < min_score:
            continue

        # ---------- 构建 OCRLine ----------

        lines.append(

            OCRLine(

                text=text,

                left=int(box[0]),

                top=int(box[1]),

                right=int(box[2]),

                bottom=int(box[3]),

                score=float(score)

            )

        )

    return Layout(lines)