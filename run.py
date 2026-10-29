#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""声坊 Voice Atelier 启动脚本。

    python run.py                 # 读取 .env 中的 HOST/PORT
    python run.py --port 9000     # 覆盖端口
    python run.py --reload        # 开发热重载
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 保证以脚本方式运行时也能 import app 包
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> None:
    parser = argparse.ArgumentParser(description="启动声坊 Voice Atelier")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--reload", action="store_true", help="开发模式：代码变更自动重载")
    args = parser.parse_args()

    from app.config import BASE_DIR, settings

    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        print("提示：未找到 .env 文件，将使用默认配置与模拟模式。")
        print("      可复制 .env.example 为 .env 并填写 SPEECH_API_KEY。")

    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=args.host or settings.host,
        port="0.0.0.0",
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
