# -*- coding: utf-8 -*-
#Author: WuFeng <763467339@qq.com>
#Date: 2026-07-13 11:03:48
#LastEditTime: 2026-07-13 12:13:43
#LastEditors: WuFeng <763467339@qq.com>
#Description: 启动脚本 - 封装 Uvicorn 启动命令
# # 方式1：直接运行
# python start.py

# # 方式2：指定端口（会读取 .env.local 中的配置）
# PORT=8002 python start.py

# # 方式3：给脚本添加执行权限（Linux/Mac）
# chmod +x start.py
# ./start.py
#FilePath: /ocr-server/start.py
#Copyright 版权声明
#
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""启动脚本 - 封装 Uvicorn 启动命令"""

import subprocess
import sys
import os

def main():
    # 获取端口配置，默认8000
    port = os.getenv("PORT", "8000")
    
    # Windows 兼容性：强制使用 polling 模式
    os.environ["WATCHFILES_FORCE_POLLING"] = "true"
    
    # 获取当前工作目录，支持跨平台
    current_dir = os.getcwd()
    
    # 构建启动命令
    cmd = [
        sys.executable, "-m", "uvicorn",
        "app.main:app",
        "--host", "0.0.0.0",
        "--port", port,
        "--reload",
        "--reload-dir", current_dir,
        "--reload-include", "*.py",
    ]
    
    print(f"🚀 启动 OCR Server... (端口: {port})")
    print(f"命令: {' '.join(cmd)}")
    print("=" * 50)
    print("💡 热重载已启用：修改 .py 文件后自动重启")
    print("💡 Windows 兼容模式：已启用 polling")
    print("=" * 50)
    
    # 执行命令
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ 启动失败: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n👋 服务已停止")

if __name__ == "__main__":
    main()