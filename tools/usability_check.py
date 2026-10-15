# -*- coding: utf-8 -*-
"""开箱可用性实测 —— 模拟「新人拿到这个仓库」的完整路径。

为什么单独有这个脚本（而不是靠自测）：
  自测覆盖的是「**我以为会错的**」，这个脚本覆盖的是「**用户真会走的路径**」。
  两者不重合 —— v0.2.2 修的「表格被空行截断」就是本脚本抓到的：
  自测里有同款结构，但检查项没覆盖"表格连续性"。

在临时目录跑，**不碰任何真实数据**。

用法：  python tools/usability_check.py
退出码：0 = 全部通过
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
TMP = os.path.join(tempfile.gettempdir(), "wbb-usability")
os.makedirs(TMP, exist_ok=True)
BUS = os.path.join(TMP, "00-bus.md")

fails = []


def sh(args, label):
    r = subprocess.run([PY, "-X", "utf8"] + args, cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    ok = r.returncode == 0
    print("  %s %-30s %s" % ("✅" if ok else "❌", label,
                             out.splitlines()[-1][:56] if out else ""))
    if not ok:
        fails.append(label)
    return r


print("=" * 70)
print("wb-bot 开箱可用性实测（模拟新人完整路径）")
print("=" * 70)

# ① 用模板建总线
src = os.path.join(ROOT, "templates", "00-bus.md")
if os.path.isfile(src):
    open(BUS, "w", encoding="utf-8").write(open(src, encoding="utf-8").read())
    print("  ✅ ① 用模板建总线")
else:
    print("  ❌ ① 模板不存在")
    fails.append("模板")

# ② - ⑥ CLI 全流程
sh(["-m", "wbb.cli", "--bus", BUS, "append",
    "alice|architect|拆了两个任务，派给 bob|done|tasks/T01.md|bob"], "② append")
sh(["-m", "wbb.cli", "--bus", BUS, "append",
    "bob|executor|T01 完成，过了 12 个断言|done|out/t01.log|reviewer"], "② append ×2")
sh(["-m", "wbb.cli", "--bus", BUS, "verify"], "③ verify")
sh(["-m", "wbb.cli", "--bus", BUS, "read", "--since", "0"], "④ read --since 0")
sh(["-m", "wbb.cli", "--bus", BUS, "claim", "shared.md|我要改这个"], "⑤ claim")
sh(["-m", "wbb.cli", "--bus", BUS, "release", "shared.md"], "⑤ release")
sh(["-m", "wbb.cli", "--bus", BUS, "view", "alice"], "⑥ view")

# ★ 表格连续性（v0.2.2 的 bug 就是在这里现形）
gl = open(BUS, encoding="utf-8").read().splitlines()
rows = [i for i, l in enumerate(gl) if l.lstrip().startswith("|") and l.count("|") >= 6]
gaps = [i for i in range(rows[0], rows[-1]) if not gl[i].strip()]
print("  %s ★  表格连续（无空行截断）%s" % ("✅" if not gaps else "❌",
                                        "" if not gaps else "  空洞 @ L%s" % [g + 1 for g in gaps]))
if gaps:
    fails.append("表格连续性")

# ⑦ 自测
for mod, want in [("wbb.bus", "0 项失败"), ("wbb.lease", "0 项失败")]:
    r = subprocess.run([PY, "-X", "utf8", "-m", mod], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    last = (r.stdout or "").strip().splitlines()[-1] if r.stdout else ""
    ok = want in last
    print("  %s ⑦ %s 自测" % ("✅" if ok else "❌", mod.split(".")[-1]))
    if not ok:
        fails.append(mod)

# ⑧ MCP（装了 mcp 包才验，没装则跳过 —— 不算失败）
code = ("import sys,os; sys.path.insert(0,'.'); os.environ['WBB_BUS']=r'%s'; "
        "import mcp_server as M; "
        "print('TOOLS=' + ','.join(t.name for t in M.mcp._tool_manager.list_tools()))") % BUS
r = subprocess.run([PY, "-X", "utf8", "-c", code], cwd=ROOT,
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
line = [l for l in (r.stdout or "").splitlines() if l.startswith("TOOLS=")]
if line:
    print("  ✅ ⑧ MCP server 注册 %d 个工具" % len(line[0][6:].split(",")))
elif "No module named 'mcp'" in (r.stderr or ""):
    print("  ⏭  ⑧ MCP server        跳过（未装 mcp 包）")
else:
    print("  ❌ ⑧ MCP server        %s" % (r.stderr or "")[:80])
    fails.append("MCP")

print()
print("=" * 70)
print("结果：%s" % ("✅ 全部通过 —— 开箱可用" if not fails else "❌ 失败项: %s" % fails))
print("=" * 70)
sys.exit(1 if fails else 0)
