# -*- coding: utf-8 -*-
"""ozon-ai-ops 入口 —— 模块化命令行工具。

用法：
    python main.py listing  [csv路径] [--limit N]    模块 A：俄语 Listing 批量生成
    python main.py diagnose [csv路径] [--limit N]    模块 B：Ozon 商品 AI 诊断

不传路径则使用 data/input/ 下的默认样例。
--limit N 只处理前 N 条（适合低成本试跑）。
"""

import sys
import time
from pathlib import Path

import pandas as pd

import config
from listing_gen import generate_listing
from product_intel import diagnose_product, summarize, assign_priorities
from llm_client import usage_summary


# --------------------------------------------------------------------------
# 公共工具
# --------------------------------------------------------------------------

def parse_args(argv, default_input):
    """解析 `[csv路径] [--limit N]`。"""
    src = Path(default_input)
    limit = None
    rest = list(argv)

    if "--limit" in rest:
        i = rest.index("--limit")
        try:
            limit = int(rest[i + 1])
        except (IndexError, ValueError):
            raise SystemExit("--limit 后面要跟一个整数，例如 --limit 5")
        del rest[i:i + 2]

    if rest:
        src = Path(rest[0])
    return src, limit


def load_products(path: Path, limit=None) -> pd.DataFrame:
    """读取商品表，CSV 和 Excel 都支持。"""
    if not path.exists():
        raise SystemExit(f"找不到输入文件：{path}")

    if path.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(path, dtype=str).fillna("")
    else:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)

    if limit:
        df = df.head(limit).copy()
    return df


def join_list(v) -> str:
    return " | ".join(v) if isinstance(v, list) else str(v)


def report(ok: int, total: int, t0: float, dst: Path) -> int:
    u = usage_summary()
    print("\n" + "=" * 62)
    print(f"成功 {ok}/{total}    耗时 {time.time() - t0:.1f}s")
    print(f"Token 用量：输入 {u['prompt_tokens']}，输出 {u['completion_tokens']}，调用 {u['calls']} 次")
    print(f"结果已导出：{dst}")
    return 0 if ok == total else 1


# --------------------------------------------------------------------------
# 模块 A：俄语 Listing 生成
# --------------------------------------------------------------------------

def cmd_listing(argv) -> int:
    src, limit = parse_args(argv, config.INPUT_DIR / "products_sample.csv")
    print("[模块 A] 俄语 Listing 生成")
    print(f"输入文件：{src}")

    df = load_products(src, limit)
    print(f"共 {len(df)} 个商品，开始生成……\n")

    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    keys = ("title_ru", "bullets_ru", "description_ru", "keywords_ru", "status")
    cols = {k: [] for k in keys}
    t0 = time.time()

    for i, row in df.iterrows():
        name = row.get("product_name_cn") or f"第 {i + 1} 行"
        print(f"[{i + 1}/{len(df)}] {name}")
        try:
            r = generate_listing(row.to_dict())
            cols["title_ru"].append(r["title_ru"])
            cols["bullets_ru"].append(" | ".join(r["bullets_ru"]))
            cols["description_ru"].append(r["description_ru"])
            cols["keywords_ru"].append(", ".join(r["keywords_ru"]))
            cols["status"].append("ok")
            print(f"    -> {r['title_ru'][:68]}")
        except Exception as exc:  # noqa: BLE001 - 单条失败不应中断整批
            for k in ("title_ru", "bullets_ru", "description_ru", "keywords_ru"):
                cols[k].append("")
            cols["status"].append(f"failed: {exc}")
            print(f"    !! 失败：{exc}")

    out = df.copy()
    for k, v in cols.items():
        out[k] = v

    dst = config.OUTPUT_DIR / f"listings_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"
    out.to_excel(dst, index=False)
    return report(cols["status"].count("ok"), len(df), t0, dst)


# --------------------------------------------------------------------------
# 模块 B：商品 AI 诊断
# --------------------------------------------------------------------------

def cmd_diagnose(argv) -> int:
    src, limit = parse_args(argv, config.INPUT_DIR / "products_real_sample.csv")
    print("[模块 B] Ozon 商品 AI 诊断")
    print(f"输入文件：{src}")

    df = load_products(src, limit)
    print(f"共 {len(df)} 个商品，开始诊断……\n")

    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    keys = ("title_assessment", "title_optimized", "content_gaps",
            "price_diagnosis", "severity", "severity_reason", "priority",
            "next_actions", "status")
    cols = {k: [] for k in keys}
    t0 = time.time()
    done = []

    for i, row in df.iterrows():
        rec = row.to_dict()
        print(f"[{i + 1}/{len(df)}] {str(rec.get('title_ru', ''))[:52]}")
        try:
            r = diagnose_product(rec)
            cols["title_assessment"].append(r["title_assessment"])
            cols["title_optimized"].append(r["title_optimized"])
            cols["content_gaps"].append(join_list(r["content_gaps"]))
            cols["price_diagnosis"].append(r["price_diagnosis"])
            cols["severity"].append(r["severity"])
            cols["severity_reason"].append(r["severity_reason"])
            cols["priority"].append("")          # 分档在循环后统一计算
            cols["next_actions"].append(join_list(r["next_actions"]))
            cols["status"].append("ok")
            done.append({**rec, **r})
            print(f"    -> 严重度 {r['severity']}  {r['title_assessment'][:44]}")
        except Exception as exc:  # noqa: BLE001
            for k in ("title_assessment", "title_optimized", "content_gaps",
                      "price_diagnosis", "severity", "severity_reason",
                      "priority", "next_actions"):
                cols[k].append("")
            cols["status"].append(f"failed: {exc}")
            print(f"    !! 失败：{exc}")

    out = df.copy()
    for k, v in cols.items():
        out[k] = v

    # 分档依赖整批的严重度分布，必须等循环结束后统一计算
    assign_priorities(done)
    prio = iter(r["priority"] for r in done)
    cols["priority"] = [next(prio) if s == "ok" else "" for s in cols["status"]]
    out["priority"] = cols["priority"]

    dst = config.OUTPUT_DIR / f"diagnosis_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"
    with pd.ExcelWriter(dst, engine="openpyxl") as w:
        out.to_excel(w, sheet_name="诊断结果", index=False)
        s = summarize(done)
        if s:
            pd.DataFrame(list(s.items()), columns=["指标", "数值"]).to_excel(
                w, sheet_name="汇总", index=False)

    if done:
        s = summarize(done)
        print(f"\n汇总：P0 {s['P0']} 个 | P1 {s['P1']} 个 | P2 {s['P2']} 个")
        print(f"      严重度 中位数 {s['严重度中位数']} / 最高 {s['严重度最高']} / 最低 {s['严重度最低']}")
        print(f"      内容分<70 共 {s['内容分低于70']} 个 | 价格指数不利 {s['价格指数不利']} 个")

    return report(cols["status"].count("ok"), len(df), t0, dst)


# --------------------------------------------------------------------------

COMMANDS = {"listing": cmd_listing, "diagnose": cmd_diagnose}


def main() -> int:
    argv = sys.argv[1:]

    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 2

    # 配置错误要立刻失败，不能等进了循环才发现
    try:
        config.validate()
    except RuntimeError as exc:
        print(exc)
        return 2

    cmd, rest = argv[0], argv[1:]
    if cmd not in COMMANDS:
        print(f"未知命令：{cmd}\n")
        print(__doc__)
        return 2
    return COMMANDS[cmd](rest)


if __name__ == "__main__":
    raise SystemExit(main())
