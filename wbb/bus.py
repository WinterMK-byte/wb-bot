# -*- coding: utf-8 -*-
"""
wbb.bus —— 单一权威的 append-only 协作日志

设计不变量（四条，缺一不可）：

  1. **唯一写入入口**：只有 ``append()``。没有 update / delete / insert_at。
     想改历史？再追加一条说明，不要原地改。

  2. **ID 在临界区内计算**：``next_id()`` 取 ``max(id) + 1``，而且这个计算与写入
     在**同一把原子锁**内完成。任何"先读后写"的分步实现，在并发下都会撞号。

  3. **写后自检，不合格自动回滚**：写完立刻验本次 ID 唯一；不合格把文件还原成
     写入前的快照并抛错。脏数据进不去，也不留下半截状态。

  4. **插入点用结构锚，不用"最后一个数据行"**：表格里的一行可能是多行条目的首行
     （行尾没有 `|`），用"最后一个闭合行"当表尾会把新行插进**表格中段**。

为什么这么较真 —— 见 ``docs/lessons/``。每一条纪律背后都有一份真实事故记录。
本模块零第三方依赖，纯标准库；CJK 路径安全。
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import sys
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = ["Bus", "BusError", "LockTimeout", "SelfCheckFailed"]


# --------------------------------------------------------------------------
# 异常
# --------------------------------------------------------------------------
class BusError(Exception):
    """总线相关的基类异常。"""


class LockTimeout(BusError):
    """等锁超时（有别的进程正在写）。"""


class SelfCheckFailed(BusError):
    """写后自检未通过——已自动回滚，本次未写入。"""


# --------------------------------------------------------------------------
# 解析用正则
# --------------------------------------------------------------------------
# 数据行的判定：**只看行首**（`| 数字 |`），不看行尾。
#   · 多行条目的首行行尾没有 `|` —— 若要求行尾闭合就会漏掉它，导致 ID 计算回退。
#   · 「变更记录」类表格的行首是日期（`| 2025-04-02 |`），数字正则天然不匹配。
ROW_START = re.compile(r"^\|\s*(\d+)\s*\|")

# 由本工具生成的时间列格式：`YYYY-MM-DD HH:MM`。
# 这是「这一行有没有走工具」的判据 —— 手写的行通常只有日期、或带占位符。
RE_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}")

DEFAULT_COLUMNS = (
    "time", "source", "role", "what", "status", "artifact", "need",
)


# --------------------------------------------------------------------------
# Bus
# --------------------------------------------------------------------------
class Bus:
    """一份 append-only 协作日志。

    典型用法::

        bus = Bus("/path/to/00-bus.md")
        bus.append(source="agent-a", role="architect",
                   what="拆了两个任务，派给 executor",
                   status="done", artifact="tasks/T01.md", need="executor")
        ok, problems, _ = bus.verify()

    参数
    ----
    path
        总线文件路径（不存在则首次 append 时创建）。
    lockdir
        锁目录，默认 ``<总线目录>/.locks``。
    archive_dir / view_dir
        归档与只读视图目录，默认 ``<总线目录>/archive``、``<总线目录>/views``。
    columns
        业务列名（不含 ID）。默认 7 列：time/source/role/what/status/artifact/need。
        列数是**可配置的** —— 只要 append 与 verify 用同一套即可。
    bus_heading
        表体所在章节的标题（用于定位插入点），默认 ``"总线"``。
    tail_heading
        表体之后的章节标题（结构锚的参照点），默认 ``"变更记录"``。
    """

    def __init__(
        self,
        path: str,
        *,
        lockdir: Optional[str] = None,
        archive_dir: Optional[str] = None,
        view_dir: Optional[str] = None,
        columns: Sequence[str] = DEFAULT_COLUMNS,
        bus_heading: str = "总线",
        tail_heading: str = "变更记录",
        stale_lock_sec: int = 60,
        lock_timeout_sec: float = 8.0,
    ) -> None:
        self.path = os.path.abspath(path)
        self.dir = os.path.dirname(self.path) or "."
        self.lockdir = lockdir or os.path.join(self.dir, ".locks")
        self.archive_dir = archive_dir or os.path.join(self.dir, "archive")
        self.view_dir = view_dir or os.path.join(self.dir, "views")
        self.columns = tuple(columns)
        self.bus_heading = bus_heading
        self.tail_heading = tail_heading
        self.stale_lock_sec = stale_lock_sec
        self.lock_timeout_sec = lock_timeout_sec
        self._buslock = os.path.join(self.lockdir, "_bus.append.lck")

    # ---------------------------------------------------------------- 路径
    def _ensure_dirs(self) -> None:
        os.makedirs(self.lockdir, exist_ok=True)

    # ---------------------------------------------------------------- 读
    def _iter_data_lines(self, lines: Iterable[str]) -> Iterable[Tuple[int, str]]:
        """逐行找数据行，跳过 ``` 代码围栏里的示例。产出 (行号, 原文)。"""
        in_fence = False
        for i, raw in enumerate(lines, 1):
            raw = raw.rstrip("\n")
            if raw.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            if ROW_START.match(raw.strip()):
                yield i, raw

    @staticmethod
    def _split_cells(stripped: str) -> Tuple[int, List[str]]:
        """把 `| 12 | a | b |` 拆成 (12, ['a','b'])。"""
        m = ROW_START.match(stripped)
        assert m is not None
        cid = int(m.group(1))
        rest = stripped[m.end():]
        if rest.rstrip().endswith("|"):
            rest = rest.rstrip()[:-1]
        return cid, [c.strip() for c in rest.split("|")]

    def rows(self) -> List[Tuple[int, int, List[str], str]]:
        """全部数据行：``[(行号, id, 列列表, 原始行)]``，按 id 升序。"""
        if not os.path.isfile(self.path):
            return []
        out: List[Tuple[int, int, List[str], str]] = []
        with open(self.path, encoding="utf-8", errors="replace") as f:
            for lineno, raw in self._iter_data_lines(f):
                cid, cells = self._split_cells(raw.strip())
                out.append((lineno, cid, cells, raw))
        out.sort(key=lambda x: x[1])
        return out

    def read(self, since_id: int = 0, include_archive: bool = False
             ) -> List[Dict[str, Any]]:
        """读条目（结构化）。``since_id`` 为水位线，只返回 id 更大的。"""
        raw_rows: List[Tuple[int, List[str]]] = [(cid, cells) for _, cid, cells, _ in self.rows()]
        if include_archive:
            raw_rows += self._read_archive_rows()
        raw_rows.sort(key=lambda x: x[0])
        out = []
        for cid, cells in raw_rows:
            if cid <= since_id:
                continue
            rec: Dict[str, Any] = {"id": cid}
            for name, val in zip(self.columns, cells):
                rec[name] = val
            out.append(rec)
        return out

    def next_id(self) -> int:
        """下一个可用 ID = ``max(id) + 1``。

        ⚠️ 只有在锁内调用它才安全 —— :meth:`append` 已经这么做了。
        """
        rows = self.rows()
        return (max(r[1] for r in rows) + 1) if rows else 1

    def stats(self) -> Dict[str, Any]:
        rows = self.rows()
        return {
            "path": self.path,
            "entries": len(rows),
            "min_id": rows[0][1] if rows else None,
            "max_id": rows[-1][1] if rows else None,
            "bytes": os.path.getsize(self.path) if os.path.isfile(self.path) else 0,
        }

    # ---------------------------------------------------------------- 锁
    def _acquire_bus_lock(self) -> bool:
        """O_CREAT|O_EXCL 原子建档当互斥量。陈旧锁（超 stale_lock_sec）自动清理。"""
        self._ensure_dirs()
        t0 = time.time()
        while True:
            try:
                fd = os.open(self._buslock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return True
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self._buslock) > self.stale_lock_sec:
                        os.remove(self._buslock)   # 陈旧锁：持有者可能已崩溃
                        continue
                except OSError:
                    pass
                if time.time() - t0 > self.lock_timeout_sec:
                    return False
                time.sleep(0.3)

    def _release_bus_lock(self) -> None:
        try:
            os.remove(self._buslock)
        except OSError:
            pass

    # ---------------------------------------------------------------- 插入点
    def _insert_index(self, txt: str) -> int:
        """新行应插入的字符偏移。

        双锚点策略（优先级从高到低）：

        **主锚** —— 表体之后那个章节标题**之前**的第一条 ``---`` 分隔线。
        结构最稳，不依赖任何行的格式。

        ⚠️ 匹配这个标题**必须要求它是独立的标题行**（行首 ``##`` + 行尾无其他内容）。
        用过 ``startswith("## 变更记录")`` 这种宽松判据，结果被**条目正文里**恰好
        以该字符串开头的续行劫持，插入点落到表格中段 —— 这是真实事故，见
        ``docs/lessons/02-insert-anchor-hijack.md``。

        **备锚** —— 最后一个数据行的行首（含多行条目首行）。
        """
        lines = txt.splitlines(keepends=True)
        head = None
        for i, l in enumerate(lines):
            if re.match(r"^##\s+%s\s*$" % re.escape(self.bus_heading), l.strip()):
                head = i
                break
        if head is None:
            return len(txt)

        # ---- 主锚 ----
        tail_hdr = None
        for i, l in enumerate(lines):
            if re.match(r"^##\s+%s\s*$" % re.escape(self.tail_heading), l.strip()):
                tail_hdr = i
                break
        if tail_hdr is not None:
            for i in range(tail_hdr - 1, head, -1):
                if lines[i].strip() == "---":
                    # ★ 向前跳过空行 —— 否则新行会插在空行**之后**，
                    #   把表格截成两段（最后一条数据行被孤立，渲染成两个独立的表格）。
                    #   这是「开箱可用性实测」抓到的真 bug：
                    #   用户拿模板建总线（模板里数据行与 `---` 之间有空行）→
                    #   第一次 append 表格就断了。
                    j = i
                    while j > head and not lines[j - 1].strip():
                        j -= 1
                    return sum(len(x) for x in lines[:j])

        # ---- 备锚 ----
        last = None
        for i in range(head + 1, len(lines)):
            if ROW_START.match(lines[i].strip()):
                last = i
        if last is None:
            for i in range(head + 1, len(lines)):
                if lines[i].strip().startswith("|") and "---" in lines[i]:
                    last = i
                    break
        if last is None:
            return len(txt)
        return sum(len(x) for x in lines[:last + 1])

    # ---------------------------------------------------------------- 写
    def _render(self, cid: int, fields: Sequence[str]) -> str:
        cells = " | ".join(str(x) for x in fields)
        return "| %d | %s |\n" % (cid, cells)

    def _selfcheck(self, new_id: int) -> Tuple[bool, str]:
        ids = [r[1] for r in self.rows()]
        n = ids.count(new_id)
        return (n <= 1), ("ID %d 出现 %d 次" % (new_id, n) if n > 1 else "")

    def append(
        self,
        *,
        what: str,
        source: str = "-",
        role: str = "-",
        status: str = "-",
        artifact: str = "-",
        need: str = "-",
        timestamp: Optional[str] = None,
        extra: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """追加一条。**这是唯一的写入入口。**

        返回 ``{"id", "line", "timestamp"}``。
        若写后自检失败，会**自动回滚**并抛 :class:`SelfCheckFailed`。
        """
        if not self._acquire_bus_lock():
            raise LockTimeout(
                "总线被其他进程占用，%.0f 秒内未拿到锁。稍后重试。"
                % self.lock_timeout_sec
            )
        try:
            ts = timestamp or datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            # 按 columns 的顺序铺字段；未提供的用 "-"
            pool = {
                "time": ts, "source": source, "role": role,
                "what": what, "status": status, "artifact": artifact, "need": need,
            }
            fields = [pool.get(c, "-") for c in self.columns]
            if extra:
                fields = list(fields) + [str(x) for x in extra]

            new_id = self.next_id()
            line = self._render(new_id, fields)

            txt = ""
            if os.path.isfile(self.path):
                with open(self.path, encoding="utf-8") as f:
                    txt = f.read()
            if not txt.endswith("\n"):
                txt += "\n"
            snapshot = txt                                   # ← 写前快照
            idx = self._insert_index(txt)
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(txt[:idx] + line + txt[idx:])

            ok, why = self._selfcheck(new_id)                # ← 写后自检
            if not ok:
                with open(self.path, "w", encoding="utf-8") as f:
                    f.write(snapshot)                        # ← 自动回滚
                raise SelfCheckFailed(
                    "写后自检未通过（%s）—— 已回滚，本次未写入。" % why
                )
            return {"id": new_id, "line": line.strip(), "timestamp": ts}
        finally:
            self._release_bus_lock()

    # ---------------------------------------------------------------- 体检
    def verify(self, fix_order: bool = False
               ) -> Tuple[bool, List[str], List[str]]:
        """体检。返回 ``(ok, problems, actions)``。

        检查四类：

        ==================  ============================  ============
        检查项              判据                          是否判 fail
        ==================  ============================  ============
        ID 唯一             出现次数 > 1                  是
        时间列格式          不匹配 ``YYYY-MM-DD HH:MM``    是（手写行铁证）
        ID 单调             物理行序与 ID 序一致          是
        列数                少于列定义数                  否（仅提示）
        ==================  ============================  ============

        最后一项**故意不判 fail**：条目内容是自由文本，可能换行成多行条目，
        其续行会命中"列数不足"。把它当错误会天天假红 —— 假红比不报更坏，
        因为它会训练人忽略告警。判据必须经得起真实数据。

        ``fix_order=True`` 只做一件**绝不改内容**的事：把数据行按 ID 升序重排。
        重号**不能自动修** —— 改 ID 会破坏既有的交叉引用，只能人工裁决。
        """
        rows = self.rows()
        problems: List[str] = []
        actions: List[str] = []
        if not rows:
            return True, ["⚠ 总线里没有数据行"], []

        expect_cols = len(self.columns)

        # ① 重号
        seen: Dict[int, List[int]] = {}
        for ln, cid, _c, _r in rows:
            seen.setdefault(cid, []).append(ln)
        for k in sorted(seen):
            if len(seen[k]) > 1:
                problems.append("重号：ID %d 出现 %d 次（行 %s）" % (k, len(seen[k]), seen[k]))

        # ② 时间列格式（手写行铁证）
        for ln, cid, cells, _r in rows:
            ts = cells[0] if cells else ""
            if not RE_TIMESTAMP.match(ts):
                problems.append(
                    "时间列不合规：ID %d（行 %d）time=%r —— 疑似**绕过本工具**手写的行"
                    % (cid, ln, ts[:24])
                )

        # ③ 列数（仅提示）
        short = [(ln, cid, len(c)) for ln, cid, c, _r in rows if len(c) < expect_cols]
        for ln, cid, n in short[:12]:
            problems.append("⚠ 列数不足：ID %d（行 %d）只有 %d 列（期望 %d）"
                            % (cid, ln, n, expect_cols))
        if len(short) > 12:
            problems.append("⚠ 另有 %d 行列数不足（多行条目的续行居多，仅提示）"
                            % (len(short) - 12))

        # ④ 行序
        ids = [c[1] for c in rows]
        if ids != sorted(ids):
            pairs = [(ids[i], ids[i + 1]) for i in range(len(ids) - 1) if ids[i] > ids[i + 1]]
            problems.append("ID 非单调 %d 处（例如 %s）"
                            % (len(pairs), "、".join("%d→%d" % p for p in pairs[:5])))

        # ---- 修复：仅重排行序 ----
        if fix_order and rows:
            txt = open(self.path, encoding="utf-8").read()
            lines = txt.splitlines(keepends=True)
            # 只在「行号连续」的块内重排。跨块相对位置一律不动。
            # 这样多行条目的续行（行号不连续）天然把块切开，绝不会被卷进重排。
            blocks: List[List[Tuple[int, int, List[str], str]]] = []
            cur = [rows[0]]
            for r in rows[1:]:
                if r[0] == cur[-1][0] + 1:
                    cur.append(r)
                else:
                    blocks.append(cur)
                    cur = [r]
            blocks.append(cur)

            changed = 0
            for blk in blocks:
                if len(blk) < 2:
                    continue
                a, b = blk[0][0] - 1, blk[-1][0] - 1
                old = lines[a:b + 1]
                new = [r[3] + "\n" for r in sorted(blk, key=lambda x: x[1])]
                if new != old:
                    lines[a:b + 1] = new
                    changed += 1
            if changed:
                with open(self.path, "w", encoding="utf-8") as f:
                    f.write("".join(lines))
                actions.append("已按 ID 升序重排 %d 个连续块（内容零改动）" % changed)
                rows = self.rows()
                if [c[1] for c in rows] == sorted(c[1] for c in rows):
                    problems = [p for p in problems if not p.startswith("ID 非单调")]
            else:
                actions.append("无需重排（行序已正确）")

        ok = not [p for p in problems if not p.startswith("⚠ ")]
        return ok, problems, actions

    # ---------------------------------------------------------------- 资源锁
    def _lock_path(self, res: str) -> str:
        safe = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", res).strip("_") or "unnamed"
        return os.path.join(self.lockdir, safe + ".lock")

    def locks(self) -> List[Dict[str, Any]]:
        out = []
        if not os.path.isdir(self.lockdir):
            return out
        for n in sorted(os.listdir(self.lockdir)):
            if not n.endswith(".lock"):
                continue
            p = os.path.join(self.lockdir, n)
            try:
                d = json.load(open(p, encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(d, dict):
                continue
            age = (time.time() - d.get("ts", 0)) / 60.0
            d["_res"] = n[:-5]
            d["_age_min"] = age
            d["_stale"] = age > (self.stale_lock_sec * 2 / 60.0) or age > 120
            out.append(d)
        return out

    def claim(self, resource: str, purpose: str = "-", owner: str = "-"
              ) -> Tuple[bool, Dict[str, Any]]:
        """声明占用某个共享资源（比如某个文件）。被占用则返回 ``(False, 持有人信息)``。"""
        self._ensure_dirs()
        for d in self.locks():
            if d["_res"] == self._lock_path(resource)[:-5].split(os.sep)[-1] and not d["_stale"]:
                return False, d
        rec = {
            "resource": resource,
            "owner": owner,
            "purpose": purpose,
            "ts": time.time(),
            "at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(self._lock_path(resource), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=2)
        return True, rec

    def release(self, resource: str) -> bool:
        p = self._lock_path(resource)
        if os.path.isfile(p):
            os.remove(p)
            return True
        return False

    # ---------------------------------------------------------------- 归档 / 视图
    def _read_archive_rows(self) -> List[Tuple[int, List[str]]]:
        out: List[Tuple[int, List[str]]] = []
        if not os.path.isdir(self.archive_dir):
            return out
        for name in sorted(os.listdir(self.archive_dir)):
            if not name.endswith(".md"):
                continue
            try:
                with open(os.path.join(self.archive_dir, name),
                          encoding="utf-8", errors="replace") as f:
                    for _ln, raw in self._iter_data_lines(f):
                        cid, cells = self._split_cells(raw.strip())
                        out.append((cid, cells))
            except Exception:
                continue
        out.sort(key=lambda x: x[0])
        return out

    def archive(self, keep: int = 200, go: bool = False) -> Dict[str, Any]:
        """把最老的条目**整段搬**进 ``archive/``（逐字节一致，只搬不改）。

        ``go=False`` 只预演。带三重安全：① 默认不真搬；② 数据行必须物理连续，
        否则不动；③ 搬完校验 ID 集合一致才删源段。
        """
        rows = self.rows()
        if len(rows) <= keep:
            return {"ok": True, "msg": "无需归档（%d 条 ≤ 保留 %d 条）" % (len(rows), keep),
                    "moved": 0, "kept": len(rows)}
        cut = len(rows) - keep
        old, new = rows[:cut], rows[cut:]
        first_id, last_id = old[0][1], old[-1][1]
        tgt = os.path.join(self.archive_dir, "%d-%d.md" % (first_id, last_id))

        if not go:
            return {"ok": True, "dry": True, "moved": cut, "kept": len(new),
                    "target": tgt,
                    "msg": "预演：将搬 %d 条（#%d..#%d）→ %s，活跃段保留 %d 条"
                           % (cut, first_id, last_id, tgt, keep)}

        txt = open(self.path, encoding="utf-8").read()
        lines = txt.splitlines(keepends=True)

        # 安全检查：要搬的这些行必须**物理连续**（行号无空洞）。
        # ⚠️ 光看 `max-min+1 == len` 是不够的 —— 条目可以是**多行**的，
        # 其续行夹在数据行之间时，行号会出现空洞。按行号区间整段切，
        # 会把"续行"一起切走、或漏掉某条真正的数据行，**切坏条目**。
        # 真实事故见 docs/lessons/。保守做法：有空洞就拒绝，让人先整理。
        lns = sorted(r[0] for r in old)
        if lns != list(range(lns[0], lns[-1] + 1)):
            holes = [x for x in range(lns[0], lns[-1] + 1) if x not in set(lns)]
            return {"ok": False,
                    "msg": "数据行不物理连续（行 %s 处夹着续行或其他内容）→ **拒绝归档**，"
                           "以免切坏多行条目。请先整理该段，或调大 keep 让边界落在干净处。"
                           % (holes[:5] or "?")}

        a, b = lns[0] - 1, lns[-1] - 1

        os.makedirs(self.archive_dir, exist_ok=True)
        header = (
            "# 归档 · #%d ~ #%d\n\n" % (first_id, last_id)
            + "> 从活跃总线整段搬出的历史条目（**内容逐字未改**）。\n"
            + "> 归档时间：%s ｜ 条数：%d\n\n"
              % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), len(old))
            + "| " + " | ".join(["ID"] + list(self.columns)) + " |\n"
            + "|" + "---|" * (len(self.columns) + 1) + "\n"
        )
        body = "".join(r[3] + "\n" for r in old)
        if os.path.exists(tgt):
            tgt = tgt.replace(".md", "_%s.md" % datetime.datetime.now().strftime("%H%M%S"))
        open(tgt, "w", encoding="utf-8").write(header + body)

        # 校验：**刚写出的那个归档文件**里的 ID 集合 == 本应搬走的 ID 集合。
        # ⚠️ 不能拿「整个归档目录」比对 —— 目录里通常已经有历史归档，
        # 那样集合永远对不上，archive 会**每次都失败**。判据要落在"本次产物"上。
        wrote: List[int] = []
        try:
            with open(tgt, encoding="utf-8", errors="replace") as f:
                for _ln, raw in self._iter_data_lines(f):
                    cid, _cells = self._split_cells(raw.strip())
                    wrote.append(cid)
        except Exception:
            wrote = []
        if sorted(wrote) != sorted(r[1] for r in old):
            return {"ok": False,
                    "msg": "归档校验失败（写出文件的 ID 集合与预期不一致），**活跃文件未改动**",
                    "wrote": sorted(wrote)[:5], "want": sorted(r[1] for r in old)[:5]}

        shutil.copy2(self.path, self.path + ".bak_before_archive")
        del lines[a:b + 1]
        open(self.path, "w", encoding="utf-8").write("".join(lines))
        left = self.rows()
        return {"ok": True, "moved": cut, "kept": len(left), "target": tgt,
                "msg": "已归档 %d 条 → %s；活跃段剩 %d 条（#%d..#%d）"
                       % (cut, os.path.basename(tgt), len(left),
                          left[0][1], left[-1][1])}

    def build_view(self, keyword: str = "", include_archive: bool = True
                   ) -> Tuple[str, int]:
        """按关键词导出**只读视图**（自动生成，手改会在下次重建时消失）。"""
        key = (keyword or "").strip().lower()
        hits: List[Tuple[int, str]] = []
        for _ln, cid, cells, raw in self.rows():
            if not key or key in " ".join(cells).lower():
                hits.append((cid, raw.rstrip()))
        if include_archive:
            for cid, cells in self._read_archive_rows():
                joined = " ".join(cells).lower()
                if not key or key in joined:
                    hits.append((cid, "| %d | %s |" % (cid, " | ".join(cells))))
        hits.sort(key=lambda x: x[0])

        os.makedirs(self.view_dir, exist_ok=True)
        out = os.path.join(self.view_dir, "%s.md" % (key or "all"))
        with open(out, "w", encoding="utf-8") as f:
            f.write("# 只读视图 · %s\n\n" % (key or "all"))
            f.write("> **自动生成，请勿手改** —— 改了下次重建就没了。\n")
            f.write("> 数据来源：`%s`（权威源）\n" % os.path.basename(self.path))
            f.write("> 生成时间：%s ｜ 命中 **%d** 条\n\n"
                    % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), len(hits)))
            f.write("| " + " | ".join(["ID"] + list(self.columns)) + " |\n")
            f.write("|" + "---|" * (len(self.columns) + 1) + "\n")
            for _cid, raw in hits:
                f.write(raw + "\n")
        return out, len(hits)


# --------------------------------------------------------------------------
# 自测：python -m wbb.bus
# --------------------------------------------------------------------------
def _selftest() -> int:
    import tempfile

    tmp = tempfile.mkdtemp(prefix="wbb-selftest-")
    bus = Bus(os.path.join(tmp, "00-bus.md"))
    fails: List[str] = []
    passed = [0]

    def check(name: str, cond: bool, detail: str = "") -> None:
        print("  %s %s%s" % ("✅" if cond else "❌", name, (" — " + detail) if detail else ""))
        if cond:
            passed[0] += 1
        else:
            fails.append(name)

    print("=" * 70)
    print("wbb.bus selftest")
    print("=" * 70)

    # 建一份带章节结构的总线
    open(bus.path, "w", encoding="utf-8").write(
        "# 协作总线\n\n"
        "## 总线\n\n"
        "| ID | time | source | role | what | status | artifact | need |\n"
        "|---|---|---|---|---|---|---|---|\n"
        "\n"
        "---\n\n"
        "## 变更记录\n\n"
        "| 日期 | 变更 | 说明 |\n|---|---|---|\n"
    )

    # 1. 首次 append
    r1 = bus.append(source="agent-a", role="architect", what="第一条",
                    status="done", artifact="-", need="-")
    check("首次 append 拿到 ID=1", r1["id"] == 1, "id=%s" % r1["id"])

    # 2. 连续 append 递增
    r2 = bus.append(source="agent-b", role="executor", what="第二条")
    r3 = bus.append(source="agent-a", role="architect", what="第三条")
    check("ID 连续递增 2,3", (r2["id"], r3["id"]) == (2, 3), "%s,%s" % (r2["id"], r3["id"]))

    # 3. 插入点正确（新行落在「## 变更记录」之前、表体之内）
    lines = open(bus.path, encoding="utf-8").read().splitlines()
    i_tail = next(i for i, l in enumerate(lines) if l.strip() == "## 变更记录")
    i_last = max(i for i, l in enumerate(lines) if ROW_START.match(l.strip()))
    check("插入点在表体内（变更记录之前）", i_last < i_tail, "数据行 L%d < 变更记录 L%d" % (i_last, i_tail))

    # 3b. ★ 表格连续性（「开箱可用性实测」抓到的真 bug）
    #     本模板是「表头 + 空行 + ---」。插入点若算在 `---` 之前而不跳过空行，
    #     新行会落在空行**之后** ⇒ 表头与首行被空行截断 ⇒ 渲染成**两个独立的表**。
    i_sep = next(i for i, l in enumerate(lines)
                 if "-" in l and set(l.strip()) <= set("|-: "))
    i_row = next(i for i, l in enumerate(lines) if ROW_START.match(l.strip()))
    check("★ 新行紧贴表头分隔行（不被空行截断）", i_row == i_sep + 1,
          "分隔 L%d → 首行 L%d" % (i_sep + 1, i_row + 1))

    # 4. 体检干净
    ok, probs, _ = bus.verify()
    check("verify 通过（新总线无问题）", ok, str(probs[:2]))

    # 5. ★ 插入点主锚不被正文劫持
    with open(bus.path, encoding="utf-8") as f:
        txt = f.read()
    txt = txt.replace("| 3 |", "| 3 |", 1)
    # 手工塞一行正文，正文以「## 变更记录」开头（模拟真实事故）
    txt = txt.replace("\n---\n\n## 变更记录",
                      "\n| 4 | 2026-01-15 12:00 | agent-c | - | 说明文字：\n"
                      "## 变更记录 之前的第一条分隔线，是这样的 | done | - | - |\n"
                      "\n---\n\n## 变更记录", 1)
    open(bus.path, "w", encoding="utf-8").write(txt)
    bus2 = Bus(bus.path)
    idx = bus2._insert_index(txt)
    # 新行必须落在「真正的 ## 变更记录」之前
    real_tail = txt.rfind("## 变更记录")
    check("插入点主锚未被正文劫持", idx < real_tail,
          "idx=%d < 真标题=%d" % (idx, real_tail))

    # 6. 重号能检出
    open(bus.path, "a", encoding="utf-8").write(
        "| 3 | 2026-01-15 12:01 | agent-x | - | 故意重号 | done | - | - |\n")
    ok2, probs2, _ = bus2.verify()
    check("重号被检出", (not ok2) and any("重号" in p for p in probs2))

    # 7. 手写行（时间列不含时分）能检出
    open(bus.path, "a", encoding="utf-8").write(
        "| 9 | 2026-01-15 | agent-y | - | 手写行，没有时分 | done | - | - |\n")
    ok3, probs3, _ = bus2.verify()
    check("手写行被检出", any("时间列不合规" in p for p in probs3))

    # 8. --fix 修行序（内容零改动）
    before = {r[1]: r[3] for r in bus2.rows()}
    ok4, probs4, acts4 = bus2.verify(fix_order=True)
    after = {r[1]: r[3] for r in bus2.rows()}
    check("fix_order 后 ID 单调",
          [r[1] for r in bus2.rows()] == sorted(r[1] for r in bus2.rows()))
    check("fix_order 不修改任何条目内容", before == after)

    # 9. 资源锁
    okc, _ = bus.claim("shared.md", "写方案")
    okc2, holder = bus.claim("shared.md", "抢同一条")
    check("claim 互斥（第二次被拒）", okc and not okc2)
    check("release 后可用", bus.release("shared.md") and bus.claim("shared.md", "再拿")[0])

    # 10. 归档（用**干净**的总线，避免前面人为制造的重号/多行条目干扰）
    clean = Bus(os.path.join(tmp, "clean-bus.md"))
    open(clean.path, "w", encoding="utf-8").write(
        "# 协作总线\n\n## 总线\n\n"
        "| ID | time | source | role | what | status | artifact | need |\n"
        "|---|---|---|---|---|---|---|---|\n\n---\n\n## 变更记录\n\n| 日期 | 变更 |\n|---|---|\n")
    for i in range(20):
        clean.append(source="bulk", role="-", what="批量 %d" % i)
    prev = clean.archive(keep=5, go=False)
    check("archive 默认只预演", prev.get("dry") is True)
    real = clean.archive(keep=5, go=True)
    check("archive 真搬成功", real.get("ok") is True, real.get("msg", "")[:56])
    check("归档后活跃段条数 == keep", len(clean.rows()) == 5, "剩 %d" % len(clean.rows()))
    check("归档后行序仍单调", [r[1] for r in clean.rows()]
          == sorted(r[1] for r in clean.rows()))

    # 10b. ★ 多行条目夹在中间 → archive 必须**拒绝**（安全缺口回归测试）
    dirty = Bus(os.path.join(tmp, "dirty-bus.md"))
    open(dirty.path, "w", encoding="utf-8").write(
        "# 协作总线\n\n## 总线\n\n"
        "| ID | time | source | role | what | status | artifact | need |\n"
        "|---|---|---|---|---|---|---|---|\n\n---\n\n## 变更记录\n\n| 日期 | 变更 |\n|---|---|\n")
    for i in range(10):
        dirty.append(source="x", role="-", what="条目 %d" % i)
    # 把一条**多行条目**插在数据行中间 —— 它的续行会让"按 ID 取前 N 条"的行号出现空洞
    lines2 = open(dirty.path, encoding="utf-8").read().splitlines(keepends=True)
    out2: List[str] = []
    for l in lines2:
        out2.append(l)
        if ROW_START.match(l.strip()) and l.strip().startswith("| 5 |"):
            out2.append("| 99 | 2026-01-15 12:00 | x | - | 多行条目首行\n")
            out2.append("  续行：行首不是 | 数字 |，所以它不是数据行 | done | - |\n")
    open(dirty.path, "w", encoding="utf-8").write("".join(out2))
    r = dirty.archive(keep=3, go=True)
    check("多行条目造成行号空洞时 archive 拒绝（不切坏数据）", r.get("ok") is False,
          r.get("msg", "")[:44])
    n_before = len(dirty.rows())
    check("拒绝时活跃文件零改动", n_before == 11, "仍有 %d 条" % n_before)

    # 10c. ★ 目录里已有旧归档时，第二次归档必须仍成功
    #      （回归「拿整个归档目录比对」导致永远失败的那个 bug）
    for i in range(10):
        clean.append(source="bulk2", role="-", what="第二批 %d" % i)
    r2 = clean.archive(keep=4, go=True)
    check("已有旧归档时再次归档仍成功", r2.get("ok") is True, r2.get("msg", "")[:44])

    # 11. 视图
    vp, n = bus.build_view("bulk")
    check("build_view 生成视图", os.path.isfile(vp) and n > 0, "命中 %d" % n)

    print()
    print("结果：%d 项通过 / %d 项失败" % (passed[0], len(fails)))
    if fails:
        print("失败项：" + "、".join(fails))
    shutil.rmtree(tmp, ignore_errors=True)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(_selftest())
