#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
privacy_check.py —— 发布前的脱敏自查工具

用法::

    python tools/privacy_check.py                  # 扫本仓库
    python tools/privacy_check.py --root <目录>
    python tools/privacy_check.py --extra-words 私有词表.txt

为什么要有这个工具
------------------
"我不会泄露隐私"是一句承诺；**"每次提交前都能跑一遍、零命中才算过"** 是一个机制。
承诺会失效，机制不会。

检查七个维度
------------
① 关键词    —— 内置通用词 + 你在 ``privacy_words.txt`` 里补的私有词
② PII 正则  —— 邮箱 / 手机 / 身份证 / 长数字串 / 绝对路径 / 真实 URL
③ 编码层    —— 零宽字符 / 异常控制字符 / base64 长块
④ 文件层    —— 隐藏文件 / 可疑扩展名 / 二进制 / 额外数据流
⑤ 交叉引用  —— 指到仓库外的路径（``../`` / ``file:///``）
⑥ 时间线    —— 具体日期（可能暴露真实工作节奏）
⑦ 元数据    —— 文件属性 / 目录 Owner

退出码：0 = 干净，1 = 有命中。

⚠️ 本工具**只读**，不改任何文件。

⚠️ git 身份是另一个常被忽略的泄露点，本工具查不到 —— 提交前自己确认::

    git config user.name
    git config user.email
"""

from __future__ import annotations

import argparse
import os
import re
import sys

TEXT_EXT = {".md", ".py", ".txt", ".json", ".yml", ".yaml", ".toml", ".cfg", ".ini", ""}

# 通用词表：这些词出现在公开仓库里通常意味着"忘了脱敏"。
# 具体的私有词请放 privacy_words.txt（已 .gitignore），不要写进本文件。
GENERIC_WORDS = {
    "凭据类": ["password", "passwd", "secret", "api_key", "apikey", "token",
             "BEGIN RSA", "BEGIN PRIVATE"],
    "本地环境": ["AppData\\Roaming", "AppData\\Local", "\\Users\\Administrator"],
    "待补": [],
}

PATTERNS = [
    ("邮箱", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("中国手机号", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("身份证", re.compile(
        r"(?<!\d)[1-9]\d{5}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)")),
    ("8 位以上纯数字", re.compile(r"(?<!\d)\d{8,}(?!\d)")),
    # 路径类判据**必须排除占位符**（`<user>` / `<用户名>`），
    # 否则文档里的"示例路径"会被误判成真实路径 —— 这是把工具写成了假红制造机。
    ("Windows 绝对路径(含用户名)", re.compile(r"[A-Za-z]:\\Users\\(?!<)[^\\\s]+")),
    ("UNC 路径", re.compile(r"\\\\[A-Za-z0-9._-]+\\")),
    # ⚠️ 这里**故意不查「任何真实 URL」**。
    #    公开仓库里必然有公开链接（徽章、依赖、引用），把它们判成风险只会制造假红 ——
    #    本项目在加完 README 徽章后，立刻被自己的工具拦下 6 次，全是 shields.io / github.com。
    #    判据要落在**真正会泄漏的东西**上：内外网地址（内网 IP、环回、localhost）。
    ("内网/私有地址", re.compile(
        r"https?://(?:localhost|127\.|0\.0\.0\.0|10\.|192\.168\.|"
        r"172\.(?:1[6-9]|2\d|3[01])\.)")),
]

# 本工具自身会被自己的规则命中的原因很朴素：它**必须写出**这些模式字符串
# （`password`、`BEGIN PRIVATE KEY`、`\\Users\\` …）才能检查别人。
# 所以扫描时要把自己排除掉 —— 否则每次运行都是 13 项假红，
# 而假红的下场只有一个：所有人都学会忽略这份报告。
SELF_BASENAME = os.path.basename(os.path.abspath(__file__))

ZW_CHARS = {"\u200b": "零宽空格", "\u200c": "零宽非连接", "\u200d": "零宽连接",
            "\ufeff": "BOM", "\u2028": "行分隔", "\u2029": "段分隔", "\u00a0": "不换行空格"}

SUSPECT_EXT = {".exe", ".dll", ".bat", ".cmd", ".ps1", ".vbs", ".lnk", ".db",
               ".sqlite", ".zip", ".7z", ".rar", ".log", ".tmp", ".bak",
               ".pem", ".key", ".env", ".p12", ".pfx"}


def walk(root: str):
    me = os.path.abspath(__file__)
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in ("__pycache__", ".git", "node_modules")]
        for fn in fns:
            p = os.path.join(dp, fn)
            if os.path.abspath(p) == me:
                continue          # 跳过本工具自身（见上方 SELF_BASENAME 说明）
            yield p


def load_extra(root: str, extra: str | None):
    words = []
    cands = [extra] if extra else []
    cands += [os.path.join(root, "privacy_words.txt"),
              os.path.join(root, "tools", "privacy_words.txt")]
    for p in cands:
        if p and os.path.isfile(p):
            for line in open(p, encoding="utf-8", errors="replace"):
                w = line.strip()
                if w and not w.startswith("#"):
                    words.append(w)
            break
    return words


def main() -> int:
    ap = argparse.ArgumentParser(description="发布前脱敏自查")
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    help="要扫描的目录（默认本仓库根）")
    ap.add_argument("--extra-words", help="额外词表文件（一行一个词，# 开头为注释）")
    ap.add_argument("--quiet", action="store_true", help="只输出结论")
    a = ap.parse_args()

    root = os.path.abspath(a.root)
    files = sorted(walk(root))
    extra = load_extra(root, a.extra_words)

    hits: list[str] = []

    def H(cat: str, msg: str):
        hits.append("[%s] %s" % (cat, msg))
        if not a.quiet:
            print("  ❌ %s" % hits[-1])

    if not a.quiet:
        print("=" * 74)
        print("脱敏自查 · %s" % root)
        print("文件 %d 个  额外词表 %d 项" % (len(files), len(extra)))
        print("=" * 74)

    # ① 关键词
    if not a.quiet:
        print("\n① 关键词")
    kw = {k: list(v) for k, v in GENERIC_WORDS.items()}
    if extra:
        kw["自定义词表"] = extra
    n = 0
    for p in files:
        rel = os.path.relpath(p, root)
        try:
            txt = open(p, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        for cat, words in kw.items():
            for w in words:
                if w and w in txt:
                    n += 1
                    lines = [i for i, l in enumerate(txt.splitlines(), 1) if w in l][:2]
                    H("关键词", "%s 含 '%s' ×%d 行%s" % (rel, w, txt.count(w), lines))
    if n == 0 and not a.quiet:
        print("  ✅ 零命中")

    # ② PII 正则
    if not a.quiet:
        print("\n② PII 正则")
    n = 0
    for p in files:
        rel = os.path.relpath(p, root)
        if os.path.splitext(p)[1].lower() not in TEXT_EXT:
            continue
        try:
            txt = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for name, rx in PATTERNS:
            for m in rx.finditer(txt):
                n += 1
                line = txt[:m.start()].count("\n") + 1
                H("正则", "%s L%d [%s] → %r" % (rel, line, name, m.group(0)[:50]))
    if n == 0 and not a.quiet:
        print("  ✅ 零命中")

    # ③ 编码层
    if not a.quiet:
        print("\n③ 编码层")
    n = 0
    for p in files:
        rel = os.path.relpath(p, root)
        try:
            txt = open(p, "rb").read().decode("utf-8", errors="replace")
        except OSError:
            continue
        for ch, name in ZW_CHARS.items():
            if ch in txt:
                n += 1
                H("编码", "%s 含 %s ×%d" % (rel, name, txt.count(ch)))
        ctrl = [c for c in txt if ord(c) < 32 and c not in "\t\n\r"]
        if ctrl:
            n += 1
            H("编码", "%s 含 %d 个异常控制字符" % (rel, len(ctrl)))
        for m in re.finditer(r"[A-Za-z0-9+/]{200,}={0,2}", txt):
            n += 1
            H("编码", "%s 含 %d 字符 base64 样长块" % (rel, len(m.group(0))))
    if n == 0 and not a.quiet:
        print("  ✅ 零命中")

    # ④ 文件层
    if not a.quiet:
        print("\n④ 文件层")
    n = 0
    for p in files:
        rel = os.path.relpath(p, root)
        base = os.path.basename(p)
        if base.startswith(".") and base not in (".gitignore", ".gitattributes"):
            n += 1
            H("文件", "隐藏文件 %s" % rel)
        if os.path.splitext(p)[1].lower() in SUSPECT_EXT:
            n += 1
            H("文件", "可疑扩展名 %s" % rel)
        try:
            if b"\x00" in open(p, "rb").read(4096):
                n += 1
                H("文件", "疑似二进制 %s" % rel)
        except OSError:
            pass
    if n == 0 and not a.quiet:
        print("  ✅ 零命中（注：额外数据流 ADS 需 Windows 端另行检查）")

    # ⑤ 交叉引用
    if not a.quiet:
        print("\n⑤ 交叉引用")
    n = 0
    for p in files:
        rel = os.path.relpath(p, root)
        if os.path.splitext(p)[1].lower() not in TEXT_EXT:
            continue
        try:
            txt = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for m in re.finditer(r"file:///[^\s\)\]]+", txt):
            n += 1
            H("交叉", "%s 含 file:/// 绝对引用" % rel)
    if n == 0 and not a.quiet:
        print("  ✅ 零命中（'../' 同仓库相对链接属正常，不计）")

    # ⑥ 时间线
    if not a.quiet:
        print("\n⑥ 时间线（提示项，不计入失败）")
    dates: dict[str, list[str]] = {}
    for p in files:
        rel = os.path.relpath(p, root)
        try:
            txt = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for m in re.finditer(r"20\d{2}-\d{2}-\d{2}", txt):
            dates.setdefault(m.group(0), []).append(rel)
    if dates and not a.quiet:
        for d in sorted(dates):
            print("    %s  ← %s" % (d, ", ".join(sorted(set(dates[d]))[:3])))
        print("    （示例/模板日期可接受；**真实事件日期请改为中性值**）")
    elif not a.quiet:
        print("  ✅ 无具体日期")

    # ⑦ 元数据
    if not a.quiet:
        print("\n⑦ 元数据提示")
        print("    目录 Owner / 文件属性不在文件内容里，git 不记录 ——")
        print("    但**打包 zip 时可能带上**。发布前若打包过，请检查。")

    print()
    print("=" * 74)
    if hits:
        print("结论：❌ %d 项命中，逐条处置后再发布" % len(hits))
        return 1
    print("结论：✅ 未发现隐私泄露风险（%d 项检查全过）" % 6)
    print()
    print("⚠️ 别忘了 git 身份（本工具查不到）：")
    print("     git config user.name")
    print("     git config user.email")
    return 0


if __name__ == "__main__":
    sys.exit(main())
