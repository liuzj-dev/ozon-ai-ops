# -*- coding: utf-8 -*-
"""LLM 调用封装：统一处理重试、超时和 token 统计。"""

import json
import time

from openai import OpenAI

import config

_client = None

# 累计 token 用量，用于成本核算
_usage = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}


def get_client() -> OpenAI:
    """惰性创建客户端，避免导入时就要求配置齐全。"""
    global _client
    if _client is None:
        config.validate()
        _client = OpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL,
            timeout=60.0,
        )
    return _client


def chat_json(system: str, user: str, temperature: float = 0.7,
              max_retries: int = 3) -> dict:
    """调用 LLM 并返回解析后的 JSON 对象，失败自动指数退避重试。

    注意：客户端在重试循环之外创建。这样「缺少 API Key」这类配置错误会立刻
    抛出，而不会被当成网络抖动白白重试三次。
    """
    client = get_client()
    last_err = None

    for attempt in range(1, max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model=config.DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                response_format={"type": "json_object"},
            )

            usage = getattr(resp, "usage", None)
            if usage:
                _usage["prompt_tokens"] += usage.prompt_tokens
                _usage["completion_tokens"] += usage.completion_tokens
            _usage["calls"] += 1

            return json.loads(resp.choices[0].message.content)

        except Exception as exc:  # noqa: BLE001 - 需要吞掉各类网络/解析异常后重试
            last_err = exc
            if attempt < max_retries:
                wait = 2 ** attempt
                print(f"    [重试 {attempt}/{max_retries - 1}] {exc}，{wait}s 后重试")
                time.sleep(wait)

    raise RuntimeError(f"LLM 调用失败（已重试 {max_retries} 次）：{last_err}")


def usage_summary() -> dict:
    """返回累计 token 用量。"""
    return dict(_usage)
