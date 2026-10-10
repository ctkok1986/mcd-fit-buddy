#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键运行全部回归测试。任意一项失败即返回非零退出码。"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SUITES = [
    ("配餐求解引擎", "test_planner.py"),
    ("下单比价引擎", "test_order_optimizer.py"),
]


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
        for line in proc.stdout.splitlines():
            if line.startswith("测试结果："):
                try:
                    nums = line.replace("测试结果：", "").replace(" passed,", "").replace(" failed", "")
                    p, f = nums.split()
                    total_pass += int(p)
                    total_fail += int(f)
                except ValueError:
                    pass
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
