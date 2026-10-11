#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""nutrition_lookup.py 回归测试。

重点不是「查得到」，而是**查不到时必须明确报错** ——
这条是本项目的铁律：营养数据缺失要说「查不到」，不得估算、不得用相近商品替代。
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import nutrition_lookup as nl  # noqa: E402

SCRIPT = os.path.join(ROOT, "scripts", "nutrition_lookup.py")
passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {msg}")
    else:
        failed += 1
        print(f"  FAIL  {msg}")


def run_cli(*argv):
    return subprocess.run([sys.executable, SCRIPT, *argv],
                          capture_output=True, text=True, encoding="utf-8")


print("=" * 64)
print("一、营养表加载")
print("=" * 64)
items = nl.load_items()
check(len(items) == 158, f"载入 158 项（实得 {len(items)}）")
check(all(it["name"] for it in items), "每项都有名称")
check(all(it["kcal"] >= 0 for it in items), "热量全部非负")
# 0 kcal 是合法的（无糖可乐、纯水），但要钉死是哪几项 ——
# 否则以后数据出错（比如某个汉堡变成 0）也不会被发现。
ZERO_KCAL_OK = {
    "无糖可口可乐中杯", "无糖可口可乐大杯", "无糖可口可乐小杯", "纯悦",
}
zero = {it["name"] for it in items if it["kcal"] == 0}
check(zero == ZERO_KCAL_OK,
      f"0 kcal 项恰为无糖可乐/纯水（实得 {sorted(zero)}）")
blank_names = [it["name"] for it in items if it["name"] != it["name"].strip()]
check(not blank_names, f"无首尾空格残留（BOM 已由 utf-8-sig 处理）：{blank_names[:3]}")

BY = {it["name"]: it for it in items}

print()
print("=" * 64)
print("二、精确命中")
print("=" * 64)
bs = BY.get("板烧鸡腿堡")
check(bs is not None, "板烧鸡腿堡在表内")
if bs:
    check(bs["kcal"] == 391 and bs["protein"] == 23 and bs["sodium"] == 1041,
          f"板烧鸡腿堡 391/23/1041（实得 {bs['kcal']:.0f}/{bs['protein']:.0f}/{bs['sodium']:.0f}）")

ic = BY.get("冰美式中杯")
check(ic is not None and ic["kcal"] == 13 and ic["protein"] == 1,
      f"冰美式中杯 13 kcal / 蛋白 1g（实得 {ic['kcal']:.0f}/{ic['protein']:.0f}）")

r = run_cli("板烧鸡腿堡")
check(r.returncode == 0, f"CLI 精确命中退出码 0（实得 {r.returncode}）")
check("391" in r.stdout and "命中" in r.stdout, "CLI 输出含数值与命中标记")
# 钠 1041 > 2000 的 50%，但 < 上限 → 不应出现超限提示
check("超过每日参考上限" not in r.stdout, "钠 1041mg 未触发超限提示（未超 2000mg）")

r2 = run_cli("巨无霸")
check(r2.returncode == 0, "CLI 巨无霸命中")
em = BY.get("巨无霸")
check(em is not None and f"{em['sodium']:.0f}" in r2.stdout, "CLI 输出含巨无霸钠值")

print()
print("=" * 64)
print("三、部分匹配")
print("=" * 64)
r3 = run_cli("冰奶铁")
check(r3.returncode == 0, "部分匹配退出码仍为 0")
check("冰奶铁中杯" in r3.stdout and "冰奶铁小杯" in r3.stdout and "冰奶铁大杯" in r3.stdout,
      "「冰奶铁」列出小/中/大三杯")
check("热奶铁中杯" not in r3.stdout, "「冰奶铁」不混入「热奶铁」（子串匹配正确）")

r4 = run_cli("奶铁")
cnt = r4.stdout.count(" kcal｜")
check(cnt == 12, f"「奶铁」命中 12 项（4 组 × 3 杯型，实得 {cnt}）")

print()
print("=" * 64)
print("四、查不到 —— 必须明确报错，且禁止替代（本文件的核心）")
print("=" * 64)
MISSING = "枫糖风味厚松饼猪柳蛋堡"
check(MISSING not in BY, f"『{MISSING}』确实不在表中（前置条件）")

r5 = run_cli(MISSING)
check(r5.returncode == 2, f"查不到时退出码为 2（实得 {r5.returncode}）")
check("查不到" in r5.stdout, "输出明确写「查不到」")
check("不得估算" in r5.stdout or "不得用相近商品替代" in r5.stdout,
      "输出含「不得估算 / 不得用相近商品替代」的禁止条款")
check("不得直接当作替代品" in r5.stdout,
      "相近名称区块标注「不得直接当作替代品」（防止被当成替代建议）")

# 相近项只应是「相似但不同」的商品，不能把查询词本身当结果
near = nl.similar(items, MISSING)
check(len(near) > 0, f"确实给出相近名称供参考（{len(near)} 项：{[n['name'] for n in near]}）")
check(all(n["name"] != MISSING for n in near), "相近项里不含查询词本身")

# 其他常见缺失词
for word in ("厚松饼", "枫糖风味"):
    rr = run_cli(word)
    check(rr.returncode == 2, f"『{word}』判定为查不到（退出码 {rr.returncode}）")

print()
print("=" * 64)
print("五、参数与边界")
print("=" * 64)
r6 = run_cli()
check(r6.returncode == 1, f"不带参数 → 退出码 1（实得 {r6.returncode}）")
check("请提供餐品名称" in r6.stdout, "提示如何提供参数")

r7 = run_cli("   ")
check(r7.returncode == 1, "纯空格参数 → 退出码 1")

r8 = run_cli("--list")
check(r8.returncode == 0, "--list 退出码 0")
check(f"共 {len(items)} 项" in r8.stdout, f"--list 报告总项数 {len(items)}")
check(len([ln for ln in r8.stdout.splitlines() if ln.startswith("  ")]) == len(items),
      "--list 逐项列出全部餐品")

# 相似度函数的退化输入不应崩
check(nl.similar(items, "") == [], "空查询不返回相近项（不崩）")
check(nl.similar(items, "板烧鸡腿堡") != [], "单字/正常查询仍能给出相近项")

print()
print("=" * 64)
print(f"结果：{passed} passed, {failed} failed")
print("=" * 64)
sys.exit(0 if failed == 0 else 1)
