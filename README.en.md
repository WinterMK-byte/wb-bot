# WB Bot

[![CI](https://github.com/WinterMK-byte/wb-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/WinterMK-byte/wb-bot/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
![Dependencies: none](https://img.shields.io/badge/dependencies-none-brightgreen.svg)

> **Others make multi-agent systems work. WB Bot makes them not fall apart.**

A **coordination discipline layer** for multi-agent systems: a single-authority
append-only bus, seat boundaries, and a lessons library grown from real incidents.

It is **not another agent framework** — it does not schedule models, manage context,
or handle tools. It does exactly one thing: **when several agents (or people plus
agents) actually work in the same repo, how do you keep the record from rotting,
the boundaries from blurring, and the handoffs from getting lost.**

```bash
python -m wbb.cli --bus ./00-bus.md append "alice|architect|Split T01/T02, assigned to bob|done|tasks/T01.md|bob"
python -m wbb.cli --bus ./00-bus.md verify
```

Zero third-party dependencies (except the optional MCP server). CJK-path safe. MIT.

---

## Why

Once a multi-agent system actually runs, what breaks is almost never *model capability*.
It is four things:

| Symptom | Real consequence |
|---|---|
| **Rotting records** | Two entries get the same ID; a new entry lands mid-table; someone hand-writes a row the parser can't read |
| **Blurred boundaries** | Nobody can say who owns which file; two agents edit one file and clobber each other |
| **Lost notifications** | Something is "registered in the doc" — but **no session ever reads that doc** |
| **False safety** | Alerts fire every day, every day they are false — so everyone learns to ignore them |

**None of these throw exceptions.** They just make coordination slowly drift,
until one day you notice seven duplicate IDs and two lines each maintaining
their own "authoritative" copy.

---

## Quick start

```bash
git clone https://github.com/WinterMK-byte/wb-bot.git
cd wb-bot

cp templates/00-bus.md ./00-bus.md

python -m wbb.cli --bus ./00-bus.md append \
  "alice|architect|Split T01/T02, assigned to bob|done|tasks/T01.md|bob"

python -m wbb.cli --bus ./00-bus.md verify
python -m wbb.cli --bus ./00-bus.md read --since 0
```

Built-in self-test (19 checks: concurrency, duplicate IDs, row order, archive, locks):

```bash
python -m wbb.bus          # or: python -m wbb.cli selftest
```

Set once and drop `--bus` everywhere:

```bash
export WBB_BUS=/abs/path/to/00-bus.md
```

---

## The four invariants

The bus looks like "just a markdown table". Miss any one of these and it breaks:

**① Single write entry point.** Only `append()`. No update, no delete, no insert-at.
*Want to change history? Append a correction — don't edit in place.*

**② IDs are computed inside the critical section.** `next_id()` takes `max(id) + 1`,
and that computation happens **inside the same atomic lock** as the write.
Any "read the ID, then write" implementation collides under concurrency.

**③ Post-write self-check, with automatic rollback.** Immediately verify the new ID
is unique; if not, restore the pre-write snapshot and raise.
Dirty data cannot get in, and no half-written state is left behind.

**④ Insertion point uses a structural anchor, not "the last data row".**
A table row may be the **first line of a multi-line entry** (no trailing `|`).
Using "the last closed row" as the table end inserts new entries **mid-table**.

Each invariant has a real incident behind it — see [`docs/lessons.md`](docs/lessons.md).

---

## MCP integration

`mcp_server.py` exposes the bus as **7 standard MCP tools**, so any MCP-capable
runtime can read and write the same bus. **Protocol-neutral, not tied to any platform.**

| Tool | Purpose |
|---|---|
| `bus_append` | Append (the only write entry point; self-check + rollback) |
| `bus_read` | Read (supports a watermark for incremental reads) |
| `bus_verify` | Health check (optionally repairs row order) |
| `bus_claim` / `bus_release` / `bus_locks` | Shared-resource locks |
| `bus_status` | Summary |

Client config:

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

Works with both **mcp 1.x** (`FastMCP`) and **mcp 2.x** (`MCPServer`) — the import
path changed in 2.0, so the code tries both.

---

## Lessons library

[`docs/lessons.md`](docs/lessons.md) is the part that is **hardest to copy** —
every entry maps to a real incident, with the scene, the root cause, and
**how the check had to change**.

| # | Lesson | In one line |
|---|---|---|
| 01 | ID collision | Split read-then-write always collides under concurrency |
| 02 | Insert anchor hijacked | Loose matching gets caught by a same-named string *inside the content* |
| 03 | Hand-written rows | How to spot, at a glance, that someone bypassed the tool |
| 04 | Hard-coded absolute paths | After a migration they fail **silently** |
| 05 | Read-only mirror = information island | An isolated agent doesn't error — it just gives you a skewed plan |
| 06 | A check that's too strict | False red is worse than no alert: it trains people to ignore alerts |
| 07 | Return codes lie | When the success code can't be trusted, judge by the outcome |
| 08 | `0` is falsy | `code or DEFAULT` swallows the success code |
| 09 | Writing to a file ≠ notifying | Notification needs a *carrier*; a doc is only "queryable" |
| 10 | Archive verification scope | Judge against *this run's output*, or it fails forever |

---

## Docs

| File | Contents |
|---|---|
| [`docs/01-why.md`](docs/01-why.md) | The shape of the problem: four failure modes |
| [`docs/02-architecture.md`](docs/02-architecture.md) | Three layers: seats / bus / injection points |
| [`docs/03-seats.md`](docs/03-seats.md) | Seat design: boundary rules and delegation terms |
| [`docs/04-bus-protocol.md`](docs/04-bus-protocol.md) | Bus protocol: columns, IDs, locks, verification |
| [`docs/05-injection.md`](docs/05-injection.md) | Injection points: which locations count as "notified" |
| [`skill/SKILL.md`](skill/SKILL.md) | Operator guide for agents (installable as a Skill) |

---

## What this project does not do

- Does not schedule models, compress context, or manage tool permissions
- Does not do real-time "multi-bot group chat" negotiation (that's a different class of tool)
- Does not assume a platform — no private APIs

It is a layer of **discipline** that stacks on top of any agent runtime.

---

## Privacy before publishing

`tools/privacy_check.py` is a reusable sanitization check. Run it before you push:

```bash
python tools/privacy_check.py
```

It scans seven dimensions: keywords · PII patterns (email/phone/ID/long digits/absolute
paths/internal addresses) · encoding (zero-width chars, control chars, base64 blobs) ·
files (hidden/binary/suspicious extensions) · out-of-repo references · timeline ·
metadata hints. **Read-only; exit code 0 = clean.**

Keep your private word list in `privacy_words.txt` (already `.gitignore`d).

> ⚠️ The tool cannot see your **git identity** — and that is the leak people miss most.
> Commits record the author name and email **permanently**. Check before your first commit:
>
> ```bash
> git config user.name
> git config user.email
> ```

---

## License

MIT — see [LICENSE](LICENSE).
