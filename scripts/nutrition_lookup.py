#!/usr/bin/env python3
"""营养数据查询 —— 查得到就给数，查不到就明说「查不到」。

设计意图（v2.3.2）：
    官方营养表只有 158 项，**并不覆盖全部在售商品**
    （实测：外送菜单有「枫糖风味厚松饼猪柳蛋堡」，但营养表里没有「厚松饼」系列）。
    模型遇到这种缺失时，很容易「就近找一个相似的填上」——那就成了编数据。
    所以这里把「查不到」做成一个**有退出码的确定性结果**，
    让调用方没法含糊过去。

用法：
    python scripts/nutrition_lookup.py 板烧鸡腿堡
    python scripts/nutrition_lookup.py 枫糖风味厚松饼猪柳蛋堡
    python scripts/nutrition_lookup.py 冰奶铁            # 部分匹配，列出全部

退出码：
    0 = 命中（精确 / 部分）
    2 = 查不到（调用方必须据此如实告知用户，不得估算或替代）
    1 = 参数错误
"""
import argparse
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(HERE, os.pardir, "data", "nutrition.csv")

# 与界面上展示的口径一致：官方上限按 WHO 建议
SODIUM_REF = 2000


def load_items(path=DATA_PATH):
    """读取营养表（注意 utf-8-sig：源文件带 BOM，用 utf-8 会导致首列名变成 \\ufeffname）。"""
    items = []
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                items.append({
                    "name": row["name"].strip(),
                    "kcal": float(row["kcal"]),
                    "protein": float(row["protein_g"]),
                    "fat": float(row["fat_g"]),
                    "carb": float(row["carb_g"]),
                    "sodium": float(row["sodium_mg"]),
                    "calcium": float(row["calcium_mg"]),
                })
            except (ValueError, KeyError):
                continue
    return items


def _bigrams(text):
    s = "".join(ch for ch in str(text) if not ch.isspace())
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def similar(items, query, top=3):
    """按字符二元组 Jaccard 相似度找「相近名称」。

    ⚠️ 仅用于让用户知道「表里有哪些东西」，**不是替代建议**。
    """
    q = _bigrams(query)
    if not q:
        return []
    scored = []
    for it in items:
        g = _bigrams(it["name"])
        if not g:
            continue
        inter = len(q & g)
        if inter == 0:
            continue
        scored.append((inter / len(q | g), it))
    scored.sort(key=lambda x: (-x[0], x[1]["name"]))
    return [it for _, it in scored[:top]]


def fmt_line(it):
    return (f"  {it['name']}  {it['kcal']:.0f} kcal｜蛋白 {it['protein']:.0f}g"
            f"｜脂肪 {it['fat']:.0f}g｜碳水 {it['carb']:.0f}g"
            f"｜钠 {it['sodium']:.0f}mg")


def main():
    p = argparse.ArgumentParser(description="麦当劳营养数据查询（查不到会明确报错）")
    p.add_argument("name", nargs="?", help="餐品名称，如 板烧鸡腿堡")
    p.add_argument("--list", action="store_true", help="列出表中全部餐品名")
    args = p.parse_args()

    items = load_items()

    if args.list:
        print(f"官方营养表共 {len(items)} 项：")
        for it in items:
            print("  " + it["name"])
        return 0

    query = (args.name or "").strip()
    if not query:
        print("❌ 请提供餐品名称，例如：nutrition_lookup.py 板烧鸡腿堡")
        return 1

    # 1) 精确命中
    exact = [it for it in items if it["name"] == query]
    if exact:
        print(f"✅ 命中（精确匹配）")
        for it in exact:
            print(fmt_line(it))
            if it["sodium"] > SODIUM_REF:
                print(f"     ⚠️ 钠 {it['sodium']:.0f}mg，超过每日参考上限 {SODIUM_REF}mg 的 "
                      f"{it['sodium'] / SODIUM_REF * 100:.0f}%")
        return 0

    # 2) 部分命中
    partial = [it for it in items if query in it["name"]]
    if partial:
        print(f"✅ 命中（部分匹配「{query}」共 {len(partial)} 项）")
        for it in partial:
            print(fmt_line(it))
        return 0

    # 3) 查不到 —— 如实说，并明确禁止替代
    print(f"❌ 查不到：『{query}』不在官方营养表（{len(items)} 项）内")
    print()
    print("   本项目铁律：**不得估算、不得用相近商品替代**。")
    print("   请如实告知用户「该商品没有营养数据」，并可请他提供包装标注。")
    near = similar(items, query)
    if near:
        print()
        print("   表中名称相近的项（仅供你了解表里有什么，**不得直接当作替代品**）：")
        for it in near:
            print(fmt_line(it))
    return 2


if __name__ == "__main__":
    sys.exit(main())
