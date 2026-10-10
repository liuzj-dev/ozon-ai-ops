# -*- coding: utf-8 -*-
"""模块 B：Ozon 商品 AI 诊断。

输入：商品明细（俄语标题、售价、平台内容分、价格指数等）
输出：标题诊断 + 优化后标题 + 内容补齐清单 + 定价建议 + 优先级 + 执行动作
"""

from llm_client import chat_json

SYSTEM_PROMPT = """你是一位资深的 Ozon 平台运营专家，精通俄语商品标题优化、Ozon 内容评分规则与定价策略。
你的任务是对商品卡做诊断，给出具体、可直接执行的优化建议。
你只输出 JSON，不输出任何多余说明。"""

USER_TEMPLATE = """请诊断以下 Ozon 商品。

【商品数据】
- 俄语标题：{title}
- 售价：{price} 元人民币
- 平台内容分：{content_score}（等级：{content_grade}）
- 平台价格指数：{price_index}
- 促销状态：{promo}
- 条码状态：{barcode}
- 上架时间：{created}

【背景】
- Ozon 内容分满分 100，反映商品卡完整度（描述、特征、图片、视频等），低于 70 通常流量受限
- 价格指数「不利」表示定价高于同类竞品，会降低曝光与转化
- 目标市场为俄罗斯，标题需符合俄语表达习惯与当地搜索习惯，不能是中文直译
- 条码「待添加」会影响商品合规与入仓

【输出要求】
1. title_assessment：诊断俄语标题的问题（表达是否地道、搜索词覆盖、是否符合平台规范），80 字以内
2. title_optimized：优化后的俄语标题，只输出标题本身，不超过 200 字符
3. content_gaps：需要补齐的内容清单，3-5 条，每条具体可执行（不要写「补充描述」这种空话）
4. price_diagnosis：结合价格指数给出的定价诊断与建议方向，60 字以内
5. severity：问题严重度，0-100 的整数。评分锚点：
   - 90-100：标题含中文/乱码/明显录入错误，或条码缺失导致无法入仓，或商品不可售
   - 70-89：内容分低于 40，或标题严重偏离俄语表达习惯
   - 50-69：内容分 40-70，标题可优化但基本可读
   - 30-49：内容基本完整，仅细节可优化
   - 0-29：几乎无需处理
6. severity_reason：给出该分值的理由，40 字以内
7. next_actions：最优先执行的 2-3 个动作

注意：severity 必须拉开区分度，不要大部分商品都给高分。
只输出 JSON 对象，字段名严格遵守：
{{"title_assessment": "...", "title_optimized": "...", "content_gaps": ["..."], "price_diagnosis": "...", "severity": 75, "severity_reason": "...", "next_actions": ["..."]}}
"""

# 分档比例：LLM 的绝对分值会被压缩在窄区间（实测 45-75），固定阈值无法稳定分档，
# 因此改用「批次内相对排名」。阈值在这里是比例，可调且无需重跑模型。
P0_RATIO = 0.15   # 严重度最高的 15% 判为 P0
P1_RATIO = 0.60   # 接下来到 60% 判为 P1，其余为 P2
MIN_BATCH_FOR_P0 = 7   # 样本太少时不做相对分档，避免「3 条里也要挑出 P0」


def assign_priorities(rows: list) -> list:
    """按批次内严重度排名分档（原地修改并返回）。

    相对排名的好处：不受模型打分尺度漂移影响，且直接回答
    「这批商品里我该先修哪几个」——这正是店铺运营真正需要的问题。
    """
    if not rows:
        return rows

    ordered = sorted(rows, key=lambda r: -r["severity"])
    n = len(ordered)

    if n < MIN_BATCH_FOR_P0:
        for r in ordered:
            r["priority"] = "P1"
        return rows

    n_p0 = max(1, round(n * P0_RATIO))
    n_p1 = max(n_p0 + 1, round(n * P1_RATIO))

    for i, r in enumerate(ordered):
        r["priority"] = "P0" if i < n_p0 else ("P1" if i < n_p1 else "P2")
    return rows


PRIORITIES = ("P0", "P1", "P2")


def build_prompt(row: dict) -> str:
    """把一行商品数据渲染成诊断提示词。"""
    return USER_TEMPLATE.format(
        title=row.get("title_ru", ""),
        price=row.get("price_cny", ""),
        content_score=row.get("content_score", ""),
        content_grade=row.get("content_grade", ""),
        price_index=row.get("price_index", ""),
        promo=row.get("promo", "") or "无",
        barcode=row.get("barcode_status", "") or "无",
        created=row.get("created_at", "") or "未知",
    )


def diagnose_product(row: dict) -> dict:
    """诊断单个商品，并归一化输出字段。"""
    data = chat_json(SYSTEM_PROMPT, build_prompt(row))

    # 严重度由模型给分，分档由本地代码决定（阈值可调，无需重跑模型）
    try:
        severity = max(0, min(100, int(round(float(data.get("severity", 50))))))
    except (TypeError, ValueError):
        severity = 50

    def as_list(key):
        v = data.get(key) or []
        if isinstance(v, str):
            v = [v]
        return [str(x).strip() for x in v]

    return {
        "title_assessment": str(data.get("title_assessment", "")).strip(),
        "title_optimized": str(data.get("title_optimized", "")).strip(),
        "content_gaps": as_list("content_gaps"),
        "price_diagnosis": str(data.get("price_diagnosis", "")).strip(),
        "severity": severity,
        "severity_reason": str(data.get("severity_reason", "")).strip(),
        # priority 由 assign_priorities() 在整批完成后统一赋值
        "next_actions": as_list("next_actions"),
    }


def summarize(rows: list) -> dict:
    """对诊断结果做本地聚合（不消耗 token）。"""
    total = len(rows)
    if total == 0:
        return {}
    by_priority = {p: sum(1 for r in rows if r["priority"] == p) for p in PRIORITIES}
    sev = sorted(r["severity"] for r in rows)
    low_content = sum(1 for r in rows if _to_float(r.get("content_score")) < 70)
    bad_price = sum(1 for r in rows if r.get("price_index") == "不利")
    return {
        "总数": total,
        "P0": by_priority["P0"],
        "P1": by_priority["P1"],
        "P2": by_priority["P2"],
        "内容分低于70": low_content,
        "价格指数不利": bad_price,
        "严重度中位数": sev[len(sev) // 2],
        "严重度最高": sev[-1],
        "严重度最低": sev[0],
    }


def _to_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0
