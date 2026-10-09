# -*- coding: utf-8 -*-
"""全局配置：从 .env 读取环境变量。"""

import os
from pathlib import Path

from dotenv import load_dotenv

# 项目根目录
ROOT = Path(__file__).resolve().parent

# 加载 .env（文件不存在也不报错，validate() 会给出明确提示）
load_dotenv(ROOT / ".env")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()

# 路径
DATA_DIR = ROOT / "data"
INPUT_DIR = DATA_DIR / "input"
OUTPUT_DIR = DATA_DIR / "output"


def validate() -> None:
    """校验必需配置，缺失时给出可操作的提示。"""
    if DEEPSEEK_API_KEY and not DEEPSEEK_API_KEY.startswith("sk-xxx"):
        return

    env_path = ROOT / ".env"
    if env_path.exists():
        hint = (
            f"  .env 已存在：{env_path}\n"
            "  请把里面的 DEEPSEEK_API_KEY=sk-xxxx... 换成你的真实 Key。\n"
        )
    else:
        hint = (
            "  1. 把 .env.example 复制一份，改名为 .env\n"
            "  2. 打开 .env，填入你的 Key\n"
        )

    raise RuntimeError(
        "\n未配置 DEEPSEEK_API_KEY，无法调用模型。\n"
        + hint
        + "  Key 申请地址：https://platform.deepseek.com/api_keys\n"
        "  说明：.env 已被 .gitignore 忽略，不会提交到 GitHub。\n"
    )
