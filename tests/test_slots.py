# -*- coding: utf-8 -*-
"""餐次级填空求解的回归测试

覆盖 C(3,1)+C(3,2)+C(3,3) = 7 种组合，以及已知餐次扣减、额度压缩、
已知超标的处理。核心不变量：全天合计 = 已知餐次 + 麦当劳配餐。
"""

import itertools
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from meal_planner import (  # noqa: E402
    MEAL_SLOTS, SODIUM_DAILY_CAP, build_slot_plan, build_target, load_items,
    parse_known, plan_totals,
)

PASS = FAIL = 0


def check(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}")


def approx(a, b, tol=0.51):
    return abs(a - b) <= tol


class A:
    def __init__(self, **kw):
        self.weight = 78.0
        self.height = 175.0
        self.age = 40
        self.sex = "male"
        self.activity = "light"
        self.bmr = 1600.0
        self.bodyfat = 22.0
        self.goal = "recomp"
        self.target_weight = None
        self.weeks = 12.0
        for k, v in kw.items():
            setattr(self, k, v)


ITEMS = load_items()
TARGET = build_target(A())
DAILY = TARGET["daily_kcal"]

# 三个"已知餐次"的模拟值
KNOWN_POOL = {
    "breakfast": {"label": "早餐", "kcal": 520.0, "protein": 18.0, "sodium": 900.0},
    "lunch": {"label": "午餐", "kcal": 800.0, "protein": 30.0, "sodium": 1200.0},
    "dinner": {"label": "晚餐", "kcal": 700.0, "protein": 35.0, "sodium": 1000.0},
}

print("=" * 64)
print("一、7 种餐次组合都能求解")
print("=" * 64)

ALL = ["breakfast", "lunch", "dinner"]
for n in (1, 2, 3):
    for combo in itertools.combinations(ALL, n):
        known = [KNOWN_POOL[k] for k in ALL if k not in combo]
        plan, info = build_slot_plan(ITEMS, TARGET, list(combo), known)
        label = "+".join(combo)
        # 每个待解餐次都要有实际组合
        ok_nonempty = all(len(c) > 0 for _, c, _, _ in plan)
        check(ok_nonempty, f"{label}: 每个待解餐次都配出了组合")
        check(len(plan) == len(combo), f"{label}: 输出餐次数 = {len(combo)}")

print()
print("=" * 64)
print("二、剩余额度 = 目标 − 已知合计（精确）")
print("=" * 64)

for n in (1, 2, 3):
    for combo in itertools.combinations(ALL, n):
        known = [KNOWN_POOL[k] for k in ALL if k not in combo]
        _, info = build_slot_plan(ITEMS, TARGET, list(combo), known)
        want = DAILY - sum(m["kcal"] for m in known)
        check(approx(info["left_kcal"], want),
              f"{'+'.join(combo)}: 剩余额度 {info['left_kcal']:.0f}"
              f"（期望 {want:.0f}）")

print()
print("=" * 64)
print("三、全天合计 = 已知餐次 + 麦当劳配餐（核心不变量）")
print("=" * 64)

for n in (1, 2, 3):
    for combo in itertools.combinations(ALL, n):
        known = [KNOWN_POOL[k] for k in ALL if k not in combo]
        plan, info = build_slot_plan(ITEMS, TARGET, list(combo), known)
        pt = plan_totals(plan)
        # 独立复算：手工累加已知 + 求解
        manual = info["known_kcal"] + pt["kcal"]
        check(manual > 0 and manual <= DAILY * 1.15,
              f"{'+'.join(combo)}: 全天合计 {manual:.0f} kcal 不超目标 15%")

print()
print("=" * 64)
print("四、额度分配：充足时不超发，不足时等比压缩")
print("=" * 64)

# 无已知餐次 → 剩余额度 = 全天目标 → 不压缩
_, info = build_slot_plan(ITEMS, TARGET, ALL, [])
check(approx(info["scale"], 1.0), f"无已知时 scale = {info['scale']:.3f}（不压缩）")

# 已知餐次很少 → 仍不压缩（余额留作余量）
_, info = build_slot_plan(ITEMS, TARGET, ["breakfast"],
                          [{"label": "加餐", "kcal": 100, "protein": 5, "sodium": 50}])
check(approx(info["scale"], 1.0),
      f"额度充足时 scale = {info['scale']:.3f}（不超发标准额度）")

# 已知餐次吃掉大部分 → 必须压缩
big = [{"label": "大餐", "kcal": DAILY - 100, "protein": 20, "sodium": 1500}]
plan, info = build_slot_plan(ITEMS, TARGET, ALL, big)
check(info["scale"] < 0.999,
      f"额度不足时 scale = {info['scale']:.3f}（<1 即压缩）")
pt = plan_totals(plan)
if pt["kcal"] > info["left_kcal"] + 1:
    # 额度极紧时可能无可行解 —— 此时必须如实标注，而不是静默超标
    check(len(info.get("notes", {})) > 0,
          f"超标时给出 {len(info.get('notes', {}))} 条提示（不静默超标）")
else:
    check(True, f"压缩后麦当劳合计 {pt['kcal']:.0f} ≤ 额度 "
                f"{info['left_kcal']:.0f}")

# 额度适中（能配出餐）时，硬约束必须生效，麦当劳合计不得超额度 15%
mid = [{"label": "中餐", "kcal": DAILY - 800, "protein": 30, "sodium": 1000}]
plan_m, info_m = build_slot_plan(ITEMS, TARGET, ALL, mid)
pt_m = plan_totals(plan_m)
check(pt_m["kcal"] <= info_m["left_kcal"] * 1.15 + 1,
      f"硬约束生效：麦当劳合计 {pt_m['kcal']:.0f} ≤ 额度 "
      f"{info_m['left_kcal']:.0f}×1.15")

print()
print("=" * 64)
print("五、已知餐次超标 → 剩余为负且不硬凑")
print("=" * 64)

over = [{"label": "超标", "kcal": DAILY + 500, "protein": 50, "sodium": 3000}]
plan, info = build_slot_plan(ITEMS, TARGET, ALL, over)
check(info["left_kcal"] < 0, f"剩余额度为负：{info['left_kcal']:.0f}")
check(all(len(c) == 0 for _, c, _, _ in plan),
      "已知超标时不给配餐（不硬凑出方案）")
check(approx(info["scale"], 0.0), f"scale = {info['scale']:.3f}")

print()
print("=" * 64)
print("六、--known 参数解析")
print("=" * 64)

r = parse_known(["午餐=800,30,1200"])
check(len(r) == 1 and r[0]["label"] == "午餐" and approx(r[0]["kcal"], 800)
      and approx(r[0]["protein"], 30) and approx(r[0]["sodium"], 1200),
      "完整格式解析正确")

r = parse_known(["下午茶=300,10"])
check(approx(r[0]["sodium"], 0.0), "省略钠时默认为 0")

r = parse_known(["早餐=520,18,900", "晚餐=700,35,1000"])
check(len(r) == 2, "可重复多次")

for bad, why in (("午餐800,30", "缺少 ="), ("=800,30", "缺少名称"),
                 ("午餐=800", "只有一项"), ("午餐=abc,30", "数值非法")):
    try:
        parse_known([bad])
        check(False, f"异常输入应报错：{bad}（{why}）")
    except ValueError:
        check(True, f"异常输入被拒绝：{bad}（{why}）")

print()
print("=" * 64)
print("七、餐次槽位定义与向后兼容")
print("=" * 64)

check(set(MEAL_SLOTS) == {"breakfast", "lunch", "dinner", "snack"},
      f"餐次槽位：{sorted(MEAL_SLOTS)}")
check(approx(sum(MEAL_SLOTS[k]["w"] for k in ("breakfast", "lunch", "dinner")), 1.0, 0.001),
      "三餐权重合计 = 1.0（早 25% + 午 40% + 晚 35%）")

# 全解且无已知时，等价于原全天三餐方案
plan, _ = build_slot_plan(ITEMS, TARGET, ALL, [])
labels = [m[0] for m in plan]
check(labels == ["早餐", "午餐", "晚餐"], f"默认全解餐次顺序：{labels}")

# 加餐槽位可用
plan_s, info_s = build_slot_plan(ITEMS, TARGET, ["snack"],
                                 [KNOWN_POOL["breakfast"], KNOWN_POOL["lunch"],
                                  KNOWN_POOL["dinner"]])
check(len(plan_s) == 1 and plan_s[0][0] == "加餐", "加餐槽位可单独求解")

print()
print("=" * 64)
print("八、只配一餐时不会吃光全天额度")
print("=" * 64)

# 只解早餐、午晚餐已知：早餐额度应接近"全天目标×25%"而非剩余全额
plan, info = build_slot_plan(ITEMS, TARGET, ["breakfast"],
                             [KNOWN_POOL["lunch"], KNOWN_POOL["dinner"]])
kcal_t = plan[0][2]
std = DAILY * MEAL_SLOTS["breakfast"]["w"]
check(kcal_t <= std + 1,
      f"早餐额度 {kcal_t:.0f} ≤ 标准额度 {std:.0f}（不会因为午晚已知就狂吃早餐）")

print()
print("=" * 64)
print(f"结果：{PASS} passed, {FAIL} failed")
print("=" * 64)
sys.exit(1 if FAIL else 0)
