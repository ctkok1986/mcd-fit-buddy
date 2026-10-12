# -*- coding: utf-8 -*-
"""生成 data/combos.json —— 套餐快照（构建期一次性产物）

数据来源：MCP `query-meals` + `query-meal-detail` 的**真实返回**，
于 2026-10-13 00:37 实测自门店 1410098（福州盛世茶亭餐厅，24h 营业）。

为什么要生成而不是运行时拉：
  套餐价格/上下架变化快，但**营养**由组成单品决定、相对稳定。
  按项目既有架构（营养本地算 / 价格走 MCP），这里只落**营养侧快照**，
  价格随快照一起标注时间，**绝不在前端假装实时**。

⚠️ 名称匹配是这里最大的坑：
  菜单名与 `nutrition.csv` 的官方名并不总是一致（如「麦辣鸡翅2块」vs「麦辣鸡翅-2块」），
  且**新品常常没有营养数据**（如马苏里拉拉丝芝士条）。
  本脚本对每个选项做三级匹配（精确 → 别名表 → 规范化），
  匹配不到的**如实记录为 missing**，绝不猜数。
"""
import csv
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")

NUT_PATH = os.path.join(DATA, "nutrition.csv")
ALIAS_PATH = os.path.join(DATA, "name-alias.csv")
OUT_PATH = os.path.join(DATA, "combos.json")

# ── 快照元信息（必须带时间，否则活不过一个月）────────────────────────
SNAPSHOT = {
    "fetched_at": "2026-10-13T00:37+08:00",
    "store_code": "1410098",
    "store_name": "麦当劳福州盛世茶亭餐厅",
    "channel": "到店自取 (orderType=1, beType=1)",
    "source": "MCP query-meals + query-meal-detail",
    "note": "价格为本店快照，实际以门店当时价为准；营养由组成单品加总得出。",
}

# ── 4 个套餐的真实结构（选项格式 "名称|差价"）────────────────────────
# 覆盖三种形态：2 轮（随心配 1+1）/ 3 轮（三件套）/ 4 轮（四件套）
COMBOS = [
    {
        "code": "9900015188",
        "name": "精选超值随心配",
        "price": 13.9, "orig": 13.9,
        "kind": "1+1",
        "rounds": [
            ("蓝区（选 1 主食）", ["高达吉士双牛堡|0", "双层吉士汉堡|1",
                                 "麦乐鸡5块|0", "麦香鸡|0", "小薯条|0"]),
            ("粉区（选 1 小食/饮料）", ["阳光柠檬红茶中杯|0", "怡泉+C麦炫酷|0",
                                       "可乐中杯|0", "香芋派|0", "迷你草莓新地|0",
                                       "迷你朱古力新地|0", "鲜萃冰咖|0", "可乐麦炫酷|0",
                                       "雪碧麦炫酷|0", "无糖可乐麦炫酷|0", "锡兰红茶|0",
                                       "中杯怡泉+C|0", "雪碧中杯|0", "无糖可口可乐中杯|0"]),
        ],
    },
    {
        "code": "9900015187",
        "name": "人气经典随心配",
        "price": 14.9, "orig": 14.9,
        "kind": "1+1",
        "rounds": [
            ("蓝区（选 1 主食）", ["双层吉士汉堡|0", "高达吉士双牛堡|-1",
                                 "麦乐鸡5块|-1", "麦香鸡|-1", "小薯条|-1"]),
            ("粉区（选 1 小食/饮料）", ["可乐麦炫酷|0", "阳光柠檬红茶中杯|0",
                                       "可乐中杯|0", "怡泉+C麦炫酷|0", "香芋派|0",
                                       "迷你草莓新地|0", "迷你朱古力新地|0", "鲜萃冰咖|0",
                                       "雪碧麦炫酷|0", "无糖可乐麦炫酷|0", "锡兰红茶|0",
                                       "中杯怡泉+C|0", "雪碧中杯|0", "无糖可口可乐中杯|0"]),
        ],
    },
    {
        "code": "9900005453",
        "name": "麦香鸡中套餐",
        "price": 28.0, "orig": 41.5,
        "kind": "3件套",
        "rounds": [
            ("汉堡", ["麦香鸡|0"]),
            ("小食", ["中薯条|0", "5块心形薯饼+韩式辣椒黄油风味酱|1",
                     "月下相思扭扭薯|1.5", "大薯条|1.5"]),
            ("饮料", ["可乐中杯|0", "无糖可口可乐中杯|0", "雪碧中杯|0",
                     "阳光柠檬红茶中杯|0", "锡兰红茶|1.5", "纯牛奶|1",
                     "大杯鲜萃咖啡|1.5", "麦咖啡冰美式中杯|9", "麦咖啡热美式中杯|9",
                     "冰浓浓黑巧中杯|11", "热浓浓黑巧中杯|11", "麦咖啡冰奶铁中杯|11",
                     "麦咖啡热奶铁中杯|11", "可乐大杯|2", "无糖可口可乐大杯|2",
                     "雪碧大杯|2", "阳光柠檬红茶大杯|2", "中杯怡泉+C|1.5",
                     "大杯怡泉+C|3.5", "【美汁源】“黄金橙橙”|3", "100%苹果汁|2",
                     "【美汁源】“多汁柠柠”|1", "美禄可可雪冰|3"]),
        ],
    },
    {
        "code": "9900000890",
        "name": "板烧鸡腿堡四件套",
        "price": 28.0, "orig": 57.0,
        "kind": "4件套",
        "rounds": [
            ("汉堡", ["板烧鸡腿堡|0"]),
            ("小食 ①", ["中薯条|0", "奥利奥麦旋风|1", "马苏里拉拉丝芝士条|1.5",
                       "蓝莓爆爆珠麦旋风|2", "5块心形薯饼+韩式辣椒黄油风味酱|1",
                       "月下相思扭扭薯|1.5", "柠檬脆脆麦旋风|2", "泷盐星星麦旋风|2"]),
            ("小食 ②", ["麦乐鸡4块|0", "薄皮焦香V翅|4.5", "麦辣鸡翅2块|3.5",
                       "麦麦脆汁鸡-琵琶腿|3.5", "脆皮鸡柳3根|2.5",
                       "蘸蘸脆皮鸡柳（牧场酱）|5.5", "蘸蘸脆皮鸡柳（山葵酱）|5.5",
                       "韩式烟熏芝士风味酱麦麦脆汁鸡-腿|6.5",
                       "韩式烟熏芝士风味酱脆皮鸡柳|5.5"]),
            ("饮料", ["可乐中杯|0", "无糖可口可乐中杯|0", "雪碧中杯|0",
                     "阳光柠檬红茶中杯|0", "锡兰红茶|0", "纯牛奶|1", "100%苹果汁|2",
                     "大杯鲜萃咖啡|1.5", "麦咖啡冰美式中杯|9", "麦咖啡热美式中杯|9",
                     "冰浓浓黑巧中杯|11", "热浓浓黑巧中杯|11", "麦咖啡冰奶铁中杯|11",
                     "麦咖啡热奶铁中杯|11", "冰浓浓燕麦黑巧中杯|13",
                     "热浓浓燕麦黑巧中杯|13", "可乐大杯|2", "无糖可口可乐大杯|2",
                     "雪碧大杯|2", "阳光柠檬红茶大杯|2", "中杯怡泉+C|1.5",
                     "大杯怡泉+C|3.5", "【美汁源】“黄金橙橙”|3",
                     "【美汁源】“多汁柠柠”|1", "鲜萃冰咖|1.5", "美禄可可雪冰|3",
                     "可乐麦炫酷|2.5", "雪碧麦炫酷|2.5", "无糖可乐麦炫酷|2.5",
                     "怡泉+C麦炫酷|4"]),
        ],
    },
]


def load_nutrition():
    rows = list(csv.DictReader(open(NUT_PATH, encoding="utf-8-sig")))
    return {r["name"]: r for r in rows}


def load_aliases():
    if not os.path.exists(ALIAS_PATH):
        return {}
    out = {}
    for r in csv.DictReader(open(ALIAS_PATH, encoding="utf-8-sig")):
        out[r["menu_name"].strip()] = r["nutrition_name"].strip()
    return out


def _norm(s):
    s = s.replace("™", "").replace("（", "(").replace("）", ")")
    s = re.sub(r"[\s\-－—]", "", s)
    return s


def make_matcher(nut, alias):
    nmap = {}
    for n in nut:
        nmap.setdefault(_norm(n), n)

    def match(menu_name):
        # ① 精确
        if menu_name in nut:
            return menu_name, "exact"
        # ② 别名表
        a = alias.get(menu_name)
        if a and a in nut:
            return a, "alias"
        # ③ 规范化
        k = _norm(menu_name)
        if k in nmap:
            return nmap[k], "norm"
        # ④ 数字位置互换：麦乐鸡4块 <-> 4块麦乐鸡
        m = re.match(r"^(.*?)(\d+)(.*)$", k)
        if m:
            alt = m.group(1) + m.group(3) + m.group(2)
            if alt in nmap:
                return nmap[alt], "num-swap"
        return None, "MISS"

    return match


def main():
    nut = load_nutrition()
    alias = load_aliases()
    match = make_matcher(nut, alias)

    out_combos = []
    all_missing = {}
    total_choices = total_ok = 0
    default_all_ok = True

    for c in COMBOS:
        rounds_out = []
        default_menu = []      # MCP 的真实默认（可能没营养数据）
        default_pick = []      # 其中能匹配到营养表的
        default_ok = True

        for rname, choices in c["rounds"]:
            ch_out = []
            for raw in choices:
                name, dp = raw.rsplit("|", 1)
                dp = float(dp)
                got, how = match(name)
                total_choices += 1
                if got:
                    total_ok += 1
                    r = nut[got]
                    ch_out.append({
                        "name": got,
                        "menu_name": name if name != got else None,
                        "diff": dp,
                        "kcal": float(r["kcal"]),
                        "protein": float(r["protein_g"]),
                        "sodium": float(r["sodium_mg"]),
                    })
                else:
                    all_missing.setdefault(name, set()).add(c["name"])
            if not ch_out:
                raise SystemExit(f"❌ 【{c['name']}】的「{rname}」没有任何可匹配选项")

            # ⚠️ 默认 = 该轮**原始列表的第一项**（MCP 中 quantity>=1 的项实测均排首位）。
            #    不能取「第一个可匹配项」—— 那会把默认项换成别的，价格和营养都错。
            dname = choices[0].rsplit("|", 1)[0]
            dgot, _ = match(dname)
            default_menu.append(dname)
            if dgot:
                default_pick.append(dgot)
            else:
                default_ok = False
            rounds_out.append({"name": rname, "choices": ch_out})

        # 默认组合营养：**只有在全部默认项都能匹配时才算**，否则如实置 null
        dt = None
        if default_ok:
            tk = tp = ts = 0.0
            for nm in default_pick:
                r = nut[nm]
                tk += float(r["kcal"]); tp += float(r["protein_g"]); ts += float(r["sodium_mg"])
            dt = {"kcal": tk, "protein": tp, "sodium": ts}

        out_combos.append({
            "code": c["code"],
            "name": c["name"],
            "kind": c["kind"],
            "price": c["price"],
            "orig": c["orig"],
            "save": round(c["orig"] - c["price"], 2),
            "rounds": rounds_out,
            "default_menu": default_menu,
            "default_total": dt,
        })

    doc = {
        "snapshot": SNAPSHOT,
        "combos": out_combos,
        "missing_options": sorted(all_missing),
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)

    # ── 报告 ──
    print(f"已生成 {os.path.relpath(OUT_PATH, ROOT)}")
    print(f"  套餐 {len(out_combos)} 个｜选项 {total_ok}/{total_choices} 可算营养"
          f"（{total_ok/total_choices*100:.0f}%）")
    print()
    for c in out_combos:
        d = c["default_total"]
        if d:
            shown = f"{d['kcal']:.0f}kcal/{d['protein']:.0f}P/{d['sodium']:.0f}Na"
        else:
            miss = [m for m in c["default_menu"] if m not in {x for r in c["rounds"] for x in [c2["name"] for c2 in r["choices"]]}]
            shown = f"默认组合营养缺失（{','.join(c['default_menu'])}）"
        print(f"  {c['name']:<14} ¥{c['price']:<5} 省¥{c['save']:<5} {shown}")
    print()
    print(f"  ❌ 无营养数据的选项 {len(all_missing)} 个（如实标注，不猜数）：")
    for m in sorted(all_missing):
        print(f"     · {m}")
    print()
    print(f"  文件大小 {os.path.getsize(OUT_PATH):,} 字节")


if __name__ == "__main__":
    main()
