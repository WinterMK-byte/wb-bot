# 文档索引

> 按「我该先读哪篇」排。每篇独立可读，不用从头看。

---

## 先读这三篇（约 10 分钟）

| 篇 | 回答 |
|---|---|
| [01 · 为什么](01-why.md) | 这套东西到底解决什么 |
| [11 · 怎么用（五种场景）](11-usage.md) | 我的情况该怎么做 —— **挑一个照做** |
| ★ [lessons · 教训库](lessons.md) | **本项目最不易被抄走的部分**（真实事故） |

---

## 核心机制

| 篇 | 内容 |
|---|---|
| [02 · 架构](02-architecture.md) | 三层结构总览 |
| [03 · 席位](03-seats.md) | 谁是谁、怎么指认 |
| [04 · 总线协议](04-bus-protocol.md) | append-only、锁、写后自检、ID 在锁内算 |
| [05 · 通知注入](05-injection.md) | ★ **怎么让"通知"真的送达**（最容易漏的一环） |

---

## 跨运行时与治理

| 篇 | 内容 |
|---|---|
| [06 · 异构运行时协作](06-heterogeneous-agents.md) | 两侧能力不对等（甚至一侧没 API）时怎么协作 |
| [07 · 席位治理](07-seat-governance.md) | 边界判据 / 越界 / 代劳三件套 / **条件性取消中间层** |
| [08 · 路由层](08-routing.md) | 「这句话归谁」怎么查 |
| [09 · 多调度源](09-multi-scheduler.md) | 定时任务散在四个调度源时怎么不出乱 |
| [10 · 跨进程资源租约](10-resource-lease.md) | 多进程抢同一份稀缺资源（平台绑定案例） |

---

## 交接（**本项目最有普适价值的两篇**）

| 篇 | 内容 |
|---|---|
| ★ [12 · 交接纪律](12-handoff-discipline.md) | **派单为什么会丢** —— 投递双通道 / 回执义务 / 三种失败模式 |
| ★ [13 · 自动唤醒](13-auto-wake.md) | 一句话派单；让「没开着的」执行方动起来（**含实测数据**） |

> 两篇合起来回答：**怎么把一句人话变成一条不会丢的活**。

---

## 迁移（**执行方是耗材，这是配套的正事**）

| 篇 | 内容 |
|---|---|
| ★ [14 · 运行时迁移](14-runtime-migration.md) | 会话会被重建 —— **接续要带什么、搬完要查什么**（含可运行实现 `wbb/migrate.py`） |

> 回答：**换了壳之后，怎么接着干、怎么不丢身份、怎么不静默失效。**

---

## 快速上手（30 秒）

```bash
git clone https://github.com/WinterMK-byte/wb-bot && cd wb-bot
cp templates/00-bus.md ./00-bus.md
python -m wbb.cli --bus ./00-bus.md append "alice|architect|拆了两个任务，派给 bob|done|tasks/T01.md|bob"
python -m wbb.cli --bus ./00-bus.md verify
```

**要迁移一条长期会话时**（会话被重建 / 换机 / 换代）：

```bash
cp templates/06-identity-block.md ./identity.md     # 先写身份块
python -m wbb.cli migrate render --identity ./identity.md --bus ./00-bus.md --out ./接续文本.md
python -m wbb.cli migrate audit  --root . --old <旧位置> --new <新位置>   # 跑到零命中为止
```

---

→ 回 [README](../README.md) ｜ 英文版 [README.en](../README.en.md)
