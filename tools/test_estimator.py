#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「描述 → 营养」估算器测试

estimateMeal 是 demo.html 里的用户输入解析器。它在纯文本上做三件事：
  1. 找出食物（最长别名优先，避免「甜豆浆」被「豆浆」截胡）
  2. 找出数量（并把数量就近配对给最近的食物）
  3. 按食物基准量换算（避免「鸡胸肉100克」被算成 100 份）

这些都会出错，所以每个用例的期望值都**手算**写死在这里，
而不是用实现去「验证实现」。

用法：python tools/test_estimator.py
"""

import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEMO = os.path.join(ROOT, "demo.html")

# (输入, 期望热量, 期望蛋白, 期望钠, 说明)
CASES = [
    ("两个包子一杯豆浆", 225 * 2 + 125, 6.5 * 2 + 11, 325 * 2 + 15,
     "无分隔连写 + 中文数量；数量需就近配对"),
    ("2个肉包 1杯牛奶", 250 * 2 + 130, 8 * 2 + 8, 400 * 2 + 100,
     "阿拉伯数字 + 空格分隔"),
    ("白粥一碗 鸡蛋一个", 90 + 70, 2 + 6.5, 10 + 66,
     "数量在食物名之后"),
    ("八宝粥一碗", 400, 16, 50,
     "关键：「八」不能被当成 8 份"),
    ("甜豆浆一杯", 190, 11, 15,
     "关键：不能被「豆浆」截胡成 125 kcal"),
    ("鸡胸肉100克", 165, 31, 74,
     "关键：100 克要换算成 1 份，不是 100 份"),
    ("米饭150克", 200, 4, 5,
     "按该食物基准量 1碗=150g 换算"),
    ("盒饭一份", 800, 30, 1800,
     "单份、无数量词"),
    ("一个苹果 一杯无糖可乐", 104 + 0, 0.5 + 0, 2 + 10,
     "无糖可乐热量为 0"),
    ("油条两根 豆浆一杯", 285 * 2 + 125, 4 * 2 + 11, 300 * 2 + 15,
     "「两」作数字而非单位"),
    ("半个红薯", 150 * 0.5, 2 * 0.5, 20 * 0.5,
     "半份"),
    ("小笼包一笼", 400, 16, 700,
     "按「笼」计份"),
    ("3杯豆浆", 125 * 3, 11 * 3, 15 * 3,
     "阿拉伯数字 + 份数"),
    ("玉米一根 红薯一个", 120 + 150, 4 + 2, 5 + 20,
     "多个食物 + 中文数量"),
    ("红薯200克 鸡胸肉150克", 150 * (200 / 150) + 165 * 1.5,
     2 * (200 / 150) + 31 * 1.5, 20 * (200 / 150) + 74 * 1.5,
     "克重换算（不同基准量）"),
    ("没吃早饭", 0, 0, 0,
     "纯文字无食物 → 应全部落在未识别"),
]

JS_DRIVER = r"""
const fs = require('fs');
const cases = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const out = cases.map(t => {
  const r = estimateMeal(t);
  return {tot: r.tot, hits: r.hits.map(h => h.name + '|' + h.qty),
          missed: r.missed};
});
console.log(JSON.stringify(out));
"""


def extract_engine(html):
    m = re.search(r"/\*__ENGINE_BEGIN__.*?\*/(.*?)/\*__ENGINE_END__\*/", html, re.S)
    if not m:
        raise SystemExit("❌ demo.html 缺少 __ENGINE_BEGIN__/__ENGINE_END__ 标记")
    return m.group(1)


def main():
    if not os.path.exists(DEMO):
        raise SystemExit("❌ 找不到 demo.html，请先运行 tools/build_demo.py")
    engine = extract_engine(open(DEMO, encoding="utf-8").read())

    tmp = tempfile.mkdtemp()
    cases_path = os.path.join(tmp, "cases.json")
    js_path = os.path.join(tmp, "drv.js")
    with open(cases_path, "w", encoding="utf-8") as f:
        json.dump([c[0] for c in CASES], f, ensure_ascii=False)
    with open(js_path, "w", encoding="utf-8") as f:
        f.write(engine + "\n" + JS_DRIVER)

    proc = subprocess.run(["node", js_path, cases_path],
                          capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr)
        raise SystemExit("❌ Node 执行失败")
    got = json.loads(proc.stdout)

    passed = failed = 0
    for i, case in enumerate(CASES):
        text, ek, ep, en, note = case
        g = got[i]
        ok = (abs(g["tot"]["kcal"] - ek) < 0.02
              and abs(g["tot"]["protein"] - ep) < 0.02
              and abs(g["tot"]["sodium"] - en) < 0.02)
        if ok:
            passed += 1
            print(f"  PASS  {text!r}")
            print(f"        {g['tot']['kcal']:.0f} kcal｜蛋白 "
                  f"{g['tot']['protein']:.1f} g｜钠 {g['tot']['sodium']:.0f} mg"
                  f"　—— {note}")
        else:
            failed += 1
            print(f"  FAIL  {text!r}　（{note}）")
            print(f"        期望 {ek:.0f} kcal / {ep:.1f} g / {en:.0f} mg")
            print(f"        实得 {g['tot']['kcal']:.0f} kcal / "
                  f"{g['tot']['protein']:.1f} g / {g['tot']['sodium']:.0f} mg")
        if g["missed"]:
            print(f"        未识别：{g['missed']}")

    # 未识别用例单独断言（最后一条：纯文字无食物）
    last = got[-1]
    if last["missed"] and not last["hits"]:
        passed += 1
        print(f"  PASS  '没吃早饭' 全部落入未识别：{last['missed']}")
    else:
        failed += 1
        print(f"  FAIL  '没吃早饭' 应无命中、全部未识别，实得 {last}")

    print()
    print("=" * 62)
    print(f"结果：{passed} passed, {failed} failed")
    print("=" * 62)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
