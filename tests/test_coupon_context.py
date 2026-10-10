#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦麦减脂搭子 · 券上下文回归测试

覆盖：券载入与排除、临期紧迫度、名称归一化匹配、券对配餐的影响、取舍报告。
运行：python tests/test_coupon_context.py
"""

import os
import sys
from datetime import datetime, timedelta

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(BASE, "scripts"))

import meal_planner as mp              # noqa: E402
import coupon_context as cc            # noqa: E402

PASS, FAIL = 0, 0
SNAP = os.path.join(BASE, "data", "coupon-snapshot.sample.json")


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {msg}")
    else:
        FAIL += 1
        print(f"  [FAIL] {msg}")


class Args:
    weight = 78
    height = 175
    age = 40
    sex = "male"
    activity = "light"
    target_weight = 72
    weeks = 12
    bmr = 1750


print("=" * 62)
print("1. 券载入与排除")
print("=" * 62)
NOW = datetime(2026, 10, 11, 0, 16)
usable, excluded, meta = cc.load_coupons(SNAP, now=NOW)

check(len(usable) == 4, f"可用券 4 张（实得 {len(usable)}）")
check(len(excluded) == 1, f"被排除 1 张（实得 {len(excluded)}）")
check(excluded[0]["title"] == "免费脆薯饼", "被排除的是免费脆薯饼")
check("不可用" in excluded[0].get("_reason", ""), "排除原因标注为不可用")

print()
print("=" * 62)
print("2. 临期紧迫度")
print("=" * 62)
check(cc.compute_urgency((NOW + timedelta(hours=6)).isoformat(), NOW) == 1.0,
      "6 小时后到期 → urgency 1.0")
check(cc.compute_urgency((NOW + timedelta(days=2)).isoformat(), NOW) == 0.6,
      "2 天后到期 → urgency 0.6")
check(cc.compute_urgency((NOW + timedelta(days=5)).isoformat(), NOW) == 0.3,
      "5 天后到期 → urgency 0.3")
check(cc.compute_urgency((NOW + timedelta(days=20)).isoformat(), NOW) == 0.1,
      "20 天后到期 → urgency 0.1")
check(cc.compute_urgency((NOW - timedelta(hours=1)).isoformat(), NOW) == 0.0,
      "已过期 → urgency 0")
check(cc.compute_urgency("不是时间", NOW) == 0.0, "无法解析 → urgency 0")

print()
print("=" * 62)
print("3. 名称归一化匹配")
print("=" * 62)
check(cc.normalize("麦咖啡™冰美式中杯") == cc.normalize("麦咖啡™热美式中杯"),
      "冰/热/杯型差异归一化后同名")
check(cc.normalize("纯牛奶（盒装）") == cc.normalize("纯牛奶(盒装)"),
      "全角/半角括号一致")
check(cc.normalize("中薯条") != cc.normalize("大薯条"), "中/大薯条不混淆")

ctx = cc.CouponContext(usable, excluded, meta)
check(ctx.lookup("冰美式中杯") is not None, "按名称命中「冰美式中杯」券")
check(ctx.lookup("麦咖啡™冰美式中杯") is not None, "带 ™ 与杯型也能命中")
check(ctx.lookup("双层吉士汉堡") is None, "无券餐品返回 None")
check(ctx.urgency_of("冰美式中杯") > 0, "有券餐品 urgency > 0")
check(ctx.urgency_of("双层吉士汉堡") == 0, "无券餐品 urgency = 0")

print()
print("=" * 62)
print("4. 券对配餐的影响")
print("=" * 62)
items = mp.load_items()
target = mp.build_target(Args())

plan_no = mp.build_plan(items, target, sodium_weight=0.5, coupon_ctx=None)
plan_cp = mp.build_plan(items, target, sodium_weight=0.5, coupon_ctx=ctx)

names_no = [i["name"] for _, c, _, _ in plan_no for i in c]
names_cp = [i["name"] for _, c, _, _ in plan_cp for i in c]

used_no = [n for n in names_no if ctx.lookup(n)]
used_cp = [n for n in names_cp if ctx.lookup(n)]

check(len(used_no) == 0, "不用券时不选带券餐品（无偏好）")
check(len(used_cp) >= 1, f"用券后至少选 1 个带券餐品（实得 {len(used_cp)}）")

t_no, t_cp = mp.plan_totals(plan_no), mp.plan_totals(plan_cp)
check(abs(t_cp["kcal"] - target["daily_kcal"]) / target["daily_kcal"] < 0.05,
      "用券后热量仍贴合目标（偏离 <5%）")

print()
print("=" * 62)
print("5. 取舍报告")
print("=" * 62)
rep = mp.render_coupon_tradeoff(plan_cp, plan_no, ctx)
check("用券的代价" in rep, "输出用券代价对比")
check("蛋白" in rep and "省下" in rep, "含蛋白与金额差异")
if t_cp["protein"] < t_no["protein"]:
    check("牺牲了蛋白" in rep, "牺牲蛋白时给出提醒")

# 无差异时应返回空
check(mp.render_coupon_tradeoff(plan_no, plan_no, ctx) == "",
      "两方案相同时不输出对比段")

print()
print("=" * 62)
print("6. 券报告渲染")
print("=" * 62)
full = mp.fmt(plan_cp, target, Args(), 0.5, "蛋白优先", coupon_ctx=ctx)
check("券使用情况" in full, "输出券使用情况段")
check("🎫" in full, "标注用上的券")
check("券优先级" in full, "输出券优先级排序（最优惠优先 + 临期加分）")
check("单独使用建议" in full, "输出未用上券的单独使用建议")
check("⏰" in full, "临期券被标记 ⏰")
check("被排除的券" in full, "输出被排除的券")
check("计价实测不可用" in full, "说明排除原因（实测不可用）")
check("免费脆薯饼" in full, "列出被排除的券名")

# 无券时不应出现券段
plain = mp.fmt(plan_no, target, Args(), 0.5, "蛋白优先", coupon_ctx=None)
check("券使用情况" not in plain, "未提供券时不输出券段")

print()
print("=" * 62)
print("7. 边界：过期券不参与")
print("=" * 62)
future = datetime(2026, 12, 1)
u2, e2, _ = cc.load_coupons(SNAP, now=future)
check(len(e2) == 5, f"全部券过期后 5 张被排除（实得 {len(e2)}）")
check(len(u2) == 0, "全部过期后可用券为 0")
ctx2 = cc.CouponContext(u2, e2, {})
plan2 = mp.build_plan(items, target, sodium_weight=0.5, coupon_ctx=ctx2)
t2, t1b = mp.plan_totals(plan2), mp.plan_totals(plan_no)
check(abs(t2["protein"] - t1b["protein"]) < 0.5,
      "无可用券时结果与不用券一致")

print()
print("=" * 62)
print(f"测试结果：{PASS} passed, {FAIL} failed")
print("=" * 62)
sys.exit(1 if FAIL else 0)
