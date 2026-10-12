#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""demo.html 静态一致性检查

页面上的「点了没反应」通常不是逻辑错，而是 **id 写错导致事件没绑上** ——
这类失败不报错、不提示，最难查。本脚本做几项静态检查：

  1. JS 里 $("xxx") 引用的每个 id，HTML 里是否真的存在
  2. HTML 里声明的 id 是否有重复
  3. 模板占位符是否都已替换
  4. ENGINE 标记是否存在（对拍脚本依赖它）
  5. 关键交互元素是否齐全
  6. 是否有指向源码文件的相对链接（Pages 上 .md/.py 会直出源码，必须用绝对地址）

用法：python tools/check_demo.py
"""

import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEMO = os.path.join(ROOT, "demo.html")


def main():
    html = open(DEMO, encoding="utf-8").read()
    script_m = re.search(r"<script>(.*)</script>", html, re.S)
    if not script_m:
        raise SystemExit("❌ demo.html 里没有 <script> 段")
    script = script_m.group(1)
    body = html[:script_m.start()]     # 标记之前的 HTML 部分

    problems = []

    # ── 1. JS 引用的 id 是否都存在 ──
    declared = set(re.findall(r'\bid="([^"]+)"', body))
    used = set(re.findall(r'\$\("([^"]+)"\)', script))
    # 动态生成的元素（写在 JS 模板字符串里的 id/data-*）不算缺失
    dynamic = set(re.findall(r'id="([^"]+)"', script))
    missing = sorted(used - declared - dynamic)
    print(f"  HTML 声明的 id：{len(declared)} 个")
    print(f"  JS 引用的 id  ：{len(used)} 个")
    if missing:
        for m in missing:
            problems.append(f"JS 引用了不存在的 id：{m}（事件将无法绑定，表现为「点了没反应」）")
    else:
        print("  ✅ 引用的 id 全部存在")

    # ── 2. id 是否重复 ──
    dup = [k for k, v in Counter(re.findall(r'\bid="([^"]+)"', html)).items() if v > 1]
    if dup:
        problems.append(f"存在重复 id：{dup}")
    else:
        print("  ✅ 无重复 id")

    # ── 3. 占位符是否已替换（ENGINE 标记是有意保留的，不算）──
    KEEP = {"__ENGINE_BEGIN__", "__ENGINE_END__"}
    leftover = [t for t in re.findall(r"__[A-Z_]+__", html) if t not in KEEP]
    if leftover:
        problems.append(f"占位符未替换：{sorted(set(leftover))}")
    else:
        print("  ✅ 无占位符残留")

    # ── 4. ENGINE 标记（对拍依赖）──
    if "__ENGINE_BEGIN__" in html and "__ENGINE_END__" in html:
        print("  ✅ ENGINE 标记完整")
    else:
        problems.append("缺少 __ENGINE_BEGIN__ / __ENGINE_END__ 标记，对拍脚本会失败")

    # ── 5. 关键交互元素存在性 ──
    for need in ('id="run"', 'id="meals"', 'id="known"', 'id="plan"',
                 'id="target"', 'id="conflict"', 'id="abs"'):
        if need not in body:
            problems.append(f"缺少关键元素 {need}")
    if not any("关键元素" in p for p in problems):
        print("  ✅ 关键交互元素齐全")

    # ── 6. 不允许指向「源码文件」的相对链接 ──
    # demo 部署在 GitHub Pages，而 Pages 的站点根 = 仓库根。
    # 于是 href="SKILL.md" 会命中 .../SKILL.md，Pages 直接以 text/markdown
    # 返回**源码**（31 KB 纯文本）—— 没有渲染、没有仓库上下文，
    # 访客会误以为「这工具把内部配置暴露了」。
    # 所以页面里引用仓库文件，一律写 GitHub 的渲染地址。
    # 注意：指向同站 .html 页面的相对链接是正常的，不算问题。
    RAW_EXT = (".md", ".py", ".json", ".csv", ".txt", ".yml", ".yaml")
    rel_raw = sorted({h for h in re.findall(r'<a\s[^>]*href="([^"]+)"', html)
                      if not h.startswith(("http://", "https://", "#", "mailto:"))
                      and h.lower().split("?")[0].endswith(RAW_EXT)})
    if rel_raw:
        problems.append(f"指向源码文件的相对链接（Pages 上会直出源码，应改成绝对地址）：{rel_raw}")
    else:
        print("  ✅ 无指向源码文件的相对链接")

    print()
    print("=" * 62)
    if problems:
        print(f"❌ 发现 {len(problems)} 个问题：")
        for p in problems:
            print(f"   · {p}")
        return 1
    print("✅ 静态检查全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
