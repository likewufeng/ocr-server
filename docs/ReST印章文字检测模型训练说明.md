# ReST 印章文字检测模型训练说明

## 模型定位

ReST 的 `train_gts.json` 标注的是印章文字区域 polygon，不是文字转写训练集。因此本模型只负责检测印章中的文字区域，不能单独输出“河南省吉米特信息技术有限公司”等文字内容。文字内容仍由项目现有 PaddleOCR 识别器完成。

本模型适合用于单印章图片中的文字区域检测，不替代 `stamp-ai-service` 的整页印章检测、定位和裁切。

## 数据目录

原始数据集只读保存于：

```text
D:\web\self\study\dataset\ReST
```

项目侧训练副本：

```text
training\dataset\rest_seal_det_fast
```

该副本包含 4500 张训练图和 500 张验证图，polygon 已做几何简化以降低 Windows 训练时的数据解析开销。原始 ReST 文件不会被改写。

## 当前训练任务

当前任务使用 RTX 3060 Laptop 6GB、Paddle GPU、PP-OCRv4 mobile seal detector 结构和 ReST 训练集，配置为 5 轮、320x320 输入、batch size 16、2 个数据加载 worker。较小输入尺寸与 ReST 中的印章图尺寸匹配，可显著降低本机训练耗时。

输出目录：

```text
training\output\rest_seal_det_fast_5ep_320
```

训练日志：

```text
training\output\rest_seal_det_fast_5ep_320\train.log
training\output\rest_seal_det_fast_5ep_320\process.stdout.log
training\output\rest_seal_det_fast_5ep_320\process.stderr.log
```

Windows 本地预计每轮约 5 至 7 分钟。训练过程中可以查看进度：

```powershell
Get-Content training\output\rest_seal_det_fast_5ep_320\train.log -Tail 20 -Wait
```

## 中断后恢复

训练每轮保存 `latest.pdparams` 和对应状态文件。恢复时使用原生 PaddleOCR 训练入口，并把 `Global.checkpoints` 指向不带扩展名的 checkpoint 前缀，例如：

```powershell
& .\.venv\Scripts\python.exe .venv\Lib\site-packages\paddlex\repo_manager\repos\PaddleOCR\tools\train.py `
  -c training\configs\rest_seal_det_fast_320.yml `
  -o Global.use_gpu=True Global.epoch_num=5 `
  Global.save_model_dir=D:/web/self/study/ocr-server/training/output/rest_seal_det_fast_5ep_320 `
  Global.checkpoints=D:/web/self/study/ocr-server/training/output/rest_seal_det_fast_5ep_320/latest `
  Train.dataset.data_dir=D:/web/self/study/ocr-server/training/dataset/rest_seal_det_fast `
  Train.dataset.label_file_list=[D:/web/self/study/ocr-server/training/dataset/rest_seal_det_fast/train.txt] `
  Train.loader.batch_size_per_card=16 Train.loader.num_workers=2 `
  Eval.dataset.data_dir=D:/web/self/study/ocr-server/training/dataset/rest_seal_det_fast `
  Eval.dataset.label_file_list=[D:/web/self/study/ocr-server/training/dataset/rest_seal_det_fast/val.txt]
```

## 导出

训练结束并确认 `best_accuracy.pdparams` 存在后，再导出部署模型：

```powershell
& .\.venv\Scripts\python.exe .venv\Lib\site-packages\paddlex\repo_manager\repos\PaddleOCR\tools\export_model.py `
  -c training\configs\rest_seal_det_fast_320.yml `
  -o Global.pretrained_model=D:/web/self/study/ocr-server/training/output/rest_seal_det_fast_5ep_320/best_accuracy.pdparams `
  Global.save_inference_dir=D:/web/self/study/ocr-server/models/stamp_text_det_rest
```

导出后至少应检查目录内包含 `inference.yml`、模型参数和推理文件。没有完整导出文件时不要配置生产服务加载该目录。

## 本次验证结论

- 训练验证集最高 hmean：`0.93596`。
- 最高 checkpoint：第 4 轮，precision=`0.90133`，recall=`0.97336`。
- 部署格式加载 smoke test：通过，GPU 上能加载 ReST 检测器和项目当前 v6 识别器。
- 真实缓存印章 A/B：对原图和展开图的直接推理均出现多条低置信度或错误文本，尚未证明最终字符识别优于现有展开 OCR。
- 当前 `.env` 保持 `STAMP_TEXT_DET_ENABLED=false`，所以不会改变现有生产结果；模型仅作为下一轮真实印章数据 A/B 的实验选项。

## 生产接入原则

1. 检测模型默认关闭，避免训练产物不完整时影响现有接口。
2. 只有完成验证后，才将导出目录配置到 `STAMP_TEXT_DET_MODEL_DIR` 并开启开关。
3. ReST 检测模型只改善文字区域定位，不能保证识别字符准确率提升；必须用真实印章样例做 A/B 对照。
4. 训练副本、checkpoint、导出模型和真实图片均已加入 Git 忽略规则，不提交到仓库。

## 已知限制

- ReST 测试集没有公开文字金标，不能仅凭测试集计算字符准确率。
- 数据集主要覆盖圆形印章，椭圆章、方章、低清晰度、严重反光和遮挡需要额外样例验证。
- 当前模型虽已完成导出和加载测试，但真实印章 A/B 尚未证明最终字符识别收益，训练完成不等于生产效果已经确认。
