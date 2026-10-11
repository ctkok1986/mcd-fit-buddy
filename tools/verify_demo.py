#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网页引擎 ↔ Python 引擎 对拍校验

demo.html 里的计算逻辑是 Python 引擎的 JS 复刻。两套实现若产生不同结果，
比"没有可视化页面"更糟——用户会看到两个互相矛盾的数字。

本脚本把 demo.html 中标记为 __ENGINE_BEGIN__ / __ENGINE_END__ 的纯计算段
抽出来，在 Node 中跑；同一批参数再喂给 Python 引擎；逐项比对。

比对项：
  · BMR / TDEE / 摄入目标 / 蛋白目标 / 缺口
  · 剩余额度 / 压缩比
  · **每个餐次最终选中的餐品名列表**（求解结果完全一致才算通过）
  · 海军法体脂率 / 腹肌可见度分级 / 水潴留

用法：
    python tools/verify_demo.py
退出码 0 = 全部一致；1 = 存在不一致。
"""

import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from abs_engine import abs_visibility, bf_navy, water_index  # noqa: E402
from meal_planner import (  # noqa: E402
    SODIUM_DAILY_CAP, build_slot_plan, build_target, load_items,
)

DEMO = os.path.join(ROOT, "demo.html")


def extract_engine(html):
    """抽出标记之间的纯计算 JS（无 DOM 依赖）。"""
    m = re.search(r"/\*__ENGINE_BEGIN__.*?\*/(.*?)/\*__ENGINE_END__\*/",
                  html, re.S)
    if not m:
        raise SystemExit("❌ demo.html 中找不到 __ENGINE_BEGIN__ / __ENGINE_END__ 标记"
                         "（请先运行 tools/build_demo.py）")
    return m.group(1)


def build_cases():
    """构造覆盖性参数组。"""
    cases = []
    solve_sets = [
        ["breakfast"],
        ["lunch"],
        ["dinner"],
        ["breakfast", "lunch"],
        ["breakfast", "dinner"],
        ["lunch", "dinner"],
        ["breakfast", "lunch", "dinner"],
    ]
    for sex in ("male", "female"):
        for goal in ("cut", "recomp", "gain"):
            for bf in (None, 15.0, 22.0, 31.0):
                for activity in ("sedentary", "light", "moderate"):
                    for solve in solve_sets[:1] + solve_sets[-1:]:
                        cases.append(dict(
                            sex=sex, goal=goal, bodyfat=bf, activity=activity,
                            weight=78.0 if sex == "male" else 65.0,
                            height=175.0 if sex == "male" else 162.0,
                            age=40 if sex == "male" else 32,
                            bmr=1600.0 if sex == "male" else 1350.0,
                            solve=solve, known=[]))
    # 各餐次组合 × 已知餐次（含 0 / 大额 / 超标三种情形）
    known_sets = [
        [],
        [{"label": "午餐", "kcal": 800, "protein": 30, "sodium": 1200}],
        [{"label": "午餐", "kcal": 800, "protein": 30, "sodium": 1200},
         {"label": "晚餐", "kcal": 700, "protein": 35, "sodium": 1000}],
        [{"label": "早餐", "kcal": 520, "protein": 18, "sodium": 900}],
        [{"label": "大餐", "kcal": 1900, "protein": 40, "sodium": 3000}],
        [{"label": "超标餐", "kcal": 2600, "protein": 60, "sodium": 4000}],
    ]
    for solve in solve_sets:
        for known in known_sets:
            cases.append(dict(
                sex="male", goal="recomp", bodyfat=22.0, activity="light",
                weight=78.0, height=175.0, age=40, bmr=1600.0,
                solve=solve, known=known))
    # 不提供实测 BMR（走公式）与不提供体脂率（按体重算蛋白）
    cases.append(dict(sex="male", goal="cut", bodyfat=None, activity="moderate",
                      weight=90.0, height=178.0, age=45, bmr=None,
                      solve=["breakfast", "lunch", "dinner"], known=[]))
    cases.append(dict(sex="female", goal="gain", bodyfat=None, activity="active",
                      weight=55.0, height=160.0, age=28, bmr=None,
                      solve=["lunch"], known=[]))
    # 海军法体脂对拍（男女各若干组，含来源验算样例）
    for sex, h, w, n, hip in (
            ("male", 175, 90, 38, None), ("male", 178, 86, 39, None),
            ("male", 175, 88, 38, None), ("male", 170, 100, 45, None),
            ("female", 165, 75, 32, 98), ("female", 162, 70, 31, 95),
    ):
        cases.append(dict(sex=sex, goal="recomp", bodyfat=None, activity="light",
                          weight=78.0, height=float(h), age=40, bmr=1600.0,
                          solve=["breakfast"], known=[],
                          waist=float(w), neck=float(n),
                          hip=(float(hip) if hip else None)))
    return cases


JS_DRIVER = r"""
const fs = require('fs');
const cases = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const out = cases.map(c => {
  const target = buildTarget({
    sex: c.sex, weight: c.weight, height: c.height, age: c.age,
    activity: c.activity, bodyfat: (c.bodyfat === null ? null : c.bodyfat),
    bmr: (c.bmr === null ? null : c.bmr), goal: c.goal
  });
  const known = (c.known || []).map(m => ({
    label: m.label, kcal: m.kcal, protein: m.protein, sodium: m.sodium
  }));
  const r = buildSlotPlan(ITEMS, target, c.solve, known, 0.5);
  const bf = (c.bodyfat === null) ? null : c.bodyfat;
  let absTitle = null, water = null;
  if (bf !== null) {
    absTitle = absVisibility(c.sex, bf).title;
    const t = r.plan.reduce((a, p) => {
      const tt = totals(p.combo);
      return { sodium: a.sodium + tt.sodium };
    }, { sodium: 0 });
    const totNa = t.sodium + known.reduce((a, m) => a + (m.sodium || 0), 0);
    const w = waterIndex(totNa, c.weight);
    water = { liters: w.liters, grade: w.grade };
  }
  const w = (c.waist !== undefined && c.waist !== null)
    ? bfNavy(c.sex, c.height, c.waist, c.neck,
             (c.hip === undefined ? null : c.hip))
    : null;
  return {
    bmr: target.bmr, tdee: target.tdee, dailyKcal: target.dailyKcal,
    proteinTarget: target.proteinTarget, dailyDeficit: target.dailyDeficit,
    leftKcal: r.info.leftKcal, scale: r.info.scale,
    meals: r.plan.map(p => ({ label: p.label, names: p.combo.map(i => i.name) })),
    absTitle: absTitle, water: water, navy: w
  };
});
console.log(JSON.stringify(out));
"""


class NS:
    """模拟 argparse 结果，供 build_target 使用。"""
    def __init__(self, c):
        self.weight = c["weight"]
        self.height = c["height"]
        self.age = c["age"]
        self.sex = c["sex"]
        self.activity = c["activity"]
        self.bmr = c["bmr"]
        self.bodyfat = c["bodyfat"]
        self.goal = c["goal"]
        self.target_weight = None
        self.weeks = 12.0


def py_run(cases, items):
    out = []
    for c in cases:
        target = build_target(NS(c))
        plan, info = build_slot_plan(items, target, c["solve"],
                                     c.get("known", []), sodium_weight=0.5)
        bf = c["bodyfat"]
        abs_title, water = None, None
        if bf is not None:
            abs_title = abs_visibility(c["sex"], bf)[0]
            tot_na = sum(i["sodium"] for _, combo, _, _ in plan for i in combo) \
                + sum(m.get("sodium", 0) or 0 for m in c.get("known", []))
            liters, grade, _ = water_index(tot_na, c["weight"])
            water = {"liters": liters, "grade": grade}
        navy = None
        if c.get("waist"):
            navy = bf_navy(c["sex"], c["height"], c["waist"], c["neck"],
                           c.get("hip"))[0]
        out.append({
            "bmr": target["bmr"], "tdee": target["tdee"],
            "dailyKcal": target["daily_kcal"],
            "proteinTarget": target["protein_target"],
            "dailyDeficit": target["daily_deficit"],
            "leftKcal": info["left_kcal"], "scale": info["scale"],
            "meals": [{"label": lb, "names": [i["name"] for i in combo]}
                      for lb, combo, _, _ in plan],
            "absTitle": abs_title, "water": water, "navy": navy,
        })
    return out


def close(a, b, tol=0.02):
    if a is None and b is None:
        return True
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= tol
    return a == b


def main():
    if not os.path.exists(DEMO):
        raise SystemExit("❌ 找不到 demo.html，请先运行 tools/build_demo.py")
    html = open(DEMO, encoding="utf-8").read()
    engine = extract_engine(html)

    cases = build_cases()
    tmp = tempfile.mkdtemp()
    cases_path = os.path.join(tmp, "cases.json")
    js_path = os.path.join(tmp, "driver.js")
    with open(cases_path, "w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False)
    with open(js_path, "w", encoding="utf-8") as f:
        f.write(engine + "\n" + JS_DRIVER)

    node = None
    for cand in ("node",):
        try:
            subprocess.run([cand, "--version"], capture_output=True, check=True)
            node = cand
            break
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    if node is None:
        raise SystemExit("❌ 未找到 node，无法对拍")

    proc = subprocess.run([node, js_path, cases_path],
                          capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr)
        raise SystemExit("❌ Node 执行失败")
    js_out = json.loads(proc.stdout)

    items = load_items()
    py_out = py_run(cases, items)

    assert len(js_out) == len(py_out), "数量不一致"

    numeric = ["bmr", "tdee", "dailyKcal", "proteinTarget",
               "dailyDeficit", "leftKcal", "scale"]
    bad = 0
    checked = 0
    for idx, (j, p) in enumerate(zip(js_out, py_out)):
        for k in numeric:
            checked += 1
            if not close(j[k], p[k]):
                bad += 1
                print(f"  ✗ 用例#{idx} [{k}] JS={j[k]} Python={p[k]}")
        checked += 1
        if j["meals"] != p["meals"]:
            bad += 1
            print(f"  ✗ 用例#{idx} [餐品列表不一致]")
            print(f"      JS    : {j['meals']}")
            print(f"      Python: {p['meals']}")
        if j["absTitle"] != p["absTitle"]:
            checked += 1
            bad += 1
            print(f"  ✗ 用例#{idx} [腹肌分级] JS={j['absTitle']} Python={p['absTitle']}")
        else:
            checked += 1
        checked += 1
        if not close(j["navy"], p["navy"], tol=0.05):
            bad += 1
            print(f"  ✗ 用例#{idx} [海军法体脂] JS={j['navy']} Python={p['navy']}")
        checked += 1
        if j["water"] != p["water"] and not (
                j["water"] and p["water"]
                and close(j["water"]["liters"], p["water"]["liters"])
                and j["water"]["grade"] == p["water"]["grade"]):
            bad += 1
            print(f"  ✗ 用例#{idx} [水潴留] JS={j['water']} Python={p['water']}")

    print("=" * 62)
    print(f"对拍用例：{len(cases)} 组")
    print(f"比对项  ：{checked} 项")
    print(f"不一致  ：{bad} 项")
    print("=" * 62)
    if bad:
        print("❌ 网页引擎与 Python 引擎存在不一致")
        return 1
    print("✅ 网页引擎与 Python 引擎逐项一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
