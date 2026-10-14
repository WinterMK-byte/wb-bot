"""wbb.lease —— 跨进程资源租约（精简参考实现）

⚠️ 这是一个**精简的参考实现**，不是生产级。它把
`docs/10-resource-lease.md` 里的机制骨架做成可运行的代码，重点演示：

  1. 三层：组清单（L1，声明式 JSON）→ 租约（L2，动态）→ 协商（L3）
  2. ★ 双轨活跃判定：租约轨 ∪ 实测轨
     （用户手动启动的服务不会自己登记租约，只认租约 = 第一天就瞎）
  3. 退出码语义：0 成功 / 5 冲突待裁定 / 6 抢到但资源不足
  4. 两个真机坑的写法：`0` 是假值、卸载异步需轮询

平台探测（GPU / 端口 / 进程）通过 `Probe` 注入 —— 本文件不含任何平台硬编码。

自测：  python -m wbb.lease
"""

from __future__ import annotations

import json
import os
import time
from typing import Callable, Dict, List, Optional, Tuple

# ---------- 退出码（调用方靠它决策，见 docs/10 §四） ----------
EXIT_OK = 0            # 成功拿到租约
EXIT_INTERNAL = 1      # 内部错误
EXIT_CONFLICT = 5      # 有冲突，待裁定（停手，请示人）
EXIT_INSUFFICIENT = 6  # 抢到了但资源仍不足（停手，不硬跑）


class Probe:
    """资源探测接口 —— 平台相关部分的注入点。

    真实实现：`free()` 查设备可用量（如 nvidia-smi），
    `active(group, self_pids)` 实测某组是否真在占（端口在听 / 进程在 / 服务状态接口有驻留）。
    """

    def free(self) -> int:
        raise NotImplementedError

    def active(self, spec: dict, self_pids: set) -> bool:
        raise NotImplementedError

    def release(self, spec: dict, self_pids: set) -> None:
        raise NotImplementedError


class FakeProbe(Probe):
    """自测用：可控的假探测。"""

    def __init__(self, free_mib: int = 20000, external: Optional[Dict[str, bool]] = None):
        self._free = free_mib
        self._external = dict(external or {})   # 组名 -> 是否(实测)活跃
        self.released: List[str] = []

    def free(self) -> int:
        return self._free

    def set_free(self, mib: int) -> None:
        self._free = mib

    def active(self, spec: dict, self_pids: set) -> bool:
        return bool(self._external.get(spec["name"], False))

    def release(self, spec: dict, self_pids: set) -> None:
        self.released.append(spec["name"])
        self._external[spec["name"]] = False


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)          # POSIX
    except AttributeError:       # pragma: no cover - Windows
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not h:
            return False
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    except (ProcessLookupError, PermissionError) as e:
        return isinstance(e, PermissionError)   # 无权限 = 进程存在
    return True


class LeaseManager:
    """L2 + L3：租约的读写与冲突协商。"""

    def __init__(self, groups_path: str, lease_path: str, probe: Optional[Probe] = None):
        self.groups_path = groups_path
        self.lease_path = lease_path
        self.probe = probe or FakeProbe()

    # ---------- 配置 ----------
    def groups(self) -> dict:
        with open(self.groups_path, encoding="utf-8") as f:
            return json.load(f).get("groups", {})

    def policy(self) -> dict:
        with open(self.groups_path, encoding="utf-8") as f:
            return json.load(f).get("policy", {})

    # ---------- L2 租约读写 ----------
    def _read_leases(self) -> dict:
        if not os.path.isfile(self.lease_path):
            return {}
        try:
            with open(self.lease_path, encoding="utf-8") as f:
                return json.load(f).get("leases", {})
        except (ValueError, OSError):
            return {}

    def _write_leases(self, leases: dict) -> None:
        tmp = self.lease_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"leases": leases}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.lease_path)      # 原子替换

    def _drop(self, leases: dict, name: str) -> dict:
        leases = dict(leases)
        leases.pop(name, None)
        return leases

    # ---------- reaper：清僵尸 / 超时 ----------
    def _reap(self, leases: dict) -> dict:
        pol = self.policy()
        timeout = pol.get("heartbeat_timeout_s", 120)
        now = time.time()
        out = {}
        for name, rec in leases.items():
            alive = _pid_alive(int(rec.get("pid", -1)))
            fresh = (now - float(rec.get("heartbeat", 0))) <= timeout
            if alive and fresh and now < float(rec.get("expire_at", 1e18)):
                out[name] = rec
        return out

    # ---------- ★ 双轨活跃判定 ----------
    def active_groups(self, leases: Optional[dict] = None) -> Dict[str, str]:
        """返回 {组名: 判定依据}。依据 = 'lease' | 'probe' | 'both'。

        轨1（lease）：有租约 ∧ pid 活 ∧ 心跳新鲜 ∧ 未过期
        轨2（probe）：实测这组真在占

        两轨**取并集** —— 因为用户手动启动的服务只有 probe 轨看得见。
        """
        leases = self._reap(leases if leases is not None else self._read_leases())
        self_pids = self._self_pids()
        result: Dict[str, str] = {}

        for name in leases:
            result[name] = "lease"
        for name, spec in self.groups().items():
            if self.probe.active(dict(spec, name=name), self_pids):
                result[name] = "both" if name in result else "probe"
        return result

    def _self_pids(self) -> set:
        """本进程 + 祖先链 —— 释放时绝不误杀自己。"""
        pids = {os.getpid()}
        try:
            pids.add(os.getppid())
        except AttributeError:      # pragma: no cover
            pass
        return pids

    # ---------- 主流程 ----------
    def acquire(
        self,
        group: str,
        *,
        force: bool = False,
        yield_on_conflict: bool = False,
        wait_s: float = 20.0,
    ) -> Tuple[int, str]:
        groups = self.groups()
        if group not in groups:
            return EXIT_INTERNAL, "未知组：%s" % group
        spec = dict(groups[group], name=group)
        need = spec.get("need_mib")

        leases = self._reap(self._read_leases())
        others = {g: how for g, how in self.active_groups(leases).items() if g != group}

        # ---- L3：冲突处置 ----
        if others:
            if yield_on_conflict:
                return EXIT_CONFLICT, "对方在跑 → --yield：本任务零副作用搁置"
            if not force:
                lines = ["检测到其他组活跃（未强占）："]
                for g, how in sorted(others.items()):
                    lines.append("  - %s（依据=%s）" % (g, how))
                lines.append("请选择：--force-others 关掉对方 / --yield 搁置 / 人工处理")
                return EXIT_CONFLICT, "\n".join(lines)

            # --force-others：释放对方（仍排除自己），然后**轮询**等回收
            self_pids = self._self_pids()
            for g in others:
                self.probe.release(dict(groups[g], name=g), self_pids)
            self._wait_free(need, wait_s)
            leases = self._drop(leases, group)

        # ---- 算账 ----
        free = self.probe.free()
        if need is not None and free < need:
            # 不够：不落租约，直接停手（绝不硬跑）
            return EXIT_INSUFFICIENT, "可用 %s < 需要 %s MiB → 停手" % (free, need)

        # ---- 落租约 ----
        pol = self.policy()
        ttl = pol.get("default_ttl_s", 1800)
        leases[group] = {
            "pid": os.getpid(),
            "started": time.time(),
            "heartbeat": time.time(),
            "ttl_s": ttl,
            "expire_at": time.time() + ttl,
            "need_mib": need,
        }
        self._write_leases(leases)
        return EXIT_OK, "已获租约：%s（需要 %s MiB / 可用 %s MiB）" % (group, need, free)

    def _wait_free(self, need: Optional[int], wait_s: float) -> int:
        """★ 卸载是异步的 —— 必须轮询，不能卸载完立刻算账。"""
        if need is None:
            return self.probe.free()
        deadline = time.time() + wait_s
        free = self.probe.free()
        while free < need and time.time() < deadline:
            time.sleep(0.2)
            free = self.probe.free()
        return free

    def release(self, group: str) -> Tuple[int, str]:
        leases = self._read_leases()
        if group not in leases:
            return EXIT_OK, "本无租约：%s" % group
        self._write_leases(self._drop(leases, group))
        return EXIT_OK, "已释放租约：%s" % group

    def status(self) -> dict:
        leases = self._reap(self._read_leases())
        return {
            "free_mib": self.probe.free(),
            "active": self.active_groups(leases),
            "leases": {g: {"pid": r.get("pid")} for g, r in leases.items()},
        }

    def heartbeat(self, group: str) -> bool:
        leases = self._read_leases()
        if group not in leases:
            return False
        leases[group]["heartbeat"] = time.time()
        self._write_leases(leases)
        return True


# ============================ 自测 ============================
def _selftest() -> int:
    import tempfile

    tmp = tempfile.mkdtemp(prefix="wbb-lease-")
    gp = os.path.join(tmp, "groups.json")
    lp = os.path.join(tmp, "leases.json")
    with open(gp, "w", encoding="utf-8") as f:
        json.dump({
            "groups": {
                "alpha": {"need_mib": 7000, "probe": "service_resident", "release": "unload_models"},
                "beta": {"need_mib": 3000, "probe": "port_listening", "release": "kill_ports"},
                "gamma": {"need_mib": None, "probe": "proc_alive", "release": "ask_manual"},
            },
            "policy": {"heartbeat_timeout_s": 120, "default_ttl_s": 1800},
        }, f)

    fails: List[str] = []

    total = [0]

    def check(name: str, cond: bool, detail: str = "") -> None:
        total[0] += 1
        print("  %s %s%s" % ("✅" if cond else "❌", name, (" — " + detail) if detail else ""))
        if not cond:
            fails.append(name)

    probe = FakeProbe(free_mib=20000)
    m = LeaseManager(gp, lp, probe)

    code, _ = m.acquire("alpha")
    check("空态 acquire → 0", code == EXIT_OK, "got %d" % code)

    code, msg = m.acquire("beta")
    check("已有租约时 acquire → 5（不 kill）", code == EXIT_CONFLICT, msg.splitlines()[0])

    code, _ = m.acquire("beta", yield_on_conflict=True)
    check("--yield → 5 且零副作用", code == EXIT_CONFLICT)

    # ★ 双轨：手动启动的组（无租约，只有实测轨）
    probe._external["gamma"] = True
    act = m.active_groups()
    check("实测轨能发现无租约的组", act.get("gamma") == "probe", str(act))
    code, _ = m.acquire("beta")
    check("实测轨生效 → 仍报冲突", code == EXIT_CONFLICT)

    # 资源不足
    probe2 = FakeProbe(free_mib=1000)
    m2 = LeaseManager(gp, os.path.join(tmp, "l2.json"), probe2)
    code, msg = m2.acquire("alpha")
    check("资源不足 → 6（不硬跑）", code == EXIT_INSUFFICIENT, msg)
    check("不足时未落租约", m2.status()["leases"] == {})

    # --force-others
    probe3 = FakeProbe(free_mib=20000, external={"alpha": True})
    m3 = LeaseManager(gp, os.path.join(tmp, "l3.json"), probe3)
    code, _ = m3.acquire("beta", force=True, wait_s=1.0)
    check("--force-others → 释放对方后成功", code == EXIT_OK and "alpha" in probe3.released)

    # release
    code, _ = m.release("alpha")
    check("release → 0 且租约清空", code == EXIT_OK and "alpha" not in m._read_leases())

    # 僵尸租约可被抢占（心跳过期）
    leases = m._read_leases()
    leases["stale"] = {"pid": os.getpid(), "heartbeat": 0, "expire_at": 1e18, "ttl_s": 10}
    m._write_leases(leases)
    check("心跳过期的僵尸租约被清", "stale" not in m.active_groups())

    print()
    print("结果：%d 项通过 / %d 项失败" % (total[0] - len(fails), len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
