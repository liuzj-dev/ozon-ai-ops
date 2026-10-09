# -*- coding: utf-8 -*-
"""模块 A：Ozon 俄语 Listing 批量生成。

输入：中文商品信息（名称、类目、参数、目标价）
输出：俄语标题 / 卖点 / 描述 / 搜索关键词
"""

from llm_client import chat_json

SYSTEM_PROMPT = """你是一位资深的俄罗斯电商（Ozon）运营专家，精通俄语商品文案与 Ozon 平台 SEO 规则。
你的任务是把中文商品信息，转化为符合 Ozon 规范、能提升点击率与转化率的俄语文案。
你只输出 JSON，不输出任何多余说明。"""

USER_TEMPLATE = """请为以下商品生成 Ozon 平台上架文案。

【商品信息】
- 中文名称：{name}
- 类目：{category}
- 关键参数：{specs}
- 目标售价：{price} 卢布
- 补充说明：{notes}

【输出要求】
1. title_ru：俄语标题，不超过 200 字符，含核心搜索词，自然可读，不要关键词堆砌
2. bullets_ru：3-5 条俄语卖点，每条不超过 120 字符，突出使用场景与用户收益
3. description_ru：俄语详细描述，150-400 字符，分段清晰
4. keywords_ru：5-8 个俄语搜索关键词

【硬性要求】
- 全文使用俄语，绝不能出现中文
- 面向俄罗斯消费者，表达要本土化，不要逐字直译
- 只输出 JSON 对象，不要 markdown 代码块，不要任何解释

输出格式（严格遵守字段名）：
{{"title_ru": "...", "bullets_ru": ["...", "..."], "description_ru": "...", "keywords_ru": ["...", "..."]}}
"""


def build_prompt(row: dict) -> str:
    """把一行商品数据渲染成提示词。"""
    return USER_TEMPLATE.format(
        name=row.get("product_name_cn", ""),
        category=row.get("category", ""),
        specs=row.get("key_specs", ""),
        price=row.get("target_price_rub", ""),
        notes=row.get("notes") or "无",
    )


def generate_listing(row: dict) -> dict:
    """为单个商品生成俄语 listing，并归一化字段。"""
    data = chat_json(SYSTEM_PROMPT, build_prompt(row))

    bullets = data.get("bullets_ru") or []
    keywords = data.get("keywords_ru") or []

    return {
        "title_ru": str(data.get("title_ru", "")).strip(),
        "bullets_ru": [str(b).strip() for b in bullets],
        "description_ru": str(data.get("description_ru", "")).strip(),
        "keywords_ru": [str(k).strip() for k in keywords],
    }
