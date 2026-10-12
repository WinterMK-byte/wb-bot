# 04 · 总线协议

> 一页说清：列怎么定、ID 怎么分、锁怎么加、体检怎么判。

---

## 一、文件结构

总线是一个普通 Markdown 文件。**必须是这个结构**（`Bus` 靠它定位插入点）：

```markdown
# 协作总线

## 总线

| ID | time | source | role | what | status | artifact | need |
|---|---|---|---|---|---|---|---|
| 1 | 2026-01-15 09:30 | agent-a | architect | 拆 T01/T02 | done | tasks/T01.md | agent-b |

---

## 变更记录

| 日期 | 变更 |
|---|---|
| 2026-01-15 | 初始化 |
```

**为什么要有 `---` 和 `## 变更记录`**：
它们是插入点的**结构锚**。新条目插在「`## 变更记录` 之前的最后一条 `---`」之上 ——
这个锚点不依赖任何一行的格式，比"找最后一个数据行"稳得多。

> ⚠️ 表体的章节标题与尾部的章节标题是**可配置**的（`bus_heading` / `tail_heading`），
> 但**一旦定下就不要改** —— 改了会让插入点定位失效。

---

## 二、列定义

默认 7 列（`columns` 参数可改，但改了就**必须与体检用同一套**）：

| 列 | 含义 | 写作要求 |
|---|---|---|
| `time` | 时间 | 由工具生成，`YYYY-MM-DD HH:MM` |
| `source` | 谁写的 | Agent 名 / 席位名 / 会话 id |
| `role` | 什么角色 | 席位名（见 [`03-seats.md`](03-seats.md)） |
| `what` | 做了什么 | **关键数字要写进来** |
| `status` | 状态 | `done` / `in-progress` / `blocked` / `review` |
| `artifact` | 产物 / 断点 | 绝对路径优先 |
| `need` | 需要谁做什么 | `-` 表示不需要 |

**关于 `what` 列**：写"改了点东西"等于没写。
写"把超时从 30s 调到 120s，因为 12 月 3 日那次 45s 的任务被误杀"才有用。
**三个月后的你，是唯一读者。**

**关于 `artifact` 列**：如果是断点，这里要放
**"磁盘上唯一可信的计数来源"**（哪个文件、哪个字段）。
不要写"进度 60%" —— 那个数字会漂。

---

## 三、ID 规则

```
new_id = max(existing_ids) + 1
```

三条硬约束：

1. **在锁内计算**（见下节）
2. **永远不复用**。删掉一条记录后，它的 ID 也作废，下一个还是 `max+1`。
   > 复用 ID 会破坏所有既有的交叉引用（"见 #184" 会指向两条记录）。
3. **不预写**。并发下 `max+1` 可能与你的预期不同 ——
   **以工具返回的 ID 为准**，不要先在文档里写"见 #216"，再去写入。

---

## 四、并发：原子锁

```python
fd = os.open(lockpath, os.O_CREAT | os.O_EXCL | os.O_WRONLY)   # 原子创建 = 拿锁
try:
    new_id = next_id()        # ① 读
    idx = insert_index(txt)   # ② 算
    write(txt[:idx] + line + txt[idx:])   # ③ 写
finally:
    os.remove(lockpath)       # 释放
```

**为什么必须整段持有**：① ② ③ 之间任何一步被别的进程插入，都会导致撞号或错位。

**三个配套细节**：

| 细节 | 为什么 |
|---|---|
| 锁要带**陈旧清理**（超时自动删） | 持有者崩溃时锁不会自己消失 |
| 锁文件里写 PID | 排查"谁拿着锁"时有用 |
| 有超时上限 | 不能让一个僵死的锁卡住所有人 |

**资源锁（`claim` / `release`）** 是另一回事：
它锁的不是"写总线"，而是**某个共享文件**（两个 Agent 要改同一份文档时先申请）。
注意：**资源锁是"声明"不是"强制"** —— 它的作用是把冲突**显式化**，靠纪律而非机制生效。

---

## 五、写后自检 + 自动回滚

```python
snapshot = txt                                    # ① 写前快照
write(txt[:idx] + line + txt[idx:])
ok, why = selfcheck(new_id)                       # ② 自检：本次 ID 唯一？
if not ok:
    write(snapshot)                               # ③ 回滚
    raise SelfCheckFailed(why)
```

**关键**：回滚的是**内存里那份快照**，不是"再删一行"。
后者在异常路径上很容易删错行。

**自检只查"本次写入"** —— 历史遗留的重号不阻断本次写入
（否则一旦历史有问题，整个系统就写不进新东西了）。

---

## 六、体检：四类判据

```bash
python -m wbb.cli --bus ./00-bus.md verify
```

| 检查 | 判据 | fail? |
|---|---|---|
| ID 唯一 | 每个 ID 出现 1 次 | ✅ 是 |
| 时间列格式 | 匹配 `^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}$` | ✅ 是（手写行铁证） |
| ID 单调 | 物理行序与 ID 序一致 | ✅ 是 |
| 列数 | 不少于列定义数 | ❌ **仅提示** |

**为什么列数不判 fail**：条目内容可能换行成多行条目，其续行会命中"列数不足"。
把它当错误会天天假红 —— 见 [教训 06](lessons.md#06--判据太严--天天假红)。

**`--fix-order`**：只做一件事 —— 把数据行按 ID 升序重排，**绝不改任何内容**。
且只在"行号连续"的块内重排（多行条目的续行天然把块切开，绝不被卷入）。

**重号不能自动修**。改 ID 会破坏既有引用，只能人工裁决。

---

## 七、归档与只读视图

**问题**：单文件涨到几百 KB 后，每次读都很贵；但拆成多个文件会破坏"单一权威"。

**解法**：**不拆权威源**，改为「归档 + 只读视图」。

```bash
python -m wbb.cli --bus ./00-bus.md archive --keep 200        # 预演（默认）
python -m wbb.cli --bus ./00-bus.md archive --keep 200 --go   # 真搬
python -m wbb.cli --bus ./00-bus.md view <关键词>              # 导出只读视图
```

| 机制 | 作用 |
|---|---|
| `archive/` | 老条目**整段搬**进归档文件（逐字节一致，只搬不改） |
| `views/<词>.md` | 按关键词过滤的**自动生成**视图（手改会在下次重建时丢失） |
| `read --with-archive` | 读的时候自动拼上归档段 → **永远读得到完整历史** |

**三重安全**：
1. 默认只预演，`--go` 才真搬
2. 要搬的段必须**物理连续**（有空洞就拒绝 —— 以免切坏多行条目）
3. 搬完**校验本次写出文件的 ID 集合**，一致才删源段

> 第 3 条的范围很关键：**只能验"本次写出的那个文件"**，
> 不能拿整个归档目录比对（目录里本来就有历史归档）。
> 见 [教训 10](lessons.md#10--归档校验的比对范围判据要落在本次产物上)。

**触发条件**：单文件 > 1 MB 或 > 500 条时考虑归档。**没到就别动** ——
多一个归档目录就多一处可能不一致的地方。

---

## 八、命令行速查

```bash
python -m wbb.cli --bus ./00-bus.md append "src|role|what|status|artifact|need"
python -m wbb.cli --bus ./00-bus.md read --since 0 [--with-archive]
python -m wbb.cli --bus ./00-bus.md verify [--fix-order]
python -m wbb.cli --bus ./00-bus.md claim "shared.md|用途"
python -m wbb.cli --bus ./00-bus.md release "shared.md"
python -m wbb.cli --bus ./00-bus.md locks
python -m wbb.cli --bus ./00-bus.md archive --keep 200 [--go]
python -m wbb.cli --bus ./00-bus.md view <关键词>
python -m wbb.cli --bus ./00-bus.md status
python -m wbb.cli selftest
```

→ 下一篇：[`05-injection.md`](05-injection.md)
