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


# 占位符识别：用户可能把 Key 替换成各种提示文字，都要能认出来。
# 否则校验会「通过」，然后拿一个假 Key 去调 API，报出难以理解的鉴权错误。
PLACEHOLDER_MARKERS = ("xxx", "your", "placeholder", "你的", "填入", "改成", "abc123")


def _looks_like_placeholder(key: str) -> bool:
    k = key.lower()
    if any(m in k for m in PLACEHOLDER_MARKERS):
        return True
    # 真实 Key 形如 sk-<32 位 ASCII 字母数字>；过短或含非 ASCII 的都视为占位符
    body = k[3:] if k.startswith("sk-") else k
    return len(body) < 20 or not body.isascii()


def validate() -> None:
    """校验必需配置，缺失时给出可操作的提示。"""
    if DEEPSEEK_API_KEY and not _looks_like_placeholder(DEEPSEEK_API_KEY):
        return

    env_path = ROOT / ".env"
    if env_path.exists():
        hint = (
            f"  .env 已存在：{env_path}\n"
            "  请把里面的 DEEPSEEK_API_KEY 换成真实 Key（不要保留占位文字）。\n"
        )
    else:
        hint = (
            "  1. 把 .env.example 复制一份，改名为 .env\n"
            "  2. 打开 .env，填入你的 Key\n"
        )

    raise RuntimeError(
        "\n未配置有效的 DEEPSEEK_API_KEY，无法调用模型。\n"
        + hint
        + "  Key 申请地址：https://platform.deepseek.com/api_keys\n"
        "  说明：.env 已被 .gitignore 忽略，不会提交到 GitHub。\n"
    )
