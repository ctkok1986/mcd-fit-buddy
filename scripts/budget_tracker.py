#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦麦减脂搭子 · 当日剩余额度追踪与推荐

场景：今天已经吃了一部分，还剩多少额度？还能吃什么样的麦当劳？

输入：身体参数 + 目标 + （可选）实测 BMR + 今日已摄入
输出：预算 / 已摄入 / 剩余三栏对照，以及在剩余额度内蛋白最高的
      单点与组合推荐，并标注钠是否会超。

用法：
    python scripts/budget_tracker.py \
        --weight 78 --height 175 --age 40 --sex male --activity light \
        --target-weight 72 --weeks 12 --bmr 1750 \
        --eaten 1200 --eaten-protein 60 --eaten-sodium 1500
"""

import argparse
import sys
from itertools import combinations

from meal_planner import (
    SODIUM_DAILY_CAP, _check_spot, build_target, classify, load_items, totals,
)


def pick_singles(items, kcal_left, top=8):
    """剩余热量内的单品，按蛋白绝对值排序。"""
    pool = [i for i in items if 0 < i["kcal"] <= kcal_left]
    pool.sort(key=lambda x: (-x["protein"], x["kcal"]))
    return pool[:top]


def pick_combos(items, kcal_left, top=5):
    """剩余热量内的组合（2-3 件），按蛋白绝对值排序。

    组合要求跨品类（主食 + 配菜 / 饮品），避免出现"两份同款"。
    """
    pool = [i for i in items if 0 < i["kcal"] <= kcal_left]
    # 按蛋白密度取前 30 个作为候选，控制搜索规模
    pool.sort(key=lambda x: -(x["protein"] / x["kcal"]))
    pool = pool[:30]

    found = []
    for r in (2, 3):
        for combo in combinations(pool, r):
            kinds = [classify(i["name"]) for i in combo]
            if len(kinds) != len(set(kinds)):
                continue          # 同类去重
            t = totals(list(combo))
            if t["kcal"] <= kcal_left:
                found.append((combo, t))
    found.sort(key=lambda x: (-x[1]["protein"], x[1]["kcal"]))
    return found[:top]


def fmt_line(items_list, sodium_left):
    """渲染一行推荐，标注钠风险。"""
    names = " + ".join(i["name"] for i in items_list)
    t = totals(list(items_list))
    sodium = t["sodium"]
    if sodium_left is not None and sodium > sodium_left:
        flag = " 🔴钠超"
    elif sodium > 900:
        flag = " 🟠钠偏高"
    else:
        flag = " ✅"
    return (f"  {names:<34} {t['kcal']:>5.0f} kcal  "
            f"蛋白 {t['protein']:>4.0f}g  钠 {sodium:>5.0f}mg{flag}")


def render(args, target, items):
    out = []
    out.append("=" * 68)
    out.append("麦麦减脂搭子 · 今日剩余额度")
    out.append("=" * 68)
    src = target.get("bmr_source", "")
    out.append(f"基础代谢 BMR：{target['bmr']:.0f} kcal"
               + (f"（{src}）" if src else ""))
    out.append(f"每日消耗 TDEE：{target['tdee']:.0f} kcal")
    out.append(f"每日摄入目标：{target['daily_kcal']:.0f} kcal")
    out.append("")

    eaten_kcal = float(args.eaten or 0)
    eaten_protein = float(args.eaten_protein or 0)
    eaten_sodium = args.eaten_sodium
    sodium_left = None
    if eaten_sodium is not None:
        sodium_left = SODIUM_DAILY_CAP - float(eaten_sodium)

    kcal_left = target["daily_kcal"] - eaten_kcal
    prot_left = target["protein_target"] - eaten_protein

    out.append(f"{'':<8}{'预算':>12}{'已摄入':>12}{'剩余':>12}")
    out.append(f"{'热量':<8}{target['daily_kcal']:>9.0f} kcal"
               f"{eaten_kcal:>9.0f} kcal{kcal_left:>9.0f} kcal")
    out.append(f"{'蛋白':<8}{target['protein_target']:>9.0f} g"
               f"{eaten_protein:>12.0f} g{prot_left:>12.0f} g")
    if eaten_sodium is not None:
        mark = "  ⚠️ 已不足 800mg" if sodium_left < 800 else ""
        out.append(f"{'钠':<8}{SODIUM_DAILY_CAP:>9.0f} mg"
                   f"{float(eaten_sodium):>9.0f} mg{sodium_left:>9.0f} mg{mark}")
    out.append("")

    if kcal_left <= 0:
        out.append("🔴 今日热量额度已用完。")
        zeros = [i for i in items if i["kcal"] == 0]
        if zeros:
            out.append("   零热量可选："
                       + "、".join(i["name"] for i in zeros[:6]))
        out.append(f"   蛋白仍缺 {prot_left:.0f} g，"
                   "靠麦当劳已无法补齐，建议非麦当劳蛋白来源。")
        out.append("=" * 68)
        return "\n".join(out)

    out.append("-" * 68)
    out.append(f"还能吃 · 单点（均在 {kcal_left:.0f} kcal 内，按蛋白排序）")
    out.append("-" * 68)
    for i in pick_singles(items, kcal_left):
        out.append(fmt_line([i], sodium_left))

    combos = pick_combos(items, kcal_left)
    if combos:
        out.append("")
        out.append("-" * 68)
        out.append(f"还能吃 · 组合（2-3 件，热量内蛋白更高）")
        out.append("-" * 68)
        for idx, (combo, t) in enumerate(combos, 1):
            sodium = t["sodium"]
            flag = (" 🔴钠超" if (sodium_left is not None and sodium > sodium_left)
                    else " 🟠钠偏高" if sodium > 900 else " ✅")
            names = " + ".join(i["name"] for i in combo)
            out.append(f"  {idx}) {names}")
            out.append(f"     {t['kcal']:.0f} kcal｜蛋白 {t['protein']:.0f}g"
                       f"｜脂肪 {t['fat']:.0f}g｜碳水 {t['carb']:.0f}g"
                       f"｜钠 {sodium:.0f}mg{flag}")

    # 钠额度紧张时，额外给一份"真的能落在额度内"的低钠选项
    if sodium_left is not None and sodium_left < 900:
        low_na = [i for i in items
                  if 0 < i["kcal"] <= kcal_left and i["sodium"] <= sodium_left]
        low_na.sort(key=lambda x: (-x["protein"], x["sodium"]))
        out.append("")
        out.append("-" * 68)
        out.append(f"还能吃 · 控钠可选（钠 ≤ {sodium_left:.0f}mg 且热量内）")
        out.append("-" * 68)
        if low_na:
            for i in low_na[:6]:
                out.append(f"  {i['name']:<34} {i['kcal']:>5.0f} kcal  "
                           f"蛋白 {i['protein']:>4.0f}g  钠 {i['sodium']:>5.0f}mg ✅")
            out.append("  ⚠️  这些能守住钠额度，但蛋白贡献有限——"
                       "这就是「控钠」与「补蛋白」不可兼得的具体体现。")
        else:
            out.append(f"  （无任何单品能同时满足热量 ≤{kcal_left:.0f} kcal "
                       f"且钠 ≤{sodium_left:.0f} mg）")

    out.append("")
    out.append("-" * 68)
    out.append("结论")
    out.append("-" * 68)
    best = combos[0][1] if combos else (
        totals([pick_singles(items, kcal_left)[0]])
        if pick_singles(items, kcal_left) else None)
    if best:
        gap = prot_left - best["protein"]
        if gap > 5:
            out.append(f"  热量内蛋白上限约 {best['protein']:.0f} g，"
                       f"距目标仍差 {gap:.0f} g。")
            out.append("  建议：这部分麦当劳餐单较难补足，可用无糖希腊酸奶/蛋白粉补充。")
        else:
            out.append(f"  热量内可把蛋白补到 {best['protein']:.0f} g，"
                       f"目标缺口仅剩 {gap:.0f} g，基本达标。")
    if sodium_left is not None and sodium_left < 900:
        out.append(f"  ⚠️  剩余钠额度仅 {sodium_left:.0f} mg，"
                   "任何一个汉堡都会顶满，优先选玉米杯/牛奶/美式。")
    out.append("=" * 68)
    return "\n".join(out)


def main():
    p = argparse.ArgumentParser(description="麦麦减脂搭子 · 今日剩余额度")
    p.add_argument("--weight", type=float, required=True)
    p.add_argument("--height", type=float, required=True)
    p.add_argument("--age", type=int, required=True)
    p.add_argument("--sex", choices=["male", "female"], required=True)
    p.add_argument("--activity", default="light")
    p.add_argument("--target-weight", type=float, default=None,
                   help="期望体重 kg（与 --weeks 搭配；若用 --goal 则不必填）")
    p.add_argument("--weeks", type=float, default=12)
    p.add_argument("--goal", default=None, choices=["cut", "recomp", "gain"],
                   help="目标模式：cut=减脂 / recomp=增肌减脂 / gain=增肌")
    p.add_argument("--bodyfat", type=float, default=None,
                   help="体脂率 %%（提供后蛋白按瘦体重计算）")
    p.add_argument("--bmr", type=float, default=None,
                   help="实测基础代谢率 kcal（体脂秤/InBody）")
    p.add_argument("--eaten", type=float, default=0,
                   help="今日已摄入热量 kcal")
    p.add_argument("--eaten-protein", type=float, default=0,
                   help="今日已摄入蛋白 g")
    p.add_argument("--eaten-sodium", type=float, default=None,
                   help="今日已摄入钠 mg（提供后启用钠额度追踪）")
    args = p.parse_args()

    # 与 meal_planner 一致的输入合理性校验（拦截明显误输入）
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
    if not (0 <= args.eaten <= 10000):
        print(f"❌ 已摄入热量 {args.eaten} 不合理，请检查")
        return 1
    if not (0 <= args.eaten_protein <= 1000):
        print(f"❌ 已摄入蛋白 {args.eaten_protein} 不合理，请检查")
        return 1
    if args.eaten_sodium is not None and not (0 <= args.eaten_sodium <= 20000):
        print(f"❌ 已摄入钠 {args.eaten_sodium} 不合理，请检查")
        return 1

    items = load_items()
    target = build_target(args)
    print(render(args, target, items))
    print(f"\n[数据源] 麦当劳官方营养表 {len(items)} 项｜"
          f"钠上限参照 WHO 建议 {SODIUM_DAILY_CAP} mg/天")
    return 0


if __name__ == "__main__":
    sys.exit(main())
