# -*- coding: utf-8 -*-
"""WB Bot —— 多 Agent 协作的纪律层。

别人解决「怎么让多 agent 协作」，这里解决「协作怎么不乱」。

核心是 :class:`wbb.bus.Bus`：一份 append-only、单权威、带原子锁与写后自检的协作日志。

v0.2 起另含 :class:`wbb.lease.LeaseManager`：跨进程资源租约（多个互不知情的进程
抢占同一份稀缺资源时的协调层，含"双轨活跃判定"）。
"""

from .bus import Bus, BusError, LockTimeout, SelfCheckFailed
from .lease import (EXIT_CONFLICT, EXIT_DEGRADED, EXIT_INSUFFICIENT, EXIT_OK,
                    LeaseManager, Probe)

__version__ = "0.2.2"
__all__ = [
    "Bus", "BusError", "LockTimeout", "SelfCheckFailed",
    "LeaseManager", "Probe",
    "EXIT_OK", "EXIT_CONFLICT", "EXIT_INSUFFICIENT", "EXIT_DEGRADED",
    "__version__",
]
