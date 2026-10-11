#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦麦减脂搭子 · 配餐优化引擎

输入：体重、身高、年龄、性别、活动强度、目标体重、周期
输出：每日热量/蛋白目标 + 三餐麦当劳组合（按营养数据真实求解）+ 目标冲突诊断

数据源：data/nutrition.csv（麦当劳官方 MCP list-nutrition-foods，158 项）

用法：
    python meal_planner.py --weight 78 --height 175 --age 40 --sex male \
        --activity light --target-weight 72 --weeks 12
"""

import argparse
import csv
import json
import os
import sys
from itertools import combinations

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", "data", "nutrition.csv")

# 1 kg 脂肪 ≈ 7700 kcal
KCAL_PER_KG_FAT = 7700
# WHO 建议每日钠摄入上限
SODIUM_DAILY_CAP = 2000

ACTIVITY = {
    "sedentary": (1.2, "久坐（办公室，几乎不运动）"),
    "light": (1.375, "轻度活动（每周 1-3 次运动）"),
    "moderate": (1.55, "中度活动（每周 3-5 次运动）"),
    "active": (1.725, "高度活动（每周 6-7 次运动）"),
    "athlete": (1.9, "极高强度（体力劳动/运动员）"),
}

# 目标模式。锚点是 TDEE，deficit_pct 为正表示缺口、为负表示盈余。
# 比例来源：
#   减脂：文献共识缺口 15-20%，超过 25% 显著增加肌肉流失
#   增肌减脂(recomp)：5-10% 小缺口，同时进行增肌与减脂
#   增肌：lean bulk 5-15% 小盈余，取 8%
# 蛋白系数（g/kg）来源：JISSN 对热量缺口下偏瘦训练者建议 2.3-3.1 g/kg 瘦体重。
#   recomp 取 2.4（区间内）、cut 取 2.2（保守下沿）、gain 取 2.0（热量充足时无需更高）
GOALS = {
    "cut": {"deficit_pct": 0.18, "protein_lbm": 2.2, "protein_bw": 1.8,
            "horizon_days": 90, "desc": "减脂（保肌优先）"},
    "recomp": {"deficit_pct": 0.08, "protein_lbm": 2.4, "protein_bw": 2.0,
               "horizon_days": 120, "desc": "增肌减脂（体成分重组）"},
    "gain": {"deficit_pct": -0.08, "protein_lbm": 2.0, "protein_bw": 1.8,
             "horizon_days": 150, "desc": "增肌（小盈余）"},
}

PROTEIN_PER_KG_LBM = 2.2   # 无 --goal 时按瘦体重算的默认系数

# ── 显式分类白名单 ──────────────────────────────────────────────
# 不用子串猜测：曾出现「柠萌风味薄皮焦香V翅」因含「柠」被误判为饮品、
# 「巨无霸/麦香鸡/麦香鱼」因不含「堡」被漏判的问题。故逐项枚举。

BREAKFAST_MAIN = {
    "猪柳麦满分", "猪柳蛋麦满分", "烟肉蛋麦满分", "火腿扒麦满分", "大脆鸡扒麦满分",
    "原味板烧鸡腿麦满分", "双层原味板烧鸡腿麦满分", "原味板烧鸡腿炒双蛋堡",
    "双层猪柳蛋麦满分", "双层火腿扒麦满分", "猪柳炒双蛋堡",
    "火腿扒早安营养卷", "图林根香肠早安营养卷", "皮蛋鸡肉粥", "雪菜脆笋鸡肉粥",
}
BREAKFAST_SIDE = {"脆薯饼", "脆香油条", "德式图林根香肠", "苹果片"}
BURGER = {
    "吉士汉堡包", "双层吉士汉堡", "麦辣鸡腿汉堡", "板烧鸡腿堡", "巨无霸",
    "麦香鸡", "麦香鱼", "培根蔬萃双层牛堡", "不素之霸双层牛堡", "双层深海鳕鱼堡",
    "儿童鱼排堡", "培根安格斯厚牛堡", "芝士安格斯厚牛堡",
    "芝士双层安格斯厚牛堡", "培根双层安格斯厚牛堡",
    "酥酥多笋卷", "鲜蔬蛋沙拉叠叠卷", "鸡肉蛋沙拉叠叠卷",
}
SIDE = {
    "中薯条", "大薯条", "小薯条", "迷你薯条", "脆脆薯条",
    "麦乐鸡5块", "麦乐鸡4块", "麦辣鸡翅-2块", "那么大鸡排", "麦麦趣鸡球",
    "薄皮焦香V翅", "柠萌风味薄皮焦香V翅",
    "蜜汁BBQ风味薄皮脆汁鸡-带骨里脊", "蜜汁BBQ风味薄皮脆汁鸡-琵琶腿",
    "麦麦脆汁鸡-琵琶腿", "麦麦脆汁鸡-带骨里脊",
    "蒜了吧黄油风味薄皮脆汁鸡-琵琶腿", "蒜了吧黄油风味薄皮脆汁鸡-带骨里脊",
    "香芋派", "菠萝派", "大杯玉米杯", "小杯玉米杯",
}
DESSERT = {
    "圆筒冰淇淋", "朱古力新地", "草莓新地", "奥利奥麦旋风", "草莓麦旋风",
    "迷你朱古力新地", "迷你草莓新地", "柠檬拉明顿", "草莓拉明顿",
    "抹茶阿芙佳朵", "咖啡阿芙佳朵", "yeyeyeye奶冻款", "yeyeyeye爆珠款",
}


def classify(name):
    """按显式白名单归类；未命中者默认视为饮品（数据表中其余均为饮品）。"""
    name = name.strip()
    if name in DESSERT:
        return "dessert"
    if name in BREAKFAST_MAIN:
        return "breakfast_main"
    if name in BREAKFAST_SIDE:
        return "breakfast_side"
    if name in BURGER:
        return "burger"
    if name in SIDE:
        return "side"
    return "drink"


def load_items():
    """载入营养数据表。用 utf-8-sig 兼容带 BOM 的 CSV。"""
    items = []
    with open(DATA_PATH, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                items.append({
                    "name": row["name"].strip(),
                    "kcal": float(row["kcal"]),
                    "protein": float(row["protein_g"]),
                    "fat": float(row["fat_g"]),
                    "carb": float(row["carb_g"]),
                    "sodium": float(row["sodium_mg"]),
                })
            except (ValueError, KeyError, AttributeError):
                continue
    return items


def calc_bmr(weight, height, age, sex):
    """Mifflin-St Jeor 公式。"""
    base = 10 * weight + 6.25 * height - 5 * age
    return base + 5 if sex == "male" else base - 161


def build_target(args):
    """计算每日热量与宏量目标，并施加安全护栏。

    两条路径：
    - 指定 --goal（cut / recomp / gain）：**锚定 TDEE**，按模式设缺口或盈余
    - 未指定 --goal：沿用旧路径，由 --target-weight + --weeks 反推缺口

    为什么锚点是 TDEE 而不是 BMR：
      摄入低于 BMR 并不等于减脂更快。实测（BMR=1600）：
        轻度活动 TDEE 2200 → 吃 1600 意味着缺口 27%，已超 25% 安全上限
        中度活动 TDEE 2480 → 缺口 35%，显著增加肌肉流失
      而增肌需要吃到 BMR 的 1.3~1.7 倍，「不超过 BMR」数学上到不了。
      故 BMR 仅作**下限护栏**（不低于 BMR×1.1），不作目标锚点。
    """
    measured_bmr = getattr(args, "bmr", None)
    if measured_bmr:
        bmr = float(measured_bmr)
        bmr_source = "用户实测"
    else:
        bmr = calc_bmr(args.weight, args.height, args.age, args.sex)
        bmr_source = "Mifflin-St Jeor 公式估算"

    factor, factor_desc = ACTIVITY[args.activity]
    tdee = bmr * factor

    warnings = []
    goal = getattr(args, "goal", None)
    g = GOALS.get(goal) if goal else None

    if g:
        target_kcal = tdee * (1 - g["deficit_pct"])
        daily_deficit = tdee - target_kcal
        total_deficit = daily_deficit * g["horizon_days"]
    else:
        delta_kg = args.weight - args.target_weight
        total_deficit = delta_kg * KCAL_PER_KG_FAT
        daily_deficit = total_deficit / (args.weeks * 7)

    # 护栏 1：缺口不超过 TDEE 的 25%（超过即显著增加肌肉流失）
    max_deficit = tdee * 0.25
    if daily_deficit > max_deficit:
        warnings.append(
            f"目标缺口 {daily_deficit:.0f} kcal/天 超过安全上限 "
            f"{max_deficit:.0f} kcal/天（TDEE 的 25%），已收窄至上限。"
        )
        daily_deficit = max_deficit

    daily_kcal = tdee - daily_deficit
    # 护栏 2：摄入不低于基础代谢的 1.1 倍
    floor_kcal = bmr * 1.1
    if daily_kcal < floor_kcal:
        warnings.append(
            f"目标摄入 {daily_kcal:.0f} kcal 低于基础代谢护栏 "
            f"{floor_kcal:.0f} kcal，已上调至护栏值（减脂速度相应放缓）。"
        )
        daily_kcal = floor_kcal

    # 护栏生效后重算实际缺口，避免"缺口"与"摄入"两个数字自相矛盾
    daily_deficit = tdee - daily_kcal

    # 蛋白：优先按瘦体重算（脂肪组织不需要蛋白）
    bf = getattr(args, "bodyfat", None)
    coef_lbm = g["protein_lbm"] if g else PROTEIN_PER_KG_LBM
    coef_bw = g["protein_bw"] if g else 1.8
    if bf:
        lbm = args.weight * (1 - bf / 100.0)
        protein_target = lbm * coef_lbm
        protein_source = f"瘦体重 {lbm:.1f} kg × {coef_lbm} g/kg LBM"
    else:
        protein_target = args.weight * coef_bw
        protein_source = f"体重 {args.weight:.1f} kg × {coef_bw}（未提供体脂率）"

    fat_min = args.weight * 0.6                 # 激素与脂溶性维生素
    carb_target = max(0, (daily_kcal - protein_target * 4 - fat_min * 9) / 4)

    return {
        "bmr": bmr, "bmr_source": bmr_source,
        "tdee": tdee, "factor": factor, "factor_desc": factor_desc,
        "daily_deficit": daily_deficit, "daily_kcal": daily_kcal,
        "protein_target": protein_target, "protein_source": protein_source,
        "fat_min": fat_min,
        "carb_target": carb_target,
        "goal": goal, "goal_desc": g["desc"] if g else "旧路径（按减重目标反推）",
        "weekly_loss": daily_deficit * 7 / KCAL_PER_KG_FAT,
        "warnings": warnings,
    }


def totals(combo):
    return {
        "kcal": sum(i["kcal"] for i in combo),
        "protein": sum(i["protein"] for i in combo),
        "fat": sum(i["fat"] for i in combo),
        "carb": sum(i["carb"] for i in combo),
        "sodium": sum(i["sodium"] for i in combo),
    }


def make_score(sodium_weight, coupon_ctx=None):
    """构造打分函数（越小越优）。

    词典序：热量偏离 >> 蛋白缺口 > 钠超标 > 蛋白密度。
    sodium_weight 越大，越倾向控钠（蛋白会让步）。

    coupon_ctx 非空时，叠加【券优先级激励】：**省钱额为主 + 临期紧迫度为辅**。
    优惠越大该组合得分越低（越容易被选中）；优惠额相当时，快过期的优先用掉。
    """
    COUPON_SAVE_W = 0.10     # 每省 1 元的激励量级（主排序）
    COUPON_URGENT_W = 0.20   # 临期紧迫度的激励量级（加分项）

    def _score(combo, kcal_target, protein_target):
        t = totals(combo)
        kcal_gap = abs(t["kcal"] - kcal_target) / max(kcal_target, 1)
        protein_gap = max(0, protein_target - t["protein"]) / max(protein_target, 1)
        sodium_penalty = max(0, t["sodium"] - 650) / 650
        density_bonus = -0.6 * (t["protein"] / max(t["kcal"], 1) * 100) / 10
        overshoot = max(0, kcal_gap - 0.15)     # 热量偏离 >15% 硬性不可接受

        coupon_bonus = 0.0
        if coupon_ctx is not None:
            # 张数按去重计，避免同一券在组合里被重复计入
            seen = set()
            for i in combo:
                c = coupon_ctx.lookup(i["name"])
                if c and c["title"] not in seen:
                    seen.add(c["title"])
                    saved, urg, _ = coupon_ctx.value_of(i["name"])
                    coupon_bonus += COUPON_SAVE_W * saved + COUPON_URGENT_W * urg

        return (100.0 * overshoot
                + 10.0 * kcal_gap
                + 3.0 * protein_gap
                + sodium_weight * sodium_penalty
                + density_bonus
                - coupon_bonus)
    return _score


def pick_meal(items, main_kinds, side_kinds, drink_kinds,
              kcal_target, protein_target, forbid, score_fn, max_sides=2,
              hard_cap=None):
    """槽位式求解：主食(必选1) + 配菜(0~max_sides) + 饮品(可选1)。

    同类去重：同一子类在一餐内至多出现一次，避免"两杯中杯奶铁"这类荒谬组合。

    hard_cap 非空时，只接受总热量 ≤ hard_cap 的组合；**无解则返回 None**。
    这是硬约束——仅靠打分函数的软惩罚不够：额度极紧时它仍会选出远超预算的组合。
    """
    def pool_of(kinds):
        return [i for i in items
                if classify(i["name"]) in kinds
                and i["name"] not in forbid
                and i["kcal"] > 0]

    mains = pool_of(main_kinds)
    side_pool = pool_of(side_kinds)
    sides = [None] + [[s] for s in side_pool]
    sides += [[a, b] for a, b in combinations(side_pool, 2)]
    drinks = [None] + [[d] for d in pool_of(drink_kinds)]

    best = None
    for m in mains:
        for s in sides:
            if s and any(classify(x["name"]) == classify(m["name"]) for x in s):
                continue
            if s and len(s) == 2 and classify(s[0]["name"]) == classify(s[1]["name"]):
                continue
            for d in drinks:
                if d and any(classify(x["name"]) == classify(d[0]["name"])
                             for x in ([m] + (s or []))):
                    continue
                combo = [m] + (s or []) + (d or [])
                if hard_cap is not None and \
                        sum(x["kcal"] for x in combo) > hard_cap:
                    continue
                sc = score_fn(combo, kcal_target, protein_target)
                if best is None or sc < best[0]:
                    best = (sc, combo)
    return best


def minimal_combo(items, slot, forbid):
    """额度不足时的兜底：取该餐次可选范围内热量最低的单个餐品。"""
    pool = [i for i in items
            if classify(i["name"]) in slot["main"]
            and i["name"] not in forbid
            and i["kcal"] > 0]
    if not pool:
        return []
    return [min(pool, key=lambda x: x["kcal"])]


def build_plan(items, target, sodium_weight=0.5, coupon_ctx=None):
    """生成全天三餐方案。早餐 25% / 午餐 40% / 晚餐 35%。

    coupon_ctx 非空时，求解会优先选用带临期券的餐品。
    """
    score_fn = make_score(sodium_weight, coupon_ctx)
    meals = [
        ("早餐", ["breakfast_main", "breakfast_side"], ["breakfast_side"], ["drink"], 0.25),
        ("午餐", ["burger"], ["side"], ["drink"], 0.40),
        ("晚餐", ["burger"], ["side"], ["drink"], 0.35),
    ]
    plan, used = [], set()
    for label, mk, sk, dk, ratio in meals:
        res = pick_meal(items, mk, sk, dk,
                        target["daily_kcal"] * ratio,
                        target["protein_target"] * ratio,
                        used, score_fn)
        if res:
            combo = res[1]
            used |= {i["name"] for i in combo}
            plan.append((label, combo,
                         target["daily_kcal"] * ratio,
                         target["protein_target"] * ratio))
    return plan


# 餐次槽位定义：任意餐次组合都可求解。
# w 为全天热量占比（早 25% / 午 40% / 晚 35%），仅用于给该餐次定"标准额度"。
MEAL_SLOTS = {
    "breakfast": {"label": "早餐", "main": ["breakfast_main", "breakfast_side"],
                  "side": ["breakfast_side"], "drink": ["drink"], "w": 0.25},
    "lunch": {"label": "午餐", "main": ["burger"], "side": ["side"],
              "drink": ["drink"], "w": 0.40},
    "dinner": {"label": "晚餐", "main": ["burger"], "side": ["side"],
               "drink": ["drink"], "w": 0.35},
    "snack": {"label": "加餐", "main": ["side", "dessert"], "side": [],
              "drink": ["drink"], "w": 0.15},
}

# 单餐额度上限系数：待解餐次最多拿到其「自然份额」的该倍数。
# 为什么需要这个上限：
#   剩余额度可能远超一餐的正常食量（例如只配晚餐，而早/午都没吃），
#   若不设上限就会把全天 2000+ kcal 塞进一顿晚餐，产出一份荒唐方案。
# 为什么是 1.30：这是产品判断，不是医学阈值 —— 取「比常规一餐最多多三成」，
#   既能消化掉常见的手误/少报带来的余量，又不会让单餐失控。
SLOT_SCALE_CAP = 1.30


def build_slot_plan(items, target, solve_keys, known_meals,
                    sodium_weight=0.5, coupon_ctx=None):
    """按指定餐次求解，并扣除已知餐次（已吃或计划吃）占用的额度。

    solve_keys  : 需要配麦当劳的餐次，如 ['breakfast'] / ['breakfast','lunch']
    known_meals : 已知餐次 [{'label':'午餐','kcal':800,'protein':30,'sodium':1200}]

    额度分配规则：
      每个待解餐次的标准份额 = 全天目标 × 该餐次权重
      剩余额度 = 全天目标 − 已知餐次合计
      scale = clamp(剩余额度 / 待解餐次标准份额合计, 0, SLOT_SCALE_CAP)
        · scale > 1 —— 剩余多，等比放大（方案会随已知餐次变化，额度不浪费）
        · scale < 1 —— 剩余少，等比压缩
        · 上限 SLOT_SCALE_CAP —— 单餐不超过自然份额的该倍数
          （防止「只配早餐」时把全天额度塞进一顿早餐）

    ⚠️ 历史缺陷（v2.4.0 修复）：旧逻辑是 `剩余 ≥ 标准 → scale = 1`，
       导致「已知合计 ≤ 全天 − 标准份额」的整个区间内方案**完全不变**，
       用户改了早餐/午餐却看不到任何变化，而且剩余额度永远用不上。

    返回 (plan, info)。plan 元素为 (餐次名, 组合, 热量目标, 蛋白目标)。
    """
    score_fn = make_score(sodium_weight, coupon_ctx)

    known_kcal = sum(float(m.get("kcal") or 0) for m in known_meals)
    known_protein = sum(float(m.get("protein") or 0) for m in known_meals)
    known_sodium = sum(float(m.get("sodium") or 0) for m in known_meals)

    left_kcal = target["daily_kcal"] - known_kcal
    left_protein = target["protein_target"] - known_protein

    std = {k: target["daily_kcal"] * MEAL_SLOTS[k]["w"] for k in solve_keys}
    total_std = sum(std.values())
    if total_std <= 0:
        scale = 0.0
    else:
        # 尺度 = 剩余额度 / 待解餐次标准份额合计，夹在 [0, SLOT_SCALE_CAP]：
        #   > 1  剩余多 → 按比例放大，让方案【响应已知餐次的变化】且把额度用上
        #   < 1  剩余少 → 等比压缩
        #   上限 单餐不得超过自然份额的 SLOT_SCALE_CAP 倍，
        #        否则「只配早餐」时会把全天额度塞进一顿早餐
        scale = min(SLOT_SCALE_CAP, max(0.0, left_kcal / total_std))

    plan, used, notes = [], set(), {}
    for k in solve_keys:
        slot = MEAL_SLOTS[k]
        kcal_t = std[k] * scale
        prot_t = target["protein_target"] * slot["w"] * scale
        if kcal_t <= 1.0:
            plan.append((slot["label"], [], kcal_t, prot_t))
            continue
        # 硬约束：组合总热量不得超过该餐次额度的 115%
        hard_cap = kcal_t * 1.15
        res = pick_meal(items, slot["main"], slot["side"], slot["drink"],
                        kcal_t, prot_t, used, score_fn, hard_cap=hard_cap)
        if res:
            combo = res[1]
        else:
            # 无可行解：给最低热量兜底，并如实标注超出多少（不硬凑）
            combo = minimal_combo(items, slot, used)
            if combo:
                actual = sum(i["kcal"] for i in combo)
                notes[slot["label"]] = (
                    f"额度 {kcal_t:.0f} kcal 内无可行组合；"
                    f"已给最低热量兜底 {actual:.0f} kcal"
                    f"（超出 {actual - kcal_t:.0f} kcal）")
            else:
                notes[slot["label"]] = "该餐次内无可选餐品"
        used |= {i["name"] for i in combo}
        plan.append((slot["label"], combo, kcal_t, prot_t))

    info = {
        "known_kcal": known_kcal, "known_protein": known_protein,
        "known_sodium": known_sodium,
        "left_kcal": left_kcal, "left_protein": left_protein,
        "scale": scale, "solve_keys": solve_keys,
        "solve_labels": [MEAL_SLOTS[k]["label"] for k in solve_keys],
        "notes": notes,
    }
    return plan, info


def plan_totals(plan):
    tot = {"kcal": 0.0, "protein": 0.0, "fat": 0.0, "carb": 0.0, "sodium": 0.0}
    for _, combo, _, _ in plan:
        for k, v in totals(combo).items():
            tot[k] += v
    return tot


def conflict_diagnosis(plan, target):
    """目标冲突诊断：判断 热量/蛋白/钠 三目标是否不可兼得。"""
    t = plan_totals(plan)
    issues = []
    if t["sodium"] > SODIUM_DAILY_CAP:
        issues.append(
            f"钠 {t['sodium']:.0f} mg，超 WHO 建议上限 "
            f"{t['sodium'] - SODIUM_DAILY_CAP:.0f} mg（{t['sodium'] / SODIUM_DAILY_CAP:.1f} 倍）"
        )
    if t["protein"] < target["protein_target"] * 0.95:
        issues.append(
            f"蛋白 {t['protein']:.0f} g，低于目标 {target['protein_target']:.0f} g"
            f"（缺口 {target['protein_target'] - t['protein']:.0f} g）"
        )
    if abs(t["kcal"] - target["daily_kcal"]) > target["daily_kcal"] * 0.05:
        issues.append(
            f"热量偏离目标 {t['kcal'] - target['daily_kcal']:+.0f} kcal"
        )
    return t, issues


def fmt(plan, target, args, sodium_weight, label, coupon_ctx=None):
    out = []
    out.append("=" * 62)
    out.append(f"麦麦减脂搭子 · 配餐方案［{label}］")
    out.append("=" * 62)
    if target.get("goal"):
        out.append(f"目标模式：{target['goal_desc']}   体重 {args.weight}kg")
    else:
        out.append(f"体重 {args.weight}kg → 目标 {args.target_weight}kg，"
                   f"周期 {args.weeks} 周")
    src = target.get("bmr_source", "")
    out.append(f"基础代谢 BMR：{target['bmr']:.0f} kcal"
               + (f"（{src}）" if src else ""))
    out.append(f"每日消耗 TDEE：{target['tdee']:.0f} kcal（{target['factor_desc']}）"
               f"  ← 摄入目标是按 TDEE 算，不是按 BMR")
    if target["daily_deficit"] >= 0:
        out.append(f"每日缺口：{target['daily_deficit']:.0f} kcal → 预期每周减 "
                   f"{target['weekly_loss']:.2f} kg")
    else:
        out.append(f"每日盈余：{-target['daily_deficit']:.0f} kcal → 预期每周增 "
                   f"{-target['weekly_loss']:.2f} kg")
    out.append(f"每日摄入目标：{target['daily_kcal']:.0f} kcal")
    out.append(f"蛋白目标：{target['protein_target']:.0f} g"
               f"（{target.get('protein_source', '')}）")
    out.append(f"脂肪下限：{target['fat_min']:.0f} g"
               f"｜碳水目标：{target['carb_target']:.0f} g")
    for w in target["warnings"]:
        out.append(f"⚠️  {w}")

    # 与「摄入不超过基础代谢」这一常见误区做对照，让代价可见
    if target.get("goal") and target["bmr"] < target["daily_kcal"] - 50:
        bmr_only = target["bmr"]
        gap_bmr = target["tdee"] - bmr_only
        pct_bmr = gap_bmr / target["tdee"] * 100
        if pct_bmr > 25:
            flag = "已超 25% 安全上限 → 会掉肌肉"
        elif pct_bmr > 20:
            flag = "逼近上限，保肌吃紧"
        else:
            flag = "缺口偏小，减得慢"
        out.append("")
        out.append("【摄入目标对照：为什么不锚定 BMR】")
        out.append(f"  若按「不超过 BMR」  {bmr_only:.0f} kcal"
                   f"  → 缺口 {gap_bmr:.0f}（{pct_bmr:.1f}%）｜{flag}")
        out.append(f"  本工具建议摄入      {target['daily_kcal']:.0f} kcal"
                   f"  → 缺口 {target['daily_deficit']:.0f}"
                   f"（{target['daily_deficit']/target['tdee']*100:.1f}%）"
                   f"｜锚定 TDEE，保住肌肉")
    out.append("-" * 62)

    for mlabel, combo, kcal_t, prot_t in plan:
        t = totals(combo)
        out.append(f"\n【{mlabel}】目标 {kcal_t:.0f} kcal / 蛋白 {prot_t:.0f} g")
        for it in combo:
            line = (f"  · {it['name']:<22} {it['kcal']:>6.0f} kcal  "
                    f"蛋白 {it['protein']:>5.0f}g  钠 {it['sodium']:>5.0f}mg")
            if coupon_ctx is not None:
                c = coupon_ctx.lookup(it["name"])
                if c:
                    hours = c.get("_until")
                    tip = f"  🎫用券「{c['title']}」"
                    if c["urgency"] >= 0.6:
                        tip += " ⏰临期"
                    line += tip
            out.append(line)
        out.append(f"  小计：{t['kcal']:.0f} kcal｜蛋白 {t['protein']:.0f}g"
                   f"｜脂肪 {t['fat']:.0f}g｜碳水 {t['carb']:.0f}g｜钠 {t['sodium']:.0f}mg")

    t, issues = conflict_diagnosis(plan, target)
    out.append("\n" + "=" * 62)
    out.append("全天合计")
    out.append(f"热量 {t['kcal']:.0f} kcal（目标 {target['daily_kcal']:.0f}）"
               f"｜偏差 {t['kcal'] - target['daily_kcal']:+.0f} kcal")
    out.append(f"蛋白 {t['protein']:.0f} g（目标 {target['protein_target']:.0f}）"
               f"｜缺口 {target['protein_target'] - t['protein']:+.0f} g")
    out.append(f"脂肪 {t['fat']:.0f} g｜碳水 {t['carb']:.0f} g")
    out.append(f"钠   {t['sodium']:.0f} mg（WHO 建议每日 < {SODIUM_DAILY_CAP} mg）")
    for msg in issues:
        out.append(f"⚠️  {msg}")
    out.append("=" * 62)

    if coupon_ctx is not None:
        out.extend(render_coupon_report(plan, coupon_ctx))
    return "\n".join(out)


def fmt_slot(plan, target, args, label, info, known_meals, coupon_ctx=None):
    """渲染餐次填空方案：已知餐次 → 额度分配 → 待解餐次 → 全天合计。"""
    out = []
    W = 66
    out.append("=" * W)
    out.append(f"麦麦减脂搭子 · 餐次配餐［{label}］")
    out.append("=" * W)

    if target.get("goal"):
        out.append(f"目标模式：{target['goal_desc']}   体重 {args.weight}kg")
    else:
        out.append(f"体重 {args.weight}kg → 目标 {args.target_weight}kg，"
                   f"周期 {args.weeks} 周")
    src = target.get("bmr_source", "")
    out.append(f"基础代谢 BMR：{target['bmr']:.0f} kcal"
               + (f"（{src}）" if src else ""))
    out.append(f"每日消耗 TDEE：{target['tdee']:.0f} kcal（{target['factor_desc']}）")
    if target["daily_deficit"] >= 0:
        out.append(f"每日缺口：{target['daily_deficit']:.0f} kcal → 预期每周减 "
                   f"{target['weekly_loss']:.2f} kg")
    else:
        out.append(f"每日盈余：{-target['daily_deficit']:.0f} kcal → 预期每周增 "
                   f"{-target['weekly_loss']:.2f} kg")
    out.append(f"每日摄入目标：{target['daily_kcal']:.0f} kcal")
    out.append(f"蛋白目标：{target['protein_target']:.0f} g"
               f"（{target.get('protein_source', '')}）")
    for w in target["warnings"]:
        out.append(f"⚠️  {w}")

    # ── 已知餐次 ──
    if known_meals:
        out.append("")
        out.append("-" * W)
        out.append("【已知餐次】（不配麦当劳，仅占用额度）")
        out.append("-" * W)
        for m in known_meals:
            na = m.get("sodium")
            na_s = f"｜钠 {float(na):.0f}mg" if na else ""
            out.append(f"  · {m['label']:<8}{m['kcal']:>6.0f} kcal"
                       f"｜蛋白 {float(m.get('protein') or 0):>5.0f} g{na_s}")
        out.append(f"  合计      {info['known_kcal']:>6.0f} kcal"
                   f"｜蛋白 {info['known_protein']:>5.0f} g"
                   + (f"｜钠 {info['known_sodium']:.0f} mg"
                      if info["known_sodium"] else ""))

    # ── 额度分配 ──
    out.append("")
    out.append("-" * W)
    out.append("【麦当劳待配餐次 · 额度分配】")
    out.append("-" * W)
    left_k = info["left_kcal"]
    if left_k < 0:
        out.append(f"  ⚠️  已知餐次已超出目标 {-left_k:.0f} kcal —— 剩余额度为负。")
        out.append("     今天已无法达成目标，下方只给最低热量建议。")
    else:
        out.append(f"  剩余额度   {left_k:.0f} kcal｜蛋白 "
                   f"{info['left_protein']:.0f} g（= 目标 − 已知）")
        if info["scale"] < 0.999:
            out.append(f"  额度不足标准分配，已按 {info['scale']*100:.0f}% "
                       f"等比压缩各餐次")
    out.append("-" * W)

    # ── 各餐次方案 ──
    for mlabel, combo, kcal_t, prot_t in plan:
        out.append("")
        note = info.get("notes", {}).get(mlabel)
        if not combo:
            out.append(f"【{mlabel}】额度不足以配餐（目标 {kcal_t:.0f} kcal）")
            if note:
                out.append(f"  ⚠️  {note}")
            continue
        t = totals(combo)
        out.append(f"【{mlabel}】目标 {kcal_t:.0f} kcal / 蛋白 {prot_t:.0f} g")
        for it in combo:
            out.append(f"  · {it['name']:<22} {it['kcal']:>6.0f} kcal"
                       f"  蛋白 {it['protein']:>5.0f}g  钠 {it['sodium']:>5.0f}mg")
        out.append(f"  小计：{t['kcal']:.0f} kcal｜蛋白 {t['protein']:.0f}g"
                   f"｜脂肪 {t['fat']:.0f}g｜碳水 {t['carb']:.0f}g"
                   f"｜钠 {t['sodium']:.0f}mg")
        if note:
            out.append(f"  ⚠️  {note}")

    # ── 全天合计（已知 + 麦当劳）──
    pt = plan_totals(plan)
    tot_kcal = pt["kcal"] + info["known_kcal"]
    tot_prot = pt["protein"] + info["known_protein"]
    tot_na = pt["sodium"] + info["known_sodium"]
    dk = target["daily_kcal"] - tot_kcal
    dp = target["protein_target"] - tot_prot

    out.append("")
    out.append("=" * W)
    out.append("【全天合计】（已知餐次 + 麦当劳配餐）")
    out.append("=" * W)
    out.append(f"  热量   {tot_kcal:>7.0f} / {target['daily_kcal']:.0f} kcal"
               f"     " + (f"剩余 {dk:.0f}" if dk >= 0 else f"超标 {abs(dk):.0f}"))
    out.append(f"  蛋白   {tot_prot:>7.0f} / {target['protein_target']:.0f} g"
               f"     " + (f"缺口 {dp:.0f}" if dp > 0 else f"超出 {abs(dp):.0f}"))
    if tot_na:
        if tot_na <= SODIUM_DAILY_CAP:
            na_note = "✅ 在限内"
        else:
            na_note = f"❌ 超上限 {tot_na - SODIUM_DAILY_CAP:.0f} mg"
        out.append(f"  钠     {tot_na:>7.0f} / {SODIUM_DAILY_CAP} mg    {na_note}")
    out.append("=" * W)

    if coupon_ctx is not None:
        out.extend(render_coupon_report(plan, coupon_ctx))
    return "\n".join(out)


def render_coupon_tradeoff(plan_coupon, plan_base, coupon_ctx):
    """用券 vs 不用券 的取舍对比。

    这是「不美化结果」原则的延伸：既然用券会挤占营养，
    就必须把这个代价摆出来，让用户自己判断值不值。
    """
    tc, tb = plan_totals(plan_coupon), plan_totals(plan_base)

    def saved_of(plan):
        tot = 0.0
        titles = set()
        for _, combo, _, _ in plan:
            for it in combo:
                c = coupon_ctx.lookup(it["name"])
                if c and c["title"] not in titles:
                    titles.add(c["title"])
                    base = float(c.get("listPrice") or 0)
                    final = float(c.get("couponPrice") or base)
                    tot += max(0.0, round(base - final, 2))
        return tot

    sc, sb = saved_of(plan_coupon), saved_of(plan_base)
    d_prot = tc["protein"] - tb["protein"]
    d_kcal = tc["kcal"] - tb["kcal"]
    d_na = tc["sodium"] - tb["sodium"]
    d_money = sc - sb

    same = (abs(d_prot) < 0.5 and abs(d_kcal) < 5 and abs(d_money) < 0.005)
    if same:
        return ""

    out = []
    out.append("")
    out.append("─" * 62)
    out.append("用券的代价（对比不用券的方案）")
    out.append("─" * 62)
    out.append(f"  蛋白 {d_prot:+.0f} g｜热量 {d_kcal:+.0f} kcal"
               f"｜钠 {d_na:+.0f} mg｜省下 ¥{d_money:+.2f}")
    if d_prot < -0.5 and d_money > 0:
        out.append("  ⚠️  用券省了钱但牺牲了蛋白。若该券优惠额不大，")
        out.append("     建议把它单独用掉（比如只买那杯咖啡），不挤进正餐方案。")
    out.append("─" * 62)
    return "\n".join(out)


def render_coupon_report(plan, coupon_ctx):
    """渲染券使用情况：优先级排序 / 已用 / 单独使用建议 / 被排除 / 未匹配。"""
    out = []
    out.append("")
    out.append("=" * 62)
    out.append("券使用情况")
    out.append("=" * 62)

    used_titles = set()
    used = []
    for _, combo, _, _ in plan:
        for it in combo:
            c = coupon_ctx.lookup(it["name"])
            if c and c["title"] not in used_titles:
                used_titles.add(c["title"])
                used.append(c)

    # 券优先级排序：省钱额为主、临期加分为辅
    ranked = []
    for c in coupon_ctx.usable:
        saved, urg, score = coupon_ctx.value_of(c.get("menuName") or c["title"])
        ranked.append((score, saved, urg, c))
    ranked.sort(key=lambda x: (-x[0], x[3]["title"]))

    total_saved = 0.0
    if used:
        for c in used:
            base = float(c.get("listPrice") or 0)
            final = float(c.get("couponPrice") or base)
            saved = max(0.0, round(base - final, 2))
            total_saved += saved
            until = c.get("validUntil", "—")
            tag = " ⏰临期" if c["urgency"] >= 0.6 else ""
            if saved > 0:
                out.append(f"  🎫 {c['title']}  ¥{base:.2f} → ¥{final:.2f}"
                           f"  省 ¥{saved:.2f}（{until} 到期）{tag}")
            else:
                out.append(f"  🎫 {c['title']}  （{until} 到期）{tag}")
        if total_saved > 0:
            out.append("  ─────────────────────────")
            out.append(f"  本次方案用券 {len(used)} 张，立省 ¥{total_saved:.2f}")
    else:
        out.append("  本次方案未用到任何可用券。")

    if ranked:
        out.append("")
        out.append("  券优先级（省钱额为主 + 临期加分）：")
        for i, (score, saved, urg, c) in enumerate(ranked, 1):
            money = f"省 ¥{saved:.2f}" if saved > 0 else "价格未知"
            tag = " ⏰临期" if urg >= 0.6 else ""
            mark = " ✔本方案已用" if c["title"] in used_titles else ""
            out.append(f"   {i}. {c['title']:<20} {money:>9}"
                       f"  综合 {score:>4.2f}{tag}{mark}")

    # 未用上的券：给出可执行的单独使用建议
    missed = [x for x in ranked if x[3]["title"] not in used_titles]
    if missed and not used:
        out.append("")
        out.append("  ⚠️  本方案没用上券 —— 券多绑在低蛋白/低热量商品上，")
        out.append("     与当前高蛋白目标冲突。用券不等于划算，代价见下方对比。")
    if missed:
        out.append("")
        out.append("  未用上的券 · 单独使用建议：")
        for score, saved, urg, c in missed:
            until = c.get("validUntil", "—")
            if urg >= 0.6:
                when = f"⏰ {until} 到期，建议尽快单独下一单用掉"
            elif saved > 0:
                when = f"不急（{until}），但属你手上优惠较大的几张"
            else:
                when = f"{until} 到期"
            out.append(f"     · {c['title']} —— {when}")

    if coupon_ctx.excluded:
        out.append("")
        out.append(f"  ❌ 被排除的券（{len(coupon_ctx.excluded)} 张，不计入优惠）：")
        for c in coupon_ctx.excluded:
            out.append(f"     · {c['title']}  —— {c.get('_reason', '不可用')}")

    # 未匹配：可用但拿不到商品名/编码，无法与餐品对应
    unmapped = [c for c in coupon_ctx.usable if not c["_key"]]
    if unmapped:
        out.append("")
        out.append("  ⚪ 未能匹配到餐品的券（缺商品编码，本工具不臆测映射）：")
        for c in unmapped:
            out.append(f"     · {c['title']}")
    out.append("=" * 62)
    return out


# 各参数的合理区间（用于拦截明显的输入错误，如把 78 敲成 780）
PLAUSIBLE = {
    "体重": (25, 300),
    "身高": (100, 250),
    "年龄": (10, 100),
    "目标体重": (25, 300),
}


def _check_spot(value, name):
    """输入合理性校验。越界直接报错，避免算出荒唐方案。"""
    lo, hi = PLAUSIBLE[name]
    if not (lo <= value <= hi):
        print(f"❌ {name} {value} 超出合理范围（{lo}~{hi}），请检查是否输错")
        raise SystemExit(1)


def parse_known(raw_list):
    """解析 --known 参数：'午餐=800,30,1200' → dict。

    格式：名称=热量,蛋白[,钠]。钠可省略。
    已吃与计划吃在数学上等价（都占用额度），故统一处理。
    """
    out = []
    for raw in raw_list:
        if "=" not in raw:
            raise ValueError(
                f"--known 格式应为 名称=热量,蛋白[,钠]，收到：{raw}")
        name, nums = raw.split("=", 1)
        name = name.strip()
        if not name:
            raise ValueError(f"--known 缺少餐次名称：{raw}")
        parts = [x.strip() for x in nums.split(",")]
        if len(parts) < 2:
            raise ValueError(f"--known 至少需要热量与蛋白两项：{raw}")
        try:
            kcal = float(parts[0])
            protein = float(parts[1])
            sodium = float(parts[2]) if len(parts) > 2 and parts[2] else 0.0
        except ValueError:
            raise ValueError(f"--known 数值无法解析：{raw}")
        out.append({"label": name, "kcal": kcal,
                    "protein": protein, "sodium": sodium})
    return out


def main():
    p = argparse.ArgumentParser(description="麦麦减脂搭子 · 配餐优化引擎")
    p.add_argument("--weight", type=float, required=True, help="当前体重 kg")
    p.add_argument("--height", type=float, required=True, help="身高 cm")
    p.add_argument("--age", type=int, required=True, help="年龄")
    p.add_argument("--sex", choices=["male", "female"], required=True)
    p.add_argument("--activity", choices=list(ACTIVITY), default="light")
    p.add_argument("--target-weight", type=float, default=None,
                   help="期望体重 kg（与 --weeks 搭配；若用 --goal 则不必填）")
    p.add_argument("--weeks", type=float, default=12, help="期望达成周期（周）")
    p.add_argument("--goal", choices=list(GOALS), default=None,
                   help="目标模式：cut=减脂 / recomp=增肌减脂 / gain=增肌。"
                        "指定后锚点改为 TDEE，无需 target-weight")
    p.add_argument("--bodyfat", type=float, default=None,
                   help="体脂率 %%（体脂秤/InBody 等）。提供后蛋白按【瘦体重】计算")
    p.add_argument("--bmr", type=float, default=None,
                   help="实测基础代谢率 kcal（体脂秤/InBody 等）。"
                        "提供后优先于公式估算")
    p.add_argument("--mode", choices=["protein", "sodium", "both"], default="both",
                   help="protein=蛋白优先 / sodium=控钠优先 / both=两种都给")
    p.add_argument("--coupons", default=None,
                   help="券快照 JSON 路径。提供后配餐会优先使用最优惠与临期券")
    p.add_argument("--solve", default="breakfast,lunch,dinner",
                   help="要配麦当劳的餐次，逗号分隔（breakfast/lunch/dinner/snack）。"
                        "例：只配早餐用 --solve breakfast；"
                        "配早餐+午餐用 --solve breakfast,lunch。默认三餐全配")
    p.add_argument("--known", action="append", default=[],
                   help="已知餐次（已吃或计划吃），格式 名称=热量,蛋白[,钠]，"
                        "可重复。例：--known \"午餐=800,30,1200\"")
    args = p.parse_args()

    _check_spot(args.weight, "体重")
    _check_spot(args.height, "身高")
    _check_spot(args.age, "年龄")
    if args.goal is None:
        if args.target_weight is None:
            print("❌ 需要 --target-weight（期望体重）或 --goal（目标模式），"
                  "至少给一个")
            return 1
        _check_spot(args.target_weight, "目标体重")
        if args.weeks <= 0:
            print("❌ 周期必须大于 0 周")
            return 1
    if args.bodyfat is not None and not (2 <= args.bodyfat <= 65):
        print(f"❌ 体脂率 {args.bodyfat}% 超出合理范围（2~65）")
        return 1
    if args.bmr is not None and args.bmr <= 0:
        print("❌ 基础代谢率必须大于 0")
        return 1

    # 解析要配麦当劳的餐次
    solve_keys = [x.strip() for x in args.solve.split(",") if x.strip()]
    if not solve_keys:
        print("❌ --solve 不能为空")
        return 1
    bad = [k for k in solve_keys if k not in MEAL_SLOTS]
    if bad:
        print(f"❌ 未知餐次：{', '.join(bad)}"
              f"（可选：{', '.join(MEAL_SLOTS)}）")
        return 1
    if len(set(solve_keys)) != len(solve_keys):
        print("❌ --solve 中存在重复餐次")
        return 1

    # 解析已知餐次（已吃或计划吃）
    try:
        known = parse_known(args.known)
    except ValueError as e:
        print(f"❌ {e}")
        return 1
    for m in known:
        if not (0 <= m["kcal"] <= 5000):
            print(f"❌ 已知餐次「{m['label']}」热量 {m['kcal']:g} 不合理（0~5000）")
            return 1
        if not (0 <= m["protein"] <= 400):
            print(f"❌ 已知餐次「{m['label']}」蛋白 {m['protein']:g} 不合理（0~400）")
            return 1
        if m["sodium"] and not (0 <= m["sodium"] <= 20000):
            print(f"❌ 已知餐次「{m['label']}」钠 {m['sodium']:g} 不合理（0~20000）")
            return 1

    items = load_items()
    target = build_target(args)

    # 券上下文（可选）：让配餐优先使用临期券
    coupon_ctx = None
    if args.coupons:
        try:
            from coupon_context import CouponContext, load_coupons
        except ImportError:
            print("❌ 找不到 coupon_context 模块，请确认 scripts/ 目录完整")
            return 1
        try:
            usable, excluded, cmeta = load_coupons(args.coupons)
        except FileNotFoundError:
            print(f"❌ 券快照文件不存在：{args.coupons}")
            return 1
        except (json.JSONDecodeError, ValueError) as e:
            print(f"❌ 券快照格式错误：{e}")
            return 1
        coupon_ctx = CouponContext(usable, excluded, cmeta)
        s = coupon_ctx.summary()
        print(f"[券上下文] 可用 {s['usable']} 张（其中临期 {s['urgent']} 张）"
              f"｜排除 {s['excluded']} 张")

    modes = [("蛋白优先", 0.5), ("控钠优先", 4.0)] if args.mode == "both" \
        else [("蛋白优先", 0.5)] if args.mode == "protein" \
        else [("控钠优先", 4.0)]

    for label, sw in modes:
        plan, info = build_slot_plan(items, target, solve_keys, known,
                                     sodium_weight=sw, coupon_ctx=coupon_ctx)
        print(fmt_slot(plan, target, args, label, info, known,
                       coupon_ctx=coupon_ctx))
        if coupon_ctx is not None:
            # 同时算一份"不用券"的方案，把用券的营养代价如实摆出来
            base_plan, _ = build_slot_plan(items, target, solve_keys, known,
                                           sodium_weight=sw, coupon_ctx=None)
            tradeoff = render_coupon_tradeoff(plan, base_plan, coupon_ctx)
            if tradeoff:
                print(tradeoff)
        print()
        print()

    # 目标冲突诊断
    print("=" * 62)
    print("目标冲突诊断")
    print("=" * 62)
    plan_p, info_p = build_slot_plan(items, target, solve_keys, known,
                                     sodium_weight=0.5)
    plan_s, _ = build_slot_plan(items, target, solve_keys, known,
                                sodium_weight=4.0)
    tp, ts = plan_totals(plan_p), plan_totals(plan_s)
    # 只有「三餐全配 + 无已知餐次」才是纯麦当劳场景，
    # 此时缺的部分无处可补，才谈得上"不可兼得"。
    full_mcd = (set(solve_keys) == {"breakfast", "lunch", "dinner"}
                and not known)
    scope = "纯麦当劳餐单" if full_mcd else "麦当劳这部分"
    print(f"  蛋白优先：蛋白 {tp['protein']:.0f} g | 钠 {tp['sodium']:.0f} mg")
    print(f"  控钠优先：蛋白 {ts['protein']:.0f} g | 钠 {ts['sodium']:.0f} mg")
    print()
    if not full_mcd:
        print(f"  注：当前只配 {len(solve_keys)} 个餐次，其余餐次由非麦当劳补足，")
        print(f"      故此处只对比{scope}的营养，不作「不可兼得」判定。")
    elif tp["sodium"] > SODIUM_DAILY_CAP and ts["protein"] < target["protein_target"] * 0.95:
        print(f"  结论：在{scope}上，「热量达标 + 蛋白达标 + 钠达标」三者不可兼得。")
        print(f"  · 要蛋白 {target['protein_target']:.0f} g，钠会到 {tp['sodium']:.0f} mg 左右")
        print(f"  · 要控钠 {SODIUM_DAILY_CAP} mg 以内，蛋白只有 {ts['protein']:.0f} g 左右")
        print("  建议：选定一侧作为主线，另一侧用非麦当劳食物补齐（如无糖希腊酸奶、")
        print("        水煮鸡胸、蛋白粉），并在方案中如实标注缺口。")
    print()
    print(f"[数据源] 麦当劳官方营养表 {len(items)} 项｜求解方式：槽位枚举 + 词典序打分择优")


if __name__ == "__main__":
    sys.exit(main())
