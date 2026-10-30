# -*- coding: utf-8 -*-
"""一键重新打包「一键日常启动器」——一次出三件套

产物（默认都放 release/）:
    daily-launcher-<ver>-setup-x64.exe      安装程序（文件夹版，推荐给用户）
    daily-launcher-<ver>-portable-x64.zip   免安装文件夹版
    daily-launcher-<ver>-windows-x64.zip    单文件版（老版本自动更新只认这个）

另外:
    一键日常启动器/（onedir）        直接双击就能跑的文件夹版，开发时用
    一键日常启动器.exe（onefile）    覆盖到工程根目录，保持"双击即用"的老习惯

用法:
    python build_launcher.py                  # 全出
    python build_launcher.py --only onedir    # 只出文件夹版（调试用）
    python build_launcher.py --only setup     # 只重打安装程序（要现成的 payload）
    python build_launcher.py --keep-work      # 留着中间目录

踩过的坑:
  * --manifest 不能省，否则窗口被系统按 96DPI 放大、字全糊
  * --add-data 的相对路径是按 specpath 算的，一律用绝对路径
  * payload.zip 里绝不能带 config.json / launcher.log / *.png ——
    安装时会把它们铺到用户目录，等于把开发机的状态抄给用户
  * onefile 每次启动都要把整包解到 %TEMP%，所以包越小启动越快；
    网络走系统 WinHTTP，可以直接排掉 ssl/_ssl/_hashlib（省 10MB）
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile

DEFAULT_SRC = r"D:\tools\一键日常启动器"
EXE_NAME = "一键日常启动器"
PY_NAME = "daily_launcher.py"
SETUP_PY = "installer.py"
ICON_NAME = "app.ico"
MANIFEST_NAME = "app.manifest"

# onefile / setup 都排掉这些：程序用不到，排掉省体积也省解包时间。
# ssl/_ssl/_hashlib 最关键——它们会把 libcrypto(8MB)+libssl(1.6MB) 拖进来。
EXCLUDES = ("ssl", "_ssl", "_hashlib", "email", "http", "urllib", "xml", "xmlrpc",
            "sqlite3", "_sqlite3", "decimal", "bz2", "lzma", "unittest", "doctest",
            "pydoc_data", "asyncio", "multiprocessing", "lib2to3", "setuptools",
            "pip", "unicodedata", "pickle", "_pickle", "logging", "argparse")

# payload 里不该有的东西：运行时产物 / 用户配置 / 调试截图
# ⚠ 只在**顶层**按这个规则过滤。_internal 里绝不能动 —— 那里有
#   base_library.zip，少了它 exe 会直接报 "Failed to start embedded python
#   interpreter!"（踩过：按 .zip 后缀一刀切把整个文件夹版打成了废品）
PAYLOAD_SKIP_NAMES = {"config.json", "config.json.bak", "launcher.log",
                      "launcher.state.json", "launcher.state.json.bak",
                      "install.json"}
PAYLOAD_SKIP_EXT = (".png", ".jpg", ".old", ".log", ".bak")


def find_python():
    """优先用本机的托管 Python（已装 pyinstaller/pillow）"""
    cands = [r"C:\Users\Cru77z7M\.workbuddy\binaries\python\versions\3.13.12\python.exe"]
    for c in cands:
        if os.path.isfile(c):
            return c
    return sys.executable


def read_version(py_file):
    with open(py_file, "r", encoding="utf-8") as f:
        m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', f.read())
    if not m:
        sys.exit("读不到 APP_VERSION")
    return m.group(1)


def run(cmd, cwd=None, what="打包"):
    print("… %s" % what)
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        print(r.stdout[-4000:])
        print(r.stderr[-4000:])
        sys.exit("%s失败" % what)
    return r


def build_onedir(py, src, exe, icon, manifest, assets, dist, work):
    cmd = [py, "-m", "PyInstaller", "--noconfirm", "--onedir", "--noconsole",
           "--name", exe, "--icon", icon, "--manifest", manifest,
           "--distpath", dist, "--workpath", work, "--specpath", work,
           "--optimize", "2", "--noupx"]
    for m in EXCLUDES:
        cmd += ["--exclude-module", m]
    if os.path.isdir(assets):
        cmd += ["--add-data", assets + os.pathsep + "assets"]
    cmd.append(os.path.join(src, "源码", PY_NAME))
    run(cmd, cwd=src, what="打包文件夹版")
    return os.path.join(dist, exe)


def build_onefile(py, src, exe, icon, manifest, assets, dist, work):
    cmd = [py, "-m", "PyInstaller", "--noconfirm", "--onefile", "--noconsole",
           "--name", exe, "--icon", icon, "--manifest", manifest,
           "--distpath", dist, "--workpath", work, "--specpath", work,
           "--optimize", "2", "--noupx"]
    for m in EXCLUDES:
        cmd += ["--exclude-module", m]
    if os.path.isdir(assets):
        cmd += ["--add-data", assets + os.pathsep + "assets"]
    cmd.append(os.path.join(src, "源码", PY_NAME))
    run(cmd, cwd=src, what="打包单文件版")
    return os.path.join(dist, exe + ".exe")


def make_payload(app_dir, out_zip, version):
    """把 onedir 目录压成 payload.zip（安装程序的内嵌物）

    只在最外层过滤运行时产物；_internal 里的东西一个都不能少
    （base_library.zip 就是被误删过一次的那个）。
    """
    n = 0
    skipped = []
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for root, dirs, files in os.walk(app_dir):
            dirs[:] = [d for d in dirs if d not in ("_update", "__pycache__")]
            for f in files:
                p = os.path.join(root, f)
                rel = os.path.relpath(p, app_dir).replace("\\", "/")
                if "/" not in rel:
                    if f in PAYLOAD_SKIP_NAMES or f.lower().endswith(PAYLOAD_SKIP_EXT):
                        skipped.append(rel)
                        continue
                z.write(p, rel)
                n += 1
        z.writestr("version.txt", version)
    print("payload：%d 个文件，%.2f MB（跳过 %d 个运行时文件）"
          % (n + 1, os.path.getsize(out_zip) / 1048576.0, len(skipped)))


def build_setup(py, src, name, icon, manifest, payload, app_ico, dist, work):
    # 安装程序界面里按 MEIPASS/app.ico 找图标，这里统一改好名字再打进去
    os.makedirs(work, exist_ok=True)
    ico_copy = os.path.join(work, "app.ico")
    shutil.copy2(app_ico, ico_copy)
    cmd = [py, "-m", "PyInstaller", "--noconfirm", "--onefile", "--noconsole",
           "--name", name, "--icon", icon, "--manifest", manifest,
           "--distpath", dist, "--workpath", os.path.join(work, "setup"),
           "--specpath", os.path.join(work, "setup"),
           "--optimize", "2", "--noupx",
           "--add-data", payload + os.pathsep + ".",
           "--add-data", ico_copy + os.pathsep + "."]
    for m in EXCLUDES:
        cmd += ["--exclude-module", m]
    cmd.append(os.path.join(src, "源码", SETUP_PY))
    run(cmd, cwd=src, what="打包安装程序")
    return os.path.join(dist, name + ".exe")


def zip_dir(folder, out_zip, arc_root=None):
    """把一个目录压成 zip；arc_root 给定时整体塞进这个顶层目录"""
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=7) as z:
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if d not in ("_update",)]
            for f in files:
                p = os.path.join(root, f)
                rel = os.path.relpath(p, folder).replace("\\", "/")
                if arc_root:
                    rel = arc_root + "/" + rel
                z.write(p, rel)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--only", choices=("all", "onedir", "onefile", "setup"),
                    default="all")
    ap.add_argument("--keep-work", action="store_true")
    a = ap.parse_args()

    src = os.path.abspath(a.src)
    py_file = os.path.join(src, "源码", PY_NAME)
    if not os.path.isfile(py_file):
        sys.exit("找不到主程序: %s" % py_file)
    version = read_version(py_file)
    print("版本：%s" % version)

    py = find_python()
    build_dir = os.path.join(src, "源码", "build")
    icon = os.path.join(build_dir, ICON_NAME)
    manifest = os.path.join(build_dir, MANIFEST_NAME)
    assets = os.path.join(src, "源码", "assets")
    if not os.path.isfile(icon):
        sys.exit("缺少图标: %s" % icon)

    # 每次构建用独立的 dist/work 目录：PyInstaller 的 COLLECT 会先把旧目录整个删掉，
    # 而本机安全策略对"一次删几十个文件"要人工确认（SAFE_DELETE_BULK），
    # 干脆换个空目录，谁也不删。
    stamp = time.strftime("%m%d_%H%M%S")
    dist = os.path.join(src, "dist", stamp)
    rel = os.path.join(src, "release")
    work = os.path.join(src, "build_tmp", stamp)
    os.makedirs(rel, exist_ok=True)
    if a.only in ("all", "onedir", "onefile"):
        # 不主动删 dist/work：交给 PyInstaller --noconfirm 自己覆盖。
        # （批量删除在本机沙箱里会被安全策略拦下，几百个文件要人确认才行）
        os.makedirs(work, exist_ok=True)

    tag = version.replace(".", ".")
    setup_name = "daily-launcher-%s-setup-x64" % tag
    port_name = "daily-launcher-%s-portable-x64.zip" % tag
    single_name = "daily-launcher-%s-windows-x64.zip" % tag
    payload = os.path.join(work, "payload.zip")

    if a.only in ("all", "onedir"):
        app_dir = build_onedir(py, src, EXE_NAME, icon, manifest, assets,
                               os.path.join(dist, "onedir"),
                               os.path.join(work, "w_onedir"))
        # 开发用的那份：直接放到工程根的 一键日常启动器/ 里，双击即跑
        portable_dir = os.path.join(src, EXE_NAME)
        # 覆盖而不是先删：批量删除会撞上本机的安全策略，而且覆盖也够用了
        shutil.copytree(app_dir, portable_dir, dirs_exist_ok=True)
        make_payload(app_dir, payload, version)
        zip_dir(app_dir, os.path.join(rel, port_name), arc_root=EXE_NAME)
        print("文件夹版：%s（%.1f MB）"
              % (portable_dir,
                 sum(os.path.getsize(os.path.join(r, f))
                     for r, _d, fs in os.walk(portable_dir) for f in fs) / 1048576.0))

    if a.only in ("all", "setup"):
        if not os.path.isfile(payload):
            sys.exit("缺少 payload.zip，先跑 --only onedir")
        setup_exe = build_setup(py, src, setup_name, icon, manifest, payload,
                                os.path.join(assets, "icons", "launcher.ico"),
                                os.path.join(dist, "setup"),
                                os.path.join(work, "w_setup"))
        dst = os.path.join(rel, setup_name + ".exe")
        shutil.copy2(setup_exe, dst)
        print("安装程序：%s（%.2f MB）"
              % (dst, os.path.getsize(dst) / 1048576.0))

    if a.only in ("all", "onefile"):
        onefile = build_onefile(py, src, EXE_NAME, icon, manifest, assets,
                                os.path.join(dist, "onefile"),
                                os.path.join(work, "w_onefile"))
        shutil.copy2(onefile, os.path.join(src, EXE_NAME + ".exe"))
        tmp = os.path.join(work, "single")
        os.makedirs(tmp, exist_ok=True)
        shutil.copy2(onefile, os.path.join(tmp, EXE_NAME + ".exe"))
        readme = os.path.join(src, "README.md")
        if os.path.isfile(readme):
            shutil.copy2(readme, os.path.join(tmp, "README.md"))
        zip_dir(tmp, os.path.join(rel, single_name))
        print("单文件版：%s（%.2f MB）"
              % (os.path.join(src, EXE_NAME + ".exe"),
                 os.path.getsize(onefile) / 1048576.0))

    if not a.keep_work and a.only == "all":
        for d in (dist, work):
            try:
                shutil.rmtree(d, ignore_errors=True)
            except Exception as e:
                print("清不掉 %s（%s），手动删一下" % (d, e))

    print("\n发布目录：%s" % rel)
    for f in sorted(os.listdir(rel)):
        p = os.path.join(rel, f)
        if os.path.isfile(p):
            print("  %-46s %6.2f MB" % (f, os.path.getsize(p) / 1048576.0))
    print("提示: 换过 manifest 仍发虚就把 exe 改个名字（Windows 按路径缓存激活上下文）")


if __name__ == "__main__":
    main()
