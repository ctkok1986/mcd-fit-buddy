# -*- coding: utf-8 -*-
"""腹肌引擎回归测试

重点：海军法公式必须与外部来源的验算样例逐一对上（公式实现错一位小数，
结果就差好几个百分点）。样例取自公开计算器的逐步验算过程。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from abs_engine import (  # noqa: E402
    ABS_FEMALE_SHIFT, PROTEIN_PER_KG_LBM, SODIUM_DAILY_CAP,
    abs_visibility, bf_navy, water_index,
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


def approx(a, b, tol):
    return abs(a - b) <= tol


print("=" * 62)
print("一、海军法公式复核（对来源验算样例）")
print("=" * 62)

# 样例A：vastcalculators 逐步验算，175cm / 腰90 / 颈38 -> 20.66%
bf, _ = bf_navy("male", 175, 90, 38)
check(approx(bf, 20.66, 0.05), f"样例A 175/90/38 -> {bf:.2f}%（期望 20.66%）")

# 样例B：nutritioncalcs 逐步验算，178cm / 腰86 / 颈39 -> 16.5%
bf, _ = bf_navy("male", 178, 86, 39)
check(approx(bf, 16.5, 0.1), f"样例B 178/86/39 -> {bf:.2f}%（期望 16.50%）")

# 样例C：calculator.nu，175cm / 腰88 / 颈38 -> 19.21%
bf, _ = bf_navy("male", 175, 88, 38)
check(approx(bf, 19.21, 0.05), f"样例C 175/88/38 -> {bf:.2f}%（期望 19.21%）")

# 样例D：calculator.nu 女性，165cm / 腰75 / 颈32 / 臀98 -> 28.9%
bf, _ = bf_navy("female", 165, 75, 32, 98)
check(approx(bf, 28.9, 0.15), f"样例D 女165/75/32/98 -> {bf:.2f}%（期望 28.90%）")

# 来源明确警告：girth 相同则结果相同（腰100/颈48 与 腰90/颈38 在175cm下等价）
b1, _ = bf_navy("male", 175, 100, 48)
b2, _ = bf_navy("male", 175, 90, 38)
check(approx(b1, b2, 0.01), f"结构性性质：girth 52 的两种测法结果一致（{b1:.2f} vs {b2:.2f}）")

# 腰围每变化 1cm，结果约变化 1 个百分点（来源：'A centimetre at the waist moves the result by roughly one percentage point'）
low, _ = bf_navy("male", 175, 88, 38)
high, _ = bf_navy("male", 175, 92, 38)
check(approx(high - low, 2.9, 0.6), f"敏感性：腰围 +4cm -> 体脂 +{high-low:.1f} 点（来源约 +2.9）")

print()
print("=" * 62)
print("二、输入校验")
print("=" * 62)

bf, err = bf_navy("male", 175, 30, 40)
check(bf is None and "腰围必须大于颈围" in err, "腰围 < 颈围 被拒绝")

bf, err = bf_navy("male", 175, 90, None)
check(bf is None and "需要腰围与颈围" in err, "缺颈围被拒绝")

bf, err = bf_navy("female", 165, 75, 32)
check(bf is None and "臀围" in err, "女性缺臀围被拒绝")

bf, err = bf_navy("male", 175, 500, 38)
check(bf is None, "极端值不返回荒谬结果")

print()
print("=" * 62)
print("三、腹肌可见度分级")
print("=" * 62)

# 逐档对照来源表格（Nutrola × 2 篇 + 99健康网 交叉一致的描述）
cases = [
    (7,  "竞技级线条"),
    (9,  "八块清晰"),
    (11, "六块清晰"),
    (14, "上腹可见"),
    (18, "上腹微现"),
    (22, "极微弱轮廓"),
    (30, "被脂肪覆盖"),
]
for bf, expect in cases:
    got = abs_visibility("male", bf)[0]
    check(got == expect, f"男 {bf}% -> {got}（期望 {expect}）")

# 阈值边界：区间语义为 [lower, upper)，即 bf 恰好等于阈值时属于【该区间】。
# 例：bf=12 属于 [12,15)，不是 [10,12)。
check(abs_visibility("male", 24.9)[0] == "极微弱轮廓", "边界 24.9% 属 20-25 档")
check(abs_visibility("male", 25.0)[0] == "被脂肪覆盖", "边界 25.0% 属 25%+ 档")
check(abs_visibility("male", 20.0)[0] == "极微弱轮廓", "边界 20.0% 属 20-25 档")
check(abs_visibility("male", 15.0)[0] == "上腹微现", "边界 15.0% 属 15-20 档")
check(abs_visibility("male", 12.0)[0] == "上腹可见", "边界 12.0% 属 12-15 档")
check(abs_visibility("male", 10.0)[0] == "六块清晰", "边界 10.0% 属 10-12 档")
check(abs_visibility("male", 8.0)[0] == "八块清晰", "边界 8.0% 属 8-10 档")
# 刚好低于下边界
check(abs_visibility("male", 19.99)[0] == "上腹微现", "19.99% 仍在 15-20 档")
check(abs_visibility("male", 11.99)[0] == "六块清晰", "11.99% 仍在 10-12 档")

# 女性阈值 = 男性 + 8（必需脂肪更高、脂肪分布不同）
check(abs_visibility("female", 18)[0] == abs_visibility("male", 10)[0],
      f"女 18% 等价男 10%（得 {abs_visibility('female',18)[0]}）")
check(abs_visibility("female", 26)[0] == abs_visibility("male", 18)[0],
      f"女 26% 等价男 18%（得 {abs_visibility('female',26)[0]}）")
check(abs_visibility("female", 33)[0] == abs_visibility("male", 25)[0],
      f"女 33% 等价男 25%（得 {abs_visibility('female',33)[0]}）")

# 单调性：体脂越高，可见度严格变差，不出现倒挂
order = ["竞技级线条", "八块清晰", "六块清晰", "上腹可见",
         "上腹微现", "极微弱轮廓", "被脂肪覆盖"]
seq = [abs_visibility("male", b)[0] for b in (7, 9, 11, 14, 18, 22, 30)]
check(seq == order, f"男性分级单调不倒挂：{seq}")

print()
print("=" * 62)
print("四、水潴留指数")
print("=" * 62)

# 钠在安全线内 -> 无额外滞留
liters, grade, _ = water_index(2000, 78)
check(liters == 0 and grade == "清爽", f"钠 2000mg -> {liters:.2f}L / {grade}")

# 钠 4000mg（超 2000）-> 0.6L
liters, grade, _ = water_index(4000, 78)
check(approx(liters, 0.6, 0.01), f"钠 4000mg -> {liters:.2f}L（期望 0.60L）")

# 极端高钠（脆汁鸡套餐级别）
liters, grade, _ = water_index(6000, 78)
check(grade in ("明显发糊", "完全盖住"), f"钠 6000mg -> {grade}")

# 同样钠摄入下，体重越轻，水潴留的视觉影响越大
_, g_light, _ = water_index(4000, 50)
_, g_heavy, _ = water_index(4000, 100)
order_w = ["清爽", "略微发糊", "明显发糊", "完全盖住"]
check(order_w.index(g_light) >= order_w.index(g_heavy),
      f"同钠下体重越轻影响越大（50kg:{g_light} / 100kg:{g_heavy}）")

print()
print("=" * 62)
print("五、系数来源标注")
print("=" * 62)
check(approx(PROTEIN_PER_KG_LBM, 2.2, 0.001),
      f"瘦体重蛋白系数 = {PROTEIN_PER_KG_LBM} g/kg LBM（JISSN 建议 2.3-3.1 的保守下沿）")
check(ABS_FEMALE_SHIFT == 8, f"女性阈值偏移 = {ABS_FEMALE_SHIFT} 点")
check(SODIUM_DAILY_CAP == 2000, f"钠上限 = {SODIUM_DAILY_CAP} mg（WHO）")

print()
print("=" * 62)
print(f"结果：{PASS} passed, {FAIL} failed")
print("=" * 62)
sys.exit(1 if FAIL else 0)
