#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def main() -> None:
    project_dir = Path(__file__).resolve().parent
    app_dir = project_dir / "app"

    # 先加载项目根目录 .env，再读取端口和本地默认模型。
    # load_dotenv 不覆盖命令行/进程环境变量，保持环境变量优先级更高。
    load_dotenv(project_dir / ".env")

    port = os.getenv("PORT", "8000")
    reload_enabled = _env_bool("DEV_RELOAD", True)

    if os.name == "nt":
        os.environ.setdefault("OCR_MODEL_PROFILE", "mobile")

    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        port,
    ]
    if reload_enabled:
        cmd.extend(["--reload", "--reload-dir", str(app_dir)])

    print(f"Starting OCR Server on port {port}")
    print(f"Command: {' '.join(cmd)}")
    print(f"Reload: {'enabled for app/' if reload_enabled else 'disabled'}")

    try:
        subprocess.run(cmd, check=True, cwd=project_dir)
    except subprocess.CalledProcessError as exc:
        print(f"Failed to start OCR Server: {exc}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nOCR Server stopped")


if __name__ == "__main__":
    main()
