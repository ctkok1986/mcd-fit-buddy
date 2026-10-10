#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦麦减脂搭子 · 券上下文模块

职责：把"券仓"数据接入配餐求解，让配餐自动优先使用【最优惠券】与【临期券】。

三条设计原则（来自实测踩坑）：
  1. 券与商品靠【名称】匹配 —— 券绑定的是某渠道的 productCode，
     而配餐用的是营养表名称，两套体系不同，必须归一化后按名匹配
  2. 券不是"有就能用" —— 带 `unavailable: true` 的券不计入优惠，
     只做提示（实测有券标着"已领取"却报 600012 不可用）
  3. 优先级 = 省钱额为主 + 临期紧迫度为辅 —— 用户要的是"最优惠优先"，
     但不能让临期的小额券盖过大额券，也不能让不着急的券一直压着临期券

券快照 JSON 格式：
{
  "meta": { "generated_at": "...", "storeCode": "...", "channel": "pickup" },
  "coupons": [
    {
      "title": "9.9元中杯冰美式",
      "couponId": "...", "couponCode": "...",
      "productCode": "507411",
      "menuName": "麦咖啡™冰美式中杯",
      "listPrice": 11.9, "couponPrice": 9.9,
      "validUntil": "2026-10-16 23:59",
      "channelTags": ["到店专用", "外送专用"],
      "unavailable": false
    }
  ]
}
"""

import json
import re
from datetime import datetime

# 名称归一化时剔除的修饰词（渠道/品牌/规格差异）
NOISE = [
    "™", "（盒装）", "(盒装)", "盒装", "麦咖啡",
    "冰", "热", "中杯", "大杯", "小杯", "（冰/热）", "(冰/热)",
]

# 临期阈值（小时）→ urgency 权重
URGENCY_TIERS = [
    (24, 1.0),      # 24 小时内到期：最高优先
    (72, 0.6),      # 3 天内
    (168, 0.3),     # 7 天内
]
URGENCY_FLOOR = 0.1  # 7 天以上

# 临期加分：优惠额相当时，每 1 点紧迫度折算的额外优先级（单位：元）
# 取 0.5 —— 意味着"快过期"最多相当于多省 0.5 元，
# 不会盖过明显的优惠额差距。
URGENT_BONUS = 0.5


def normalize(name):
    """把商品名归一化，用于券与餐品匹配。"""
    s = (name or "").strip()
    for w in NOISE:
        s = s.replace(w, "")
    return re.sub(r"\s+", "", s)


def parse_time(text):
    """解析时间字符串。

    同时兼容空格分隔与 ISO 的 'T' 分隔（券接口与本地脚本格式不一致）。
    """
    if not isinstance(text, str):
        return None
    s = text.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def compute_urgency(valid_until, now):
    """临期紧迫度：0（不紧迫/已过期）~ 1（马上过期）。"""
    dt = parse_time(valid_until) if isinstance(valid_until, str) else valid_until
    if dt is None:
        return 0.0
    hours = (dt - now).total_seconds() / 3600
    if hours <= 0:
        return 0.0          # 已过期，不再激励
    for limit, weight in URGENCY_TIERS:
        if hours <= limit:
            return weight
    return URGENCY_FLOOR


def load_coupons(path, now=None):
    """载入券快照，返回 (可用券列表, 被排除券列表, meta)。

    被排除 = 已过期 或 标记为不可用（如实测报 600012 的券）。
    """
    now = now or datetime.now()
    with open(path, encoding="utf-8-sig") as f:
        snap = json.load(f)

    usable, excluded = [], []
    for c in snap.get("coupons", []):
        dt = parse_time(c.get("validUntil", ""))
        rec = dict(c)
        rec["_until"] = dt
        rec["urgency"] = compute_urgency(c.get("validUntil"), now)
        rec["_key"] = normalize(c.get("menuName") or c.get("title", ""))

        if c.get("unavailable"):
            rec["_reason"] = "计价实测不可用"
            excluded.append(rec)
        elif dt is not None and dt < now:
            rec["_reason"] = "已过期"
            excluded.append(rec)
        else:
            usable.append(rec)

    return usable, excluded, snap.get("meta", {})


class CouponContext:
    """配餐时使用的券上下文。"""

    def __init__(self, usable, excluded, meta=None):
        self.usable = usable
        self.excluded = excluded
        self.meta = meta or {}
        # 归一化名 -> 券（同名取优惠最大的那张）
        self.by_name = {}
        for c in usable:
            k = c["_key"]
            if not k:
                continue
            cur = self.by_name.get(k)
            if cur is None or self._saving(c) > self._saving(cur):
                self.by_name[k] = c

    @staticmethod
    def _saving(c):
        try:
            return float(c.get("listPrice", 0)) - float(c.get("couponPrice", 0))
        except (TypeError, ValueError):
            return 0.0

    def lookup(self, item_name):
        """按餐品名找可用券。"""
        return self.by_name.get(normalize(item_name))

    def urgency_of(self, item_name):
        """该餐品对应券的临期紧迫度；无券为 0。"""
        c = self.lookup(item_name)
        return c["urgency"] if c else 0.0

    def value_of(self, item_name):
        """该餐品对应券的综合优先级。

        返回 (省钱金额, 紧迫度, 综合分)；无券返回 (0, 0, 0)。

        综合分 = 省钱额 + URGENT_BONUS × 紧迫度
        —— **省钱额是主排序**（用户明确要求"最优惠的券优先使用"），
           紧迫度作为加分项：优惠额相当时，先用快过期的。
           这样既不会为了用掉小额临期券而放弃更大的优惠，
           也不会让一张不着急的大额券永远压着临期券不用。
        """
        c = self.lookup(item_name)
        if not c:
            return 0.0, 0.0, 0.0
        saved = self._saving(c)
        urg = c["urgency"]
        return saved, urg, saved + URGENT_BONUS * urg

    def price_of(self, item):
        """返回 (原价, 券后价, 立省)。无券时券后价 = 原价。"""
        c = self.lookup(item["name"])
        base = float(item.get("price", 0))
        if not c:
            return base, base, 0.0
        cp = float(c.get("couponPrice", base))
        # 券价高于现价时不用券（避免负优化）
        if cp >= base:
            return base, base, 0.0
        return base, cp, round(base - cp, 2)

    def summary(self):
        """券仓概览：可用张数、临期张数、被排除张数与原因。"""
        urgent = [c for c in self.usable if c["urgency"] >= 0.6]
        return {
            "usable": len(self.usable),
            "urgent": len(urgent),
            "excluded": len(self.excluded),
        }
