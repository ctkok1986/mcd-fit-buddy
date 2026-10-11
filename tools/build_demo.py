#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 data/nutrition.csv 内联进可视化页面，生成 demo.html。

单一数据源：营养数据一律取自 data/nutrition.csv（官方 MCP 快照），
不手工抄写，避免页面数字与引擎数字不一致。

用法：
    python tools/build_demo.py
"""

import csv
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CSV_PATH = os.path.join(ROOT, "data", "nutrition.csv")
COMMON_PATH = os.path.join(ROOT, "data", "common-foods.csv")
TPL_PATH = os.path.join(ROOT, "demo.template.html")
OUT_PATH = os.path.join(ROOT, "demo.html")


def load_rows():
    """读取营养表，返回 [name, kcal, protein, fat, carb, sodium] 列表。"""
    rows = []
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                rows.append([
                    row["name"].strip(),
                    round(float(row["kcal"]), 1),
                    round(float(row["protein_g"]), 1),
                    round(float(row["fat_g"]), 1),
                    round(float(row["carb_g"]), 1),
                    round(float(row["sodium_mg"]), 1),
                ])
            except (ValueError, KeyError, AttributeError):
                continue
    return rows


def load_common():
    """读取常见食物表（非麦当劳餐品），用于"描述自动估算营养"。"""
    rows = []
    with open(COMMON_PATH, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                keys = [k.strip() for k in row["keys"].split("|") if k.strip()]
                if row["name"].strip() not in keys:
                    keys.insert(0, row["name"].strip())
                rows.append({
                    "name": row["name"].strip(),
                    "keys": keys,
                    "kcal": round(float(row["kcal"]), 1),
                    "protein": round(float(row["protein_g"]), 1),
                    "fat": round(float(row["fat_g"]), 1),
                    "carb": round(float(row["carb_g"]), 1),
                    "sodium": round(float(row["sodium_mg"]), 1),
                    "portion": row["portion"].strip(),
                })
            except (ValueError, KeyError, AttributeError):
                continue
    return rows


def render_data(rows):
    """紧凑 JS 数组字面量：[名称, 热量, 蛋白, 脂肪, 碳水, 钠]。"""
    lines = []
    for r in rows:
        nums = ",".join(repr(x) for x in r[1:])
        lines.append(f"[{json.dumps(r[0], ensure_ascii=False)},{nums}]")
    return "[\n" + ",\n".join(lines) + "\n]"


def render_common(rows):
    """常见食物 → JS 对象数组（含别名与份量说明）。"""
    out = []
    for r in rows:
        keys = ",".join(json.dumps(k, ensure_ascii=False) for k in r["keys"])
        out.append(
            "{" + f"name:{json.dumps(r['name'], ensure_ascii=False)}"
            + f",keys:[{keys}]"
            + f",kcal:{r['kcal']!r},protein:{r['protein']!r}"
            + f",fat:{r['fat']!r},carb:{r['carb']!r},sodium:{r['sodium']!r}"
            + f",portion:{json.dumps(r['portion'], ensure_ascii=False)}" + "}")
    return "[\n" + ",\n".join(out) + "\n]"


def main():
    rows = load_rows()
    common = load_common()
    tpl = open(TPL_PATH, encoding="utf-8").read()
    for token in ("__NUTRITION_DATA__", "__ITEM_COUNT__", "__COMMON_FOODS__"):
        if token not in tpl:
            raise SystemExit(f"模板缺少占位符 {token}")
    html = (tpl
            .replace("__NUTRITION_DATA__", render_data(rows))
            .replace("__COMMON_FOODS__", render_common(common))
            .replace("__ITEM_COUNT__", str(len(rows))))
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"已生成 {os.path.relpath(OUT_PATH, ROOT)}")
    print(f"  麦当劳营养数据 {len(rows)} 项")
    print(f"  常见食物数据   {len(common)} 项")
    print(f"  文件大小 {len(html):,} 字节")


if __name__ == "__main__":
    main()
