# 贡献指南

> 先说一句：**这个项目最值钱的不是代码，是「真实事故」。**
> 如果你在多 Agent 协作里踩过坑，**把那个坑写出来比一个 PR 更有价值**。

---

## 最欢迎什么（按价值排）

| 类型 | 说明 |
|---|---|
| ★ **真实事故教训** | 见 [`docs/lessons.md`](docs/lessons.md) 现有条目的格式：症状 / 根因 / 判据 / 防法 |
| **新平台的注入点 / 调度源口径** | 见 [`docs/05`](docs/05-injection.md)、[`docs/09`](docs/09-multi-scheduler.md) |
| **bug + 最小复现** | 说清「怎么复现」，比说「它坏了」有用得多 |
| **文档改进** | 尤其是「我卡在哪儿了」—— 那正是文档该补的地方 |

---

## 不欢迎什么

- ❌ **加抽象层**（本项目刻意保持薄）
- ❌ **加第三方依赖** —— 核心**零依赖**是刻意的（MCP server 除外）
- ❌ 把 CLI 换成"更现代"的框架封装
- ❌ 一个 PR 改一堆无关文件

---

## 提交前跑这几条

```bash
python -m wbb.bus                 # 总线自测（20 项）
python -m wbb.lease               # 租约自测（15 项）
python -m wbb.migrate             # 迁移自测（23 项）
python tools/usability_check.py   # ★ 开箱实测（模拟"新人拿到仓库"）
python tools/version_check.py     # ★ 版本三处一致（pyproject / __init__ / CHANGELOG）
python tools/link_check.py        # ★ 相对链接可达 + docs 索引完整
python tools/privacy_check.py     # 脱敏门禁（本仓库是公开的，必过）
```

> ★ **每个 bug 修复都必须带一个自测项**（防回归）。
> 这是本项目从真实事故里学到的最硬的一条 ——
> 见 `docs/13` §三：验证要**三重证据交叉**，单看一个都会被"假象"骗过去。

### 两条会被 CI 自动检查的纪律

| 改了什么 | 必须同步 |
|---|---|
| 新增 / 改名文档 | `docs/README.md` 与根 `README.md` 的索引（否则**等于没写** —— 没人会走到那儿） |
| 版本号 | `pyproject.toml` + `wbb/__init__.py` + `CHANGELOG.md` **三处一致**（这个坑本项目踩过两次） |

---

## 代码风格

- **标准库优先**，不引第三方依赖（MCP server 除外）
- 注释写「**为什么**」，不重复代码在做什么
- 公开 API 改了要同步：`README` / `README.en` / `CHANGELOG`
- **自测写反向用例优先**：先证明它**抓得到错**，再证明它对的不报错

---

## 提 issue

走 [新建 issue](https://github.com/WinterMK-byte/wb-bot/issues/new/choose)，三张表单按内容选：

| 表单 | 用途 |
|---|---|
| ★ **真实事故** | 你在真实协作里撞出来的坑 —— **最欢迎**，字段与 `docs/lessons.md` 对齐，填完就是一条教训草稿 |
| **缺陷** | 带最小复现的 bug |
| **想法** | 想要的能力 / 觉得该改的规矩 |

**「我这情况该怎么用」这类提问请走 [Discussions](https://github.com/WinterMK-byte/wb-bot/discussions)** —— issue 留给可复现的东西。

> 只提**文档改进**也完全算贡献。尤其是「**我卡在哪一句上了**」——
> 那正是文档该补的地方，而且它证明真实读者真会走到那儿。
