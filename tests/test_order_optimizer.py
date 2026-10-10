#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦麦减脂搭子 · 下单渠道比价引擎回归测试

覆盖：名称归一化、跨渠道商品匹配、缺货识别、成本拆解自洽、券适配规则。
运行：python tests/test_order_optimizer.py
"""

import copy
import json
import os
import sys

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(BASE, "scripts"))

import order_optimizer as oo  # noqa: E402

PASS, FAIL = 0, 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {msg}")
    else:
        FAIL += 1
        print(f"  [FAIL] {msg}")


with open(os.path.join(BASE, "data", "channel-snapshot.sample.json"), encoding="utf-8") as f:
    SNAP = json.load(f)

print("=" * 62)
print("1. 名称归一化（跨渠道命名差异）")
print("=" * 62)
check(oo.normalize("麦咖啡™冰美式中杯") == oo.normalize("麦咖啡™热美式中杯"),
      "冰美式 与 热美式 归一化后同名（渠道命名差异）")
check(oo.normalize("纯牛奶（盒装）") == oo.normalize("纯牛奶(盒装)"),
      "全角/半角括号归一化一致")
check(oo.normalize("中薯条") != oo.normalize("大薯条"),
      "中薯条 与 大薯条 不混淆")

print()
print("=" * 62)
print("2. 跨渠道商品匹配")
print("=" * 62)
pickup = SNAP["channels"]["pickup"]
delivery = SNAP["channels"]["delivery"]
basket = SNAP["basket"]

m_pick, miss_pick = oo.match_basket(basket, pickup["menu"])
m_deliv, miss_deliv = oo.match_basket(basket, delivery["menu"])

check(len(m_pick) == 3 and not miss_pick, "自提渠道 3 项全部命中")
check(len(m_deliv) == 3 and not miss_deliv, "外送渠道 3 项全部命中")
check([l["productCode"] for l in m_pick] == ["1120", "4810", "507411"],
      "自提编码映射正确（1120/4810/507411）")
check([l["productCode"] for l in m_deliv] == ["901120", "501205", "507368"],
      "外送编码映射正确（901120/501205/507368，与自提完全不同）")

print()
print("=" * 62)
print("3. 缺货识别（calculate-price 静默丢弃的防线）")
print("=" * 62)
# 构造一个只有自提才有的商品
basket_bf = [{"name": "脆薯饼", "quantity": 1}, {"name": "不存在的商品", "quantity": 1}]
_, miss = oo.match_basket(basket_bf, pickup["menu"])
check("不存在的商品" in miss, "识别出渠道不可售商品")

# 用一个大配餐篮模拟：外送菜单缺少的自提专有商品
partial = copy.deepcopy(SNAP)
partial["basket"] = [
    {"name": "双层吉士汉堡", "quantity": 1},
    {"name": "麦辣鸡腿汉堡", "quantity": 1},   # 不在样例菜单中
]
res = oo.compare(partial["channels"], partial["basket"], [])
pickup_res = next(r for r in res if r["key"] == "pickup")
check(len(pickup_res["missing"]) == 1, f"自提缺 {len(pickup_res['missing'])} 项被识别")

print()
print("=" * 62)
print("4. 成本拆解与比价正确性（真实抓取数据复核）")
print("=" * 62)
results = oo.compare(SNAP["channels"], SNAP["basket"], SNAP["coupons"])
pu = next(r for r in results if r["key"] == "pickup")
dl = next(r for r in results if r["key"] == "delivery")

# 自提：23 + 14 + 11.9 = 48.90，券省 2.00 → 46.90
check(abs(pu["productOriginal"] - 48.90) < 0.005, f"自提商品原价 48.90（实得 {pu['productOriginal']}）")
check(abs(pu["couponSaved"] - 2.00) < 0.005, f"自提券省 2.00（实得 {pu['couponSaved']}）")
check(abs(pu["total"] - 46.90) < 0.005, f"自提合计 46.90（实得 {pu['total']}）")

# 外送：25 + 15.5 + 11.9 = 52.40，+ 运费 6.00 + 打包 1.90 = 60.30
check(abs(dl["productOriginal"] - 52.40) < 0.005, f"外送商品原价 52.40（实得 {dl['productOriginal']}）")
check(abs(dl["extraFees"] - 7.90) < 0.005, f"外送附加费 7.90（实得 {dl['extraFees']}）")
check(abs(dl["total"] - 60.30) < 0.005, f"外送合计 60.30（实得 {dl['total']}）")

gap = round(dl["total"] - pu["total"], 2)
check(abs(gap - 13.40) < 0.005, f"总差额 13.40（实得 {gap}）")

# 拆解三部分必须严格加总等于总差额（这是曾经写错符号的地方）
unit_diff = round(dl["productOriginal"] - pu["productOriginal"], 2)
fee_diff = round(dl["extraFees"] - pu["extraFees"], 2)
coupon_diff = round(pu["couponSaved"] - dl["couponSaved"], 2)
check(abs(unit_diff - 3.50) < 0.005, f"单价差 3.50（实得 {unit_diff}）")
check(abs(fee_diff - 7.90) < 0.005, f"附加费差 7.90（实得 {fee_diff}）")
check(abs(coupon_diff - 2.00) < 0.005, f"券收益差 +2.00（实得 {coupon_diff}，符号为正）")
check(abs((unit_diff + fee_diff + coupon_diff) - gap) < 0.02,
      f"三项拆解之和 = 总差额（{unit_diff}+{fee_diff}+{coupon_diff}={round(unit_diff+fee_diff+coupon_diff,2)} vs {gap}）")

print()
print("=" * 62)
print("5. 券适配规则")
print("=" * 62)
check(len(pu["couponsApplied"]) == 1, "券在自提渠道被应用")
check(len(dl["couponsApplied"]) == 0,
      "券在外送渠道未被应用（外送商品编码 507368 与券绑定编码 507411 不一致）")

# 券价高于标价时不应应用
cheap = copy.deepcopy(SNAP)
cheap["coupons"] = [{
    "title": "测试券", "couponId": "X", "couponCode": "X",
    "productCode": "1120", "couponPrice": 99.0,
}]
r2 = oo.compare(cheap["channels"], cheap["basket"], cheap["coupons"])
pu2 = next(r for r in r2 if r["key"] == "pickup")
check(pu2["couponSaved"] == 0, "券价高于标价时不应用（避免负优化）")

print()
print("=" * 62)
print("6. 结论渲染")
print("=" * 62)
report = oo.render(results, SNAP["basket"], SNAP.get("meta", {}))
check("最优惠：到店自提" in report, "结论指出最优惠渠道")
check("¥13.40" in report, "结论含总差额")
check("三项之和 = 总差额" in report, "输出含拆解校验自洽声明")
check("不一致" not in report, "拆解无矛盾警告")

print()
print("=" * 62)
print(f"测试结果：{PASS} passed, {FAIL} failed")
print("=" * 62)
sys.exit(1 if FAIL else 0)
