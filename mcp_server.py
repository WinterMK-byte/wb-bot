#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WB Bot · MCP server —— 把协作总线的操作暴露成标准 MCP 工具

任何支持 MCP 的 Agent 运行时（各类 MCP 客户端、自建 harness…）
接上这个 server，就能读/写同一份协作总线。**协议层中立，不绑任何平台。**

总线路径（二选一）
------------------
* 环境变量 ``WBB_BUS``（推荐，写在你的 MCP 配置的 env 里）
* 命令行 ``--bus <路径>``

接入示例（MCP 客户端配置）::

    {
      "mcpServers": {
        "wb-bot": {
          "command": "python",
          "args": ["/abs/path/to/mcp_server.py"],
          "env": { "WBB_BUS": "/abs/path/to/00-bus.md" }
        }
      }
    }

工具一览
--------
bus_append   追加一条（唯一写入入口，写后自检 + 自动回滚）
bus_read     读条目（支持水位线增量）
bus_verify   体检：ID 唯一 / 时间列格式 / 行序 / 列数（可选自动修行序）
bus_claim    占用某个共享资源（多 Agent 并发写同一个文件时用）
bus_release  释放占用
bus_locks    当前所有占用
bus_status   总线概况
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wbb.bus import Bus, LockTimeout, SelfCheckFailed   # noqa: E402

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:                                     # pragma: no cover
    sys.stderr.write(
        "需要 mcp 包：pip install mcp\n"
        "（若你只想用命令行，可直接用 wbb.cli，无需 MCP。）\n"
    )
    raise SystemExit(3)

_BUS_PATH: str = ""


def _bus() -> Bus:
    path = _BUS_PATH or os.environ.get("WBB_BUS", "")
    if not path:
        raise RuntimeError(
            "未指定总线路径。设置环境变量 WBB_BUS，或用 --bus 启动本 server。"
        )
    return Bus(path)


mcp = FastMCP("wb-bot")


@mcp.tool()
def bus_append(source: str, role: str, what: str,
               status: str = "-", artifact: str = "-", need: str = "-") -> str:
    """向协作总线追加一条记录（这是唯一写入入口）。

    Args:
        source: 谁写的（Agent 名 / 席位名 / 会话 id）
        role: 什么角色（例如 architect / reviewer / executor）
        what: 做了什么。**关键数字要写进来**，别写"改了点东西"
        status: 状态（done / in-progress / blocked / review）
        artifact: 产物路径（绝对路径优先），或断点信息
        need: 需要谁做什么（"-" 表示不需要）

    Returns:
        写入结果，含真实分配的 ID。**并发下 ID 可能与预期不同，以返回值为准。**
    """
    try:
        r = _bus().append(source=source, role=role, what=what,
                          status=status, artifact=artifact, need=need)
        return "已追加 #%d：%s" % (r["id"], r["line"])
    except (LockTimeout, SelfCheckFailed) as e:
        return "追加失败（未写入）：%s" % e


@mcp.tool()
def bus_read(since_id: int = 0, include_archive: bool = False,
             limit: int = 50) -> str:
    """读协作总线上的记录。

    Args:
        since_id: 水位线 —— 只返回 ID 大于它的条目（增量读）。传 0 表示全量。
        include_archive: 是否连已归档的老条目一起读。
        limit: 最多返回多少条（默认 50，倒序取最新）。

    Returns:
        条目的 JSON 数组。
    """
    recs = _bus().read(since_id=since_id, include_archive=include_archive)
    if limit and len(recs) > limit:
        recs = recs[-limit:]
    return json.dumps(recs, ensure_ascii=False, indent=2)


@mcp.tool()
def bus_verify(fix_order: bool = False) -> str:
    """体检协作总线：ID 唯一 / 时间列格式 / 行序单调 / 列数。

    Args:
        fix_order: True 时顺带修复行序（**只重排，绝不改任何条目内容**）。
                   重号无法自动修 —— 会破坏既有交叉引用，只能人工裁决。

    Returns:
        体检报告。首行是结论。
    """
    ok, probs, acts = _bus().verify(fix_order=fix_order)
    lines = ["结论：%s" % ("✅ 通过" if ok else "❌ 发现 %d 个问题" % len(probs))]
    for x in acts:
        lines.append("  · " + x)
    for p in probs:
        lines.append("  · " + p)
    lines.append("")
    lines.append("提示：时间列不合规 = 有人绕过了本工具手写行；"
                 "重号需人工裁决（改 ID 会破坏引用）。")
    return "\n".join(lines)


@mcp.tool()
def bus_claim(resource: str, purpose: str = "-", owner: str = "-") -> str:
    """声明占用某个共享资源（并发写同一个文件前先申请）。

    Args:
        resource: 资源标识，通常是文件路径或路径片段
        purpose: 你打算用它做什么
        owner: 占用者标识

    Returns:
        成功 / 失败（失败时附当前持有者信息）。
    """
    ok, d = _bus().claim(resource, purpose, owner)
    if ok:
        return "已占用：%s（%s）。完工后请调用 bus_release。" % (d["resource"], d["at"])
    return ("占用失败 —— 已被持有：\n  资源 %s\n  用途 %s\n  时间 %s\n"
            "  → 先确认对方是否还在写，不要强行覆盖。"
            % (d.get("resource", d.get("_res")), d.get("purpose", "-"), d.get("at", "-")))


@mcp.tool()
def bus_release(resource: str) -> str:
    """释放之前占用的共享资源。"""
    return "已释放：%s" % resource if _bus().release(resource) else "无此占用：%s" % resource


@mcp.tool()
def bus_locks() -> str:
    """列出当前所有占用（含是否已陈旧可抢）。"""
    ls = _bus().locks()
    if not ls:
        return "当前无占用。"
    return "\n".join(
        "  %s ← %.0f 分钟前%s | %s | %s"
        % (d["_res"], d["_age_min"], "（陈旧，可抢）" if d["_stale"] else "",
           d.get("purpose", "-"), d.get("at", "-"))
        for d in ls
    )


@mcp.tool()
def bus_status() -> str:
    """总线概况：条目数 / ID 范围 / 文件大小。"""
    return json.dumps(_bus().stats(), ensure_ascii=False, indent=2)


def main() -> int:
    global _BUS_PATH
    ap = argparse.ArgumentParser(description="WB Bot MCP server")
    ap.add_argument("--bus", help="总线文件路径（默认取环境变量 WBB_BUS）")
    ap.add_argument("--transport", default="stdio", choices=["stdio", "sse"],
                    help="传输方式，默认 stdio")
    a = ap.parse_args()
    _BUS_PATH = a.bus or ""
    if not (_BUS_PATH or os.environ.get("WBB_BUS")):
        sys.stderr.write(
            "警告：未指定总线路径（--bus 或 WBB_BUS）。工具调用时会报错。\n"
        )
    mcp.run(transport=a.transport)
    return 0


if __name__ == "__main__":
    sys.exit(main())
