# OCR 模型与 CPU/GPU 切换指南

本文说明如何在本项目中切换 PP-OCRv5、PP-OCRv6、不同精度档位，以及 CPU/GPU 推理。所有配置均在项目根目录的 `.env` 中修改；修改后必须重启服务或重建 Docker 容器。

当前推荐组合：

| 场景 | 推荐配置 | 说明 |
| --- | --- | --- |
| Linux/Docker CPU 生产 | `v6 + mobile + cpu` | v6 的 `mobile` 映射为 tiny，速度和资源占用最小。 |
| Windows CPU 开发 | `v6 + mobile + cpu` | 自动使用动态 Safetensors 模型，规避 Windows v6 静态推理兼容问题。 |
| Windows NVIDIA GPU 开发/测试 | `v6 + medium + gpu:0` | 当前本机已验证的高精度组合。 |
| 需要较高准确率但无 GPU | `v6 + small + cpu` | 比 tiny 慢很多，应先压测再用于生产。 |
| 回退旧模型排查 | `v5 + mobile/server + cpu` | 用于和旧版本结果对照，不建议作为新部署默认值。 |

## 1. 配置项说明

```dotenv
# 官方 OCR 模型大版本，只能是 v5 或 v6。
OCR_MODEL_VERSION=v6

# 模型档位。可用值随大版本而变化，见下一节。
OCR_MODEL_PROFILE=mobile

# 推理引擎。通常保持 auto。
OCR_MODEL_ENGINE=auto

# 推理设备：cpu、gpu:0、gpu:1 等。
OCR_DEVICE=cpu

# Paddle 后端；OpenVINO 仅支持 CPU 对照实验。
OCR_INFERENCE_BACKEND=paddle

# true 时仅使用 models/my_bank_card_det 作为文字检测模型；
# 文字识别模型仍由上面的版本和档位决定。
OCR_USE_FINE_TUNED_MODEL=false
```

### 身份证正面透视/弯曲增强

```dotenv
OCR_ID_FRONT_USE_DOC_UNWARPING=false
```

该开关只影响 `id_front`，开启后使用项目中的 UVDoc 对身份证正面做文档展平，适合透视、轻微弯曲和斜拍图片。CPU 会增加推理耗时，建议先在鲁棒性集上做对照；GPU 环境可优先测试 `true`。修改后需要重启服务或重建容器，且应递增 `OCR_CACHE_VERSION`，避免复用旧 OCR 缓存。

配置优先级为：Shell/Docker 环境变量 > `.env` > `app/config.py` 默认值。Docker Compose 中的 `OCR_DEVICE: cpu` 是显式固定的，因此仅修改 `.env` 不能让当前 CPU Docker 镜像使用 GPU。

## 2. v5 与 v6 的模型档位

| `OCR_MODEL_VERSION` | 可填写的 `OCR_MODEL_PROFILE` | 实际检测/识别模型 |
| --- | --- | --- |
| `v5` | `mobile` | `PP-OCRv5_mobile_det` / `PP-OCRv5_mobile_rec` |
| `v5` | `server` | `PP-OCRv5_server_det` / `PP-OCRv5_server_rec` |
| `v6` | `mobile` 或 `tiny` | `PP-OCRv6_tiny_det` / `PP-OCRv6_tiny_rec` |
| `v6` | `small` | `PP-OCRv6_small_det` / `PP-OCRv6_small_rec` |
| `v6` | `server` 或 `medium` | `PP-OCRv6_medium_det` / `PP-OCRv6_medium_rec` |

`mobile` 与 `server` 是便于兼容旧配置的别名。对于 v6，建议写清楚 `tiny`、`small`、`medium`；这样从 `.env` 就能直接看出实际模型档位。

## 3. 快速切换示例

### v6 tiny：CPU 默认推荐

```dotenv
OCR_MODEL_VERSION=v6
OCR_MODEL_PROFILE=tiny
OCR_MODEL_ENGINE=auto
OCR_DEVICE=cpu
OCR_INFERENCE_BACKEND=paddle
OCR_USE_FINE_TUNED_MODEL=false
OCR_ENABLE_MKLDNN=true
OCR_CPU_THREADS=8
OCR_TEXT_RECOGNITION_BATCH_SIZE=6
```

### v6 small：CPU 准确率优先

```dotenv
OCR_MODEL_VERSION=v6
OCR_MODEL_PROFILE=small
OCR_MODEL_ENGINE=auto
OCR_DEVICE=cpu
OCR_INFERENCE_BACKEND=paddle
OCR_USE_FINE_TUNED_MODEL=false
```

small 的 CPU 耗时会明显高于 tiny，尤其是营业执照和发票。不要只通过增加 `OCR_MAX_CONCURRENT_REQUESTS` 来提高吞吐；应优先增加容器实例并进行压测。

### v6 medium：Windows NVIDIA GPU 推荐

```dotenv
OCR_MODEL_VERSION=v6
OCR_MODEL_PROFILE=medium
OCR_MODEL_ENGINE=auto
OCR_DEVICE=gpu:0
OCR_INFERENCE_BACKEND=paddle
OCR_USE_FINE_TUNED_MODEL=false
OCR_TEXT_RECOGNITION_BATCH_SIZE=16
```

`OCR_TEXT_RECOGNITION_BATCH_SIZE=16` 是可选起点。显存足够且营业执照、发票占比较高时，可测试 `32`；若出现显存不足则降回 `16` 或 `6`。

### 回退到 v5 mobile

```dotenv
OCR_MODEL_VERSION=v5
OCR_MODEL_PROFILE=mobile
OCR_MODEL_ENGINE=auto
OCR_DEVICE=cpu
OCR_INFERENCE_BACKEND=paddle
OCR_USE_FINE_TUNED_MODEL=false
```

### 回退到 v5 server

```dotenv
OCR_MODEL_VERSION=v5
OCR_MODEL_PROFILE=server
OCR_MODEL_ENGINE=auto
OCR_DEVICE=cpu
OCR_INFERENCE_BACKEND=paddle
OCR_USE_FINE_TUNED_MODEL=false
```

v5 server 在 CPU 上通常较慢，适合与历史识别结果进行对照；若运行在 GPU 上，则将 `OCR_DEVICE` 改为 `gpu:0` 并确保已安装 GPU 版 PaddlePaddle。

## 4. CPU 与 GPU 切换

### 本地 Windows 切换为 CPU

将 `.env` 改为：

```dotenv
OCR_DEVICE=cpu
OCR_ENABLE_MKLDNN=true
OCR_CPU_THREADS=8
```

若虚拟环境已安装 GPU 版 PaddlePaddle，也可以使用 CPU 配置运行；只是 GPU 相关依赖仍会占用磁盘空间。

### 本地 Windows 切换为 NVIDIA GPU

将 `.env` 改为：

```dotenv
OCR_DEVICE=gpu:0
OCR_INFERENCE_BACKEND=paddle
OCR_MODEL_ENGINE=auto
```

必须同时满足以下条件：

1. Windows 已正确安装 NVIDIA 驱动，且命令行可执行 `nvidia-smi`。
2. 虚拟环境安装的是 GPU 版 PaddlePaddle，而不是仅 CPU 版。
3. `paddle.is_compiled_with_cuda()` 返回 `True`，且 `paddle.get_device()` 返回 `gpu:0`。

本项目当前验证使用的安装命令如下。该命令会下载较大的 CUDA/cuDNN 运行库，网络较慢时需要耐心等待。

```powershell
.\.venv\Scripts\python.exe -m pip install `
  --index-url https://www.paddlepaddle.org.cn/packages/stable/cu126/ `
  --upgrade "paddlepaddle-gpu==3.3.1"
```

验证 GPU：

```powershell
.\.venv\Scripts\python.exe -c "import paddle; print(paddle.is_compiled_with_cuda()); print(paddle.get_device())"
```

预期输出包含：

```text
True
gpu:0
```

### Docker/Linux CPU

当前 `docker-compose.yml`、`docker-compose.scale.yml` 和 `docker-compose.openvino.yml` 都显式使用：

```yaml
OCR_DEVICE: cpu
```

因此 Docker 部署按 CPU 模式运行。可通过 `.env` 切换 v5/v6 和模型档位，但 GPU 需要专门的 GPU 镜像、NVIDIA Container Toolkit 和 Compose GPU 设备声明；不能只把 `.env` 改为 `OCR_DEVICE=gpu:0`。

## 5. 模型文件目录与加载规则

服务优先从项目目录加载模型：

```text
models/official_models/
```

当项目中缺少所需模型时，PaddleX 会下载并使用用户缓存目录，例如 Windows 的：

```text
C:\Users\<用户名>\.paddlex\official_models\
```

为了支持离线部署并确保所有环境加载相同模型，应将模型放入项目 `models/official_models`。目录名必须与下表完全一致。

| 运行方式 | 模型目录后缀 | 示例 |
| --- | --- | --- |
| Windows v6，`OCR_MODEL_ENGINE=auto` | `_safetensors` | `PP-OCRv6_medium_det_safetensors` |
| Linux/Docker v6，`OCR_MODEL_ENGINE=auto` | 无后缀（静态模型） | `PP-OCRv6_medium_det` |
| v5 静态推理 | 无后缀 | `PP-OCRv5_server_det` |

同一版本和档位必须同时准备检测模型（`*_det`）和识别模型（`*_rec`）。若同一项目既要 Windows GPU 又要 Linux/Docker 使用同一档位，建议同时保留动态和静态两套目录。

例如，Windows GPU 使用 v6 medium 时需要：

```text
models/official_models/PP-OCRv6_medium_det_safetensors/
models/official_models/PP-OCRv6_medium_rec_safetensors/
```

Linux/Docker CPU 使用 v6 medium 时还需要：

```text
models/official_models/PP-OCRv6_medium_det/
models/official_models/PP-OCRv6_medium_rec/
```

将 PaddleX 已下载的 Windows dynamic 模型纳入项目目录：

```powershell
$paddlexCache = "$env:USERPROFILE\.paddlex\official_models"
$projectModels = "D:\web\self\study\ocr-server\models\official_models"

Copy-Item "$paddlexCache\PP-OCRv6_medium_det_safetensors" $projectModels -Recurse
Copy-Item "$paddlexCache\PP-OCRv6_medium_rec_safetensors" $projectModels -Recurse
```

复制前若目标目录已存在，PowerShell 会在其中嵌套一个同名目录。目标已存在时，请使用：

```powershell
Copy-Item "$paddlexCache\PP-OCRv6_medium_det_safetensors\*" `
  "$projectModels\PP-OCRv6_medium_det_safetensors" -Recurse -Force
Copy-Item "$paddlexCache\PP-OCRv6_medium_rec_safetensors\*" `
  "$projectModels\PP-OCRv6_medium_rec_safetensors" -Recurse -Force
```

## 6. 自训练检测模型切换

```dotenv
OCR_USE_FINE_TUNED_MODEL=true
```

启用后，文字检测会读取：

```text
models/my_bank_card_det/
```

文字识别仍使用 `OCR_MODEL_VERSION` 与 `OCR_MODEL_PROFILE` 决定的官方 `*_rec` 模型。当前没有使用自训练模型的计划时，应保持：

```dotenv
OCR_USE_FINE_TUNED_MODEL=false
```

## 7. 重启与验证

### Python 本地开发

先在运行窗口按 `Ctrl+C` 停止，然后执行：

```powershell
python start.py
```

若服务在后台运行，先查找 8000 端口：

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen |
  Select-Object OwningProcess
```

再停止对应进程树：

```powershell
taskkill /PID <PID> /T /F
```

### Docker 单实例 CPU

仅修改 `.env` 后重新创建容器：

```bash
docker compose up -d --force-recreate
```

修改 `Dockerfile`、`requirements.txt` 或项目依赖后重新构建：

```bash
docker compose up -d --build
```

### 查看实际加载的模型

启动日志会打印以下字段：

```text
version=v6, profile=medium, detector=PP-OCRv6_medium_det,
recognizer=PP-OCRv6_medium_rec, engine=paddle_dynamic, device=gpu:0
```

同时观察 PaddleX 的模型路径。若使用项目内模型，应出现类似：

```text
D:\web\self\study\ocr-server\models\official_models\PP-OCRv6_medium_det_safetensors
```

若出现 `C:\Users\<用户名>\.paddlex\official_models`，说明项目 `models` 中缺少对应目录，PaddleX 已回退到用户缓存。

## 8. 常见问题

### 改了 `.env` 但仍是旧模型

服务进程不会自动重新读取 `.env`。本地需重启 `python start.py`；Docker 需执行 `docker compose up -d --force-recreate`。此外，Shell 或 Docker `environment` 中的同名变量优先级高于 `.env`。

### v6 在 Windows CPU 使用静态模型报错

保持：

```dotenv
OCR_MODEL_ENGINE=auto
```

项目会在 Windows v6 下自动选择 `paddle_dynamic` 和 `_safetensors` 模型。不要强制配置 `paddle_static`，PaddlePaddle 3.3.1 的 Windows CPU 静态 PIR 推理存在已验证的兼容问题。

### 设置 `OCR_DEVICE=gpu:0` 后无法启动

通常是 GPU 版 PaddlePaddle、NVIDIA 驱动或 CUDA 运行库未准备好。先运行本指南中的 GPU 验证命令；只有输出 `True` 与 `gpu:0` 后再启动服务。

### GPU 日志提示 cuDNN 版本不一致

本地实测出现过 Paddle 编译的 cuDNN 版本与机器运行库版本不完全一致的警告，当前 OCR 可以执行，但应在稳定使用前统一驱动、CUDA 和 cuDNN 版本，再做回归识别与压测。

### OpenVINO 能否配合 GPU

不能。项目配置已限制 `OCR_INFERENCE_BACKEND=openvino` 时必须使用 `OCR_DEVICE=cpu`。GPU 场景使用 `OCR_INFERENCE_BACKEND=paddle`。
