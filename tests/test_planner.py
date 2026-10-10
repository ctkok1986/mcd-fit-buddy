#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦麦减脂搭子 · 回归测试

覆盖：数据加载、分类、BMR/TDEE 计算、安全护栏、配餐求解、冲突诊断。
运行：python tests/test_planner.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import meal_planner as mp  # noqa: E402

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


print("=" * 60)
print("1. 营养数据加载")
print("=" * 60)
items = mp.load_items()
check(len(items) == 158, f"加载 158 项营养数据（实际 {len(items)}）")
check(all(i["kcal"] >= 0 for i in items), "热量字段非负")
check(all(i["protein"] >= 0 for i in items), "蛋白字段非负")
check(any(i["name"] == "巨无霸" for i in items), "巨无霸在数据集中")

print()
print("=" * 60)
print("2. 餐品分类（回归：曾出现 V翅误判为饮品、巨无霸漏判）")
print("=" * 60)
check(mp.classify("柠萌风味薄皮焦香V翅") == "side", "柠萌V翅 → side（曾误判为 drink）")
check(mp.classify("巨无霸") == "burger", "巨无霸 → burger（曾漏判为 other）")
check(mp.classify("麦香鸡") == "burger", "麦香鸡 → burger（曾漏判为 other）")
check(mp.classify("麦香鱼") == "burger", "麦香鱼 → burger（曾漏判为 other）")
check(mp.classify("烟肉蛋麦满分") == "breakfast_main", "烟肉蛋麦满分 → breakfast_main")
check(mp.classify("脆薯饼") == "breakfast_side", "脆薯饼 → breakfast_side")
check(mp.classify("圆筒冰淇淋") == "dessert", "圆筒冰淇淋 → dessert")
check(mp.classify("冰美式中杯") == "drink", "冰美式中杯 → drink")
uncat = [i["name"] for i in items if mp.classify(i["name"]) == "other"]
check(len(uncat) == 0, f"无未分类餐品（实际 {len(uncat)} 项）")

print()
print("=" * 60)
print("3. BMR / TDEE 计算（Mifflin-St Jeor）")
print("=" * 60)
# 男 78kg/175cm/40岁: 10*78 + 6.25*175 - 5*40 + 5 = 780+1093.75-200+5 = 1678.75
check(abs(mp.calc_bmr(78, 175, 40, "male") - 1678.75) < 0.01,
      "男性 BMR 手算复核 1678.75")
# 女 65kg/162cm/32岁: 10*65 + 6.25*162 - 5*32 - 161 = 650+1012.5-160-161 = 1341.5
check(abs(mp.calc_bmr(65, 162, 32, "female") - 1341.5) < 0.01,
      "女性 BMR 手算复核 1341.5")

t = mp.build_target(Args())
check(abs(t["tdee"] - 1678.75 * 1.375) < 0.01, "TDEE = BMR × 1.375")
check(t["daily_kcal"] >= t["bmr"] * 1.1 - 1e-6, "摄入目标不低于 BMR×1.1 护栏")

print()
print("=" * 60)
print("4. 安全护栏")
print("=" * 60)
# 极端激进：6 周减 15kg，应触发两条护栏
aggr = mp.build_target(Args(weight=85, target_weight=70, weeks=6))
floor = aggr["bmr"] * 1.1
check(aggr["daily_kcal"] >= floor - 1e-6, "激进目标下摄入仍守住 BMR 护栏")
check(len(aggr["warnings"]) >= 1, "激进目标触发护栏警告")
check(abs((aggr["tdee"] - aggr["daily_kcal"]) - aggr["daily_deficit"]) < 1e-6,
      "缺口与摄入自洽（deficit = tdee - kcal）")
check(abs(aggr["weekly_loss"] - aggr["daily_deficit"] * 7 / 7700) < 1e-9,
      "周减重 = 缺口×7/7700")

print()
print("=" * 60)
print("5. 配餐求解")
print("=" * 60)
plan = mp.build_plan(items, t, sodium_weight=0.5)
check(len(plan) == 3, f"生成三餐（实际 {len(plan)}）")
check([p[0] for p in plan] == ["早餐", "午餐", "晚餐"], "餐次顺序为 早餐/午餐/晚餐")
for label, combo, _, _ in plan:
    check(len(combo) >= 1, f"{label} 至少含 1 项")
    check(len(combo) <= 4, f"{label} 项数合理（{len(combo)} ≤ 4）")

# 同类去重：一餐内不应出现两个同分类餐品
dup_found = False
for label, combo, _, _ in plan:
    kinds = [mp.classify(i["name"]) for i in combo]
    if len(kinds) != len(set(kinds)):
        dup_found = True
check(not dup_found, "一餐内无同类重复（曾出现两杯奶铁）")

# 三餐之间不重复
all_names = [i["name"] for _, c, _, _ in plan for i in c]
check(len(all_names) == len(set(all_names)), "三餐之间无重复餐品")

t_all = mp.plan_totals(plan)
check(abs(t_all["kcal"] - t["daily_kcal"]) / t["daily_kcal"] < 0.05,
      f"全天热量贴合目标（偏差 {t_all['kcal'] - t['daily_kcal']:+.0f} kcal，<5%）")

print()
print("=" * 60)
print("6. 目标冲突诊断")
print("=" * 60)
plan_p = mp.build_plan(items, t, sodium_weight=0.5)
plan_s = mp.build_plan(items, t, sodium_weight=4.0)
tp, ts = mp.plan_totals(plan_p), mp.plan_totals(plan_s)
check(tp["sodium"] > ts["sodium"], "蛋白优先模式的钠 高于 控钠优先模式")
check(tp["protein"] > ts["protein"], "蛋白优先模式的蛋白 高于 控钠优先模式")
_, issues_p = mp.conflict_diagnosis(plan_p, t)
check(len(issues_p) >= 1, "蛋白优先模式被识别出至少 1 项冲突")

print()
print("=" * 60)
print("7. 女性用例")
print("=" * 60)
tf = mp.build_target(Args(weight=65, height=162, age=32, sex="female",
                          activity="sedentary", target_weight=58, weeks=16))
planf = mp.build_plan(items, tf, sodium_weight=0.5)
check(len(planf) == 3, "女性用例生成三餐")
tf_all = mp.plan_totals(planf)
check(abs(tf_all["kcal"] - tf["daily_kcal"]) / tf["daily_kcal"] < 0.05,
      f"女性用例热量贴合（{tf_all['kcal']:.0f} vs {tf['daily_kcal']:.0f}）")
check(tf["bmr"] < t["bmr"], "女性 BMR 低于男性（同参数下）")

print()
print("=" * 60)
print(f"测试结果：{PASS} passed, {FAIL} failed")
print("=" * 60)
sys.exit(1 if FAIL else 0)
