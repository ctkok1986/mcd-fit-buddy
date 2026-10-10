# -*- coding: utf-8 -*-
"""目标模式（cut/recomp/gain）与券双维优先级的回归测试

重点验证两件事：
1. 摄入目标锚定 TDEE 而非 BMR —— 这是相对旧算法的核心修正
2. 券优先级 = 省钱额为主 + 临期加分为辅 —— 用户明确要求"最优惠优先"
"""

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from coupon_context import CouponContext, URGENT_BONUS  # noqa: E402
from meal_planner import GOALS, build_target, make_score, totals  # noqa: E402

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
    """模拟 argparse 结果。"""

    def __init__(self, **kw):
        self.weight = 78.0
        self.height = 175.0
        self.age = 40
        self.sex = "male"
        self.activity = "light"
        self.bmr = 1600.0
        self.bodyfat = None
        self.goal = None
        self.target_weight = None
        self.weeks = 12.0
        for k, v in kw.items():
            setattr(self, k, v)


TDEE = 1600.0 * 1.375          # 2200
LBM_22 = 78.0 * (1 - 0.22)     # 60.84

print("=" * 64)
print("一、摄入目标锚定 TDEE（不是 BMR）")
print("=" * 64)

for goal, pct in (("cut", 0.18), ("recomp", 0.08), ("gain", -0.08)):
    t = build_target(A(goal=goal))
    expect = TDEE * (1 - pct)
    check(approx(t["daily_kcal"], expect),
          f"{goal}: 摄入 {t['daily_kcal']:.0f} kcal = TDEE×{1-pct:.2f}"
          f"（期望 {expect:.0f}）")

# 核心断言：三种模式下摄入都显著高于 BMR（=1600），
# 这直接反驳"摄入不超过基础代谢"的做法
for goal in ("cut", "recomp", "gain"):
    t = build_target(A(goal=goal))
    check(t["daily_kcal"] >= 1600,
          f"{goal}: 摄入 {t['daily_kcal']:.0f} ≥ BMR 1600（不锚定 BMR）")

t_gain = build_target(A(goal="gain"))
check(t_gain["daily_kcal"] > TDEE,
      f"gain 模式为盈余：{t_gain['daily_kcal']:.0f} > TDEE {TDEE:.0f}")

print()
print("=" * 64)
print("二、蛋白按瘦体重计算")
print("=" * 64)

for goal, coef in (("cut", 2.2), ("recomp", 2.4), ("gain", 2.0)):
    t = build_target(A(goal=goal, bodyfat=22))
    expect = LBM_22 * coef
    check(approx(t["protein_target"], expect),
          f"{goal}: 蛋白 {t['protein_target']:.1f} g = LBM {LBM_22:.2f}×{coef}"
          f"（期望 {expect:.1f}）")

# 未提供体脂率时退回按体重，并明确标注来源
t_no_bf = build_target(A(goal="cut"))
check(approx(t_no_bf["protein_target"], 78.0 * 1.8),
      f"无体脂率时退回体重×1.8 = {t_no_bf['protein_target']:.0f} g")
check("未提供体脂率" in t_no_bf["protein_source"],
      f"来源标注清晰：{t_no_bf['protein_source']}")

# 高体脂时按瘦体重算出的值应低于按体重算出的值
t_bf = build_target(A(goal="cut", bodyfat=22))
check(t_bf["protein_target"] != t_no_bf["protein_target"],
      f"体脂率改变蛋白目标：{t_no_bf['protein_target']:.0f} → "
      f"{t_bf['protein_target']:.0f} g")

print()
print("=" * 64)
print("三、护栏仍然生效")
print("=" * 64)

# 极端案例：BMR 很低但活动量很大 → 若锚定 BMR 会触发缺口上限
t = build_target(A(bmr=1200, activity="athlete", goal="cut"))
gap_pct = t["daily_deficit"] / t["tdee"]
check(gap_pct <= 0.2501, f"缺口被限制在 TDEE 的 25% 内（实际 {gap_pct*100:.1f}%）")
check(t["daily_kcal"] >= 1200 * 1.1 - 0.51,
      f"摄入不低于 BMR×1.1 = {1200*1.1:.0f}（实际 {t['daily_kcal']:.0f}）")

# 旧路径仍然可用（向后兼容）
t_old = build_target(A(target_weight=72.0, weeks=12))
check(t_old["goal"] is None, "未传 --goal 时走旧路径")
check(approx(t_old["protein_target"], 78.0 * 1.8),
      f"旧路径蛋白仍按体重×1.8 = {t_old['protein_target']:.0f} g")

print()
print("=" * 64)
print("四、券优先级：省钱额为主 + 临期加分为辅")
print("=" * 64)

NOW = datetime(2026, 10, 11, 12, 0)


def mk(title, list_price, coupon_price, hours_left):
    return {
        "title": title, "couponId": "x", "couponCode": "y",
        "productCode": "1", "menuName": title,
        "listPrice": list_price, "couponPrice": coupon_price,
        "validUntil": (NOW + timedelta(hours=hours_left)).strftime(
            "%Y-%m-%d %H:%M"),
        "unavailable": False,
    }


from coupon_context import load_coupons  # noqa: E402


def ctx_of(coupons):
    """绕过文件，直接构造上下文。"""
    import json
    import tempfile
    d = tempfile.mkdtemp()
    p = os.path.join(d, "c.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"meta": {}, "coupons": coupons}, f, ensure_ascii=False)
    u, e, m = load_coupons(p, now=NOW)
    return CouponContext(u, e, m)


# 1) 优惠额优先：省 ¥5（不急）应排在省 ¥1（24h 内到期）之前
c = ctx_of([mk("大额券", 10.0, 5.0, 500), mk("小额临期券", 3.0, 2.0, 5)])
s_big, u_big, sc_big = c.value_of("大额券")
s_small, u_small, sc_small = c.value_of("小额临期券")
check(sc_big > sc_small,
      f"省钱多的优先：大额券 {sc_big:.2f} > 小额临期券 {sc_small:.2f}")
check(approx(s_big, 5.0) and approx(s_small, 1.0),
      f"省钱额计算正确：{s_big:.2f} / {s_small:.2f}")

# 2) 临期加分：两者省钱相同时，临期的优先
c2 = ctx_of([mk("不着急券", 3.0, 2.0, 500), mk("临期券", 3.0, 2.0, 5)])
_, _, sc_a = c2.value_of("不着急券")
_, _, sc_b = c2.value_of("临期券")
check(sc_b > sc_a,
      f"省钱相同时临期优先：{sc_b:.2f} > {sc_a:.2f}"
      f"（差 {sc_b - sc_a:.2f} = URGENT_BONUS×Δurgency）")

# 3) 临期加分不会盖过明显优惠差：省 ¥2 不急 应胜过 省 ¥1 临期
c3 = ctx_of([mk("省两元不急", 5.0, 3.0, 500), mk("省一元临期", 3.0, 2.0, 5)])
_, _, sc_x = c3.value_of("省两元不急")
_, _, sc_y = c3.value_of("省一元临期")
check(sc_x > sc_y,
      f"¥2 不急({sc_x:.2f}) 胜 ¥1 临期({sc_y:.2f}) —— 临期不翻盘金额差")

# 4) 已过期券 urgency=0（不激励）
c4 = ctx_of([mk("过期券", 10.0, 0.0, -5)])
check(len(c4.usable) == 0 and len(c4.excluded) == 1,
      "已过期券被排除，不参与激励")

# 5) 不可用券被排除且不计入优惠
bad = mk("不可用券", 10.0, 0.0, 500)
bad["unavailable"] = True
c5 = ctx_of([bad])
check(len(c5.usable) == 0, "标记 unavailable 的券被排除")

# 6) 激励确实影响打分函数：有券的组合得分更低
c6 = ctx_of([mk("鸡块券", 20.0, 8.0, 5)])
item = {"name": "鸡块券", "kcal": 200, "protein": 12, "fat": 8,
        "carb": 10, "sodium": 300}
s_with = make_score(0.5, c6)([item], 200, 12)
s_without = make_score(0.5, None)([item], 200, 12)
check(s_with < s_without,
      f"有券使得分更低（更易被选中）：{s_with:.3f} < {s_without:.3f}")

print()
print("=" * 64)
print("五、系数来源标注")
print("=" * 64)
check(GOALS["cut"]["deficit_pct"] == 0.18, "cut 缺口 18%（文献 15-20%）")
check(GOALS["recomp"]["deficit_pct"] == 0.08, "recomp 缺口 8%（小缺口）")
check(GOALS["gain"]["deficit_pct"] == -0.08, "gain 盈余 8%（lean bulk）")
check(URGENT_BONUS == 0.5, f"临期加分系数 = {URGENT_BONUS} 元/点紧迫度")

print()
print("=" * 64)
print(f"结果：{PASS} passed, {FAIL} failed")
print("=" * 64)
sys.exit(1 if FAIL else 0)
