# 印章 OCR 接口说明

## 处理边界

`ocr-server` 负责单个印章的前景提取、形状分析、圆章/椭圆章文字展开和 PaddleOCR 识别。
整页合同、采集表或票据中的印章检测、定位和裁切由 `stamp-ai-service` 负责。本接口只返回识别证据，
不做印章真伪、签名、业务审核或字段自动比对。

## 单印章识别

```text
POST /api/ocr/stamp
Content-Type: multipart/form-data
```

字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `file` | 文件 | 必填，单个印章图片，支持 JPG、PNG、WEBP |
| `debug` | 布尔 | 可选，`true` 时保存圆章/椭圆章展开图和 mask |

成功响应：

```json
{
  "code": 0,
  "msg": "success",
  "request_id": "xxx",
  "data": {
    "type": "stamp",
    "shape": "circle",
    "shape_confidence": 0.93,
    "text": "某某科技有限公司",
    "confidence": 0.91,
    "words": [
      {"text": "某某科技有限公司", "confidence": 0.91, "box": [[10, 20], [100, 20], [100, 40], [10, 40]]}
    ]
  }
}
```

`shape` 可能为 `circle`、`ellipse`、`square` 或 `unknown`。`unknown` 不会阻止 OCR，服务会直接对原始单印章图进行普通 OCR。
空 OCR 结果返回 `code=4001`。

## 多印章文档识别

```text
POST /api/ocr/document-stamps
Content-Type: multipart/form-data
```

该接口先调用：

```text
POST {STAMP_SERVICE_URL}/api/stamp/extract
```

调用参数为 `return_type=base64`、`strategy=MODEL`、`debug=false`，然后逐个识别裁切图。
stamp-ai-service 不可用返回 `code=5021`，超时返回 `code=5041`，不会伪装成 OCR 失败。

## 文件和配置

原图保存到 `data/uploads/{request_id}/`，OCR 中间文件和结果保存到 `data/outputs/{request_id}/`，按项目现有清理策略自动清理。印章 OCR 中间图使用 PNG，避免透明边缘的 JPEG 压缩伪影。

```dotenv
STAMP_SERVICE_URL=http://127.0.0.1:18080
STAMP_SERVICE_TIMEOUT_SECONDS=30
STAMP_SERVICE_API_KEY=
```

透明 PNG 在存在有效 Alpha 通道时优先使用 Alpha 生成前景 mask；普通图片使用 HSV 颜色、灰度阈值和形态学处理。几何判断是路径选择依据，不是印章分类模型，真实拍摄的透视、反光、遮挡和低清晰度仍可能导致 `unknown` 或 OCR 漏字。
