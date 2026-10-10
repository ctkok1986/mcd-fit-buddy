#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦麦减脂搭子 · 下单渠道比价与优化引擎

输入：一份"渠道快照" JSON（由 Agent 通过麦当劳 MCP 拉取后落盘）
      —— 包含配餐篮、各渠道菜单、券信息、渠道附加费
输出：各渠道（到店自提 / 麦乐送）的真实总价对比、成本拆解、券适配情况、
      渠道缺货预警，并给出最优惠渠道建议

设计要点（全部来自真实踩坑，见 references/mcp-tools.md）：
  1. 自提与外送使用【两套互不相同的商品编码】，且无统一映射规则，必须按名称匹配
  2. calculate-price 对渠道不可售商品会【静默丢弃】，只返回 success:true → 必须逐项核对
  3. 外送商品单价普遍高于自提，另有运费与打包费 → 成本必须拆成三项对比
  4. 券可能与某渠道的商品编码不匹配（即使券标签写着"外送专用"）→ 券要逐渠道试算

用法：
    python scripts/order_optimizer.py data/channel-snapshot.sample.json
"""

import argparse
import json
import os
import re
import sys

# 名称归一化时剔除的修饰词（渠道间命名差异：冰/热、™、杯型、装等）
NOISE = [
    "™", "（盒装）", "(盒装)", "盒装",
    "冰", "热", "中杯", "大杯", "小杯", "（冰/热）", "(冰/热)",
]


def normalize(name):
    """把商品名归一化，用于跨渠道匹配。"""
    s = name.strip()
    for w in NOISE:
        s = s.replace(w, "")
    return re.sub(r"\s+", "", s)


def build_index(menu):
    """把菜单构建成 {归一化名称: (productCode, 记录)} 索引。"""
    idx = {}
    for code, item in menu.items():
        key = normalize(item["name"])
        idx.setdefault(key, (code, item))
    return idx


def match_basket(basket, menu):
    """把配餐篮匹配到指定渠道的菜单，返回 (命中列表, 缺失列表)。"""
    idx = build_index(menu)
    matched, missing = [], []
    for line in basket:
        key = normalize(line["name"])
        if key in idx:
            code, item = idx[key]
            matched.append({
                "name": item["name"],
                "productCode": code,
                "quantity": line["quantity"],
                "unitPrice": float(item["price"]),
                "subtotal": round(float(item["price"]) * line["quantity"], 2),
            })
        else:
            # 退化：尝试包含匹配
            hit = None
            for k, (code, item) in idx.items():
                if key and (key in k or k in key):
                    hit = (code, item)
                    break
            if hit:
                code, item = hit
                matched.append({
                    "name": item["name"],
                    "productCode": code,
                    "quantity": line["quantity"],
                    "unitPrice": float(item["price"]),
                    "subtotal": round(float(item["price"]) * line["quantity"], 2),
                })
            else:
                missing.append(line["name"])
    return matched, missing


def apply_coupon(matched, coupons, channel_key):
    """在指定渠道内应用可用券，返回 (优惠总额, 应用明细)。"""
    total_discount = 0.0
    applied = []
    for cp in coupons:
        target_code = cp.get("productCode")
        for line in matched:
            if line["productCode"] != target_code:
                continue
            list_price = line["unitPrice"]
            coupon_price = float(cp["couponPrice"])
            # 只在该券比当前价更低时才用，且避免重复应用同一行
            if coupon_price < list_price and not line.get("_coupon"):
                saved = round((list_price - coupon_price) * line["quantity"], 2)
                total_discount += saved
                line["_coupon"] = {"title": cp["title"], "saved": saved}
                applied.append({
                    "title": cp["title"],
                    "on": line["name"],
                    "listPrice": list_price,
                    "couponPrice": coupon_price,
                    "saved": saved,
                    "channel": channel_key,
                })
    return round(total_discount, 2), applied


def price_channel(channel_key, channel, basket, coupons):
    """计算单个渠道的完整成本结构。"""
    matched, missing = match_basket(basket, channel["menu"])

    product_original = round(sum(l["subtotal"] for l in matched), 2)
    coupon_saved, applied = apply_coupon(matched, coupons, channel_key)
    product_final = round(product_original - coupon_saved, 2)

    delivery_fee = float(channel.get("deliveryFee", 0.0))
    packing_fee = float(channel.get("packingFee", 0.0))
    extra = round(delivery_fee + packing_fee, 2)

    return {
        "key": channel_key,
        "label": channel.get("label", channel_key),
        "storeCode": channel.get("storeCode"),
        "lines": matched,
        "missing": missing,
        "productOriginal": product_original,
        "couponSaved": coupon_saved,
        "couponsApplied": applied,
        "productFinal": product_final,
        "deliveryFee": delivery_fee,
        "packingFee": packing_fee,
        "extraFees": extra,
        "total": round(product_final + extra, 2),
        "requestedCount": sum(l["quantity"] for l in basket),
        "matchedCount": sum(l["quantity"] for l in matched),
    }


def compare(channels, basket, coupons):
    """对所有渠道计价并输出对比。"""
    results = []
    for key, ch in channels.items():
        results.append(price_channel(key, ch, basket, coupons))
    results.sort(key=lambda r: r["total"])
    return results


def render(results, basket, meta):
    out = []
    out.append("=" * 68)
    out.append("麦麦减脂搭子 · 下单渠道比价")
    out.append("=" * 68)
    if meta.get("generated_at"):
        out.append(f"数据时间：{meta['generated_at']}")
    out.append("")
    out.append("配餐篮：")
    for l in basket:
        out.append(f"  · {l['name']} × {l['quantity']}")
    out.append("")

    # 缺货预警（最先输出，因为它会推翻比价结论）
    for r in results:
        if r["missing"]:
            out.append(f"🔴 [{r['label']}] 有 {len(r['missing'])} 项该渠道不可售，"
                       f"比价结果不成立：")
            for m in r["missing"]:
                out.append(f"     - {m}")
    if any(r["missing"] for r in results):
        out.append("")

    out.append("-" * 68)
    out.append("成本拆解")
    out.append("-" * 68)
    for r in results:
        out.append(f"\n【{r['label']}】门店 {r['storeCode']}")
        for l in r["lines"]:
            cp = l.get("_coupon")
            tag = f"  ← 用券「{cp['title']}」省 ¥{cp['saved']:.2f}" if cp else ""
            out.append(f"  {l['name']:<20} ×{l['quantity']}  "
                       f"¥{l['unitPrice']:>6.2f}  小计 ¥{l['subtotal']:>6.2f}{tag}")
        out.append(f"  商品原价小计          ¥{r['productOriginal']:>7.2f}")
        if r["couponSaved"] > 0:
            out.append(f"  券优惠                -¥{r['couponSaved']:>6.2f}")
        out.append(f"  商品实付              ¥{r['productFinal']:>7.2f}")
        if r["deliveryFee"] > 0:
            out.append(f"  运费                  +¥{r['deliveryFee']:>6.2f}")
        if r["packingFee"] > 0:
            out.append(f"  打包费                +¥{r['packingFee']:>6.2f}")
        out.append(f"  ─────────────────────────────")
        out.append(f"  合计                  ¥{r['total']:>7.2f}")

    out.append("")
    out.append("=" * 68)
    out.append("对比结论")
    out.append("=" * 68)

    valid = [r for r in results if not r["missing"]]
    if len(results) >= 2 and valid == results:
        base, best = results[0], results[0]
        worst = results[-1]
        diff = round(worst["total"] - best["total"], 2)
        pct = diff / worst["total"] * 100 if worst["total"] else 0
        out.append(f"✅ 最优惠：{best['label']}  ¥{best['total']:.2f}")
        out.append(f"   {worst['label']}：¥{worst['total']:.2f}"
                   f"（贵 ¥{diff:.2f}，{pct:.1f}%）")

        # 差异拆解。三部分必须严格加总等于总差额：
        #   总差额 = 单价差 + 附加费差 + 券收益差
        unit_diff = round(worst["productOriginal"] - best["productOriginal"], 2)
        fee_diff = round(worst["extraFees"] - best["extraFees"], 2)
        coupon_diff = round(best["couponSaved"] - worst["couponSaved"], 2)
        out.append("")
        out.append("   差额构成（三项之和 = 总差额）：")
        check_sum = round(unit_diff + fee_diff + coupon_diff, 2)
        if abs(unit_diff) > 0.005:
            out.append(f"     · 商品单价差    ¥{unit_diff:>+7.2f}")
        if abs(fee_diff) > 0.005:
            out.append(f"     · 运费+打包费   ¥{fee_diff:>+7.2f}")
        if abs(coupon_diff) > 0.005:
            out.append(f"     · 券收益差      ¥{coupon_diff:>+7.2f}"
                       f"（{best['label']} 用券省 ¥{best['couponSaved']:.2f}，"
                       f"{worst['label']} 省 ¥{worst['couponSaved']:.2f}）")
        out.append(f"     ─────────────────────────────")
        out.append(f"     合计          ¥{check_sum:>+7.2f}")
        if abs(check_sum - diff) > 0.02:
            out.append(f"     ⚠️  拆解与总差额（¥{diff:.2f}）不一致，请复核数据源")
    elif valid:
        out.append(f"⚠️  仅 {valid[0]['label']} 可完整履约：¥{valid[0]['total']:.2f}")
        for r in results:
            if r["missing"]:
                out.append(f"   {r['label']} 缺 {len(r['missing'])} 项，不可选")
    else:
        out.append("❌ 所有渠道均无法完整履约，请调整配餐篮")

    out.append("")
    out.append("提示：券的可用性必须在对应渠道单独试算。"
               "券标签写「外送专用」不代表外送编码能被该券命中。")
    out.append("=" * 68)
    return "\n".join(out)


def main():
    p = argparse.ArgumentParser(description="麦麦减脂搭子 · 下单渠道比价引擎")
    p.add_argument("snapshot", help="渠道快照 JSON 路径")
    args = p.parse_args()

    with open(args.snapshot, encoding="utf-8") as f:
        snap = json.load(f)

    basket = snap["basket"]
    coupons = snap.get("coupons", [])
    results = compare(snap["channels"], basket, coupons)
    print(render(results, basket, snap.get("meta", {})))
    return 0


if __name__ == "__main__":
    sys.exit(main())
