# -*- coding: utf-8 -*-
"""WB Bot —— 多 Agent 协作的纪律层。

别人解决「怎么让多 agent 协作」，这里解决「协作怎么不乱」。

核心是 :class:`wbb.bus.Bus`：一份 append-only、单权威、带原子锁与写后自检的协作日志。
"""

from .bus import Bus, BusError, LockTimeout, SelfCheckFailed

__version__ = "0.1.0"
__all__ = ["Bus", "BusError", "LockTimeout", "SelfCheckFailed", "__version__"]
