# WB Bot

[![CI](https://github.com/WinterMK-byte/wb-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/WinterMK-byte/wb-bot/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/WinterMK-byte/wb-bot?color=blue)](https://github.com/WinterMK-byte/wb-bot/releases)
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

Two ways: **pip** if you just want to use it; **clone** if you want the source.

### Option 1 · pip (recommended)

```bash
pip install wb-bot              # core has zero dependencies
pip install "wb-bot[mcp]"       # only if you need the MCP server

wbb --bus ./00-bus.md append "alice|architect|Split T01/T02, assigned to bob|done|tasks/T01.md|bob"
wbb --bus ./00-bus.md verify
```

### Option 2 · from the repo (no install)

```bash
git clone https://github.com/WinterMK-byte/wb-bot.git
cd wb-bot

cp templates/00-bus.md ./00-bus.md

python -m wbb.cli --bus ./00-bus.md append \
  "alice|architect|Split T01/T02, assigned to bob|done|tasks/T01.md|bob"

python -m wbb.cli --bus ./00-bus.md verify
python -m wbb.cli --bus ./00-bus.md read --since 0
```

Built-in self-test (20 checks: concurrency, duplicate IDs, row order, **table continuity**, archive, locks):

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
| [`docs/06-heterogeneous-agents.md`](docs/06-heterogeneous-agents.md) | Collaboration across runtimes (single bus + watermark) |
| [`docs/07-seat-governance.md`](docs/07-seat-governance.md) | Seat governance: boundaries, delegation, conditional removal of the middle layer |
| [`docs/08-routing.md`](docs/08-routing.md) | Routing: utterance → owner → entry point |
| [`docs/09-multi-scheduler.md`](docs/09-multi-scheduler.md) | Multiple scheduler sources: four dialects, one discipline |
| [`docs/10-resource-lease.md`](docs/10-resource-lease.md) | Cross-process resource leases (platform-bound case) |
| [`docs/11-usage.md`](docs/11-usage.md) | **How to use** — five scenarios; pick one and copy |
| [`docs/12-handoff-discipline.md`](docs/12-handoff-discipline.md) | ★ **Handoff discipline** — why assignments get lost, and how to stop it |
| [`docs/13-auto-wake.md`](docs/13-auto-wake.md) | ★ **One-line dispatch & auto-wake** — with measured data (~30 s delay), trade-offs |
| ★ [`docs/14-runtime-migration.md`](docs/14-runtime-migration.md) | **Runtime migration** — sessions get rebuilt; what a handoff must carry, and what to audit afterwards |
| ★ [`docs/15-adopting.md`](docs/15-adopting.md) | **Adoption guide** — pick one of three depths; **which parameters only you can decide**; the three tests for "it's actually wired up"; anti-patterns |
| [`docs/lessons.md`](docs/lessons.md) | ★ **Lessons from real incidents** (the point of this project) |
| [`docs/README.md`](docs/README.md) | Doc index (ordered by "what should I read first") |
| [`skill/SKILL.md`](skill/SKILL.md) | Operator guide for agents (installable as a Skill) |
| [`CHANGELOG.md`](CHANGELOG.md) | Changelog (v0.1 → v0.5.0) |
| [`ROADMAP.md`](ROADMAP.md) | **Roadmap** — shipped / in progress / **explicitly out of scope**, and how to influence it |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | How to file issues / PRs (★ **real incidents** most welcome) |

> Docs are in **Chinese** (they were grown from a real setup).
> This README is the English front door; for depth, use a translator —
> or open an issue and ask.

---

## v0.2 · Cross-runtime governance

Beyond "several sessions in one runtime", v0.2 covers **several different agent runtimes**:
how to split capability boundaries, who owns what, the five kinds of handoff artifacts,
how to keep scheduled tasks from colliding across four scheduler sources,
and how multiple processes share one scarce resource without stepping on each other.

## v0.3 · Handoff

Two additions that came out of a real incident
(an assignment that never landed, and nobody noticed — for **six days**):

- **`docs/12` Handoff discipline** — dual-channel delivery, receipt obligation, three failure modes
- **`docs/13` Auto-wake** — make a *closed* session actually start working (with measured delay)

## v0.4 · Runtime migration

**Executors are consumables.** Any long-lived session has a lifecycle *shorter* than the work
it carries — context fills up, the model generation turns over, the machine gets reinstalled,
or the process just dies. When that happens the session **gets a new shell**.

The trouble: getting a new shell **does not raise an error**. The new session starts up perfectly
fine — it just starts from zero. It forgets **who it is** (and starts crossing boundaries) and
**what it was in the middle of** (so work gets done twice, or by nobody).

- **`wbb/migrate.py`** — runnable: `render` builds the handoff document, `audit` finds references
  still pointing at the *old* location. Exit code `0` clean / `8` needs work. 23 self-tests.
- **`docs/14` Runtime migration** — three things a handoff must carry; what to scan after moving
- **`templates/06-identity-block.md`** — the identity block that `render --identity` consumes

```bash
python -m wbb.cli migrate render --identity ./identity.md --bus ./00-bus.md --out ./handoff.md
python -m wbb.cli migrate audit  --root . --old <old-path> --new <new-path>
```

> **Why this needs a tool, not a habit**: a hard-coded path that survives a move produces a
> **silent** failure — reading a missing file usually does not throw, it returns empty, and empty
> gets read as "nothing to do today". That is more dangerous than a crash, because nobody notices.

---

## Getting involved

**The most valuable input to this project is not code — it is a "real incident".**
If you hit a wall coordinating multiple agents, write it down: it becomes the next entry in
`docs/lessons.md`. **Mechanisms can be copied; lessons cannot.**

| Where | When | How |
|---|---|---|
| ★ **Real incident** | You hit a wall in a *real* setup — **most welcome**; the form is basically a lesson draft | [new issue](https://github.com/WinterMK-byte/wb-bot/issues/new/choose) → pick the incident form |
| **Bug** | It doesn't do what the docs say, and you can give a minimal reproduction | same → pick the bug form |
| **Idea / question** | You want a capability, or you're asking "how would I use this here?" | [Discussions](https://github.com/WinterMK-byte/wb-bot/discussions) |

### How this project matures *through use*

It doesn't rely on planning ahead. It relies on one loop — every step is driven by a concrete action:

```
   actually use it (wire it into your repo)
        ↓
   hit a wall   ←── this step cannot be planned; it can only be encountered
        ↓
   file the "real incident" form (= a lesson draft)
        ↓
   ★ add a self-test proving the check catches it   ←── skip this and it just happens again
        ↓
   it lives in CI forever (plus version / docs / privacy gates)
        ↓
   the next person can't fall into that hole
```

So **"where did I get stuck?" is itself a requirement** — it proves a real user actually walks
that path. Doc improvements, lower barriers, clearer errors: all count as needs.

Run these before opening a PR:

```bash
python -m wbb.bus                 # bus self-test (20)
python -m wbb.lease               # lease self-test (15)
python -m wbb.migrate             # migration self-test (23)
python tools/usability_check.py   # out-of-the-box check (simulates a newcomer cloning the repo)
python tools/version_check.py     # ★ version must match in three places
python tools/link_check.py        # ★ relative links resolve + docs are all indexed
python tools/privacy_check.py     # sanitization gate (zero hits to pass)
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`ROADMAP.md`](ROADMAP.md).

> This is a **personally maintained community project with no promised timeline**
> (why: see the top of [ROADMAP](ROADMAP.md)) — but every issue gets read.

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
