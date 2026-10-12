#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_mcp.py —— 独立校验：MCP server 能否导入、7 个工具是否齐备

CI 和本地都能跑：

    python tools/check_mcp.py

未安装 ``mcp`` 包时**不算失败**（返回 0），只是跳过 —— 因为本项目的主体
（``wbb``）是零依赖的，MCP 只是可选的一层。

为什么单独做成文件而不是写在 CI 的 run 里：
YAML 块里的 heredoc 会带上缩进，而 bash 的结束标记必须顶格 —— 这是个很容易踩的坑。
写成文件既避开它，也让你在本地能跑同一条检查。
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("WBB_BUS", os.path.join(tempfile.gettempdir(), "wbb_mcp_check.md"))

EXPECT = {
    "bus_append", "bus_read", "bus_verify", "bus_claim",
    "bus_release", "bus_locks", "bus_status",
}


def main() -> int:
    try:
        import mcp_server as M
    except ImportError as e:
        print("[跳过] 未安装 mcp 包（pip install mcp）：%s" % e)
        return 0

    tools = {t.name for t in M.mcp._tool_manager.list_tools()}
    print("注册工具 %d 个：%s" % (len(tools), ", ".join(sorted(tools))))

    missing = EXPECT - tools
    if missing:
        print("[失败] 缺少工具：%s" % ", ".join(sorted(missing)))
        return 1

    extra = tools - EXPECT
    if extra:
        print("[提示] 多出未预期的工具：%s" % ", ".join(sorted(extra)))

    print("[OK] 7 个工具齐备")
    return 0


if __name__ == "__main__":
    sys.exit(main())
