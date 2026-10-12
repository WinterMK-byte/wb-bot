# WB Bot

[![CI](https://github.com/WinterMK-byte/wb-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/WinterMK-byte/wb-bot/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
![Dependencies: none](https://img.shields.io/badge/dependencies-none-brightgreen.svg)

**简体中文** ｜ [English](README.en.md)

> **别人解决「怎么让多 Agent 协作」，这里解决「协作怎么不乱」。**

一套给多 Agent 系统用的**协作纪律层**：单一权威的 append-only 总线、席位边界判据、
以及一份从真实事故里长出来的**反错清单**。

它不是又一个 agent 框架 —— 它**不调度模型、不管上下文、不管工具**。
它只管一件事：**当多个 Agent（或多人 + 多个 Agent）真的在同一个仓库里干活时，
怎么让记录不烂、边界不糊、信息不丢。**

```
python -m wbb.cli --bus ./00-bus.md append "alice|architect|拆了两个任务，派给 bob|done|tasks/T01.md|bob"
python -m wbb.cli --bus ./00-bus.md verify
```

零第三方依赖（MCP server 除外）。CJK 路径安全。MIT。

---

## 目录

- [为什么需要它](#为什么需要它)
- [三个核心概念](#三个核心概念)
- [快速开始](#快速开始)
- [四条设计不变量](#四条设计不变量)
- [MCP 接入](#mcp-接入)
- [教训库（本项目的重点）](#教训库本项目的重点)
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

```bash
git clone <this-repo>
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

自带自测（19 项，覆盖并发、重号、行序、归档、锁）：

```bash
python -m wbb.bus          # 或 python -m wbb.cli selftest
```

设一次环境变量就不用每次带 `--bus`：

```bash
export WBB_BUS=/abs/path/to/00-bus.md      # Windows: setx WBB_BUS ...
```

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

## 文档

| 文件 | 内容 |
|---|---|
| [`docs/01-why.md`](docs/01-why.md) | 问题的形状：多 Agent 协作的四类失效 |
| [`docs/02-architecture.md`](docs/02-architecture.md) | 三层架构：席位 / 总线 / 注入点 |
| [`docs/03-seats.md`](docs/03-seats.md) | 席位设计：边界判据、代劳条款 |
| [`docs/04-bus-protocol.md`](docs/04-bus-protocol.md) | 总线协议：列定义、ID 规则、锁、体检 |
| [`docs/05-injection.md`](docs/05-injection.md) | 注入点：哪些位置才算"通知" |
| [`skill/SKILL.md`](skill/SKILL.md) | 给 Agent 用的操作指引（可直接装成 Skill） |

---

## 本项目不做什么

- ❌ 不调度模型、不管上下文压缩、不管工具权限
- ❌ 不做"多 Bot 群聊"式的即时协商（那是另一类项目）
- ❌ 不假设某个平台 —— 不依赖任何私有 API

它是一层**纪律**，可以叠加在任意 agent 运行时之上。

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

本项目是**独立社区项目**，与腾讯、DeepSeek 及任何模型厂商**无关联**，
**未被其赞助、认可或背书**。

总线文件默认是**纯文本 Markdown**，请自行确认其中不含敏感信息后再提交到公开仓库。

## License

MIT — 见 [LICENSE](LICENSE)。
