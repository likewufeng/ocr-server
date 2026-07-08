from dataclasses import dataclass
from typing import List


@dataclass
class OCRData:
    texts: List[str]
    scores: List[float]
    boxes: List[list]
    polys: List[list]
    angle: int