# -*- coding: utf-8 -*-
"""入口：读取商品表 -> 批量生成俄语 Listing -> 导出 Excel。

用法：
    python main.py                              # 用默认样例数据
    python main.py data/input/我的商品.csv       # 指定输入文件
"""

import sys
import time
from pathlib import Path

import pandas as pd

import config
from listing_gen import generate_listing
from llm_client import usage_summary

INPUT_DEFAULT = config.INPUT_DIR / "products_sample.csv"


def load_products(path: Path) -> pd.DataFrame:
    """读取商品表，CSV 和 Excel 都支持。"""
    if not path.exists():
        raise FileNotFoundError(f"找不到输入文件：{path}")
    if path.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(path, dtype=str).fillna("")
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def main() -> int:
    # 先校验配置：配置错误要立刻失败，不能等进了循环才发现
    try:
        config.validate()
    except RuntimeError as exc:
        print(exc)
        return 2

    src = Path(sys.argv[1]) if len(sys.argv) > 1 else INPUT_DEFAULT
    print(f"输入文件：{src}")

    df = load_products(src)
    print(f"共 {len(df)} 个商品，开始生成俄语 Listing……\n")

    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    titles, bullets, descs, keywords, status = [], [], [], [], []
    t0 = time.time()

    for i, row in df.iterrows():
        name = row.get("product_name_cn") or f"第 {i + 1} 行"
        print(f"[{i + 1}/{len(df)}] {name}")
        try:
            r = generate_listing(row.to_dict())
            titles.append(r["title_ru"])
            bullets.append(" | ".join(r["bullets_ru"]))
            descs.append(r["description_ru"])
            keywords.append(", ".join(r["keywords_ru"]))
            status.append("ok")
            print(f"    -> {r['title_ru'][:70]}")
        except Exception as exc:  # noqa: BLE001 - 单个失败不应中断整批
            titles.append("")
            bullets.append("")
            descs.append("")
            keywords.append("")
            status.append(f"failed: {exc}")
            print(f"    !! 失败：{exc}")

    out = df.copy()
    out["title_ru"] = titles
    out["bullets_ru"] = bullets
    out["description_ru"] = descs
    out["keywords_ru"] = keywords
    out["status"] = status

    dst = config.OUTPUT_DIR / f"listings_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"
    out.to_excel(dst, index=False)

    ok = status.count("ok")
    u = usage_summary()
    print("\n" + "=" * 60)
    print(f"成功 {ok}/{len(df)}    耗时 {time.time() - t0:.1f}s")
    print(f"Token 用量：输入 {u['prompt_tokens']}，输出 {u['completion_tokens']}，调用 {u['calls']} 次")
    print(f"结果已导出：{dst}")

    return 0 if ok == len(df) else 1


if __name__ == "__main__":
    raise SystemExit(main())
