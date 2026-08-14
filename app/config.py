"""应用配置入口。

配置优先级：进程环境变量 > 项目根目录 .env > 本文件中的默认值。
生产部署主要修改 .env 或 Docker 环境变量，业务代码统一从本模块读取配置。
"""

import os
import socket
from pathlib import Path

from dotenv import load_dotenv


# load_dotenv 默认不会覆盖 Docker、Shell 已经传入的环境变量。
load_dotenv()


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


BASE_DIR = Path(__file__).resolve().parent.parent


# ---------- 服务基础配置 ----------
APP_NAME = os.getenv("APP_NAME")
HOST = os.getenv("HOST")
PORT = int(os.getenv("PORT"))
INSTANCE_NAME = os.getenv("INSTANCE_NAME", socket.gethostname()).strip()

# 是否采集并暴露 /metrics 与 /metrics/json 进程指标。
METRICS_ENABLED = _env_bool("METRICS_ENABLED", True)


# ---------- 动态数据与模型目录 ----------
# .env 中的相对路径统一拼接到项目根目录，避免受启动目录影响。
UPLOAD_DIR = BASE_DIR / os.getenv("UPLOAD_DIR", "data/uploads")
OUTPUT_DIR = BASE_DIR / os.getenv("OUTPUT_DIR", "data/outputs")
CACHE_DIR = BASE_DIR / os.getenv("CACHE_DIR", "data/cache")
MODEL_DIR = BASE_DIR / os.getenv("MODEL_DIR", "models")
LOG_DIR = BASE_DIR / os.getenv("LOG_DIR", "data/logs")
# 银行名称别名、卡种文案和 BIN/IIN 数据文件。生产环境可挂载更新该文件，无需修改解析代码。
BANK_CARD_CATALOG_FILE = BASE_DIR / os.getenv(
    "BANK_CARD_CATALOG_FILE", "app/resources/bank_card/catalog.json"
)
BANK_CARD_IIN_FILE = BASE_DIR / os.getenv(
    "BANK_CARD_IIN_FILE", "app/resources/bank_card/iin_catalog.json"
)


# ---------- 文件保留与清理周期 ----------
# uploads、outputs、cache 共用动态文件保留天数。
DYNAMIC_FILE_RETENTION_DAYS = int(os.getenv("DYNAMIC_FILE_RETENTION_DAYS", "1"))
LOG_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "3"))
CLEANUP_INTERVAL_SECONDS = int(os.getenv("CLEANUP_INTERVAL_SECONDS", "3600"))


# ---------- OCR 模型选择 ----------
# true 只替换文字检测模型为 models/my_bank_card_det；识别模型仍使用官方模型。
OCR_USE_FINE_TUNED_MODEL = _env_bool("OCR_USE_FINE_TUNED_MODEL", False)

# OCR_MODEL_VERSION controls the official OCR model family. v6 is the current default.
OCR_MODEL_VERSION = os.getenv("OCR_MODEL_VERSION", "v6").strip().lower()
if OCR_MODEL_VERSION not in {"v5", "v6"}:
    raise ValueError("OCR_MODEL_VERSION must be 'v5' or 'v6'")

OCR_MODEL_PROFILE = os.getenv("OCR_MODEL_PROFILE", "mobile").strip().lower()
_OCR_MODEL_VARIANTS = {
    "v5": {"mobile": "mobile", "server": "server"},
    "v6": {
        "mobile": "tiny",
        "server": "medium",
        "tiny": "tiny",
        "small": "small",
        "medium": "medium",
    },
}
if OCR_MODEL_PROFILE not in _OCR_MODEL_VARIANTS[OCR_MODEL_VERSION]:
    allowed_profiles = ", ".join(_OCR_MODEL_VARIANTS[OCR_MODEL_VERSION])
    raise ValueError(
        f"OCR_MODEL_PROFILE for {OCR_MODEL_VERSION} must be one of: {allowed_profiles}"
    )

OCR_MODEL_VARIANT = _OCR_MODEL_VARIANTS[OCR_MODEL_VERSION][OCR_MODEL_PROFILE]

# PP-OCRv6 static PIR models currently fail in PaddlePaddle's Windows CPU executor.
# Auto uses Safetensors dynamic inference on Windows and static inference on Linux.
OCR_MODEL_ENGINE = os.getenv("OCR_MODEL_ENGINE", "auto").strip().lower()
if OCR_MODEL_ENGINE == "auto":
    OCR_MODEL_ENGINE = (
        "paddle_dynamic"
        if os.name == "nt" and OCR_MODEL_VERSION == "v6"
        else "paddle_static"
    )
if OCR_MODEL_ENGINE not in {"paddle_static", "paddle_dynamic"}:
    raise ValueError(
        "OCR_MODEL_ENGINE must be 'auto', 'paddle_static' or 'paddle_dynamic'"
    )

# 支持 cpu、gpu:0 等 PaddleX 设备写法。
# 使用 GPU 还必须准备 GPU 版 PaddlePaddle 和 CUDA 运行环境。
OCR_DEVICE = os.getenv("OCR_DEVICE", "cpu").strip().lower()

# paddle：当前稳定的 Paddle Inference/MKLDNN 后端；openvino：仅用于已安装
# PaddleX HPIP、UltraInfer 和 Paddle2ONNX 的 CPU 对照实验。
OCR_INFERENCE_BACKEND = os.getenv(
    "OCR_INFERENCE_BACKEND", "paddle"
).strip().lower()
if OCR_INFERENCE_BACKEND not in {"paddle", "openvino"}:
    raise ValueError("OCR_INFERENCE_BACKEND must be 'paddle' or 'openvino'")
if OCR_INFERENCE_BACKEND == "openvino" and OCR_DEVICE != "cpu":
    raise ValueError("OCR_INFERENCE_BACKEND=openvino requires OCR_DEVICE=cpu")


# ---------- CPU 推理参数 ----------
# MKLDNN 是 CPU 推理加速后端；GPU 模式不会使用该开关。
OCR_ENABLE_MKLDNN = _env_bool("OCR_ENABLE_MKLDNN", True)

# 未配置时最多使用 8 个线程，同时不会超过系统报告的 CPU 数量。
OCR_CPU_THREADS = max(
    1, int(os.getenv("OCR_CPU_THREADS", str(min(8, os.cpu_count() or 1))))
)


# ---------- 识别批处理 ----------
# 控制一次送入识别模型的文字框数量，不是 HTTP 请求并发数。
OCR_TEXT_RECOGNITION_BATCH_SIZE = max(
    1, int(os.getenv("OCR_TEXT_RECOGNITION_BATCH_SIZE", "6"))
)

# 身份证正面的小号蓝色标签在模糊照片中置信度可能偏低；仅对该类型降低过滤门槛，
# 由解析器的字段和坐标校验兜底。其它证件仍使用 OCR 默认门槛。
OCR_ID_FRONT_MIN_SCORE = min(
    1.0, max(0.0, float(os.getenv("OCR_ID_FRONT_MIN_SCORE", "0.5")))
)


# ---------- 文档方向与形变预处理 ----------
# 控制方向模型是否在 pipeline 初始化时加载。
OCR_ENABLE_DOC_ORIENTATION_MODEL = _env_bool(
    "OCR_ENABLE_DOC_ORIENTATION_MODEL", True
)

# /ocr 未传 auto_orientation 时使用该默认值；生产默认 true 更稳妥。
OCR_USE_DOC_ORIENTATION = _env_bool("OCR_USE_DOC_ORIENTATION", True)

# UVDoc 用于弯曲、透视文档展平，CPU 开销较高。
OCR_USE_DOC_UNWARPING = _env_bool("OCR_USE_DOC_UNWARPING", False)
# 仅对身份证正面启用文档展平。开启后可改善透视/轻微弯曲图片，CPU 会增加推理耗时；
# 建议先在鲁棒性测试集上做 A/B，对 GPU 生产环境可优先开启。
OCR_ID_FRONT_USE_DOC_UNWARPING = _env_bool(
    "OCR_ID_FRONT_USE_DOC_UNWARPING", False
)

# 仅在首轮结构化解析缺少姓名或生日时，对对应的小区域做一次放大补识别。
# 正常身份证不会触发，不依赖整图质量阈值。
OCR_ID_FRONT_FIELD_ROI_RETRY_ENABLED = _env_bool(
    "OCR_ID_FRONT_FIELD_ROI_RETRY_ENABLED", False
)
OCR_ID_FRONT_FIELD_ROI_SCALE = min(
    4.0, max(1.0, float(os.getenv("OCR_ID_FRONT_FIELD_ROI_SCALE", "3.0")))
)
OCR_ID_FRONT_FIELD_ROI_MIN_SCORE = min(
    1.0, max(0.0, float(os.getenv("OCR_ID_FRONT_FIELD_ROI_MIN_SCORE", "0.5")))
)

# 营业执照经营范围为空或明显过短时，裁剪该区域做一次局部 OCR。默认关闭，
# 应先通过金标集 A/B 验证后再按部署环境启用；本地 --reload 不监听 .env，修改后也需重启服务。
OCR_BUSINESS_SCOPE_ROI_RETRY_ENABLED = _env_bool(
    "OCR_BUSINESS_SCOPE_ROI_RETRY_ENABLED", False
)
OCR_BUSINESS_SCOPE_ROI_MIN_CHARS = max(
    1, int(os.getenv("OCR_BUSINESS_SCOPE_ROI_MIN_CHARS", "48"))
)
OCR_BUSINESS_SCOPE_ROI_SCALE = min(
    2.0, max(1.0, float(os.getenv("OCR_BUSINESS_SCOPE_ROI_SCALE", "1.5")))
)
OCR_BUSINESS_SCOPE_ROI_MAX_SIDE = max(
    960, int(os.getenv("OCR_BUSINESS_SCOPE_ROI_MAX_SIDE", "2200"))
)
OCR_BUSINESS_SCOPE_ROI_MIN_SCORE = min(
    1.0, max(0.0, float(os.getenv("OCR_BUSINESS_SCOPE_ROI_MIN_SCORE", "0.5")))
)

# 仅在营业执照的统一社会信用代码、名称或法定代表人为空时，按标签位置裁剪小区域补识别。
# 默认关闭，避免为正常请求增加第二次推理；修改 .env 后需重启服务。
OCR_BUSINESS_FIELD_ROI_RETRY_ENABLED = _env_bool(
    "OCR_BUSINESS_FIELD_ROI_RETRY_ENABLED", False
)
OCR_BUSINESS_FIELD_ROI_SCALE = min(
    4.0, max(1.0, float(os.getenv("OCR_BUSINESS_FIELD_ROI_SCALE", "3.0")))
)
OCR_BUSINESS_FIELD_ROI_MIN_SCORE = min(
    1.0, max(0.0, float(os.getenv("OCR_BUSINESS_FIELD_ROI_MIN_SCORE", "0.5")))
)

# 营业执照通常包含字号较小且行数较多的经营范围。默认保持通用检测边长，
# 可在金标 A/B 中提高至 1280 以换取更高的文字检测分辨率；修改 .env 后需重启服务，默认 960。
OCR_BUSINESS_LICENSE_DETECTION_SIDE_LIMIT = max(
    640, int(os.getenv("OCR_BUSINESS_LICENSE_DETECTION_SIDE_LIMIT", "960"))
)

# ---------- 银行卡专用区域定位 ----------
# 可选 ONNX 模型先定位卡号和有效期区域，再对小区域补做 OCR。默认关闭，避免
# 未部署模型时影响现有银行卡接口，也避免给所有证件增加一次检测推理。
OCR_BANK_CARD_ROI_ENABLED = _env_bool("OCR_BANK_CARD_ROI_ENABLED", False)
OCR_BANK_CARD_ROI_MODEL_FILE = BASE_DIR / os.getenv(
    "OCR_BANK_CARD_ROI_MODEL_FILE", "models/bank_card_roi/yolo_best.onnx"
)
OCR_BANK_CARD_ROI_INPUT_SIZE = max(
    320, int(os.getenv("OCR_BANK_CARD_ROI_INPUT_SIZE", "640"))
)
OCR_BANK_CARD_ROI_CONFIDENCE = min(
    0.95, max(0.05, float(os.getenv("OCR_BANK_CARD_ROI_CONFIDENCE", "0.45")))
)
OCR_BANK_CARD_ROI_NMS = min(
    0.95, max(0.05, float(os.getenv("OCR_BANK_CARD_ROI_NMS", "0.45")))
)
OCR_BANK_CARD_ROI_PADDING_RATIO = min(
    0.5, max(0.0, float(os.getenv("OCR_BANK_CARD_ROI_PADDING_RATIO", "0.08")))
)
OCR_BANK_CARD_ROI_MIN_SCORE = min(
    1.0, max(0.0, float(os.getenv("OCR_BANK_CARD_ROI_MIN_SCORE", "0.35")))
)

# 身份证正面低质量图片的条件重试。首轮结果完整时不会触发第二次推理；
# 重试只使用温和的放大、CLAHE 和锐化，不改变生产默认的 UVDoc 行为。
OCR_ID_FRONT_QUALITY_RETRY_ENABLED = _env_bool(
    "OCR_ID_FRONT_QUALITY_RETRY_ENABLED", False
)
OCR_ID_FRONT_RETRY_ON_INCOMPLETE = _env_bool(
    "OCR_ID_FRONT_RETRY_ON_INCOMPLETE", True
)
OCR_ID_FRONT_RETRY_SCALE = min(
    2.0, max(1.0, float(os.getenv("OCR_ID_FRONT_RETRY_SCALE", "1.5")))
)
OCR_ID_FRONT_RETRY_MAX_SIDE = max(
    768, int(os.getenv("OCR_ID_FRONT_RETRY_MAX_SIDE", "2400"))
)
OCR_ID_FRONT_RETRY_BLUR_THRESHOLD = max(
    0.0, float(os.getenv("OCR_ID_FRONT_RETRY_BLUR_THRESHOLD", "45"))
)
OCR_ID_FRONT_RETRY_MIN_SIDE = max(
    1, int(os.getenv("OCR_ID_FRONT_RETRY_MIN_SIDE", "300"))
)
OCR_ID_FRONT_RETRY_DARK_MEAN = min(
    255.0, max(0.0, float(os.getenv("OCR_ID_FRONT_RETRY_DARK_MEAN", "35")))
)
OCR_ID_FRONT_RETRY_BRIGHT_MEAN = min(
    255.0, max(0.0, float(os.getenv("OCR_ID_FRONT_RETRY_BRIGHT_MEAN", "235")))
)
OCR_ID_FRONT_RETRY_CLIPPED_RATIO = min(
    1.0,
    max(0.0, float(os.getenv("OCR_ID_FRONT_RETRY_CLIPPED_RATIO", "0.35"))),
)


# ---------- 预处理排查图片 ----------
# 图片通过后台线程保存，不计入正常接口响应等待时间。
OCR_SAVE_PREPROCESSED_IMAGE = _env_bool("OCR_SAVE_PREPROCESSED_IMAGE", True)

OCR_PREPROCESSED_JPEG_QUALITY = min(
    100, max(1, int(os.getenv("OCR_PREPROCESSED_JPEG_QUALITY", "90")))
)


# ---------- OCR 原始结果缓存 ----------
# 缓存键包含图片 SHA-256、模型和推理参数，过期时间复用动态文件保留天数。
OCR_CACHE_ENABLED = _env_bool("OCR_CACHE_ENABLED", True)

# 模型或预处理算法发生不兼容变化时递增版本号，可立即隔离旧缓存。
OCR_CACHE_VERSION = os.getenv("OCR_CACHE_VERSION", "7").strip()


# ---------- HTTP OCR 并发 ----------
# 当前所有请求共享一个 PaddleX pipeline，默认串行最稳妥。
OCR_MAX_CONCURRENT_REQUESTS = max(
    1, int(os.getenv("OCR_MAX_CONCURRENT_REQUESTS", "1"))
)


# ---------- 启动时确保运行目录存在 ----------
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)
MODEL_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
