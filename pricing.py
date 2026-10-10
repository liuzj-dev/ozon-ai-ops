# -*- coding: utf-8 -*-
"""模块 C：Ozon 定价与利润核算引擎。

业务逻辑提取自作者自研的「Ozon 上品定价核算工具」v1→v7（单文件网页工具），
重构为可批量调用的 Python 引擎。

相比原网页版的三点改进：
1. 费率表外置为 data/rates.json —— 物流商调价时改配置即可，不必改代码
2. 取消全局状态，物流商 / 配送方式作为显式参数传入，可并发、可测试
3. 反推定价增加收敛检测 —— 目标利润率不可达时明确报错，而不是静默返回错误价格
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RATES_PATH = ROOT / "data" / "rates.json"

DEFAULT_FX_RATE = 0.0917          # 1 卢布 = 0.0917 人民币
DEFAULT_WITHDRAWAL_RATE = 0.012   # 提现手续费 1.2%
POST = "POST"                     # 邮政陆运
MIN_RUB_PRICE = 500               # 建议最低售价（卢布）
HIGH_COMMISSION = 0.20            # 高佣金品类阈值

CARRIER_NAMES = {"CEL": "CEL", "GUOO": "GUOO", "OYX_XY": "OYX/星远", "POST": "邮政陆运"}
DELIVERIES = ("Economy", "Standard", "Express")


@dataclass
class PricingInput:
    """一次核价所需的全部输入。"""
    cost_cny: float                        # 采购成本（元）
    weight_g: float                        # 商品重量（克）
    commission_rate: float                 # 平台佣金率，小数（0.15 表示 15%）
    logistics: str = "CEL"                 # 物流商
    delivery: str = "Economy"              # 配送方式
    misc_fee: float = 0.0                  # 杂费（元）
    return_rate: float = 0.0               # 退货率，小数
    withdrawal_rate: float = DEFAULT_WITHDRAWAL_RATE
    fx_rate: float = DEFAULT_FX_RATE


@dataclass
class PricingResult:
    price_cny: float = 0.0
    price_rub: float = 0.0
    cost: float = 0.0
    logistics: float = 0.0
    commission: float = 0.0
    agent: float = 0.0
    misc: float = 0.0
    withdrawal: float = 0.0
    return_fee: float = 0.0
    settlement: float = 0.0
    net_profit: float = 0.0
    profit_rate: float = 0.0       # 售价利润率 %
    cost_rate: float = 0.0         # 成本利润率 %
    warnings: list = field(default_factory=list)


_rates_cache = None


def load_rates(path=None) -> dict:
    """加载费率表（带缓存）。"""
    global _rates_cache
    if _rates_cache is None:
        p = Path(path) if path else RATES_PATH
        if not p.exists():
            raise SystemExit(f"找不到费率表：{p}")
        _rates_cache = json.loads(p.read_text(encoding="utf-8"))
    return _rates_cache


def find_rate(logistics: str, delivery: str, weight_g: float, value_cny: float):
    """按「货值区间 + 重量区间」查费率档位。

    匹配顺序：双条件精确匹配 → 仅按重量匹配 → 最后一档兜底。
    """
    if logistics == POST:
        return None

    rates = load_rates()
    tiers = rates.get(logistics, {}).get(delivery)
    if not tiers:
        raise SystemExit(f"费率表里没有 {logistics} / {delivery} 这一档")

    for t in tiers:
        if t["minG"] <= weight_g <= t["maxG"] and t["minVal"] <= value_cny <= t["maxVal"]:
            return t
    for t in tiers:
        if t["minG"] <= weight_g <= t["maxG"]:
            return t
    return tiers[-1]


def calc_logistics_cost(inp: PricingInput, price_cny: float) -> float:
    """物流费（元）。邮政陆运按「基础 + 重量 + 售价 5%」计费。"""
    if inp.logistics == POST:
        return 1.9 + 0.026 * inp.weight_g + price_cny * 0.05

    rate = find_rate(inp.logistics, inp.delivery, inp.weight_g, price_cny)
    return rate["base"] + rate["per_g"] * inp.weight_g


def calc_agent_commission(price_rub: float) -> float:
    """代理佣金（卢布）。"""
    return 15.0 if price_rub <= 750 else min(price_rub * 0.02, 200.0)


def calc_net_profit(inp: PricingInput, price_cny: float) -> PricingResult:
    """给定人民币售价，算出完整利润拆解。"""
    r = PricingResult(price_cny=price_cny, cost=inp.cost_cny)

    r.price_rub = price_cny / inp.fx_rate if inp.fx_rate else 0.0
    agent_rub = calc_agent_commission(r.price_rub)
    r.agent = agent_rub * inp.fx_rate
    r.logistics = calc_logistics_cost(inp, price_cny)
    r.commission = price_cny * inp.commission_rate
    r.misc = inp.misc_fee

    # 提现基数：邮政陆运的运费不参与计算（运费已在售价外单独结算）
    if inp.logistics == POST:
        wd_base = max(0.0, price_cny - r.commission - r.agent - inp.misc_fee)
    else:
        wd_base = max(0.0, price_cny - r.logistics - r.commission - r.agent - inp.misc_fee)
    r.withdrawal = wd_base * inp.withdrawal_rate

    r.return_fee = price_cny * inp.return_rate if inp.return_rate > 0 else 0.0

    r.settlement = (price_cny - r.commission - r.logistics - r.agent
                    - inp.misc_fee - r.withdrawal - r.return_fee)
    r.net_profit = r.settlement - inp.cost_cny
    r.profit_rate = r.net_profit / price_cny * 100 if price_cny > 0 else 0.0
    r.cost_rate = r.net_profit / inp.cost_cny * 100 if inp.cost_cny > 0 else 0.0

    r.warnings = _build_warnings(inp, r)
    return r


def _build_warnings(inp: PricingInput, r: PricingResult) -> list:
    """业务告警，规则沿用原工具并在无解/异常时补充提示。"""
    w = []
    if r.net_profit < 0:
        w.append(f"当前定价亏损 ¥{abs(r.net_profit):.2f}，建议提高售价")
    if 0 < r.price_rub < MIN_RUB_PRICE:
        w.append(f"建议售价不低于 ₽{MIN_RUB_PRICE}（约 ¥{MIN_RUB_PRICE * inp.fx_rate:.2f}）")
    if inp.commission_rate >= HIGH_COMMISSION:
        w.append(f"高佣金品类（{inp.commission_rate:.0%}），注意利润空间")
    if inp.logistics == POST:
        w.append("邮政陆运含售价 5%，售价越高运费越贵")
    return w


def solve_price_for_margin(inp: PricingInput, target_margin: float,
                           tol: float = 1e-6, max_iter: int = 200):
    """反推：求满足目标售价利润率的定价。

    返回 (售价元, 是否收敛)。目标不可达时 solved=False —— 这是相对原网页版的改进，
    原版固定迭代 80 次后无论是否收敛都直接返回，可能给出误导性价格。
    """
    if inp.cost_cny <= 0:
        raise ValueError("采购成本必须大于 0")
    if target_margin <= 0:
        raise ValueError("目标利润率必须大于 0")

    lo = inp.cost_cny * 1.05
    hi = max(inp.cost_cny * 10, 1000.0)

    # 先把上界扩张到能覆盖目标利润率
    for _ in range(20):
        r = calc_net_profit(inp, hi)
        if hi > 0 and r.net_profit / hi >= target_margin:
            break
        hi *= 2
    else:
        return hi, False        # 上界扩到极限仍达不到，判定无解

    price = (lo + hi) / 2
    for _ in range(max_iter):
        r = calc_net_profit(inp, price)
        rate = r.net_profit / price if price > 0 else 0.0
        if abs(rate - target_margin) < tol:
            return price, True
        if rate < target_margin:
            lo = price
        else:
            hi = price
        price = (lo + hi) / 2

    r = calc_net_profit(inp, price)
    rate = r.net_profit / price if price > 0 else 0.0
    return price, abs(rate - target_margin) < 1e-4
