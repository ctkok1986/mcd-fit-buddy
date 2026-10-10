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
import os
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
    """计算每日热量与宏量目标，并施加安全护栏。"""
    bmr = calc_bmr(args.weight, args.height, args.age, args.sex)
    factor, factor_desc = ACTIVITY[args.activity]
    tdee = bmr * factor

    delta_kg = args.weight - args.target_weight
    total_deficit = delta_kg * KCAL_PER_KG_FAT
    daily_deficit = total_deficit / (args.weeks * 7)

    warnings = []
    # 护栏 1：缺口不超过 TDEE 的 25%
    max_deficit = tdee * 0.25
    if daily_deficit > max_deficit:
        warnings.append(
            f"目标缺口 {daily_deficit:.0f} kcal/天 超过安全上限 "
            f"{max_deficit:.0f} kcal/天（TDEE 的 25%），已收窄至上限。"
            f"按此速度需约 {total_deficit / max_deficit / 7:.1f} 周。"
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

    protein_target = args.weight * 1.8          # 减脂期保肌
    fat_min = args.weight * 0.6                 # 激素与脂溶性维生素
    carb_target = max(0, (daily_kcal - protein_target * 4 - fat_min * 9) / 4)

    return {
        "bmr": bmr, "tdee": tdee, "factor": factor, "factor_desc": factor_desc,
        "daily_deficit": daily_deficit, "daily_kcal": daily_kcal,
        "protein_target": protein_target, "fat_min": fat_min,
        "carb_target": carb_target,
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


def make_score(sodium_weight):
    """构造打分函数（越小越优）。

    词典序：热量偏离 >> 蛋白缺口 > 钠超标 > 蛋白密度。
    sodium_weight 越大，越倾向控钠（蛋白会让步）。
    """
    def _score(combo, kcal_target, protein_target):
        t = totals(combo)
        kcal_gap = abs(t["kcal"] - kcal_target) / max(kcal_target, 1)
        protein_gap = max(0, protein_target - t["protein"]) / max(protein_target, 1)
        sodium_penalty = max(0, t["sodium"] - 650) / 650
        density_bonus = -0.6 * (t["protein"] / max(t["kcal"], 1) * 100) / 10
        overshoot = max(0, kcal_gap - 0.15)     # 热量偏离 >15% 硬性不可接受
        return (100.0 * overshoot
                + 10.0 * kcal_gap
                + 3.0 * protein_gap
                + sodium_weight * sodium_penalty
                + density_bonus)
    return _score


def pick_meal(items, main_kinds, side_kinds, drink_kinds,
              kcal_target, protein_target, forbid, score_fn, max_sides=2):
    """槽位式求解：主食(必选1) + 配菜(0~max_sides) + 饮品(可选1)。

    同类去重：同一子类在一餐内至多出现一次，避免"两杯中杯奶铁"这类荒谬组合。
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
                sc = score_fn(combo, kcal_target, protein_target)
                if best is None or sc < best[0]:
                    best = (sc, combo)
    return best


def build_plan(items, target, sodium_weight=0.5):
    """生成全天三餐方案。早餐 25% / 午餐 40% / 晚餐 35%。"""
    score_fn = make_score(sodium_weight)
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


def fmt(plan, target, args, sodium_weight, label):
    out = []
    out.append("=" * 62)
    out.append(f"麦麦减脂搭子 · 配餐方案［{label}］")
    out.append("=" * 62)
    out.append(f"体重 {args.weight}kg → 目标 {args.target_weight}kg，周期 {args.weeks} 周")
    out.append(f"基础代谢 BMR：{target['bmr']:.0f} kcal")
    out.append(f"每日消耗 TDEE：{target['tdee']:.0f} kcal（{target['factor_desc']}）")
    out.append(f"每日缺口：{target['daily_deficit']:.0f} kcal → 预期每周减 "
               f"{target['weekly_loss']:.2f} kg")
    out.append(f"每日摄入目标：{target['daily_kcal']:.0f} kcal")
    out.append(f"蛋白目标：{target['protein_target']:.0f} g｜脂肪下限：{target['fat_min']:.0f} g"
               f"｜碳水目标：{target['carb_target']:.0f} g")
    for w in target["warnings"]:
        out.append(f"⚠️  {w}")
    out.append("-" * 62)

    for mlabel, combo, kcal_t, prot_t in plan:
        t = totals(combo)
        out.append(f"\n【{mlabel}】目标 {kcal_t:.0f} kcal / 蛋白 {prot_t:.0f} g")
        for it in combo:
            out.append(f"  · {it['name']:<22} {it['kcal']:>6.0f} kcal  "
                       f"蛋白 {it['protein']:>5.0f}g  钠 {it['sodium']:>5.0f}mg")
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
    return "\n".join(out)


def main():
    p = argparse.ArgumentParser(description="麦麦减脂搭子 · 配餐优化引擎")
    p.add_argument("--weight", type=float, required=True, help="当前体重 kg")
    p.add_argument("--height", type=float, required=True, help="身高 cm")
    p.add_argument("--age", type=int, required=True, help="年龄")
    p.add_argument("--sex", choices=["male", "female"], required=True)
    p.add_argument("--activity", choices=list(ACTIVITY), default="light")
    p.add_argument("--target-weight", type=float, required=True)
    p.add_argument("--weeks", type=float, default=12, help="期望达成周期（周）")
    p.add_argument("--mode", choices=["protein", "sodium", "both"], default="both",
                   help="protein=蛋白优先 / sodium=控钠优先 / both=两种都给")
    args = p.parse_args()

    items = load_items()
    target = build_target(args)

    modes = [("蛋白优先", 0.5), ("控钠优先", 4.0)] if args.mode == "both" \
        else [("蛋白优先", 0.5)] if args.mode == "protein" \
        else [("控钠优先", 4.0)]

    for label, sw in modes:
        plan = build_plan(items, target, sodium_weight=sw)
        print(fmt(plan, target, args, sw, label))
        print()

    # 目标冲突诊断
    print("=" * 62)
    print("目标冲突诊断")
    print("=" * 62)
    plan_p = build_plan(items, target, sodium_weight=0.5)
    plan_s = build_plan(items, target, sodium_weight=4.0)
    tp, ts = plan_totals(plan_p), plan_totals(plan_s)
    print(f"  蛋白优先：蛋白 {tp['protein']:.0f} g | 钠 {tp['sodium']:.0f} mg")
    print(f"  控钠优先：蛋白 {ts['protein']:.0f} g | 钠 {ts['sodium']:.0f} mg")
    print()
    if tp["sodium"] > SODIUM_DAILY_CAP and ts["protein"] < target["protein_target"] * 0.95:
        print("  结论：在纯麦当劳餐单上，「热量达标 + 蛋白达标 + 钠达标」三者不可兼得。")
        print(f"  · 要蛋白 {target['protein_target']:.0f} g，钠会到 {tp['sodium']:.0f} mg 左右")
        print(f"  · 要控钠 {SODIUM_DAILY_CAP} mg 以内，蛋白只有 {ts['protein']:.0f} g 左右")
        print("  建议：选定一侧作为主线，另一侧用非麦当劳食物补齐（如无糖希腊酸奶、")
        print("        水煮鸡胸、蛋白粉），并在方案中如实标注缺口。")
    print()
    print(f"[数据源] 麦当劳官方营养表 {len(items)} 项｜求解方式：槽位枚举 + 词典序打分择优")


if __name__ == "__main__":
    main()
