# -*- coding: utf-8 -*-
"""
wbb.migrate —— 运行时迁移助手（精简参考实现）

为什么需要它
------------
Agent 会话是**会被重建的**。上下文塞满、模型换代、机器重装、进程崩了 ——
任何一种都会让一条长期会话「换一个壳继续活着」。

换壳时最容易丢的恰恰是最要紧的两样：

  1. **它是谁** —— 身份 / 职责 / 边界。丢了就会开始干不属于自己的活。
  2. **它在办什么** —— 未闭事项。丢了就会出现「同一件事被做两遍」或「没人接着做」。

而这两样**都不会报错**：新会话启动得很正常，只是从零开始。

它做两件事
----------
``render``
    把「身份块 + 总线里的在办事实」渲染成一份**接续文本**，
    放在新会话「启动必读」的位置。**生成物不手改**，改源。

``audit``
    迁移**之后**扫一遍：哪些文件里还写着**旧位置**。
    这是迁移里最阴的一类故障 —— 路径写死 → 搬家后**静默失效**（不报错、只读空）。

退出码
------
``0``  无待处理引用
``8``  audit 有命中（需人工处理）

自测::

    python -m wbb.migrate
"""

from __future__ import annotations

import os
import re
import sys
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .bus import Bus, _marks, _safe_stdout

EXIT_OK = 0
EXIT_NEEDS_WORK = 8

# 渲染出的接续文本固定五节。写死成常量是为了**能被自测**：
# 少一节 = 新会话少一份上下文，而这种缺失从输出里看不出来。
SECTION_TITLES: Tuple[str, ...] = (
    "一、你是谁（身份块）",
    "二、你在办什么（最近事实）",
    "三、还没闭口的事",
    "四、迁移后必须先做的三件事",
    "五、这份文件怎么用",
)

# 视为「已闭口」的状态词。其余一律当成未闭口 —— 宁可多提醒一次。
CLOSED_STATUS = {"done", "完成", "已闭", "已闭口", "closed", "ok", "pass", "通过"}

SKIP_DIRS = frozenset({
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    "dist", "build", ".locks", "archive", "views",
    ".mypy_cache", ".pytest_cache", ".idea", ".vscode",
})

SCAN_EXT = frozenset({
    ".md", ".markdown", ".txt", ".py", ".json", ".yml", ".yaml", ".toml",
    ".cfg", ".ini", ".sh", ".bat", ".ps1", ".vbs", ".csv", ".tsv", ".xml",
    ".html", ".css", ".js", ".ts", ".sql", "",
})

DEFAULT_MAX_BYTES = 2000000


# --------------------------------------------------------------------------
# render
# --------------------------------------------------------------------------
def _is_closed(status: str) -> bool:
    return (status or "").strip().lower() in CLOSED_STATUS


def _fmt_row(rec: Dict[str, object]) -> str:
    cells = [str(rec.get(k, "-") or "-").replace("|", "\\|")
             for k in ("id", "time", "source", "role", "what", "status", "artifact", "need")]
    return "| " + " | ".join(cells) + " |"


def build_handoff(
    identity: str = "",
    records: Optional[Sequence[Dict[str, object]]] = None,
    title: str = "接续文本",
    source_note: str = "",
) -> str:
    """拼出接续文本。**纯函数**（不碰文件系统）—— 方便直接自测。"""
    records = list(records or [])
    open_items = [r for r in records if not _is_closed(str(r.get("status", "")))]

    L: List[str] = []
    L.append("# " + title.strip())
    L.append("")
    L.append("> 本文件由 `wbb migrate render` 生成，**不要手改** —— 要改就改源，然后重新生成。")
    if source_note:
        L.append("> 来源：" + source_note)
    L.append("")
    L.append("---")
    L.append("")

    # 一
    L.append("## " + SECTION_TITLES[0])
    L.append("")
    L.append(identity.strip() if identity.strip() else
             "_（未提供身份块文件。**这是一处缺口**：新会话会不知道自己是谁、"
             "边界在哪。建议补上再迁移。）_")
    L.append("")

    # 二
    L.append("## " + SECTION_TITLES[1])
    L.append("")
    if records:
        L.append("| ID | 时间 | 来源 | 角色 | 做了什么 | 状态 | 产物 | 需要谁 |")
        L.append("|---|---|---|---|---|---|---|---|")
        for r in records:
            L.append(_fmt_row(r))
    else:
        L.append("_（没有取到事实条目。若源总线为空，属正常；"
                 "否则检查总线路径是否指对了。）_")
    L.append("")

    # 三
    L.append("## " + SECTION_TITLES[2])
    L.append("")
    if open_items:
        for r in open_items:
            L.append("- [ ] #%s %s —— **%s**（产物：%s）"
                     % (r.get("id"), str(r.get("what", "")).strip(),
                        str(r.get("status", "")).strip() or "未知",
                        str(r.get("artifact", "-")).strip() or "-"))
    else:
        L.append("- [x] 无未闭口事项。")
    L.append("")

    # 四
    L.append("## " + SECTION_TITLES[3])
    L.append("")
    L.append("1. **读第三节**，逐条认领 —— 没认领的，回来在总线里写明「我不接」。")
    L.append("2. **跑一次迁移审计**：`python -m wbb.cli migrate audit --root . --old <旧位置>` "
             "把还指着旧位置的地方全部改掉。**不改就会静默失效**（不报错、只读空）。")
    L.append("3. **登记接续**：往总线追加一条，写明「谁接的、从哪接的」。"
             "这是事实登记，不是请示。")
    L.append("")

    # 五
    L.append("## " + SECTION_TITLES[4])
    L.append("")
    L.append("- **什么时候读**：本会话被重建（换壳/换机/换代）后的**第一份**。")
    L.append("- **什么时候重建**：源变了就重新生成，别在生成物上打补丁。")
    L.append("- **和别的东西什么关系**：这份只管「接上」；"
             "「单子怎么派才不丢」看交接纪律那篇。")
    L.append("")
    return "\n".join(L)


def render(
    identity_path: str = "",
    bus_path: str = "",
    tail: int = 20,
    title: str = "接续文本",
    out_path: str = "",
    quiet: bool = False,
) -> int:
    identity = ""
    if identity_path:
        if not os.path.isfile(identity_path):
            sys.stderr.write("找不到身份块文件：%s\n" % identity_path)
            return 2
        identity = open(identity_path, encoding="utf-8", errors="replace").read()

    records: List[Dict[str, object]] = []
    note_bits: List[str] = []
    if bus_path:
        if not os.path.isfile(bus_path):
            sys.stderr.write("找不到总线文件：%s\n" % bus_path)
            return 2
        bus = Bus(bus_path)
        allrec = bus.read()
        records = allrec[-tail:] if tail > 0 else allrec
        note_bits.append("%s（共 %d 条，取末尾 %d 条）"
                         % (os.path.basename(bus_path), len(allrec), len(records)))

    txt = build_handoff(identity=identity, records=records, title=title,
                        source_note=" · ".join(note_bits))

    if out_path:
        d = os.path.dirname(os.path.abspath(out_path))
        if d:
            os.makedirs(d, exist_ok=True)
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(txt)
        if not quiet:
            missing = [s for s in SECTION_TITLES if ("## " + s) not in txt]
            print("已生成接续文本：%s" % out_path)
            print("  身份块 %s ｜ 事实 %d 条 ｜ 未闭口 %d 条"
                  % ("有" if identity.strip() else "**缺**", len(records),
                     len([r for r in records if not _is_closed(str(r.get("status", "")))])))
            print("  自检：五节%s" % ("齐备" if not missing else "**缺 %s**" % missing))
    else:
        print(txt)
    return 0


# --------------------------------------------------------------------------
# audit
# --------------------------------------------------------------------------
def _looks_binary(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return b"\x00" in f.read(4096)
    except OSError:
        return True


def _iter_scan_files(root: str, max_bytes: int) -> Iterable[str]:
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            p = os.path.join(dp, fn)
            ext = os.path.splitext(fn)[1].lower()
            if ext not in SCAN_EXT and not fn.startswith(".git"):
                continue
            try:
                if os.path.getsize(p) > max_bytes:
                    continue
            except OSError:
                continue
            if _looks_binary(p):
                continue
            yield p


def audit(
    root: str,
    olds: Sequence[str],
    new: str = "",
    max_bytes: int = DEFAULT_MAX_BYTES,
    quiet: bool = False,
) -> int:
    """扫出还指着**旧位置**的引用。返回 0（干净）或 8（有命中）。"""
    olds = [o for o in (olds or []) if o]
    if not root or not os.path.isdir(root):
        sys.stderr.write("audit 需要一个存在的目录：--root <目录>\n")
        return 2
    if not olds:
        sys.stderr.write("audit 至少要给一个旧位置片段：--old <片段>（可多次）\n")
        return 2

    hits: List[Tuple[str, int, str, str]] = []   # (文件, 行号, 命中的片段, 原文)
    scanned = 0
    for p in _iter_scan_files(root, max_bytes):
        scanned += 1
        try:
            txt = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if not any(o in txt for o in olds):
            continue
        rel = os.path.relpath(p, root)
        for i, line in enumerate(txt.splitlines(), 1):
            for o in olds:
                if o in line:
                    hits.append((rel, i, o, line.strip()[:160]))
                    break

    if not quiet:
        print("=" * 70)
        print("迁移审计 · %s" % os.path.abspath(root))
        print("=" * 70)
        print("  扫描 %d 个文本文件 ｜ 旧位置片段 %d 个" % (scanned, len(olds)))
        for o in olds:
            print("    · 旧：%s%s" % (o, ("  →  新：" + new) if new else ""))
        print()

    if not hits:
        if not quiet:
            print("  ✅ 零命中：已经没有任何地方指着旧位置。")
        return EXIT_OK

    if not quiet:
        print("  ❌ %d 处引用仍指着旧位置 —— **这些不会报错，只会静默失效**：" % len(hits))
        for rel, ln, o, line in hits:
            print("    %s : L%d" % (rel, ln))
            print("        %s" % line)
            if new:
                print("        → 建议：%s  →  %s" % (o, new))
        print()
        print("  处理完再跑一次本命令；零命中才算迁移收尾。")
    return EXIT_NEEDS_WORK


# --------------------------------------------------------------------------
# selftest
# --------------------------------------------------------------------------
def _selftest() -> int:
    import tempfile

    _safe_stdout()
    OK_M, FAIL_M = _marks()
    tmp = tempfile.mkdtemp(prefix="wbb-migrate-")
    fails: List[str] = []
    passed = [0]

    def check(name: str, cond: bool, detail: str = "") -> None:
        print("  %s %s%s" % (OK_M if cond else FAIL_M, name,
                             (" — " + detail) if detail else ""))
        if cond:
            passed[0] += 1
        else:
            fails.append(name)

    print("=" * 70)
    print("wbb.migrate selftest")
    print("=" * 70)

    # ---- 造一份带章节结构的总线 ------------------------------------------
    bus_path = os.path.join(tmp, "00-bus.md")
    open(bus_path, "w", encoding="utf-8").write(
        "# 协作总线\n\n## 总线\n\n"
        "| ID | time | source | role | what | status | artifact | need |\n"
        "|---|---|---|---|---|---|---|---|\n\n---\n\n## 变更记录\n\n"
        "| 日期 | 变更 |\n|---|---|\n"
    )
    bus = Bus(bus_path)
    for i in range(25):
        bus.append(source="a", role="exec", what="事项 %02d" % i,
                   status="done" if i % 5 else "doing", artifact="-", need="-")

    identity = "# 身份\n\n我是执行方。边界：只做派给我的活。\n"
    id_path = os.path.join(tmp, "identity.md")
    open(id_path, "w", encoding="utf-8", newline="\n").write(identity)

    out_path = os.path.join(tmp, "handoff.md")
    rc = render(identity_path=id_path, bus_path=bus_path, tail=20, out_path=out_path,
                quiet=True)
    check("render 返回 0", rc == 0, "rc=%d" % rc)
    txt = open(out_path, encoding="utf-8").read() if os.path.isfile(out_path) else ""

    check("产物落盘", bool(txt))
    check("含身份块原文", "只做派给我的活" in txt)
    missing = [s for s in SECTION_TITLES if ("## " + s) not in txt]
    check("五节齐备", not missing, "缺 %s" % missing)
    tail_rows = [l for l in txt.splitlines() if re.match(r"^\|\s*\d+\s*\|", l)]
    check("只取末尾 N 条", len(tail_rows) == 20, "实得 %d" % len(tail_rows))
    check("取到的是末尾（25 条取 20 ⇒ 事项 05..24）",
          "事项 24" in txt and "事项 05" in txt and "事项 04" not in txt)
    open_cnt = len([l for l in txt.splitlines() if l.startswith("- [ ] ")])
    check("未闭口只列 status 非 done", open_cnt == 4,
          "实得 %d（尾部 20 条里 doing = 事项 05/10/15/20，共 4 条）" % open_cnt)
    check("未闭口指向 doing 的条目", "事项 05" in txt and "doing" in txt)
    check("提醒了迁移后三件事", "迁移审计" in txt and "登记接续" in txt)

    # ---- 无身份块 / 空总线也不崩 -----------------------------------------
    empty_bus = os.path.join(tmp, "empty.md")
    open(empty_bus, "w", encoding="utf-8").write(
        "# 协作总线\n\n## 总线\n\n| ID | time | source | role | what | status | artifact | need |\n"
        "|---|---|---|---|---|---|---|---|\n\n---\n\n## 变更记录\n\n| 日期 | 变更 |\n|---|---|\n"
    )
    rc2 = render(bus_path=empty_bus, out_path=os.path.join(tmp, "h2.md"), quiet=True)
    txt2 = open(os.path.join(tmp, "h2.md"), encoding="utf-8").read()
    check("空总线 render 不崩", rc2 == 0)
    check("无身份块时显式标为缺口", "缺" in txt2)

    # ---- audit ----------------------------------------------------------
    proj = os.path.join(tmp, "proj")
    os.makedirs(os.path.join(proj, ".git"), exist_ok=True)
    os.makedirs(os.path.join(proj, "sub"), exist_ok=True)
    OLD = "D:" + os.sep + "old-workspace"
    open(os.path.join(proj, "config.md"), "w", encoding="utf-8").write(
        "数据目录：" + OLD + "\n" + "无关注释行\n")
    open(os.path.join(proj, "sub", "task.py"), "w", encoding="utf-8", newline="\n").write(
        "PATH = " + OLD + "\n")
    open(os.path.join(proj, "clean.md"), "w", encoding="utf-8").write("这里没有旧位置\n")
    open(os.path.join(proj, ".git", "config"), "w", encoding="utf-8").write(OLD + "\n")
    # 扩展名是文本、内容却是二进制 —— 必须靠「探测 NUL」跳过，不能只看扩展名
    with open(os.path.join(proj, "blob.md"), "wb") as f:
        f.write(b"\x00\x01" + OLD.encode())
    # 真·超限文件（否则这项检查是空的）
    open(os.path.join(proj, "huge.txt"), "w", encoding="utf-8").write(
        OLD + "\n" + "x" * (DEFAULT_MAX_BYTES + 500))

    n = audit(root=proj, olds=[OLD], new="E:" + os.sep + "new-workspace", quiet=True)
    check("audit 有命中 → 退出码 8", n == EXIT_NEEDS_WORK, "rc=%d" % n)

    import io as _io
    buf = _io.StringIO()
    old_out = sys.stdout
    sys.stdout = buf
    try:
        audit(root=proj, olds=[OLD], new="E:" + os.sep + "new-workspace", quiet=False)
    finally:
        sys.stdout = old_out
    report = buf.getvalue()
    check("报告列出 config.md", "config.md" in report)
    check("报告列出 task.py 且带行号", "task.py : L1" in report)
    check("给了 --new 时输出替换建议", "→ 建议" in report)
    check("跳过 .git 目录", ".git" + os.sep + "config" not in report)
    check("跳过二进制文件（探测 NUL，不靠扩展名）", "blob.md" not in report)
    check("跳过超限大文件（--max-bytes）", "huge.txt" not in report)
    check("干净文件不误报", len([l for l in report.splitlines() if "clean.md" in l]) == 0)

    n2 = audit(root=proj, olds=["根本不存在的片段"], quiet=True)
    check("干净 root → 退出码 0", n2 == EXIT_OK, "rc=%d" % n2)
    err = _io.StringIO()
    old_err = sys.stderr
    sys.stderr = err
    try:
        rc_no_old = audit(root=proj, olds=[], quiet=True)
    finally:
        sys.stderr = old_err
    check("缺 --old 时返回 2", rc_no_old == 2, "rc=%d" % rc_no_old)
    check("缺 --old 时给了提示语", "--old" in err.getvalue())

    # ---- CJK 路径 -------------------------------------------------------
    cjk = os.path.join(tmp, "测试目录", "中文 路径")
    os.makedirs(cjk, exist_ok=True)
    cjk_bus = os.path.join(cjk, "00-bus.md")
    open(cjk_bus, "w", encoding="utf-8").write(
        "# 协作总线\n\n## 总线\n\n| ID | time | source | role | what | status | artifact | need |\n"
        "|---|---|---|---|---|---|---|---|\n\n---\n\n## 变更记录\n\n| 日期 | 变更 |\n|---|---|\n"
    )
    Bus(cjk_bus).append(source="a", role="exec", what="中文路径条目", status="doing",
                        artifact="-", need="-")
    cjk_out = os.path.join(cjk, "接续 文本.md")
    rc3 = render(identity_path=id_path, bus_path=cjk_bus, tail=5, out_path=cjk_out, quiet=True)
    check("CJK 路径下 render 可用",
          rc3 == 0 and os.path.isfile(cjk_out)
          and "中文路径条目" in open(cjk_out, encoding="utf-8").read())

    print()
    print("=" * 70)
    if fails:
        print("❌ %d 项未过（共 %d 项）：%s" % (len(fails), passed[0] + len(fails), fails))
        return 1
    print("✅ 全过：%d/%d" % (passed[0], passed[0]))
    return 0


if __name__ == "__main__":
    sys.exit(_selftest())
