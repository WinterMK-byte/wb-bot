# -*- coding: utf-8 -*-
"""文档一致性门禁 —— 两件事：

  ① **相对链接必须可达**（`[文字](路径)` / `![图](路径)`）
  ② **docs/ 里每篇文档都必须进索引**（`docs/README.md` 与根 `README.md`）

为什么必须工具化（本项目踩过的坑）：
  · 链接失效**不报错** —— 读者点进去 404，维护者永远不知道。
    典型成因：文档改名/合并（`lessons.md` 合过）之后，别处的引用原地作废。
  · 新增文档**不进索引 = 等于没写** —— 它存在，但没人会走到那儿。
    和本项目反复强调的「写进文件 ≠ 通知到位」是同一类失效。
  · **大小写不匹配在 Windows 上永远发现不了**（本机文件系统不区分大小写），
    但 CI 跑 Linux —— 会挂。这类"本机全绿、CI 全红"正是要机械拦的一种。

四类误判是**刻意排除**的（本项目教训 06：判据太严 = 天天假红，假红比不报更坏）：
  · 代码块里的 `[x](y)` 不算链接 —— 那是示例，不是导航
  · 外链 / 锚点 / mailto 不检查
  · 只要目标存在即可，不要求它是文件（允许链到目录）
  · 不检查 `#锚点` 是否真的存在（锚点由渲染器生成，正则追不准）

用法：
  python tools/link_check.py                 # 查本仓库
  python tools/link_check.py --root <目录>    # 查别的目录（自测用）
  python tools/link_check.py --selftest      # 自测（含 4 个反向用例）
退出码：0 = 无失效链接且索引完整
"""
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

try:
    from urllib.parse import unquote
except ImportError:  # pragma: no cover
    def unquote(s):
        return s

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LINK_RE = re.compile(r'!?\[[^\]]*\]\(([^)]*)\)')

SKIP_DIRS = frozenset((
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    "dist", "build", ".locks", "archive", "views", ".mypy_cache",
))

EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "tel:", "data:", "#", "/")


def iter_markdown(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS and not d.endswith(".egg-info")]
        for name in filenames:
            if name.lower().endswith((".md", ".markdown")):
                yield os.path.join(dirpath, name)


def parse_target(raw):
    """`path` / `<path with space>` / `path "title"` -> 纯路径（不含锚点）。"""
    raw = raw.strip()
    if raw.startswith("<"):
        end = raw.find(">")
        raw = raw[1:end] if end != -1 else raw[1:]
    elif " " in raw:
        raw = raw.split()[0]        # 丢掉尾部的 "标题"
    raw = unquote(raw)
    return raw.split("#", 1)[0].strip()


def _case_exact(path):
    """目标是否存在**且大小写完全一致**。

    Windows 上 `Docs/READme.md` 照样能打开，但 Linux CI 会 404 ——
    所以要自己去目录里比一次字符串。
    """
    parent, name = os.path.split(path)
    if not parent:
        parent = "."
    try:
        entries = os.listdir(parent)
    except OSError:
        return None                  # 连目录都没有 -> 交给 exists() 判
    return name in entries


def scan_links(root):
    """-> list[(md 路径, 行号, 原始目标, 问题说明)]"""
    problems = []
    for md in sorted(iter_markdown(root)):
        with open(md, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        base = os.path.dirname(md)
        in_fence = False
        for lineno, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for raw in LINK_RE.findall(line):
                if not raw.strip():
                    continue
                low = raw.strip().lower()
                if low.startswith(EXTERNAL_PREFIXES) or "://" in low:
                    continue
                target = parse_target(raw)
                if not target:
                    continue
                full = os.path.normpath(os.path.join(base, target.replace("/", os.sep)))
                rel = os.path.relpath(md, root)
                if not os.path.exists(full):
                    problems.append((rel, lineno, target, "目标不存在"))
                elif _case_exact(full) is False:
                    problems.append((rel, lineno, target, "大小写不匹配（本机可读，Linux CI 会 404）"))
    return problems


def scan_docs_index(root):
    """docs/ 下每篇文档都必须出现在 docs/README.md 与根 README.md 里。"""
    ddir = os.path.join(root, "docs")
    if not os.path.isdir(ddir):
        return []
    idx_path = os.path.join(ddir, "README.md")
    root_readme = os.path.join(root, "README.md")
    idx = open(idx_path, encoding="utf-8", errors="replace").read() \
        if os.path.isfile(idx_path) else None
    rme = open(root_readme, encoding="utf-8", errors="replace").read() \
        if os.path.isfile(root_readme) else None

    problems = []
    for name in sorted(os.listdir(ddir)):
        if not name.endswith(".md") or name == "README.md":
            continue
        if idx is not None and name not in idx:
            problems.append(("docs/README.md", 0, name, "文档未进索引"))
        if rme is not None and name not in rme:
            problems.append(("README.md", 0, name, "文档未进索引"))
        if idx is None:
            problems.append(("docs/README.md", 0, name, "docs/README.md 不存在（索引缺失）"))
            break
    return problems


def check(root=ROOT, quiet=False):
    if not quiet:
        print("=" * 70)
        print("文档一致性门禁（相对链接可达 + docs 索引完整）")
        print("=" * 70)

    links = scan_links(root)
    index = scan_docs_index(root)
    n_md = sum(1 for _ in iter_markdown(root))

    if not quiet:
        print("  扫描 markdown：%d 篇" % n_md)
        print("  %s 相对链接可达        %s"
              % ("✅" if not links else "❌",
                 "全部可达" if not links else "%d 处失效" % len(links)))
        print("  %s docs 索引完整        %s"
              % ("✅" if not index else "❌",
                 "全部已登记" if not index else "%d 处缺登记" % len(index)))

    problems = links + index
    if problems:
        if not quiet:
            print("-" * 70)
        for rel, lineno, target, why in problems:
            where = "%s:%d" % (rel.replace(os.sep, "/"), lineno) if lineno else rel
            print("  ❌ %s  ->  %s   [%s]" % (where, target, why))

    if not quiet:
        print("-" * 70)
        print("✅ 通过" if not problems else "❌ 失败 %d 项" % len(problems))
        print("=" * 70)
    return 1 if problems else 0


def _selftest():
    """★ 每个用例**先把目录清空再铺料**。

    踩过的坑：把「铺料」写在 `cases.append(...)` 前一行，写文件就在**建列表时**
    全跑完了 —— 于是所有用例共享最后一次写入的状态，第一个"干净"用例必然假红。
    用例之间**必须互不残留**，否则自测本身在骗人。
    """
    tmp = os.path.join(tempfile.gettempdir(), "wbb-link-check")
    fails = []

    CLEAN_DOCS = "索引：[01](01-a.md)\n"

    def write(rel, text):
        p = os.path.join(tmp, rel)
        d = os.path.dirname(p)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)

    def run():
        return subprocess.run([sys.executable, "-X", "utf8", os.path.abspath(__file__),
                               "--root", tmp, "--quiet"],
                              capture_output=True).returncode

    def case_clean():
        write("docs/README.md", CLEAN_DOCS)
        write("docs/01-a.md", "# a\n")
        write("README.md", "见 [01](docs/01-a.md)\n")

    def case_broken():
        case_clean()
        write("README.md", "见 [01](docs/01-a.md) 和 [旧](docs/lessons/01-id-collision.md)\n")

    def case_fence():
        case_clean()
        write("README.md", "```\n[示例](不存在的路径.md)\n```\n见 [01](docs/01-a.md)\n")

    def case_missing_index():
        case_clean()
        write("docs/02-b.md", "# b\n")

    def case_case_mismatch():
        case_clean()
        write("docs/02-b.md", "")
        write("README.md", "见 [01](docs/01-a.md) 和 [B](docs/02-B.md)\n")

    def case_external():
        case_clean()
        write("README.md", "[外](https://example.com/x.md) [锚](#章节) [01](docs/01-a.md)\n")

    cases = [
        ("干净仓库", case_clean, 0),
        ("失效链接", case_broken, 1),
        ("代码块内链接被忽略", case_fence, 0),
        ("文档未进索引", case_missing_index, 1),
        ("大小写不匹配", case_case_mismatch, 1),
        ("外链/锚点跳过", case_external, 0),
    ]

    print("link_check 自测")
    for name, setup, want in cases:
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(os.path.join(tmp, "docs"))
        setup()
        got = run()
        ok = got == want
        print("  %s %-24s 期望退出码 %d，实际 %d" % ("✅" if ok else "❌", name, want, got))
        if not ok:
            fails.append(name)

    shutil.rmtree(tmp, ignore_errors=True)
    print("结果：%s" % ("✅ 全过" if not fails else "❌ 失败 %s" % fails))
    return 1 if fails else 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        return _selftest()
    root = ROOT
    if "--root" in argv:
        root = argv[argv.index("--root") + 1]
    return check(root, quiet="--quiet" in argv)


if __name__ == "__main__":
    sys.exit(main())
