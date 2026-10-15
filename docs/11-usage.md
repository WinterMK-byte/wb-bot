# 11 · 怎么用（四种场景）

> 前面十篇讲「**为什么这么设计**」；这一篇只讲「**怎么用**」。
> 按你的情况挑一个场景 —— 全部命令都在本机实跑验证过。

---

## 场景 A · 最短上手（3 条命令）

```bash
git clone https://github.com/WinterMK-byte/wb-bot
cd wb-bot

# ① 建一份带结构的空总线
cp templates/00-bus.md ./00-bus.md

# ② 写入第一条 —— 六段内容用 | 分隔
python -m wbb.cli --bus ./00-bus.md append \
  "alice|architect|拆了两个任务，派给 bob|done|tasks/T01.md|bob"

# ③ 体检（ID 唯一 / 时间列 / 行序）
python -m wbb.cli --bus ./00-bus.md verify
```

**append 的六段分别填什么**：

| 段 | 含义 | 例 |
|---|---|---|
| `source` | **谁** | `alice` |
| `role` | 什么角色 | `architect` / `executor` / `reviewer` |
| `what` | **做了什么** | `拆了两个任务，派给 bob` |
| `status` | 状态 | `done` / `doing` / `blocked` |
| `artifact` | **产物在哪** | `tasks/T01.md` |
| `need` | **需要谁做什么** | `bob` / `-` |

> **不要预写 ID、不要写时间** —— 工具自动分配，并发下以返回值 为准。
> **唯一写入入口就是 `append`** —— 别手改表格行（体检查得出来）。

省得每次带 `--bus`：

```bash
export WBB_BUS=/abs/path/to/00-bus.md     # Windows: setx WBB_BUS ...
```

---

## 场景 B · 接进一个真实项目（**最推荐**）

**核心动作只有一个**：在项目根放一份 `00-bus.md`，让**所有参与者**（多个 Agent / 多个人）都往它写。

```
你的项目/
├── 00-bus.md          ← 协作总线（唯一权威日志）
├── README.md          ← 写一句：所有交接写进 00-bus.md，用 wbb.cli append
├── src/
└── ...
```

**开始会话时**（任一方）：

```bash
python -m wbb.cli --bus ./00-bus.md read --since 0    # 先看别人写了什么
```

**干完一件事时**：

```bash
python -m wbb.cli --bus ./00-bus.md append "我|角色|做了X|done|产物路径|需要谁"
```

**要动共享文件时**（防止两边同时改）：

```bash
python -m wbb.cli --bus ./00-bus.md claim  "src/core.py|我要重构这块"
# …改完…
python -m wbb.cli --bus ./00-bus.md release "src/core.py"
python -m wbb.cli --bus ./00-bus.md locks        # 看现在谁占着什么
```

**为什么值得**：出问题的**从来不是单个 Agent 的能力，是交接** ——
"谁改了什么、断点在哪、下一步要什么"，这些不落盘就一定会丢。

---

## 场景 C · 让 Agent 自己读写（MCP）

如果你的 Agent 运行时支持 MCP（**推荐**），它就能**自己调工具**，不用你去敲命令：

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

装好后 Agent 拿到 **7 个工具**：

```
bus_append   追加（唯一写入入口，写后自检 + 自动回滚）
bus_read     读（支持水位线增量）
bus_verify   体检
bus_claim    占用共享资源
bus_release  释放
bus_locks    列占用
bus_status   概况
```

> **为什么不写成一个插件？** 插件绑死一个平台；**MCP 是协议** —— 同一份总线，
> 不同的 Agent 运行时可以**同时**读写。这才是多 Agent 协作的前提：大家得先看见同一份记录。

---

## 场景 D · 多个进程抢同一份稀缺资源

适合：**几个互不知情的服务抢同一份独占资源**（显存 / 端口 / 连接池 / 独占文件锁）。

```python
from wbb.lease import LeaseManager, Probe

class MyProbe(Probe):
    def free(self): ...        # 现在还剩多少资源
    def active(self, spec, self_pids): ...   # 这一组真的在占吗
    def release(self, spec, self_pids): ...  # 怎么让它让出来

m = LeaseManager("groups.json", "leases.json", MyProbe())

code, msg = m.acquire("my-group")
if code != 0:
    print(msg); raise SystemExit(code)     # 5=冲突待裁定 / 6=资源不足 → 停手
try:
    ...  # 干活
finally:
    m.release("my-group")
```

**三条要点**（`docs/10` 详述）：

1. **组 ≠ 应用** —— 共用同一份资源的几个进程是**一个组**
2. **活跃判定必须双轨** —— 租约轨 ∪ **实测轨**（用户手动启动的东西不会自己登记租约）
3. **冲突默认不杀，请示人** —— `code=5` 是"需要决策"，不是错误

自测：`python -m wbb.lease`（15 项）

---

## 命令速查

| 想干什么 | 命令 |
|---|---|
| 写一条 | `python -m wbb.cli --bus B append "源\|角色\|做了什么\|状态\|产物\|需要谁"` |
| 体检 | `python -m wbb.cli --bus B verify` |
| 读增量 | `python -m wbb.cli --bus B read --since <上次最大ID>` |
| 占资源 | `python -m wbb.cli --bus B claim "文件\|说明"` |
| 放资源 | `python -m wbb.cli --bus B release "文件"` |
| 看谁占着 | `python -m wbb.cli --bus B locks` |
| 概况 | `python -m wbb.cli --bus B status` |
| 生成视图 | `python -m wbb.cli --bus B view <关键词>` |
| 自测 | `python -m wbb.bus` / `python -m wbb.lease` |
| 开箱自检 | `python tools/usability_check.py` |

---

## 常见坑

| 坑 | 怎么说 |
|---|---|
| **手改表格行** | 会绕过锁与插入点。体检查得出（"只有日期没时间"就是手写行的铁证） |
| **预写 ID** | 并发下必撞号。**ID 由工具在锁内算** |
| **多行条目** | 「做了什么」里允许含 `\|`，但**续行不能以 `\| 数字 \|` 开头**（会被当成新数据行） |
| **`read` 依赖水位线** | 水位线是**加速器不是过滤器** —— 换人或冷启动时请 `--since 0` 全量读 |
| **改了历史行** | 不允许。要更正就**再追加一条说明** |

---

→ 相关：[04 · 总线协议](04-bus-protocol.md)（列定义与锁）｜[05 · 注入点](05-injection.md)（怎么让"通知"真的送达）｜[10 · 资源租约](10-resource-lease.md)
