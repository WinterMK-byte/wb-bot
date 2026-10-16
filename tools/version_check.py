# -*- coding: utf-8 -*-
"""版本一致性门禁 —— 三处版本号必须完全一致。

为什么必须工具化：
  「版本号忘记同步」本项目**已经踩过两次** —— `pyproject.toml` 与 `wbb/__init__.py`
  各写各的。它**不报错**：`pip install` 出来的包和 `wbb --version` 说的不一样，
  用户按文档排查会一路怀疑到自己的环境上。
  两类失效都属于「不报错的错」，只能靠机械校验拦。

三处真源（改一处就必须改三处）：
  ① `pyproject.toml`  ->  [project] version
  ② `wbb/__init__.py` ->  __version__
  ③ `CHANGELOG.md`    ->  最新一条 `## [x.y.z]`

外加一条不变量：**CHANGELOG 条目必须降序**（新的在最上面）。
  否则「最新版本是哪个」这个判断本身就不成立 —— 也就没法比对。

用法：
  python tools/version_check.py                  # 查本仓库
  python tools/version_check.py --root <目录>     # 查别的目录（自测用）
  python tools/version_check.py --selftest       # 自测（含故意写错的反向用例）
退出码：0 = 三处一致且 CHANGELOG 降序
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

# ★ Windows 控制台默认不是 UTF-8 —— 直接 print 中文/符号会 UnicodeEncodeError。
#   本项目主打 CJK 安全，崩在这里等于自打脸。先切 UTF-8；切不动也不报错。
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RE_PROJECT_VER = re.compile(r'(?m)^\s*version\s*=\s*"([^"]+)"')
RE_DUNDER_VER = re.compile(r'(?m)^__version__\s*=\s*"([^"]+)"')
RE_CHANGELOG_HEAD = re.compile(r'(?m)^##\s*\[([0-9][^\]]*)\]')


def read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def _semver_key(v):
    """把 '0.10.2' 变成可比较的元组（字符串比较会把 0.10 排在 0.9 前面）。"""
    parts = []
    for tok in v.split("."):
        parts.append(int(tok) if tok.isdigit() else -1)
    return tuple(parts + [0] * (4 - len(parts)))


def collect(root):
    """-> (sources: dict[label]->(path, version-or-None), changelog_versions: list)"""
    sources = {}

    p = os.path.join(root, "pyproject.toml")
    if os.path.isfile(p):
        m = RE_PROJECT_VER.search(read(p))
        sources["pyproject.toml"] = (p, m.group(1) if m else None)
    else:
        sources["pyproject.toml"] = (p, None)

    p = os.path.join(root, "wbb", "__init__.py")
    if os.path.isfile(p):
        m = RE_DUNDER_VER.search(read(p))
        sources["wbb/__init__.py"] = (p, m.group(1) if m else None)
    else:
        sources["wbb/__init__.py"] = (p, None)

    p = os.path.join(root, "CHANGELOG.md")
    versions = []
    if os.path.isfile(p):
        versions = RE_CHANGELOG_HEAD.findall(read(p))
    sources["CHANGELOG.md"] = (p, versions[0] if versions else None)
    return sources, versions


def check(root=ROOT, quiet=False, expect=None):
    sources, versions = collect(root)
    problems = []

    if not quiet:
        print("=" * 70)
        print("版本一致性门禁")
        print("=" * 70)

    for label in ("pyproject.toml", "wbb/__init__.py", "CHANGELOG.md"):
        path, ver = sources[label]
        if not os.path.isfile(path):
            problems.append("%s 不存在：%s" % (label, path))
        elif ver is None:
            problems.append("%s 里找不到版本号" % label)
        if not quiet:
            print("  %s %-18s %s" % ("✅" if ver else "❌", label, ver or "（未找到）"))

    found = [v for _, v in sources.values() if v]
    if len(set(found)) > 1:
        problems.append("三处版本号不一致：%s" % " / ".join(
            "%s=%s" % (k, v or "?") for k, (_, v) in sorted(sources.items())))

    # --expect：发版流程用 —— 「tag 说的版本」必须就是「仓库里的版本」
    if expect and (not found or set(found) != {expect}):
        problems.append("版本与期望不符：期望 %s，实际 %s"
                        % (expect, " / ".join(sorted(set(found))) or "（无）"))
        if not quiet:
            print("  ❌ 期望版本              %s（实际 %s）"
                  % (expect, " / ".join(sorted(set(found))) or "（无）"))

    # CHANGELOG 降序 —— 「最新版本」这个判断的前提
    if len(versions) > 1:
        keys = [_semver_key(v) for v in versions]
        bad = [(versions[i], versions[i + 1])
               for i in range(len(keys) - 1) if keys[i] < keys[i + 1]]
        if bad:
            problems.append("CHANGELOG 不是降序（新的要在最上面）：%s" % bad)
        if not quiet:
            print("  %s CHANGELOG 降序        %d 条条目，最新 %s"
                  % ("✅" if not bad else "❌", len(versions), versions[0]))

    # ★ 失败详情**不受 --quiet 影响** —— 静默模式下也必须说清哪里不对，
    #   否则调用方（CI / 开箱实测）只能看到一个非零退出码。
    if problems:
        if not quiet:
            print("-" * 70)
        print("❌ 版本门禁失败 %d 项：" % len(problems))
        for p in problems:
            print("   · %s" % p)
    elif not quiet:
        print("-" * 70)
        print("✅ 通过 —— 三处版本一致：%s，CHANGELOG 降序" % found[0])

    if not quiet:
        print("=" * 70)
    return 1 if problems else 0


def _selftest():
    """反向用例优先：**先证明它抓得到错**，再证明它对的不报错。"""
    tmp = os.path.join(tempfile.gettempdir(), "wbb-version-check")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(os.path.join(tmp, "wbb"))
    fails = []

    def write(ver_py, ver_init, changelog):
        with open(os.path.join(tmp, "pyproject.toml"), "w", encoding="utf-8") as f:
            f.write('[project]\nname = "x"\nversion = "%s"\n' % ver_py)
        with open(os.path.join(tmp, "wbb", "__init__.py"), "w", encoding="utf-8") as f:
            f.write('__version__ = "%s"\n' % ver_init)
        with open(os.path.join(tmp, "CHANGELOG.md"), "w", encoding="utf-8") as f:
            f.write(changelog)

    def run():
        return subprocess.run([sys.executable, "-X", "utf8", os.path.abspath(__file__),
                               "--root", tmp, "--quiet"],
                              capture_output=True).returncode

    cl_ok = "## [0.5.0] - 2026-01-01\n\n## [0.4.0] - 2025-12-01\n"
    cases = [
        ("一致（0.5.0）", ("0.5.0", "0.5.0", cl_ok), 0),
        ("两处不一致", ("0.5.0", "0.4.9", cl_ok), 1),
        ("CHANGELOG 落后", ("0.5.0", "0.5.0", "## [0.4.0] - 2025-12-01\n"), 1),
        ("CHANGELOG 乱序", ("0.5.0", "0.5.0",
                            "## [0.4.0] - a\n\n## [0.5.0] - b\n"), 1),
        ("双位数版本比较（0.10 > 0.9）", ("0.10.0", "0.10.0",
                                          "## [0.10.0] - a\n\n## [0.9.0] - b\n"), 0),
    ]
    print("version_check 自测")
    for name, args, want in cases:
        write(*args)
        got = run()
        ok = got == want
        print("  %s %-28s 期望退出码 %d，实际 %d" % ("✅" if ok else "❌", name, want, got))
        if not ok:
            fails.append(name)

    # --expect：发版流程用的判据 —— 「tag 说的版本」必须就是「仓库里的版本」
    for expect, want, label in (("0.5.0", 0, "--expect 命中"),
                                ("0.4.0", 1, "--expect 不符 -> 拒发")):
        write("0.5.0", "0.5.0", cl_ok)
        got = subprocess.run([sys.executable, "-X", "utf8", os.path.abspath(__file__),
                              "--root", tmp, "--quiet", "--expect", expect],
                             capture_output=True).returncode
        ok = got == want
        print("  %s %-28s 期望退出码 %d，实际 %d" % ("✅" if ok else "❌", label, want, got))
        if not ok:
            fails.append(label)

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
    expect = argv[argv.index("--expect") + 1] if "--expect" in argv else None
    return check(root, quiet="--quiet" in argv, expect=expect)


if __name__ == "__main__":
    sys.exit(main())
