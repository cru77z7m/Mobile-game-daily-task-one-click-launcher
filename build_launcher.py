# -*- coding: utf-8 -*-
"""一键重新打包 一键日常启动器.exe

在 skill 目录里改不了东西也能用：把 --src 指到工程目录即可。
默认按本机工程 D:\\tools\\一键日常启动器 走。

用法:
    python build_launcher.py                    # 用默认工程目录
    python build_launcher.py --src D:\\xxx      # 指定工程目录（里面要有 源码\\daily_launcher.py）
    python build_launcher.py --assets           # 顺手把 skill 里的图标复制进 build/

要点（都是踩过的）：
  * --manifest 不能省，否则窗口被系统按 96DPI 放大、字全糊
  * 打包必须在工程根目录跑，--icon/--manifest 用绝对路径
  * onefile + noconsole 出来的是单文件 exe，双击即用
"""
import argparse
import os
import shutil
import subprocess
import sys

DEFAULT_SRC = r"D:\tools\一键日常启动器"
EXE_NAME = "一键日常启动器"
PY_NAME = "daily_launcher.py"
ICON_NAME = "app.ico"
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_python():
    """优先用本机的托管 Python（已装 pyinstaller/pillow）"""
    cands = [
        r"C:\Users\Cru77z7M\.workbuddy\binaries\python\versions\3.13.12\python.exe",
    ]
    for c in cands:
        if os.path.isfile(c):
            return c
    return sys.executable


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--assets", action="store_true",
                    help="把 skill/assets 下的图标复制到 源码\\build")
    ap.add_argument("--keep-work", action="store_true")
    a = ap.parse_args()

    src = os.path.abspath(a.src)
    py_file = os.path.join(src, "源码", PY_NAME)
    if not os.path.isfile(py_file):
        sys.exit("找不到主程序: %s" % py_file)

    build_dir = os.path.join(src, "源码", "build")
    if a.assets:
        for n in ("icon_257.png", ICON_NAME):
            s = os.path.join(SKILL_DIR, "assets", n)
            if os.path.isfile(s):
                shutil.copy2(s, os.path.join(build_dir, n))
                print("复制资源:", n)

    py = find_python()
    icon = os.path.join(build_dir, ICON_NAME)
    manifest = os.path.join(build_dir, "app.manifest")
    if not os.path.isfile(icon):
        sys.exit("缺少图标: %s（先跑 make_icon_head.py 或加 --assets）" % icon)

    dist = os.path.join(src, "dist")
    work = os.path.join(src, "build_tmp")
    shutil.rmtree(dist, ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)

    cmd = [
        py, "-m", "PyInstaller", "--noconfirm", "--onefile", "--noconsole",
        "--name", EXE_NAME,
        "--icon", icon,
        "--manifest", manifest,
        "--distpath", dist,
        "--workpath", os.path.join(work, "work"),
        "--specpath", work,
        "--optimize", "2",      # 去掉 docstring/assert，PYZ 小一点、导入快一点
    ]
    # onefile 每次启动都要把整包解压到 %TEMP%，包越小启动越快。
    # 这里排掉程序根本用不到的模块；其中 ssl/_ssl/_hashlib 最关键——
    # 它们会把 libcrypto(8MB) + libssl(1.6MB) 拖进来，光解压就两三百毫秒。
    # 网络部分已改用系统自带的 WinHTTP（见 daily_launcher.py 里 _http_open）。
    for mod in ("ssl", "_ssl", "_hashlib", "email", "http", "urllib",
                "xml", "xmlrpc", "sqlite3", "_sqlite3", "decimal",
                "bz2", "lzma", "unittest", "doctest", "pydoc_data",
                "asyncio", "multiprocessing", "lib2to3", "setuptools", "pip",
                "unicodedata", "pickle", "_pickle", "logging", "argparse"):
        cmd += ["--exclude-module", mod]
    # 界面图标（assets/icons/*.ico）必须一起打进去：
    # onefile 运行时解到 sys._MEIPASS，代码里 assets_dir() 会优先读那里。
    assets = os.path.join(src, "源码", "assets")
    if os.path.isdir(assets):
        cmd += ["--add-data", assets + os.pathsep + "assets"]
        print("打包资源:", assets)
    cmd.append(py_file)
    print("打包中…（约 30~60 秒）")
    r = subprocess.run(cmd, cwd=src, capture_output=True, text=True,
                       errors="replace")
    if r.returncode != 0:
        print(r.stdout[-3000:])
        print(r.stderr[-3000:])
        sys.exit("打包失败")

    out = os.path.join(dist, EXE_NAME + ".exe")
    dst = os.path.join(src, EXE_NAME + ".exe")
    shutil.copy2(out, dst)
    size = os.path.getsize(dst) / 1024.0 / 1024.0
    print("完成: %s  %.2f MB" % (dst, size))

    if not a.keep_work:
        shutil.rmtree(dist, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)
    print("提示: 换过 manifest 仍发虚就把 exe 改个名字（Windows 按路径缓存激活上下文）")


if __name__ == "__main__":
    main()
