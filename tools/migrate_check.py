# -*- coding: utf-8 -*-
"""迁移架构门禁 —— 专抓「会变的东西被写死了」。

## 它检查什么（对应「迁移四律」的前三条，都可机械判）

| 律 | 检查 |
|---|---|
| **一 · 会变的，不写死** | 骨架文件里出现「**实例路径**」（默认：时间戳形态）→ **必须**在指针文件里登记过。没登记 = 写死了会变的东西 |
| **二 · 权威，只有一处** | 指针文件里登记的每个路径都必须**真实存在**。不存在 = **死指针**，说明书已经和现实漂了 |
| **三 · 入口，挂启动必读位** | 指定的注入点文件里必须**真的含**指向罗盘/指针的关键词。只写文件 ≠ 送达 |

## 为什么必须工具化（本仓库自己踩出来的四起事故）

这四类失效**全都不报错** —— 不报错，就没人会发现：

```
路径写死     →  搬家后读空        →  被当成「今天没事」
权威两份     →  改了一处          →  另一处悄悄漂
入口没挂     →  机制落地了        →  但没人读到
形状接线混着 →  换个环境          →  整套报错
```

四处真实事故，形状**一模一样**（见 `docs/14-runtime-migration.md` §六）：
迁移能力没写进 skill · 任务写死路径 · SOP 漏了迁移 · 席位表把自己钉在旧工作区。

⇒ **靠「记得」防不住，靠「判据」才防得住。**

## 用法

    python tools/migrate_check.py \\
        --index    seats.json \\
        --skeleton SKELETON.md \\
        --graft    IDENTITY.md --needle SKELETON

    python tools/migrate_check.py --selftest     # 自测（6 项，含 4 个反向用例）
    python tools/migrate_check.py --demo         # 端到端演示（现场铺一份干净的，跑三项）

**退出码**：`0` = 三项全过 ｜ `1` = 有问题
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 「实例」的默认形状：时间戳目录（2026-10-16-18-53-22）
# 这类东西**每次重建都会变**，是写死风险最高的一类。
DEFAULT_INSTANCE_RE = r"\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}"

# 什么算「一个绝对路径」（用于律二的可达性检查）
ABS_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|/)[^\s]*$")


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def collect_index_paths(obj, out=None):
    """递归收集 JSON 里所有「看起来像绝对路径」的字符串值。"""
    if out is None:
        out = []
    if isinstance(obj, str):
        if ABS_PATH_RE.match(obj.strip()):
            out.append(obj.strip())
    elif isinstance(obj, dict):
        for v in obj.values():
            collect_index_paths(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            collect_index_paths(v, out)
    return out


def check_index_reachable(index_path):
    """律二：指针文件里的路径必须真实存在（否则是死指针）。"""
    problems = []
    try:
        data = json.loads(_read(index_path))
    except Exception as e:
        return [("%s" % index_path, "指针文件读不了（%s）" % e)]
    for p in collect_index_paths(data):
        if not os.path.exists(p):
            problems.append((index_path, "死指针：登记的路径不存在 -> %s" % p))
    return problems


def find_instances(text, instance_re):
    """找出文本里所有「实例形状」的片段（去重，保持出现顺序）。"""
    seen, out = set(), []
    for m in re.finditer(instance_re, text):
        s = m.group(0)
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def check_skeleton(index_path, skeleton_paths, instance_re):
    """律一：骨架里出现的实例，必须能在指针里找到对应登记。"""
    try:
        data = json.loads(_read(index_path))
    except Exception as e:
        return [("%s" % index_path, "指针文件读不了（%s）" % e)]
    registered = collect_index_paths(data)
    reg_blob = "\n".join(registered)

    problems = []
    for sk in skeleton_paths:
        if not os.path.isfile(sk):
            problems.append((sk, "骨架文件不存在"))
            continue
        for inst in find_instances(_read(sk), instance_re):
            if inst not in reg_blob:
                problems.append(
                    (sk, "写死了没登记的实例「%s」—— 它每次重建都会变，"
                         "请在指针文件里登记，或改成从指针现取" % inst))
    return problems


def check_grafts(grafts, needle):
    """律三：启动必读位必须真的含指针关键词。"""
    problems = []
    for g in grafts:
        if not os.path.isfile(g):
            problems.append((g, "注入点文件不存在（入口没挂）"))
            continue
        if needle not in _read(g):
            problems.append((g, "注入点里没有指向「%s」的指针（只写文件 ≠ 送达）" % needle))
    return problems


def check(index="", skeletons=(), grafts=(), needle="", instance_re=DEFAULT_INSTANCE_RE,
          quiet=False):
    if not quiet:
        print("=" * 70)
        print("迁移架构门禁（会变的不写死 / 权威可达 / 入口已挂）")
        print("=" * 70)

    p1 = check_skeleton(index, list(skeletons), instance_re) if (index and skeletons) else []
    p2 = check_index_reachable(index) if index else []
    p3 = check_grafts(list(grafts), needle) if (grafts and needle) else []

    if not quiet:
        print("  实例形状正则：%s" % instance_re)
        print("  %s 律一 骨架未写死实例    %s"
              % ("✅" if not p1 else "❌", "通过" if not p1 else "%d 处写死" % len(p1)))
        print("  %s 律二 指针可达          %s"
              % ("✅" if not p2 else "❌", "通过" if not p2 else "%d 个死指针" % len(p2)))
        print("  %s 律三 入口已挂          %s"
              % ("✅" if not p3 else "❌", "通过" if not p3 else "%d 处未挂" % len(p3)))

    problems = p1 + p2 + p3
    if problems:
        if not quiet:
            print("-" * 70)
        for where, why in problems:
            print("  ❌ %s  ->  %s" % (where, why))

    if not quiet:
        print("-" * 70)
        print("✅ 通过" if not problems else "❌ 失败 %d 项" % len(problems))
        print("=" * 70)
    return 1 if problems else 0


def _selftest():
    """★ 每个用例先清空目录再铺料 —— 用例之间不许残留（link_check 踩过这个坑）。"""
    tmp = os.path.join(tempfile.gettempdir(), "wbb-migrate-check")
    fails = []

    OK_WS = "2026-10-16-18-53-22"

    def write(rel, text):
        p = os.path.join(tmp, rel)
        d = os.path.dirname(p)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)

    def make_dirs():
        # 让指针里的路径真实存在（律二要用）
        os.makedirs(os.path.join(tmp, "ws", OK_WS), exist_ok=True)

    def base():
        make_dirs()
        write("seats.json", json.dumps({
            "architect": {
                "canonical_memory": os.path.join(tmp, "ws", OK_WS),
                "current": os.path.join(tmp, "ws", OK_WS),
            }
        }, ensure_ascii=False, indent=2))
        write("SKELETON.md", "你的工作区可能是 `%s`，看指针文件。\n" % OK_WS)
        write("IDENTITY.md", "开工先读 SKELETON.md。\n")

    def case_clean():
        base()

    def case_dead_pointer():
        base()
        write("seats.json", json.dumps({
            "architect": {"canonical_memory": os.path.join(tmp, "ws", "2026-01-01-00-00-00")}
        }, ensure_ascii=False, indent=2))

    def case_skeleton_hardcoded():
        base()
        write("SKELETON.md", "写死一个新实例 `2026-99-99-99-99-99`，没登记过。\n")

    def case_graft_missing():
        base()
        write("IDENTITY.md", "这里没有指向罗盘的指针。\n")

    def case_fixed_path_ok():
        # 固定路径（不含实例形状）不该被误报 —— 判据过严 = 天天假红
        base()
        write("SKELETON.md", "固定文件 `~/agent/IDENTITY.md` 与实例 `%s`。\n" % OK_WS)

    def case_date_file_ok():
        # 日期流水文件（2026-10-16.md）不是实例目录，不该误报
        base()
        write("SKELETON.md", "读 `2026-10-16.md` 与实例 `%s`。\n" % OK_WS)

    def run():
        return subprocess.run(
            [sys.executable, "-X", "utf8", os.path.abspath(__file__),
             "--index", os.path.join(tmp, "seats.json"),
             "--skeleton", os.path.join(tmp, "SKELETON.md"),
             "--graft", os.path.join(tmp, "IDENTITY.md"),
             "--needle", "SKELETON", "--quiet"],
            capture_output=True).returncode

    cases = [
        ("干净", case_clean, 0),
        ("死指针（登记的路径不存在）", case_dead_pointer, 1),
        ("骨架写死未登记实例", case_skeleton_hardcoded, 1),
        ("入口未挂指针", case_graft_missing, 1),
        ("固定路径不误报", case_fixed_path_ok, 0),
        ("日期流水不误报", case_date_file_ok, 0),
    ]

    print("migrate_check 自测")
    for name, setup, want in cases:
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp, exist_ok=True)
        setup()
        got = run()
        ok = got == want
        print("  %s %-26s 期望 %d，实际 %d" % ("✅" if ok else "❌", name, want, got))
        if not ok:
            fails.append(name)

    shutil.rmtree(tmp, ignore_errors=True)
    print("结果：%s" % ("✅ 全过" if not fails else "❌ 失败 %s" % fails))
    return 1 if fails else 0


def _demo():
    """端到端演示：现场铺一份**配置正确**的样例，跑三项检查。

    给两类人用：① CI（证明工具在真实文件上真的能跑通，不只是单元自测）
              ② 第一次接触的人（5 秒看懂「指针 / 骨架 / 入口」各长什么样）
    """
    tmp = os.path.join(tempfile.gettempdir(), "wbb-migrate-demo")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    ws = os.path.join(tmp, "ws", "2026-10-16-18-53-22")
    os.makedirs(ws)

    def write(rel, text):
        with open(os.path.join(tmp, rel), "w", encoding="utf-8") as f:
            f.write(text)

    # 指针文件：会变的东西都登记在这里（律二）
    write("seats.json", json.dumps({
        "architect": {"canonical_memory": ws, "current": ws},
    }, ensure_ascii=False, indent=2))
    # 骨架文件：只讲规则，不写死实例 —— 实例从指针现取（律一）
    write("SKELETON.md", "你的工作区可能是 `%s`（★ 从指针文件现取，不要写死）。\n"
          "无论谁是执行方：开工先读身份文件；收尾必须登记总线。\n" % "2026-10-16-18-53-22")
    # 启动必读位：真的含指向指针的字符串（律三）
    write("IDENTITY.md", "开工先读 SKELETON.md。\n")

    print("== 端到端演示：在临时目录铺一份「配置正确」的样例 ==")
    code = check(index=os.path.join(tmp, "seats.json"),
                 skeletons=[os.path.join(tmp, "SKELETON.md")],
                 grafts=[os.path.join(tmp, "IDENTITY.md")],
                 needle="SKELETON")
    shutil.rmtree(tmp, ignore_errors=True)
    return code


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        return _selftest()
    if "--demo" in argv:
        return _demo()

    def opt(name, default=""):
        return argv[argv.index(name) + 1] if name in argv else default

    def multi(name):
        out = []
        for i, a in enumerate(argv):
            if a == name and i + 1 < len(argv):
                out.append(argv[i + 1])
        return out

    index = opt("--index")
    skeletons = multi("--skeleton")
    grafts = multi("--graft")
    needle = opt("--needle")
    instance_re = opt("--instance-re", DEFAULT_INSTANCE_RE)

    if not index:
        print("需要 --index <指针文件>（或 --selftest）")
        return 2
    return check(index=index, skeletons=skeletons, grafts=grafts,
                 needle=needle, instance_re=instance_re,
                 quiet="--quiet" in argv)


if __name__ == "__main__":
    sys.exit(main())
