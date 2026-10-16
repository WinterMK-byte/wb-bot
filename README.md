# WB Bot

[![CI](https://github.com/WinterMK-byte/wb-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/WinterMK-byte/wb-bot/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/WinterMK-byte/wb-bot?color=blue)](https://github.com/WinterMK-byte/wb-bot/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
![Dependencies: none](https://img.shields.io/badge/dependencies-none-brightgreen.svg)

**简体中文** ｜ [English](README.en.md)

> **别人解决「怎么让多 Agent 协作」，这里解决「协作怎么不乱」。**

一套给多 Agent 系统用的**协作纪律层**：单一权威的 append-only 总线、席位边界判据、
跨运行时的交接契约、以及一份从真实事故里长出来的**反错清单**。

它不是又一个 agent 框架 —— 它**不调度模型、不管上下文、不管工具**。
它只管一件事：**当多个 Agent（或多人 + 多个 Agent）真的在同一个仓库里干活时，
怎么让记录不烂、边界不糊、信息不丢。**

```
python -m wbb.cli --bus ./00-bus.md append "alice|architect|拆了两个任务，派给 bob|done|tasks/T01.md|bob"
python -m wbb.cli --bus ./00-bus.md verify
```

零第三方依赖（MCP server 除外）。CJK 路径安全。MIT。

> **v0.2 新增**：除了"一个运行时内的多会话"，现在也覆盖"**多个不同 Agent 运行时之间**"
> —— 能力边界怎么切、主导权归谁、交接件有哪五种、定时任务散在四个调度源时怎么不出乱、
> 多个进程抢同一份稀缺资源时怎么协调。见 [跨 Agent 治理层](#v02--跨-agent-治理层)。

---

## 目录

- [为什么需要它](#为什么需要它)
- [三个核心概念](#三个核心概念)
- [快速开始](#快速开始)
- [四条设计不变量](#四条设计不变量)
- [MCP 接入](#mcp-接入)
- [教训库（本项目的重点）](#教训库本项目的重点)
- [v0.2 · 跨 Agent 治理层](#v02--跨-agent-治理层)
- [文档](#文档)
- [免责声明](#免责声明)

---

## 为什么需要它

多 Agent 系统一旦真的跑起来，出问题的**几乎从来不是模型能力**，而是这四类：

| 症状 | 真实后果 |
|---|---|
| **记录烂** | 两条记录撞了同一个 ID；新条目插进了表格中段；有人手写的格式工具读不出来 |
| **边界糊** | 谁该改哪个文件说不清，两个 Agent 同时改同一个，改乱了才发现 |
| **信息丢** | 明明写进"注册表"了，可**没有任何会话会主动读它** → 等于没通知 |
| **假安全** | 告警天天亮、天天假红，于是所有人学会忽略告警 |

这些问题**不会报错**。它们只是让协作缓慢失准，直到某天你发现：
总线上有 7 条重号、两条线各自维护了一份"权威"数据、某个 Agent 半年没收到过更新。

本项目把这些教训固化成可执行的机制 + 一份可查的清单。

---

## 三个核心概念

### 1. 席位（seat）

Agent 不是"一堆实例"，而是**有职责边界的位置**：谁做判断、谁做执行、谁做验收。
边界写下来，才有"越界"可言。

### 2. 总线（bus）

**单一权威、只追加**的共享日志。所有交接都往这儿写。
它不是聊天记录 —— 每条都要有**来源 / 角色 / 做了什么 / 状态 / 产物 / 需要谁**。

### 3. 注入点（injection point）

> **写进一个文件 ≠ 通知到任何人。**
>
> 只有落在「Agent 每次启动都会自动读」的那几处，才算真通知。
> 一份没人主动读的注册表，只是一份文档。

这三个概念对应 `docs/` 下的三篇。

---

## 快速开始

**两条路**：想直接用 → pip 装；想看源码 / 改代码 → clone。

### 方式一 · pip 装（推荐）

```bash
pip install wb-bot              # 核心零依赖
pip install "wb-bot[mcp]"       # 只有要用 MCP server 才需要

wbb --bus ./00-bus.md append "alice|architect|拆了两个任务，派给 bob|done|tasks/T01.md|bob"
wbb --bus ./00-bus.md verify
```

### 方式二 · 直接用仓库（零安装）

```bash
git clone https://github.com/WinterMK-byte/wb-bot
cd wb-bot

# 1. 建一份带结构的空总线（用模板）
cp templates/00-bus.md ./00-bus.md

# 2. 写入第一条
python -m wbb.cli --bus ./00-bus.md append \
  "alice|architect|拆了两个任务，派给 bob|done|tasks/T01.md|bob"

# 3. 体检
python -m wbb.cli --bus ./00-bus.md verify

# 4. 读（支持水位线增量）
python -m wbb.cli --bus ./00-bus.md read --since 0
```

自带自测（20 项，覆盖并发、重号、行序、**表格连续性**、归档、锁）：

```bash
python -m wbb.bus          # 或 python -m wbb.cli selftest
```

设一次环境变量就不用每次带 `--bus`：

```bash
export WBB_BUS=/abs/path/to/00-bus.md      # Windows: setx WBB_BUS ...
```

> 📖 **更完整的用法（四种场景 + 六段内容说明 + 常见坑）见
> [`docs/11-usage.md`](docs/11-usage.md)** ——
> 最短上手 / **接进真实项目** / **让 Agent 自己读写（MCP）** / 多进程抢资源。

---

## 四条设计不变量

总线看起来"就是一个 markdown 表格"，但下面这四条**缺一条就会出事**：

### ① 唯一写入入口

只有 `append()`。没有 update / delete / insert_at。
**想改历史？再追加一条说明，不要原地改。**

### ② ID 在临界区内计算

`next_id()` 取 `max(id) + 1`，而且这个计算与写入在**同一把原子锁**内完成。

> 任何"先读 ID，再写文件"的分步实现，在并发下都会撞号。
> 这不是理论 —— 见 [`lessons/01-id-collision.md`](docs/lessons/01-id-collision.md)。

### ③ 写后自检，不合格自动回滚

写完立刻验本次 ID 唯一；不合格就把文件还原成写入前的快照并抛错。
**脏数据进不去，也不留下半截状态。**

### ④ 插入点用结构锚，不用「最后一个数据行」

表格里的一行可能是**多行条目的首行**（行尾没有 `|`）。
用"最后一个闭合行"当表尾，会把新条目插进**表格中段**。

> 更狠的是：这个 bug 的根因是**插入锚被条目正文劫持** ——
> 见 [`lessons/02-insert-anchor-hijack.md`](docs/lessons/02-insert-anchor-hijack.md)。
> 那一篇值得一读，因为它是一个"修理工具时给工具自己埋雷"的典型案例。

---

## MCP 接入

`mcp_server.py` 把总线暴露成 **7 个标准 MCP 工具**，任何支持 MCP 的运行时都能接：

```
bus_append   追加（唯一写入入口，写后自检 + 自动回滚）
bus_read     读（支持水位线增量）
bus_verify   体检（可顺带修行序）
bus_claim    占用共享资源
bus_release  释放
bus_locks    列占用
bus_status   概况
```

客户端配置：

```json
{
  "mcpServers": {
    "wb-bot": {
      "command": "python",
      "args": ["/abs/path/to/mcp_server.py"],
      "env": { "WBB_BUS": "/abs/path/to/00-bus.md" }
    }
  }
}
```

> **为什么要 MCP 而不是写一个插件？**
> 插件绑死一个平台；MCP 是协议。同一份总线，不同的 Agent 运行时
> 可以同时读写 —— 这才是多 Agent 协作的**前提**：
> 大家得先能看见同一份记录。
>
> MCP 层与 CLI 层共享同一个 `Bus`，所以两条路的行为**逐字一致**。

---

## 教训库（本项目的重点）

`docs/lessons.md` 是这份项目里**最不容易被抄走**的部分 ——
一条条都对应真实事故，附现场、根因，以及"**判据到底该怎么改才对**"。

| # | 教训 | 一句话 |
|---|---|---|
| 01 | ID 撞号 | 分步读写的窗口期，并发下必撞号 |
| 02 | 插入锚被正文劫持 | 宽松匹配会被"内容里的同名串"钓走 |
| 03 | 手写行 vs 工具行 | 怎么一眼认出"有人绕过了工具" |
| 04 | 写死的绝对路径 | 迁移后必然静默失效，而且**不报错** |
| 05 | 只读镜像 = 信息孤岛 | 被隔离的 Agent 不报错，只会给出偏的方案 |
| 06 | 判据太严 = 天天假红 | 假红比不报更坏，它训练人忽略告警 |
| 07 | 返回值会说谎 | 成功码不可信时，判据只能落在"结果状态"上 |
| 08 | `0` 是假值 | `code or DEFAULT` 会把成功码吃掉 |
| 09 | 写进文件 ≠ 通知到位 | 通知要有"载体"，文档只是"可查证" |
| 10 | 归档校验的比对范围 | 判据要落在"本次产物"上，否则永远失败 |

→ 全文：[**`docs/lessons.md`**](docs/lessons.md)

---

## v0.2 · 跨 Agent 治理层

v0.1 解决的是**一个运行时内多个会话**怎么共享一条总线。
v0.2 往上加了一层：**多个不同 Agent 运行时之间**怎么协作与治理。

| 文档 | 解决什么 | 核心洞察 |
|---|---|---|
| [`docs/06-heterogeneous-agents.md`](docs/06-heterogeneous-agents.md) | 两个不同厂商的 Agent 怎么通讯 | **一侧常常没有 API** → 不能推送，只能"单一总线 + 水位线" |
| [`docs/07-seat-governance.md`](docs/07-seat-governance.md) | 谁有权改什么 | 多 Agent 最贵的成本**不是算力，是越界**；配"代劳三件套" |
| [`docs/08-routing.md`](docs/08-routing.md) | 一句话进来归谁接 | **口语 → 责任方 → 入口**；"能力"和"归属"是两张不同的表 |
| [`docs/09-multi-scheduler.md`](docs/09-multi-scheduler.md) | 定时任务散在四个源怎么办 | 四源口径不同；**写死的路径会静默失效** |
| [`docs/10-resource-lease.md`](docs/10-resource-lease.md) | 多进程抢同一份稀缺资源（⚠️ 平台绑定案例） | **活跃判定必须双轨**；再加**降级轨**（谁占着却跑在慢路径上） |

配套：

| 件 | 作用 |
|---|---|
| [`templates/03-routing-card.md`](templates/03-routing-card.md) | 路由卡（口语 → 责任方 → 入口 + 归属表） |
| [`templates/04-seat-boundaries.md`](templates/04-seat-boundaries.md) | 席位边界 + 代劳三件套（贴在注入点） |
| [`templates/05-resource-groups.json`](templates/05-resource-groups.json) | 资源组清单（声明式，新组不改代码） |
| [`wbb/lease.py`](wbb/lease.py) | 资源租约**精简参考实现**（15 项自测，含双轨判定 + **降级轨**） |
| [`skill/healthcheck.md`](skill/healthcheck.md) | 协作层体检：ID 唯一 / 行序 / 插入点 / 水位线 / 备份 |
| [`skill/onboarding.md`](skill/onboarding.md) | 新成员接入 + **全员知会**（注入点同步） |
| [`skill/ownership-audit.md`](skill/ownership-audit.md) | 会话归属审计：用实测证据，不用自述 |

```bash
# 租约参考实现自测
python -m wbb.lease
```

---

## v0.4 · 运行时迁移

**执行方是耗材。** 任何长期会话的生命周期都**短于**它承担的工作 ——
上下文塞满、模型换代、机器重装、进程崩了，任何一种都会让它「换个壳继续活着」。

麻烦在于：换壳**不会报错**。新会话启动得很正常，只是从零开始 ——
**忘了自己是谁**（开始越界），和**忘了在办什么**（同一件事做两遍，或没人接着做）。

| 件 | 作用 |
|---|---|
| [`docs/14-runtime-migration.md`](docs/14-runtime-migration.md) | **迁移机制** —— 为什么执行方必然被重建 / 接续必须带三样 / 搬完必须查什么 |
| [`wbb/migrate.py`](wbb/migrate.py) | 实现：`render` 生成接续文本 · `audit` 扫出还指着旧位置的引用（**23 项自测**） |
| [`templates/06-identity-block.md`](templates/06-identity-block.md) | **身份块模板**（`render --identity` 的输入） |

```bash
# 迁移一条长期会话
python -m wbb.cli migrate render --identity ./identity.md --bus ./00-bus.md --out ./接续文本.md
# 搬完之后：跑到零命中，才算这次迁移收口
python -m wbb.cli migrate audit --root . --old <旧位置> --new <新位置>
# 参考实现自测
python -m wbb.migrate
```

**两条最容易被跳过的纪律**：

1. **接续文本要放进「启动时真的会读到」的位置。** 放对了位置但启动不读 = 没放。
2. **迁移不做完 = 静默失效。** 路径写死后搬家，读一个不存在的文件通常不抛异常，
   返回空 —— 空结果被当成「今天没事」。**它比崩溃危险，因为没人知道。**

---

## 文档

| 文件 | 内容 |
|---|---|
| [`docs/01-why.md`](docs/01-why.md) | 问题的形状：多 Agent 协作的四类失效 |
| [`docs/02-architecture.md`](docs/02-architecture.md) | 三层架构：席位 / 总线 / 注入点 |
| [`docs/03-seats.md`](docs/03-seats.md) | 席位设计：边界判据、代劳条款 |
| [`docs/04-bus-protocol.md`](docs/04-bus-protocol.md) | 总线协议：列定义、ID 规则、锁、体检 |
| [`docs/05-injection.md`](docs/05-injection.md) | 注入点：哪些位置才算"通知" |
| [`docs/06-heterogeneous-agents.md`](docs/06-heterogeneous-agents.md) | 跨运行时协作：单一总线 + 水位线 |
| [`docs/07-seat-governance.md`](docs/07-seat-governance.md) | 席位治理：边界判据、代劳三件套、规则怎么改 |
| [`docs/08-routing.md`](docs/08-routing.md) | 路由层：口语 → 责任方 → 入口 |
| [`docs/09-multi-scheduler.md`](docs/09-multi-scheduler.md) | 多调度源：四源口径 + 统一纪律 |
| [`docs/10-resource-lease.md`](docs/10-resource-lease.md) | 跨进程资源租约（平台绑定案例） |
| [`docs/11-usage.md`](docs/11-usage.md) | **怎么用（五种场景）** —— 最短上手 / 接进项目 / MCP / 资源租约 / 迁移 |
| [`docs/12-handoff-discipline.md`](docs/12-handoff-discipline.md) | **交接纪律** —— 派单为什么会丢：**投递双通道 / 回执义务 / 三种失败模式** |
| [`docs/13-auto-wake.md`](docs/13-auto-wake.md) | **一句话派单与自动唤醒** —— 含**实测数据**（30 秒延迟）、两条路、代价边界 |
| ★ [`docs/14-runtime-migration.md`](docs/14-runtime-migration.md) | **运行时迁移** —— 执行方是**耗材**：接续要带什么（身份 / 在办事实 / 未闭口）、搬完要查什么（写死路径的**静默失效**） |
| [`docs/lessons.md`](docs/lessons.md) | **10 条真实事故教训**（本项目重点） |
| [`skill/SKILL.md`](skill/SKILL.md) | 给 Agent 用的操作指引（可直接装成 Skill） |
| [`docs/README.md`](docs/README.md) | **文档索引**（按「该先读哪篇」排） |
| [`CHANGELOG.md`](CHANGELOG.md) | **更新日志**（v0.1 → v0.4.0） |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | 怎么提 issue / PR |

---

## 本项目不做什么

- ❌ 不调度模型、不管上下文压缩、不管工具权限
- ❌ 不做"多 Bot 群聊"式的即时协商（那是另一类项目）
- ❌ 不假设某个平台 —— 不依赖任何私有 API

它是一层**纪律**，可以叠加在任意 agent 运行时之上。

> **与上游的关系**：本项目的机制提炼自一个真实的（私有的）多 Agent 协作环境，
> 是它的**泛化与脱敏版本**。上游是内部工具，**不承诺与本仓库同步**；
> bug 修复与真实事故教训**优先沉淀进本仓库**（它有 CI / 自测 / 隐私门禁，质量闸更严）。
> 两者**不合并** —— 功能已基本对齐，差异在表头格式与使用习惯，而迁移历史记录的收益不抵风险。

> **姊妹项目**：[**agent-workflow-sop**](https://github.com/WinterMK-byte/agent-workflow-sop)
> —— 那是**流程层**（活怎么派、谁该干什么、**直派要满足哪四条判据**）；
> 本仓库是**机制层**（记录怎么不烂、通知怎么不丢、资源怎么不抢）。
> 两个配套：SOP 决定「下一步归谁」，wb-bot 提供「交接时不丢东西」的器具。

---

## 隐私与发布前检查

**"我不会泄露隐私"是承诺；"提交前能跑一遍、零命中才算过"是机制。**

仓库自带 [`tools/privacy_check.py`](tools/privacy_check.py)，发布前必跑：

```bash
python tools/privacy_check.py
```

它查七个维度：关键词 · PII 正则（邮箱/手机/身份证/长数字/绝对路径/真实 URL）·
编码层（零宽字符/控制字符/base64 长块）· 文件层（隐藏/二进制/可疑扩展）·
交叉引用（指到仓库外的绝对路径）· 时间线（具体日期）· 元数据提示。
**只读，不改任何文件。** 退出码 0 = 干净。

自定义私有词表放 `privacy_words.txt`（一行一个词，**已在 `.gitignore` 中**），
**不要硬编码进脚本**。

> ⚠️ **本工具查不到 git 身份 —— 而那是最常被忽略、也最难挽回的泄露点。**
>
> ```bash
> git config user.name
> git config user.email
> ```
>
> 提交（commit）会把作者名与邮箱**永久写进历史**。事后改配置**不会**改掉已有提交 ——
> 想清掉只能重写历史（`filter-repo` / 重建仓库）。所以**第一次 commit 之前**就要设好。
>
> **推荐做法**：用 GitHub 的 noreply 邮箱。
> 到 GitHub → Settings → Emails 勾选 *Keep my email addresses private*，
> 它会给你一个 `<数字ID>+<用户名>@users.noreply.github.com`。
> 然后**只为这个仓库**设置（**不要加 `--global`**）：
>
> ```bash
> cd wb-bot
> git init
> git config user.name  "<你的 GitHub 用户名>"
> git config user.email "<数字ID>+<用户名>@users.noreply.github.com"
> python tools/privacy_check.py        # 提交前再跑一次，零命中才算过
> git add . && git commit -m "init"
> ```
>
> 验证：
>
> ```bash
> git log -1 --format='%an <%ae>'      # 应当显示 noreply 地址，不是你的真实邮箱
> ```

本项目自身已通过该项检查（**零命中**）。

---

## 免责声明

本项目是**独立社区项目**，与任何模型厂商、软件厂商**无关联**，
**未被其赞助、认可或背书**。为保持中立，文档中不出现任何具体平台的名称。

总线文件默认是**纯文本 Markdown**，请自行确认其中不含敏感信息后再提交到公开仓库。

## License

MIT — 见 [LICENSE](LICENSE)。
