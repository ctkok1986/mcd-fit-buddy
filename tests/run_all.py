#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键运行全部回归测试。任意一项失败即返回非零退出码。"""

import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SUITES = [
    ("配餐求解引擎", "test_planner.py"),
    ("下单比价引擎", "test_order_optimizer.py"),
    ("剩余额度追踪", "test_budget_tracker.py"),
    ("券上下文", "test_coupon_context.py"),
    ("体成分与腹肌引擎", "test_abs_engine.py"),
    ("目标模式与券优先级", "test_goals.py"),
    ("餐次级填空求解", "test_slots.py"),
    ("营养数据查询", "test_nutrition_lookup.py"),
]

# 各套件汇总行写法不一（"结果：" / "测试结果："），统一用正则抓计数，
# 避免因前缀差异导致漏统计。
SUMMARY = re.compile(r"(\d+)\s+passed,\s*(\d+)\s+failed")


def main():
    total_pass = total_fail = 0
    failed_suites = []

    for label, script in SUITES:
        print()
        print("#" * 64)
        print(f"# {label}  ({script})")
        print("#" * 64)
        proc = subprocess.run([sys.executable, os.path.join(HERE, script)],
                              capture_output=True, text=True, encoding="utf-8")
        print(proc.stdout)
        if proc.stderr:
            print(proc.stderr)
        found = SUMMARY.findall(proc.stdout)
        if found:
            p, f = found[-1]        # 取最后一行汇总
            total_pass += int(p)
            total_fail += int(f)
        else:
            print(f"  ⚠️  {script} 未输出可识别的汇总行，计数可能不准")
        if proc.returncode != 0:
            failed_suites.append(label)

    print()
    print("=" * 64)
    print(f"总计：{total_pass} passed, {total_fail} failed")
    if failed_suites:
        print(f"失败套件：{', '.join(failed_suites)}")
    print("=" * 64)
    return 1 if (total_fail or failed_suites) else 0


if __name__ == "__main__":
    sys.exit(main())
