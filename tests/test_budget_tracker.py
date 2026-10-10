#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦麦减脂搭子 · 剩余额度与实测 BMR 回归测试

覆盖：实测 BMR 覆盖、输入合理性校验、剩余额度计算、推荐逻辑、边界场景。
运行：python tests/test_budget_tracker.py
"""

import os
import subprocess
import sys

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SCRIPTS = os.path.join(BASE, "scripts")
sys.path.insert(0, SCRIPTS)

import meal_planner as mp          # noqa: E402
import budget_tracker as bt        # noqa: E402

PASS, FAIL = 0, 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {msg}")
    else:
        FAIL += 1
        print(f"  [FAIL] {msg}")


class Args:
    def __init__(self, **kw):
        self.weight = kw.get("weight", 78)
        self.height = kw.get("height", 175)
        self.age = kw.get("age", 40)
        self.sex = kw.get("sex", "male")
        self.activity = kw.get("activity", "light")
        self.target_weight = kw.get("target_weight", 72)
        self.weeks = kw.get("weeks", 12)
        self.bmr = kw.get("bmr", None)


def run(script, *a):
    return subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, script), *a],
        capture_output=True, text=True, encoding="utf-8")


print("=" * 62)
print("1. 实测 BMR 覆盖公式估算")
print("=" * 62)
t_formula = mp.build_target(Args())
t_measured = mp.build_target(Args(bmr=1750))

check(abs(t_formula["bmr"] - 1678.75) < 0.01, "无 --bmr 时用 Mifflin-St Jeor 公式")
check(t_formula["bmr_source"] == "Mifflin-St Jeor 公式估算", "来源标注为公式估算")
check(abs(t_measured["bmr"] - 1750) < 0.01, "提供 --bmr 时采用实测值")
check(t_measured["bmr_source"] == "用户实测", "来源标注为用户实测")
check(abs(t_measured["tdee"] - 1750 * 1.375) < 0.01, "实测 BMR 参与 TDEE 计算")
check(t_measured["tdee"] > t_formula["tdee"], "实测 BMR 更高 → TDEE 更高")
check(t_measured["daily_kcal"] > t_formula["daily_kcal"],
      "实测 BMR 更高 → 每日摄入目标更高")
# 护栏 B 应基于实测 BMR
check(t_measured["daily_kcal"] >= 1750 * 1.1 - 1e-6,
      "护栏 B 基于实测 BMR（摄入 ≥ 实测BMR×1.1）")

print()
print("=" * 62)
print("2. 输入合理性校验")
print("=" * 62)
for val, name, should_fail in [(780, "体重", True), (15, "身高", True),
                               (5, "年龄", True), (500, "目标体重", True),
                               (78, "体重", False), (175, "身高", False)]:
    try:
        mp._check_spot(val, name)
        failed = False
        err = ""
    except SystemExit:
        failed = True
        err = "已拦截"
    ok = (failed == should_fail)
    check(ok, f"{name}={val} {'应拦截' if should_fail else '应放行'}"
              f"{'（' + err + '）' if err else ''}")

# CLI 层拦截
r = run("budget_tracker.py", "--weight", "780", "--height", "175",
        "--age", "40", "--sex", "male", "--target-weight", "72")
check(r.returncode == 1 and "超出合理范围" in r.stdout,
      "CLI 层拦截体重 780（退出码 1）")
r = run("budget_tracker.py", "--weight", "78", "--height", "175",
        "--age", "40", "--sex", "male", "--target-weight", "72",
        "--eaten", "-100")
check(r.returncode == 1, "CLI 层拦截负数已摄入热量")

print()
print("=" * 62)
print("3. 剩余额度计算")
print("=" * 62)
items = mp.load_items()
a = Args(bmr=1750, eaten=1200, eaten_protein=60, eaten_sodium=1500)
a.eaten = 1200
a.eaten_protein = 60
a.eaten_sodium = 1500
target = mp.build_target(a)
report = bt.render(a, target, items)

check(f"{target['daily_kcal'] - 1200:.0f} kcal" in report, "输出剩余热量")
check(f"{target['protein_target'] - 60:.0f} g" in report, "输出剩余蛋白")
check(f"{bt.SODIUM_DAILY_CAP - 1500:.0f} mg" in report, "输出剩余钠额度")
check("用户实测" in report, "输出标注 BMR 来源")

print()
print("=" * 62)
print("4. 推荐逻辑")
print("=" * 62)
kcal_left = target["daily_kcal"] - 1200

singles = bt.pick_singles(items, kcal_left)
check(len(singles) > 0, f"在 {kcal_left:.0f} kcal 内给出单品推荐")
check(all(i["kcal"] <= kcal_left for i in singles), "所有单品均在剩余热量内")
check(singles == sorted(singles, key=lambda x: (-x["protein"], x["kcal"])),
      "单品按蛋白降序排列")
check(singles[0]["protein"] >= singles[-1]["protein"], "首位蛋白最高")

combos = bt.pick_combos(items, kcal_left)
check(len(combos) > 0, "给出组合推荐")
check(all(t["kcal"] <= kcal_left for _, t in combos), "所有组合均在剩余热量内")
for combo, _ in combos:
    kinds = [mp.classify(i["name"]) for i in combo]
    if len(kinds) != len(set(kinds)):
        check(False, "组合内出现同类重复")
        break
else:
    check(True, "组合内无同类重复")
check(combos[0][1]["protein"] >= combos[-1][1]["protein"], "组合按蛋白降序排列")

print()
print("=" * 62)
print("5. 控钠选项")
print("=" * 62)
check("控钠可选" in report, "钠额度紧张时输出控钠选项段")
check("不可兼得" in report, "说明控钠与补蛋白不可兼得")

r2 = run("budget_tracker.py", "--weight", "78", "--height", "175", "--age", "40",
         "--sex", "male", "--target-weight", "72", "--bmr", "1750",
         "--eaten", "1200", "--eaten-protein", "60", "--eaten-sodium", "1950")
check("控钠可选" in r2.stdout, "剩余钠 50mg 时仍给出控钠段")
check("无任何单品能同时满足" in r2.stdout or "热牛奶" in r2.stdout
      or "冰美式" in r2.stdout or "玉米杯" in r2.stdout,
      "极小钠额度下输出合理结果")

print()
print("=" * 62)
print("6. 边界场景")
print("=" * 62)
a_zero = Args(bmr=1750)
a_zero.eaten = 5000
a_zero.eaten_protein = 200
a_zero.eaten_sodium = None
rep_zero = bt.render(a_zero, mp.build_target(a_zero), items)
check("额度已用完" in rep_zero, "超额时提示额度用完")
check("无糖可口可乐" in rep_zero, "超额时给出零热量选项")

a_no_na = Args(bmr=1750)
a_no_na.eaten = 1000
a_no_na.eaten_protein = 40
a_no_na.eaten_sodium = None
rep_no_na = bt.render(a_no_na, mp.build_target(a_no_na), items)
check("控钠可选" not in rep_no_na, "未提供钠摄入时不显示控钠段")
check("钠" not in rep_no_na.split("剩余额度")[1].split("---")[0],
      "未提供钠摄入时不显示钠额度行")

print()
print("=" * 62)
print(f"测试结果：{PASS} passed, {FAIL} failed")
print("=" * 62)
sys.exit(1 if FAIL else 0)
