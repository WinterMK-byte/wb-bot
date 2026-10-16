# -*- coding: utf-8 -*-
"""
wbb.cli —— 命令行入口

总线的所有操作都从这里走。它与 MCP server（``mcp_server.py``）共享同一个
:class:`wbb.bus.Bus`，所以两条路的行为**逐字一致** —— 这很重要：如果 CLI 和
MCP 各写一套逻辑，早晚会出现"用命令行写进去的行，MCP 读不出来"这种事。

用法::

    # 指定总线文件（也可用环境变量 WBB_BUS 或 --bus）
    python -m wbb.cli --bus ./00-bus.md append "来源|角色|做了什么|状态|产物|需要对方"
    python -m wbb.cli --bus ./00-bus.md read --since 0
    python -m wbb.cli --bus ./00-bus.md verify [--fix-order]
    python -m wbb.cli --bus ./00-bus.md claim "shared.md|我要改这个文件"
    python -m wbb.cli --bus ./00-bus.md release "shared.md"
    python -m wbb.cli --bus ./00-bus.md locks
    python -m wbb.cli --bus ./00-bus.md archive --keep 200 [--go]
    python -m wbb.cli --bus ./00-bus.md view <关键词>
    python -m wbb.cli --bus ./00-bus.md status
    python -m wbb.cli migrate render --identity id.md --bus ./00-bus.md --out handoff.md
    python -m wbb.cli migrate audit --root . --old <旧位置> [--new <新位置>]
    python -m wbb.cli selftest
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Optional

from . import __version__
from .bus import Bus, LockTimeout, SelfCheckFailed, _safe_stdout
from .migrate import DEFAULT_MAX_BYTES


def _bus_from_args(a: argparse.Namespace) -> Bus:
    path = a.bus or os.environ.get("WBB_BUS")
    if not path:
        sys.stderr.write(
            "未指定总线文件。用 --bus <路径> 或设环境变量 WBB_BUS。\n"
        )
        raise SystemExit(2)
    return Bus(path)


def main(argv: Optional[List[str]] = None) -> int:
    # ★ Windows 控制台默认**不是** UTF-8 —— 不处理的话中文输出会**乱码**
    #   （严重时在别处直接 UnicodeEncodeError）。CLI 是主入口，这点最致命。
    #   ⚠️ `PYTHONIOENCODING` 的优先级**高于** `-X utf8`，
    #      所以只能在本进程里 reconfigure，不能靠启动参数。
    _safe_stdout()
    ap = argparse.ArgumentParser(
        prog="wbb",
        description="WB Bot —— 多 Agent 协作的纪律层（命令行）",
    )
    ap.add_argument("--bus", help="总线文件路径（默认取环境变量 WBB_BUS）")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("--version", action="version", version="wbb " + __version__)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("append", help="追加一条（唯一写入入口）")
    p.add_argument("payload", nargs="?", default="",
                   help="'来源|角色|做了什么|状态|产物|需要对方'（缺的补 -）")
    p.add_argument("--source"); p.add_argument("--role")
    p.add_argument("--what"); p.add_argument("--status")
    p.add_argument("--artifact"); p.add_argument("--need")

    p = sub.add_parser("read", help="读条目")
    p.add_argument("--since", type=int, default=0, help="水位线：只返回 id 更大的")
    p.add_argument("--with-archive", action="store_true", help="连归档段一起读")

    p = sub.add_parser("verify", help="体检：ID 唯一 / 时间列 / 行序 / 列数")
    p.add_argument("--fix-order", action="store_true", help="顺带修行序（绝不改内容）")

    p = sub.add_parser("claim", help="声明占用共享资源")
    p.add_argument("spec", help="'资源|用途'")
    p.add_argument("--owner", default="-")

    p = sub.add_parser("release", help="释放占用")
    p.add_argument("resource")

    sub.add_parser("locks", help="列出当前占用")

    p = sub.add_parser("archive", help="归档最老条目（默认只预演）")
    p.add_argument("--keep", type=int, default=200)
    p.add_argument("--go", action="store_true", help="真搬（不加则只预演）")

    p = sub.add_parser("view", help="导出只读视图")
    p.add_argument("keyword", nargs="?", default="")

    sub.add_parser("status", help="总线概况")

    p = sub.add_parser("migrate", help="运行时迁移：render 生成接续文本 / audit 扫旧位置引用")
    p.add_argument("action", choices=("render", "audit"))
    # ★ 这里**必须再声明一次** `--bus`：argparse 只在「属性尚未设置」时才写默认值，
    #   所以放在子命令后面写也能生效，而不会把前面的值覆盖成 None。
    #   （不放这里的话，`migrate render --bus X` 会直接报 unrecognized arguments）
    p.add_argument("--bus", default=None, help="render：作为在办事实来源的总线文件")
    p.add_argument("--identity", default="", help="身份块文件（原始 markdown，原样搬进接续文本）")
    p.add_argument("--tail", type=int, default=20, help="取总线末尾 N 条作为在办事实")
    p.add_argument("--title", default="接续文本")
    p.add_argument("--out", default="", help="输出文件（缺省打到 stdout）")
    p.add_argument("--root", default="", help="audit：要扫描的目录")
    p.add_argument("--old", action="append", default=[], help="audit：旧位置片段（可多次）")
    p.add_argument("--new", default="", help="audit：新位置片段（给替换建议）")
    p.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES,
                   help="audit：超过这个大小的文件跳过")
    p.add_argument("--quiet", action="store_true")

    sub.add_parser("selftest", help="跑内置自测")

    a = ap.parse_args(argv)

    if a.cmd == "selftest":
        from .bus import _selftest
        return _selftest()

    # migrate 不依赖总线（--bus 只是它的**数据源之一**，可缺省）
    if a.cmd == "migrate":
        from . import migrate as _mig
        if a.action == "render":
            return _mig.render(
                identity_path=a.identity,
                bus_path=a.bus or os.environ.get("WBB_BUS") or "",
                tail=a.tail, title=a.title, out_path=a.out, quiet=a.quiet,
            )
        return _mig.audit(root=a.root, olds=a.old, new=a.new,
                          max_bytes=a.max_bytes, quiet=a.quiet)

    if not a.cmd:
        ap.print_help()
        return 0

    bus = _bus_from_args(a)

    # ---------------------------------------------------------------- status
    if a.cmd == "status":
        st = bus.stats()
        if a.json:
            print(json.dumps(st, ensure_ascii=False, indent=2))
        else:
            print("总线：%s" % st["path"])
            print("  条目 %d 条 ｜ ID %s..%s ｜ %.1f KB"
                  % (st["entries"], st["min_id"], st["max_id"], st["bytes"] / 1024))
        return 0

    # ---------------------------------------------------------------- append
    if a.cmd == "append":
        if a.payload:
            parts = [x.strip() for x in a.payload.split("|")]
        else:
            parts = [a.source, a.role, a.what, a.status, a.artifact, a.need]
        while len(parts) < 6:
            parts.append("-")
        # 按 columns 顺序：time, source, role, what, status, artifact, need
        src, role, what, status, art, need = parts[:6]
        try:
            r = bus.append(source=src, role=role, what=what, status=status,
                           artifact=art, need=need)
        except (LockTimeout, SelfCheckFailed) as e:
            sys.stderr.write("追加失败：%s\n" % e)
            return 2
        if a.json:
            print(json.dumps(r, ensure_ascii=False))
        else:
            print("已追加：")
            print("  " + r["line"])
        return 0

    # ---------------------------------------------------------------- read
    if a.cmd == "read":
        recs = bus.read(since_id=a.since, include_archive=a.with_archive)
        if a.json:
            print(json.dumps(recs, ensure_ascii=False, indent=2))
            return 0
        print("共 %d 条（since=%d%s）"
              % (len(recs), a.since, "，含归档" if a.with_archive else ""))
        for r in recs:
            print("  #%-4s %s  %s" % (r.get("id"), r.get("time", "")[:16],
                                      str(r.get("what", ""))[:70]))
        return 0

    # ---------------------------------------------------------------- verify
    if a.cmd == "verify":
        ok, probs, acts = bus.verify(fix_order=a.fix_order)
        st = bus.stats()
        if a.json:
            print(json.dumps({"ok": ok, "problems": probs, "actions": acts,
                              "stats": st}, ensure_ascii=False, indent=2))
            return 0 if ok else 1
        print("=" * 62)
        print("总线体检" + ("（--fix-order）" if a.fix_order else ""))
        print("=" * 62)
        print("  条目 %d 条，ID %s..%s，%.1f KB"
              % (st["entries"], st["min_id"], st["max_id"], st["bytes"] / 1024))
        for x in acts:
            print("  · " + x)
        if ok:
            print("  ✅ 通过：ID 唯一、时间列合规、行序单调")
            return 0
        print("  ❌ %d 个问题：" % len(probs))
        for p in probs:
            print("     · " + p)
        print()
        print("  重号无法自动修（改 ID 会破坏既有引用）→ 需人工裁决。")
        return 1

    # ---------------------------------------------------------------- 锁
    if a.cmd == "claim":
        res, _, purpose = a.spec.partition("|")
        ok, d = bus.claim(res.strip(), purpose.strip() or "-", owner=a.owner)
        if ok:
            print("已占用：%s  @ %s" % (d["resource"], d["at"]))
            print("完工后：python -m wbb.cli release \"%s\"" % res.strip())
        else:
            print("占用失败 —— 已被持有：")
            print("  资源 %s" % d.get("resource", d.get("_res")))
            print("  用途 %s" % d.get("purpose", "-"))
            print("  时间 %s" % d.get("at", "-"))
            print("  → 先确认对方是否还在写，不要强行覆盖。")
        return 0 if ok else 1

    if a.cmd == "release":
        print("已释放：" + a.resource if bus.release(a.resource)
              else "无此占用：" + a.resource)
        return 0

    if a.cmd == "locks":
        ls = bus.locks()
        print("当前占用 %d 个" % len(ls))
        for d in ls:
            print("  %s ← %s%s | %s | %s"
                  % (d["_res"], "%.0f 分钟前" % d["_age_min"],
                     "  ⚠陈旧可抢" if d["_stale"] else "",
                     d.get("purpose", "-"), d.get("at", "-")))
        return 0

    # ---------------------------------------------------------------- archive
    if a.cmd == "archive":
        r = bus.archive(keep=a.keep, go=a.go)
        print(("✅ " if r.get("ok") else "❌ ") + str(r.get("msg", "")))
        if a.go and r.get("ok"):
            print("   备份：%s.bak_before_archive" % os.path.basename(bus.path))
            print("   建议接着跑：python -m wbb.cli verify")
        return 0 if r.get("ok") else 1

    # ---------------------------------------------------------------- view
    if a.cmd == "view":
        path, n = bus.build_view(a.keyword)
        print("已生成只读视图：%s（命中 %d 条）" % (path, n))
        print("提示：该文件是自动生成的，手改会在下次重建时丢失。")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
