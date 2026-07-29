使用 `PPOCRLabel` 标注工具最爽的一点是：它内置了**“自动标注（Auto-Labeling）”**功能。您可以用它自带的预训练模型一键把图片里 90% 以上的框自动圈出来，您只需要**手动修正识别错的、或者微调没框准的边界**，这能帮您省下 90% 的标注时间！

以下是**从零安装 PPOCRLabel 到完成标注并一键划分数据集**的保姆级实战指南：

------

### 第一步：在您的电脑上安装并启动 PPOCRLabel

`PPOCRLabel` 是一个基于 Python 和 PyQt5 开发的桌面图形化工具。建议在您自己的**本地电脑（Windows 或 macOS）**上安装运行它：

1. **新建一个虚拟环境并激活（推荐，避免库冲突）**

   ```bash
   python -m venv .venv
   # Windows 激活命令：
   .venv\Scripts\activate
   ```

   

2. 在终端/命令行执行以下命令安装：

   ```bash
   pip install PyQt5
   pip install PPOCRLabel
   
   pip install paddlepaddle-gpu -i https://pypi.tuna.tsinghua.edu.cn/simple
   # pip install paddlepaddle -i https://pypi.tuna.tsinghua.edu.cn/simple
   pip install "paddlex[ocr]" -i https://pypi.tuna.tsinghua.edu.cn/simple
   pip install matplotlib -i https://pypi.tuna.tsinghua.edu.cn/simple # 校验数据集需要画出标注框尺寸和坐标的统计直方图，而画图工作必须依赖 matplotlib（Python 著名的绘图库）
   ```

3. 一键启动：

   ```bash
   # 启动并默认设置为中文标注模式
   PPOCRLabel --lang ch
   
   # 或者
   python -c "import PPOCRLabel, os; print(os.path.join(os.path.dirname(PPOCRLabel.__file__), 'PPOCRLabel.py'))"
   python D:\web\self\study\my-PPOCRLabel\.venv\lib\site-packages\PPOCRLabel\PPOCRLabel.py --lang ch # 用上一步输出的地址替换
   ```
   
   启动后，您会看到一个非常直观的图形界面。

### 第二步：利用“自动标注”极速开工

1. **导入图片**：点击左上角的 `文件` -> `打开目录`，选择您存放原数据集图片的文件夹。

2. 一键自动标注

   ：

   - 点击界面上方的 **`自动标注`** 按钮（或快捷键 `Ctrl + Shift + A`）。
   - 此时，后台会调用 PaddleOCR 官方最强模型，自动把图片里所有的文字位置用绿色矩形框圈好。

3. 人工微调修正（最核心部分）

   ：

   - **检查漏框**：如果有某些银行卡号或发票代码因为比较模糊而漏检，按住鼠标左键拉一个矩形框框住它，并在弹出的框中填入该处的真实文字。
   - **修改错字**：在右侧的文本框列表中，快速检查文字。如果识别错了，双击修改即可。
   - **微调框位置**：如果文本框太偏，鼠标拖拽文本框边缘进行缩放或平移，**确保文本框精准、饱满地包住所有文字**（这也是提升检测Det模型精度的关键！）。

4. **保存当前图**：按快捷键 `Ctrl + S` 保存当前图片标注。

5. **切换下一张**：按快捷键 `D` 切换到下一张，重复这个极速调整过程。

### 第三步：导出标注结果

当您把所有的图片都标注、并保存完毕后：

1. 点击左上角 `文件` -> `导出标记结果`。
2. 这会在您的图片文件夹下自动生成两个最重要文件：
   - `Label.txt`（包含所有检测框的坐标和标注信息，我们后续需要它）。
   - `fileState.txt`（记录标注进度）。

### 第四步：一键自动划分 Train / Val 数据集 (赠送脚本)

通常，我们需要将数据集划分为 **训练集（Train，占 85%）** 用于模型学习，和 **验证集（Val，占 15%）** 用于评估准确度。

为了让您完全免去手动分割的痛苦，我为您写好了下面这个**一键划分脚本**。

#### 1. 创建划分脚本

在您服务器的图片目录同级下（或者在本工作区），创建一个名为 `split_dataset.py` 的文件，并将以下内容复制进去：

```python
# -*- coding: utf-8 -*-
"""
一键自动将 PPOCRLabel 导出的 Label.txt 划分为 train.txt 和 val.txt 
同时生成规范的 PaddleX 训练集结构
"""
import os
import random

# ================= 配置区域 =================
DATASET_DIR = "./my_ocr_dataset"  # 您的数据集目录（内含 images 文件夹和 Label.txt）
TRAIN_RATIO = 0.85                # 训练集比例 (85%)
# ============================================

def split_dataset():
    label_path = os.path.join(DATASET_DIR, "Label.txt")
    if not os.path.exists(label_path):
        print(f"❌ 未在 {DATASET_DIR} 目录下找到 Label.txt，请确保已成功导出！")
        return

    # 读取全部标注行
    with open(label_path, "r", encoding="utf-8") as f:
        lines = [line for line in f.read().splitlines() if line.strip()]

    # 随机打乱，保证训练集和验证集样本分布均匀
    random.seed(42)
    random.shuffle(lines)

    total_count = len(lines)
    train_count = int(total_count * TRAIN_RATIO)

    train_lines = lines[:train_count]
    val_lines = lines[train_count:]

    # 写入 train.txt
    train_path = os.path.join(DATASET_DIR, "train.txt")
    with open(train_path, "w", encoding="utf-8") as f:
        for line in train_lines:
            f.write(line + "\n")

    # 写入 val.txt
    val_path = os.path.join(DATASET_DIR, "val.txt")
    with open(val_path, "w", encoding="utf-8") as f:
        for line in val_lines:
            f.write(line + "\n")

    print("🎉 数据集划分成功！")
    print(f"📊 总样本数: {total_count} 张图片")
    print(f"   └── 🛠️ 训练集 (train.txt): {len(train_lines)} 张 ({TRAIN_RATIO*100:.1f}%)")
    print(f"   └── 📝 验证集 (val.txt): {len(val_lines)} 张 ({ (1-TRAIN_RATIO)*100:.1f}%)")

if __name__ == "__main__":
    split_dataset()
```

#### 2. 运行划分

整理好目录后，在终端运行此脚本：

```bash
python split_dataset.py
```

它就会完美划分好 `train.txt` 和 `val.txt`。

划分完成后，您就可以**直接无缝衔接到上一步（即使用 `python main.py -c ...` 开始微调训练）**啦！

您可以先下载安装 `PPOCRLabel` 标注几张图片体验一下它的自动标注功能。如果在安装或自动标注中有任何疑问，随时向我提问！





## 微调流程



### 一、 定位准确率问题的根源

PaddleX OCR 产线由两个核心单模型串联而成：

1. 文本检测模型（Det）

   ：负责把图片中的文字“框”出来。

   - **表现症状**：文字定位不准、文字漏检、或者检测框把字砍掉了一半。
   - **解决方案**：**微调文本检测模型**（如 `PP-OCRv5_server_det`）。

2. 文本识别模型（Rec）

   ：负责把圈出来的检测框内的文字“认”出来。

   - **表现症状**：框定位得很准，但字认错了，比如把“0”认成“O”，或某些生僻字、特殊符号、数字混淆。
   - **解决方案**：**微调文本识别模型**（如 `PP-OCRv5_server_rec`）。



### 二、 极简微调工作流（以 PaddleX 3.0 为例）

#### 第一步：准备您的私有数据集

建议准备 **500张以上**（生产环境推荐 1000~5000张）的业务真实场景图片进行标注。

- 检测（Det）数据集标注格式

  ：

  使用

   

  PPOCRLabel

   

  等工具进行标注。每一行格式为：

  ```
  图片相对路径 \t [{"transcription": "文本内容", "points": [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]}, ...]
  ```

- 识别（Rec）数据集标注格式

  ：

  裁剪出单行文本小图。每一行格式为：

  ```
  小图相对路径 \t 文本内容
  ```

#### 第二步：在您的目录下创建 `main.py`

在您的当前项目根目录下（与您的 `bank/bank0` 同级），新建一个名为 **`main.py`** 的文件，并把以下内容粘贴进去：

```python
# -*- coding: utf-8 -*-
from paddlex.engine import Engine

if __name__ == "__main__":
    Engine().run()
```

*(是的，这就是飞桨 PaddleX 官方核心训练引擎的完整包装代码！)*

#### 第二步：数据集效验

在训练前，使用 PaddleX 自带的命令行工具，一键校验数据集格式是否正确：

```bash
python main.py -c .venv/Lib/site-packages/paddlex/configs/modules/text_detection/PP-OCRv5_server_det.yaml 
	-o Global.mode=check_dataset 
	-o Global.dataset_dir=./bank/bank0
```

#### 第三步：一行命令启动微调（以文本识别模型微调为例）

在含有 GPU 的环境里，指定您在 `models/official_models` 下的预训练模型权重作为基础，执行微调训练：

```bash
# 启动微调训练（使用 CPU 请把 gpu:0 替换为 cpu）：
python main.py -c .venv/Lib/site-packages/paddlex/configs/modules/text_detection/PP-OCRv5_server_det.yaml -o Global.mode=train -o Global.dataset_dir=./bank/bank0 -o Global.device=gpu:0

# cpu训练
python main.py -c .venv/Lib/site-packages/paddlex/configs/modules/text_detection/PP-OCRv5_server_det.yaml -o Global.mode=train -o Global.dataset_dir=./bank/bank0 -o Global.device=cpu
	
	
# 如果上一条命令报错执行以下命令，再执行上一条命令
mkdir -p .venv/lib/site-packages/paddlex/repo_manager/repos
paddlex --install PaddleOCR


# 如果python main.py -c .venv/Lib/site-packages/paddlex/configs/modules/text_detection/PP-OCRv5_server_det.yaml -o Global.mode=train -o Global.dataset_dir=./bank/bank0 -o Global.device=gpu:0执行失败，执行以下命令
# 通过 pip 安装的 paddlex 内部，没有打包 PP-OCRv5_server_det 模型的二次开发训练配置文件， 打印出您电脑上支持微调的全部 OCR 检测模型名单
python -c "import paddlex, os; base = os.path.dirname(paddlex.__file__); config_path = os.path.join(base, 'repo_apis', 'PaddleOCR_api', 'configs'); print('\n'.join(os.listdir(config_path)) if os.path.exists(config_path) else '该目录下没有 configs 文件夹！')"
# 如果上一条命令查不到相对路径和固定目录都找不到，我们直接使用 Python 进行全盘扫描。这一招是绝对降维打击：直接遍历您本地安装好的整个 paddlex 文件夹，抓出所有的 .yaml（和 .yml）配置文件，打印出它们的绝对路径！
python -c "import paddlex, os; base = os.path.dirname(paddlex.__file__); yaml_files = [os.path.join(root, f) for root, dirs, files in os.walk(base) for f in files if (f.endswith('.yaml') or f.endswith('.yml')) and 'det' in f]; print('\n'.join(yaml_files) if yaml_files else '未找到任何含有 det 的配置文件！')"
```

*训练完成后，最优秀的模型权重会保存在 `output/best_model` 文件夹中。*

##### 如果第三步执行失败

**我们可以用一行 Python 脚本，直接在您的虚拟环境中自动创建该缺失文件夹，并将所有的检测和识别配置文件强行拷贝并映射过去！** 这属于“降维打击”式的代码级硬修复：

请在您的 Git Bash 终端中运行以下一键修复指令：

```python
python -c "
import os, shutil, paddlex
base = os.path.dirname(paddlex.__file__)
target_dir = os.path.join(base, 'repo_apis', 'PaddleOCR_api', 'configs')
os.makedirs(target_dir, exist_ok=True)

# 寻找刚才安装成功拉取到的真·底层配置文件根目录
ocr_repos_dir = os.path.join(base, 'repo_manager', 'repos', 'PaddleOCR', 'configs')

if os.path.exists(ocr_repos_dir):
    copied_count = 0
    # 递归遍历 PaddleOCR 下所有底层的 .yml / .yaml 配置文件
    for root, dirs, files in os.walk(ocr_repos_dir):
        for f in files:
            if f.endswith('.yml') or f.endswith('.yaml'):
                src_file = os.path.join(root, f)
                # 将文件名统一标准化为 .yaml 后缀拷贝过去
                name_without_ext = os.path.splitext(f)[0]
                dst_file = os.path.join(target_dir, name_without_ext + '.yaml')
                shutil.copy(src_file, dst_file)
                copied_count += 1
    print(f'🎉 拷贝成功！共将 {copied_count} 个真正的底层训练配置文件成功映射归位！')
else:
    print('❌ 未在依赖包中找到 PaddleOCR 源码配置文件目录，请确保 paddlex --install PaddleOCR 已运行成功！')
"
```



#### 第四步：在项目中应用微调后的模型

训练完成后，您只需要修改 `ocr-server` 里的 `app/services/ocr_service.py` 文件，在创建 pipeline 时直接将本地微调模型路径传给对应的参数即可：

```python
# 修改 app/services/ocr_service.py
self.pipeline = create_pipeline(
    "OCR",
    det_model="/home/user/ocr-server/models/fine_tuned_det_best", # 指向您微调后的检测模型路径
    rec_model="/home/user/ocr-server/models/fine_tuned_rec_best", # 指向您微调后的识别模型路径
    det_db_unclip_ratio=2.0,
    det_db_score_mode="slow",
)
```

或者，您也可以通过修改 PaddleX 的 `pipeline.yaml` 配置文件并加载它来实现模型无缝替换。

















# 🛠️ CPU/GPU不匹配解决方案

针对您当前电脑是否有 NVIDIA 独立显卡，有以下两种解决路径：

#### 方案 A：直接在 CPU 上进行训练（最快、最省心）

文本检测模型（Det）小数据集在 CPU 上训练完全是可行的！您只需要把设备参数指定为 **`cpu`**。

请在 Git Bash 中运行以下命令：

Bash



```
python main.py -c .venv/Lib/site-packages/paddlex/configs/modules/text_detection/PP-OCRv5_server_det.yaml -o Global.mode=train -o Global.dataset_dir=./bank/bank0 -o Global.device=cpu
```

------

#### 方案 B：使用显卡（GPU）进行超高速训练

如果您本地电脑配备了 NVIDIA 独立显卡，且配置好了 CUDA，想要开启超高速训练：

1. 卸载当前的 CPU 版飞桨：

   Bash

   

   ```
   pip uninstall paddlepaddle -y
   ```

2. 安装匹配您 CUDA 版本的 GPU 版飞桨（以 CUDA 11.8 为例）：

   Bash

   

   ```
   pip install paddlepaddle-gpu==3.0.0b1 -i https://www.paddlepaddle.org.cn/packages/stable/cu118/
   ```

3. 重新启动 GPU 训练命令：

   Bash

   

   ```
   python main.py -c .venv/Lib/site-packages/paddlex/configs/modules/text_detection/PP-OCRv5_server_det.yaml -o Global.mode=train -o Global.dataset_dir=./bank/bank0 -o Global.device=gpu:0
   ```

------

### 🏁 我的建议：

您可以**直接先用“方案 A”（把末尾改成 `-o Global.device=cpu`）启动训练**！

因为在 CPU 上跑通前几轮迭代（Epoch），可以帮您百分之百验证整套训练流程、数据读取、日志落盘是否通畅。后续如果有更大量的图片，您可以随时按照“方案 B”更换为 GPU。

快去终端输入 CPU 启动命令，见证飞桨训练正式跑起来的历史性瞬间吧！🚀