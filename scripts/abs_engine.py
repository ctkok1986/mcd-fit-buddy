#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦麦腹肌教练 · 体成分引擎

回答一个具体问题：**我现在的身体，离"看得见腹肌"还有多远？在麦当劳能做到吗？**

与配餐引擎的分工：
- 本引擎负责「定性」——体脂率、瘦体重、腹肌可见度、水量滞留、时间线
- meal_planner.py 负责「定量」——把这些目标翻译成具体餐单

设计原则（与项目一致）：
- 数据可追溯：每个系数标注来源，不凭记忆
- 结论不美化：能达成说能，不能达成说卡在哪
- 区分「可改变」与「不可改变」：腹肌形状由基因决定，可见度才由你决定

用法：
    python scripts/abs_engine.py --weight 78 --height 175 --age 40 --sex male \
        --waist 92 --neck 38 --goal-bodyfat 12
"""

import argparse
import math
import sys

# ── 常量与来源 ──────────────────────────────────────────────────────
KCAL_PER_KG_FAT = 7700

# 海军法（U.S. Navy circumference method），Hodgdon & Beckett, NHRC 1984。
# 密度形式，周长与身高单位均为厘米。多个独立来源一致：
#   %BF = 495 / (1.0324 - 0.19077·log10(waist - neck) + 0.15456·log10(height)) - 450
#   验算样例：175cm / 腰围90 / 颈围38 → 20.66%（与来源逐步验算一致）
NAVY_MALE = dict(k1=1.0324, k2=0.19077, k3=0.15456, base=495, sub=450)
NAVY_FEMALE = dict(k1=1.29579, k2=0.35004, k3=0.22100, base=495, sub=450)
NAVY_ERROR = "±3~4%（相对 DEXA）"

# 腹肌可见度分级（男性体脂率 %）。三个独立来源交叉一致，区间与描述严格对应：
#   25%+    腹部没有明显轮廓
#   20-25%  良好光线下非常微弱的轮廓
#   15-20%  上腹肌稍微显现
#   12-15%  上腹可见、下腹微弱
#   10-12%  清晰的六块腹肌可见
#   8-10%   深刻的线条、完整的定义
#   6-8%    竞技水平的定义（难以长期维持）
# 语义：bf < threshold 时命中该档，即阈值构成 [lower, upper) 区间。
# 例：bf=12 属于 [12,15) → "上腹可见"，不属于 [10,12)。
ABS_MALE = [
    (8,  "竞技级线条",   "腹部分离深刻，接近比赛状态。长期维持可能影响激素水平。"),
    (10, "八块清晰",     "腹肌分块完全可见，线条锐利。这是可持续的下限附近。"),
    (12, "六块清晰",     "六块腹肌完全可见，手臂血管明显。多数人追求的理想区间。"),
    (15, "上腹可见",     "上腹肌清晰，下腹仍被少量皮脂覆盖——下腹通常最后显现。"),
    (20, "上腹微现",     "良好光线下上腹轮廓开始显现，腰部明显收紧。"),
    (25, "极微弱轮廓",   "仅在良好光线与角度下能看到极其微弱的轮廓。"),
    (999, "被脂肪覆盖",  "皮下脂肪完全盖住腹肌，此时练腹再多也看不到。"),
]
# 女性阈值整体上移 8 个点（必需脂肪更高，脂肪分布不同）
ABS_FEMALE_SHIFT = 8

# 减脂保肌的蛋白目标。
# 来源共识：1.6-2.2 g/kg【体重】；若基数较大，应改用瘦体重或目标体重计算。
# JISSN 对偏瘦训练者在热量缺口下的建议为 2.3-3.1 g/kg【瘦体重】。
# 本项目取 2.2 g/kg FFM —— 落在建议区间下沿，属保守取值。
PROTEIN_PER_KG_LBM = 2.2
PROTEIN_PER_KG_BW = 1.8      # 无体脂数据时的退路（原逻辑）

# 安全速率：每周减重不超过体重的 0.5%~1%，取 0.5% 为体脂下降的稳健速率
WEEKLY_BF_DROP_MAX = 0.005

# 无力量训练时的肌肉流失占比（文献：单纯节食减重约有 25% 来自肌肉）
LBM_LOSS_SHARE_NO_TRAIN = 0.25
LBM_LOSS_SHARE_TRAIN = 0.05   # 有力量训练时大幅降低

# WHO 每日钠摄入上限
SODIUM_DAILY_CAP = 2000

# 钠→水潴留换算：每超出 1000 mg 钠，估算皮下滞留 0.3~0.5 L 水。
# 取 0.3 L 作保守估计（不夸大）。来源：运动营养实践中对钠致水分滞留的经验换算，
# 以及"钠/碳水引起的水潴留可在夜间掩盖 2-3 周减脂进展"的共识描述。
WATER_L_PER_1000MG_SODIUM = 0.3


# ── 体脂率 ──────────────────────────────────────────────────────────

def bf_navy(sex, height_cm, waist_cm, neck_cm, hip_cm=None):
    """海军法估算体脂率。返回 (体脂率%, 说明) 或 (None, 错误说明)。"""
    if sex == "male":
        if not (waist_cm and neck_cm):
            return None, "男性海军法需要腰围与颈围"
        girth = waist_cm - neck_cm
        if girth <= 0:
            return None, "腰围必须大于颈围"
        p = NAVY_MALE
    else:
        if not (waist_cm and neck_cm and hip_cm):
            return None, "女性海军法需要腰围、臀围与颈围"
        girth = waist_cm + hip_cm - neck_cm
        if girth <= 0:
            return None, "腰围+臀围必须大于颈围"
        p = NAVY_FEMALE
    denom = p["k1"] - p["k2"] * math.log10(girth) + p["k3"] * math.log10(height_cm)
    if denom <= 0:
        return None, "输入数值超出公式适用范围"
    bf = p["base"] / denom - p["sub"]
    if not (2 <= bf <= 65):
        return None, f"估算结果 {bf:.1f}% 超出合理范围，请检查测量值"
    return bf, f"海军法（腰{waist_cm:.0f}/颈{neck_cm:.0f}" + \
               (f"/臀{hip_cm:.0f}" if hip_cm else "") + f"/身高{height_cm:.0f}）"


def abs_visibility(sex, bf):
    """体脂率 → 腹肌可见度分级。"""
    table = ABS_MALE
    b = bf
    if sex == "female":
        b = bf - ABS_FEMALE_SHIFT      # 女性等价折算到男性阈值表
    for threshold, title, desc in table:
        if b < threshold:
            return title, desc
    return table[-1][1], table[-1][2]


# ── 核心计算 ────────────────────────────────────────────────────────

def build_body_plan(args):
    """体成分测算：体脂率 → 瘦体重 → 目标体脂对应的体重 → 时间线。

    统一返回 (plan | None, issues)。plan 为 None 时 issues 非空。
    """
    warnings = []
    bf = None
    bf_source = None

    if getattr(args, "bodyfat", None):
        bf = float(args.bodyfat)
        bf_source = "用户实测"
        if not (2 <= bf <= 65):
            return None, [f"体脂率 {bf}% 超出合理范围（2~65%）"]
    else:
        bf, note = bf_navy(args.sex, args.height, args.waist, args.neck,
                           getattr(args, "hip", None))
        if bf is None:
            return None, [f"无法估算体脂率：{note}。请补充测量值，或直接用 --bodyfat 填写实测值。"]
        bf_source = note

    weight = args.weight
    fat_mass = weight * bf / 100.0
    lbm = weight - fat_mass

    goal_bf = float(getattr(args, "goal_bodyfat", 0) or 0)
    if not goal_bf:
        # 未指定则按性别给一个"腹肌可见"的默认目标
        goal_bf = 12.0 if args.sex == "male" else 20.0
        warnings.append(
            f"未指定目标体脂率，已按{args.sex == 'male' and '男性' or '女性'}腹肌可见的"
            f"常规阈值取 {goal_bf:.0f}%。")

    if goal_bf >= bf:
        warnings.append(
            f"目标体脂 {goal_bf:.0f}% 不低于当前 {bf:.1f}%——"
            f"不需要减脂，可直接进入增肌/塑形阶段。")

    # 目标体重：假设瘦体重保持不变（需力量训练支撑）
    if goal_bf < 95:
        target_weight = lbm / (1 - goal_bf / 100.0)
    else:
        target_weight = weight
    target_fat = target_weight * goal_bf / 100.0
    fat_to_lose = fat_mass - target_fat

    # 两个版本的减重需求：有无力量训练，结果差异很大
    # 无训练：掉的部分有 LBM_LOSS_SHARE_NO_TRAIN 来自肌肉
    real_loss_no_train = fat_to_lose / (1 - LBM_LOSS_SHARE_NO_TRAIN) \
        if fat_to_lose > 0 else 0.0
    real_loss_train = fat_to_lose / (1 - LBM_LOSS_SHARE_TRAIN) \
        if fat_to_lose > 0 else 0.0

    # 时间线：按「每周最多减掉体重 0.5% 的脂肪」这一安全速率反推。
    # 口径统一到可验证的物理量（脂肪公斤数），而非体脂率百分点。
    weekly_fat_kg = weight * WEEKLY_BF_DROP_MAX
    # 以「有力量训练」为基准估算总减重（纯脂肪 + 不可避免的少量肌肉）
    weeks_at_max = real_loss_train / weekly_fat_kg if weekly_fat_kg > 0 else 0.0

    cur_title, cur_desc = abs_visibility(args.sex, bf)
    goal_title, goal_desc = abs_visibility(args.sex, goal_bf)

    # 蛋白目标：瘦体重驱动 vs 按体重（对照）
    protein_lbm = lbm * PROTEIN_PER_KG_LBM
    protein_bw = weight * PROTEIN_PER_KG_BW

    return {
        "bf": bf, "bf_source": bf_source, "bf_error": NAVY_ERROR,
        "fat_mass": fat_mass, "lbm": lbm,
        "goal_bf": goal_bf, "target_weight": target_weight,
        "target_fat": target_fat, "fat_to_lose": fat_to_lose,
        "real_loss_no_train": real_loss_no_train,
        "real_loss_train": real_loss_train,
        "bf_drop": max(0.0, bf - goal_bf), "weeks_at_max": weeks_at_max,
        "weekly_fat_kg": weekly_fat_kg,
        "cur_title": cur_title, "cur_desc": cur_desc,
        "goal_title": goal_title, "goal_desc": goal_desc,
        "protein_lbm": protein_lbm, "protein_bw": protein_bw,
        "warnings": warnings,
    }, []


def water_index(daily_sodium, weight):
    """估算钠致水分滞留。返回 (滞留升数, 分级, 说明)。"""
    excess = max(0.0, daily_sodium - SODIUM_DAILY_CAP)
    liters = excess / 1000.0 * WATER_L_PER_1000MG_SODIUM
    # 按体重折算相对影响：滞留水占体重的比例
    pct = liters / weight * 100 if weight else 0
    if pct < 0.2:
        grade = "清爽"
        note = "钠在安全线内，腹肌不会被水盖住。"
    elif pct < 0.4:
        grade = "略微发糊"
        note = "有轻微水潴留，晨起可能比晚间清晰。"
    elif pct < 0.7:
        grade = "明显发糊"
        note = "皮下水分把腹肌线条泡软了——即使体脂达标，看起来也会「平」。"
    else:
        grade = "完全盖住"
        note = "水潴留严重，腹肌在视觉上基本被抹平。此时照镜子会严重低估你的真实进度。"
    return liters, grade, note


# ── 渲染 ────────────────────────────────────────────────────────────

def fmt(args, p):
    out = []
    W = 66
    out.append("=" * W)
    out.append("麦麦腹肌教练 · 体成分测算")
    out.append("=" * W)

    out.append("")
    out.append("【一、当前体成分】")
    out.append(f"  体重           {args.weight:.1f} kg")
    out.append(f"  体脂率         {p['bf']:.1f} %   （{p['bf_source']}｜误差 {p['bf_error']}）")
    out.append(f"  脂肪量         {p['fat_mass']:.1f} kg")
    out.append(f"  瘦体重 LBM     {p['lbm']:.1f} kg   ← 这个才是「需要蛋白的部分」")

    out.append("")
    out.append("【二、腹肌可见度】")
    out.append(f"  当前 {p['bf']:.1f}% → {p['cur_title']}")
    out.append(f"        {p['cur_desc']}")
    if p["bf_drop"] > 0.05:
        out.append(f"  目标 {p['goal_bf']:.1f}% → {p['goal_title']}")
        out.append(f"        {p['goal_desc']}")
    else:
        out.append(f"  你已在腹肌可见区间，接下来的重点是「练厚」而不是「再减」。")

    out.append("")
    out.append("【三、目标体重与时间线】")
    if p["fat_to_lose"] > 0.05:
        out.append(f"  需减脂肪       {p['fat_to_lose']:.1f} kg"
                   f"（从 {p['fat_mass']:.1f} kg 降到 {p['target_fat']:.1f} kg）")
        out.append(f"  目标体重       {p['target_weight']:.1f} kg"
                   f"（假设瘦体重 {p['lbm']:.1f} kg 保持不变）")
        out.append("")
        out.append(f"  但「瘦体重不变」需要力量训练保障。真实差距：")
        out.append(f"    · 有力量训练：实际需减重约 {p['real_loss_train']:.1f} kg")
        out.append(f"    · 无力量训练：实际需减重约 {p['real_loss_no_train']:.1f} kg"
                   f"（掉的部分约 {LBM_LOSS_SHARE_NO_TRAIN*100:.0f}% 来自肌肉）")
        out.append("")
        out.append(f"  安全速率       ≤ {p['weekly_fat_kg']:.2f} kg 脂肪/周"
                   f"（体重的 0.5%）")
        out.append(f"  预计周期       约 {p['weeks_at_max']:.0f} 周"
                   f"（{p['weeks_at_max']/4.3:.1f} 个月，按有力量训练的减重口径）")
        out.append(f"                 ← 这是「以月计」的事，不是「以周计」")
    else:
        out.append(f"  无需减脂，目标体重维持在 {args.weight:.1f} kg 附近。")

    out.append("")
    out.append("【四、蛋白目标：按瘦体重算，不是按体重】")
    out.append(f"  瘦体重驱动     {p['protein_lbm']:.0f} g/天"
               f"（{p['lbm']:.1f} kg LBM × {PROTEIN_PER_KG_LBM}）")
    out.append(f"  按总体重算     {p['protein_bw']:.0f} g/天"
               f"（{args.weight:.1f} kg × {PROTEIN_PER_KG_BW}，旧算法）")
    diff = p["protein_bw"] - p["protein_lbm"]
    if abs(diff) >= 3:
        # diff = 按体重 - 按瘦体重。为正说明旧算法多给了蛋白。
        direction = "高" if diff > 0 else "低"
        out.append(f"  差异           {diff:+.0f} g —— 旧算法算{direction}了。")
        if diff > 0:
            out.append(f"                 脂肪组织不需要蛋白。旧算法多算的 {diff:.0f} g 会推高食量，")
            out.append(f"                 容易选到钠含量偏高的餐品（如脆汁鸡、安格斯系列）。")
        else:
            out.append(f"                 你偏瘦，按体重算会吃不饱，肌肉有流失风险。")
            out.append(f"                 瘦体重高的人必须按瘦体重算才够。")

    out.append("")
    out.append("【五、水潴留：腹肌的隐形敌人】")
    sodium_in = getattr(args, "sodium", None)
    if sodium_in:
        src = "你提供的实际摄入"
    else:
        sodium_in = SODIUM_DAILY_CAP
        src = "WHO 上限假设（未提供实际摄入，用 --sodium 可填实测值）"
    liters, grade, note = water_index(sodium_in, args.weight)
    out.append(f"  每日钠摄入     {sodium_in:.0f} mg（{src}）")
    out.append(f"  钠致滞留水     约 {liters:.2f} L（占体重 {liters/args.weight*100:.2f}%）")
    out.append(f"  腹肌清晰度     【{grade}】")
    out.append(f"        {note}")
    out.append("")
    out.append("  这也是麦当劳餐单上的一组取舍：要把蛋白吃够，往往要选钠含量较高的")
    out.append("  餐品（如脆汁鸡、安格斯系列，钠 900~1400 mg/份）；要控钠，则多为")
    out.append("  玉米杯/牛奶/美式，蛋白偏低。两个目标难以同时满足。")

    out.append("")
    out.append("【六、必须说清的边界】")
    out.append("  · 腹肌的块数与形状由基因决定（腱划数量与位置）。")
    out.append("    有人天生六块、有人非对称四块或八块——这一点练不出来，也吃不出来。")
    out.append("    你能决定的是「可见度」：把覆盖它的脂肪减掉。")
    out.append("  · 体脂率估算误差 ±3~4%。看趋势比看单次数字可靠。")
    out.append("  · 男性低于 8%、女性低于 16% 属竞技区间，长期维持可能损害激素与免疫。")
    out.append("  · 本工具不构成医疗建议。有基础疾病请咨询医生。")

    if p["warnings"]:
        out.append("")
        out.append("【提示】")
        for w in p["warnings"]:
            out.append(f"  · {w}")

    out.append("=" * W)
    return "\n".join(out)


def main():
    p = argparse.ArgumentParser(description="麦麦腹肌教练 · 体成分引擎")
    p.add_argument("--weight", type=float, required=True, help="体重 kg")
    p.add_argument("--height", type=float, required=True, help="身高 cm")
    p.add_argument("--age", type=int, required=True, help="年龄")
    p.add_argument("--sex", choices=["male", "female"], required=True)
    p.add_argument("--waist", type=float, help="腰围 cm（海军法用）")
    p.add_argument("--neck", type=float, help="颈围 cm（海军法用）")
    p.add_argument("--hip", type=float, help="臀围 cm（女性海军法用）")
    p.add_argument("--bodyfat", type=float, help="实测体脂率 %%（优先于海军法估算）")
    p.add_argument("--goal-bodyfat", type=float, default=0,
                   help="目标体脂率 %%，如男性 12、女性 20")
    p.add_argument("--sodium", type=float, default=None,
                   help="当前实际每日钠摄入 mg（用于估算水潴留，"
                        "可直接接配餐引擎算出的实际值）")
    args = p.parse_args()

    errs = _validate(args)
    if errs:
        for e in errs:
            print(f"❌ {e}")
        return 1

    plan, issues = build_body_plan(args)
    if plan is None:
        for e in issues:
            print(f"❌ {e}")
        return 1

    print(fmt(args, plan))
    return 0


def _validate(a):
    errs = []
    if not (25 <= a.weight <= 300):
        errs.append(f"体重 {a.weight} kg 不合理（应在 25~300）")
    if not (100 <= a.height <= 250):
        errs.append(f"身高 {a.height} cm 不合理（应在 100~250）")
    if not (10 <= a.age <= 100):
        errs.append(f"年龄 {a.age} 不合理（应在 10~100）")
    for name, v in (("腰围", a.waist), ("颈围", a.neck), ("臀围", a.hip)):
        if v is not None and not (20 <= v <= 200):
            errs.append(f"{name} {v} cm 不合理（应在 20~200）")
    if a.bodyfat is not None and not (2 <= a.bodyfat <= 65):
        errs.append(f"体脂率 {a.bodyfat}% 不合理（应在 2~65）")
    if a.goal_bodyfat and not (2 <= a.goal_bodyfat <= 65):
        errs.append(f"目标体脂率 {a.goal_bodyfat}% 不合理（应在 2~65）")
    if a.sex == "female" and a.hip is None and a.bodyfat is None:
        errs.append("女性使用海军法必须提供臀围（--hip），或直接填 --bodyfat")
    return errs


if __name__ == "__main__":
    sys.exit(main())
