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

# ★ Windows 控制台默认**不是** UTF-8 —— 直接 print("📋") 会
#   ``UnicodeEncodeError: 'gbk' codec can't encode character``。
#   本项目主打 CJK 安全，崩在这里等于自打脸。先切 UTF-8；切不动也不报错。
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

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
for mod, want in [("wbb.bus", "0 项失败"), ("wbb.lease", "0 项失败"),
                  ("wbb.migrate", "全过")]:
    r = subprocess.run([PY, "-X", "utf8", "-m", mod], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    last = (r.stdout or "").strip().splitlines()[-1] if r.stdout else ""
    ok = want in last
    print("  %s ⑦ %s 自测" % ("✅" if ok else "❌", mod.split(".")[-1]))
    if not ok:
        fails.append(mod)

# ⑧ 迁移（新人真会走的路：拿身份块模板 → render → 发现旧引用 → 修 → 复扫）
MIG = os.path.join(TMP, "migrate")
os.makedirs(MIG, exist_ok=True)
IDENT = os.path.join(MIG, "identity.md")
HANDOFF = os.path.join(MIG, "handoff.md")
id_src = os.path.join(ROOT, "templates", "06-identity-block.md")
if os.path.isfile(id_src):
    open(IDENT, "w", encoding="utf-8").write(open(id_src, encoding="utf-8").read())
else:
    print("  ❌ ⑧ 身份块模板不存在")
    fails.append("身份块模板")

sh(["-m", "wbb.cli", "migrate", "render", "--identity", IDENT,
    "--bus", BUS, "--out", HANDOFF], "⑧ migrate render")

# 产物必须真的是「五节齐备」的接续文本 —— 少一节就是少一份上下文
SECTIONS = ["一、你是谁", "二、你在办什么", "三、还没闭口的事",
            "四、迁移后必须先做的三件事", "五、这份文件怎么用"]
htxt = open(HANDOFF, encoding="utf-8").read() if os.path.isfile(HANDOFF) else ""
miss = [s for s in SECTIONS if s not in htxt]
print("  %s ⑧ 接续文本五节齐备%s" % ("✅" if not miss else "❌",
                                   "" if not miss else "  缺 %s" % miss))
if miss:
    fails.append("接续五节")

# 旧引用：先种一个，应当被扫到（退出码 8）；改掉后再扫，应当干净（退出码 0）
STALE = os.path.join(MIG, "notes.md")
OLD = "wbb-usability-old-root"
open(STALE, "w", encoding="utf-8").write("数据目录：" + OLD + "\n")
r = subprocess.run([PY, "-X", "utf8", "-m", "wbb.cli", "migrate", "audit",
                    "--root", MIG, "--old", OLD, "--new", "new-root"],
                   cwd=ROOT, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
caught = r.returncode == 8 and "notes.md" in (r.stdout or "")
print("  %s ⑧ audit 能扫到旧引用（退出码 8）" % ("✅" if caught else "❌"))
if not caught:
    fails.append("audit 命中")

open(STALE, "w", encoding="utf-8").write("数据目录：new-root\n")
r2 = subprocess.run([PY, "-X", "utf8", "-m", "wbb.cli", "migrate", "audit",
                     "--root", MIG, "--old", OLD],
                    cwd=ROOT, capture_output=True, text=True,
                    encoding="utf-8", errors="replace")
gone = r2.returncode == 0
print("  %s ⑧ 改完复扫 → 零命中（退出码 0）" % ("✅" if gone else "❌"))
if not gone:
    fails.append("audit 零命中")

# ⑨ MCP（装了 mcp 包才验，没装则跳过）
#
# ⚠️ 别用「stderr 里有没有某句话」当判据 —— mcp_server.py 在缺包时是
#    **自己 raise SystemExit(3)**，stderr 是它自己的文案；
#    拿 "No module named 'mcp'" 去匹配必然落空 ⇒ CI 上假红（v0.2.2 踩过）。
#    正确做法：**先探测包在不在**。
probe = subprocess.run(
    [PY, "-c", "import importlib.util,sys; "
               "sys.exit(0 if importlib.util.find_spec('mcp') else 1)"],
    capture_output=True)
if probe.returncode != 0:
    print("  ⏭  ⑨ MCP server        跳过（未装 mcp 包）")
else:
    code = ("import sys,os; sys.path.insert(0,'.'); os.environ['WBB_BUS']=r'%s'; "
            "import mcp_server as M; "
            "print('TOOLS=' + ','.join(t.name for t in M.mcp._tool_manager.list_tools()))") % BUS
    r = subprocess.run([PY, "-X", "utf8", "-c", code], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    line = [l for l in (r.stdout or "").splitlines() if l.startswith("TOOLS=")]
    if line:
        print("  ✅ ⑨ MCP server 注册 %d 个工具" % len(line[0][6:].split(",")))
    else:
        print("  ❌ ⑨ MCP server        %s" % (r.stderr or "")[:80])
        fails.append("MCP")

print()
print("=" * 70)
print("结果：%s" % ("✅ 全部通过 —— 开箱可用" if not fails else "❌ 失败项: %s" % fails))
print("=" * 70)
sys.exit(1 if fails else 0)
