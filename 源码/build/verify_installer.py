# -*- coding: utf-8 -*-
"""安装程序回归检查：能装上、锁住时说人话、写入失败会重试、只读占用能绕过去。

用例都直接调 Installer.run()，不经过窗口，也不碰真实注册表/快捷方式
（register_uninstall / make_shortcuts 在这里被替换成空操作，否则会把用户
真正的卸载项指向临时目录）。

跑法：
    python 源码/build/verify_installer.py
"""
import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "源码"))

import installer  # noqa: E402

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p,
                                 wt.DWORD, wt.DWORD, ctypes.c_void_p]
kernel32.CreateFileW.restype = wt.HANDLE
kernel32.CloseHandle.argtypes = [wt.HANDLE]

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
INVALID_HANDLE = ctypes.c_void_p(-1).value

FILES = {
    "一键日常启动器.exe": b"MZ fake exe " * 400,
    "_internal/python313.dll": b"fake dll " * 900,
    "_internal/base_library.zip": b"PK fake zip " * 200,
    "version.txt": b"v9.9.9\n",
}


def make_payload(path):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in FILES.items():
            z.writestr(name, data)


def snapshot(directory):
    out = {}
    for base, _dirs, names in os.walk(directory):
        for n in names:
            p = Path(base) / n
            out[(Path(base) / n).relative_to(directory).as_posix()] = \
                hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def lock_file(path):
    """用独占句柄锁住文件（模拟"程序正在运行"）。"""
    h = kernel32.CreateFileW(str(path), GENERIC_READ | GENERIC_WRITE, 0, None,
                             OPEN_EXISTING, 0x80, None)
    if h == INVALID_HANDLE:
        raise OSError("CreateFileW 失败：%d" % ctypes.get_last_error())
    return h


def share_read_delete(path):
    """以「只读 + 允许删除」打开文件。

    复刻 v2.18.0 踩到的那类句柄（杀软扫盘、游戏启动器扫描、云盘同步）：
    FILE_SHARE_READ | FILE_SHARE_DELETE，但不共享写。
    → open(path, 'r+b') 报 PermissionError，改名却可以。
    """
    h = kernel32.CreateFileW(str(path), GENERIC_READ,
                             0x1 | 0x4, None, OPEN_EXISTING, 0x80, None)
    if h == INVALID_HANDLE:
        raise OSError("CreateFileW 失败：%d" % ctypes.get_last_error())
    return h


def run_installer(target, log):
    installer.PAYLOAD = str(PAYLOAD)
    installer.LOG_PATH = str(log)
    inst = installer.Installer(str(target), want_shortcut=False, want_run=False)
    inst.run()
    return inst


fails = 0


def check(ok, label, extra=""):
    global fails
    fails += 0 if ok else 1
    print("%s %-22s %s" % ("PASS" if ok else "FAIL", label, extra))


tmp = Path(tempfile.mkdtemp(prefix="verify-inst-"))
PAYLOAD = tmp / "payload.zip"
make_payload(PAYLOAD)

# 别把用户真正的卸载项/快捷方式指向临时目录
installer.register_uninstall = lambda *a, **k: None
installer.make_shortcuts = lambda *a, **k: []
installer._fail_box = lambda *a, **k: None

try:
    # ---- 1) 干净安装 ----
    t1 = tmp / "app1"
    inst = run_installer(t1, tmp / "a.log")
    want = {k: hashlib.sha256(v).hexdigest() for k, v in FILES.items()
            if k != "version.txt"}
    got = {k: v for k, v in snapshot(t1).items() if k != "install.json"}
    meta = json.loads((t1 / "install.json").read_text(encoding="utf-8"))
    ok = (inst.done and not inst.error and got == want
          and meta["version"] == "v9.9.9" and "version.txt" not in got)
    check(ok, "干净安装", "%d 个文件，install.json=%s" % (len(got), meta["version"]))
    if not ok:
        print("   error=%r 文件数=%d 期望=%d" % (inst.error, len(got), len(want)))

    # ---- 2) 文件被占用：报人话，且一个文件都不动 ----
    t2 = tmp / "app2"
    run_installer(t2, tmp / "b1.log")
    (t2 / "version.txt").write_text("v0.0.0\n", encoding="utf-8")
    before = snapshot(t2)
    h = lock_file(t2 / "_internal/python313.dll")
    try:
        inst = run_installer(t2, tmp / "b2.log")
    finally:
        kernel32.CloseHandle(h)
    after = snapshot(t2)
    ok = (inst.error and "请先退出" in inst.error and before == after)
    check(ok, "占用时提前拦下", "error=%r 目录未改动=%s" % (inst.error, before == after))

    # ---- 3) 写入中途失败：重试后成功 ----
    t3 = tmp / "app3"
    real = installer.shutil.copyfileobj
    calls = {"n": 0}

    def flaky(src, dst, *a, **k):
        calls["n"] += 1
        if calls["n"] <= 2:                       # 前两次装成被占用
            raise PermissionError(13, "The process cannot access the file",
                                  str(getattr(dst, "name", "")))
        return real(src, dst, *a, **k)

    installer.shutil.copyfileobj = flaky
    installer.FILE_RETRY_DELAY = 0.01
    try:
        inst = run_installer(t3, tmp / "c.log")
    finally:
        installer.shutil.copyfileobj = real
        installer.FILE_RETRY_DELAY = 0.15
    # 3 个文件各写一次 = 3 次调用，前两次失败各多试一次 → 5 次
    want_calls = (len(FILES) - 1) + 2
    ok = inst.done and not inst.error and calls["n"] == want_calls
    check(ok, "写入失败重试", "调用 %d 次（2 次失败后成功，应为 %d）"
          % (calls["n"], want_calls))

    # ---- 4) 一直失败：报人话，且不写 install.json ----
    t4 = tmp / "app4"
    calls["n"] = 0

    def always_fail(src, dst, *a, **k):
        calls["n"] += 1
        raise PermissionError(32, "The process cannot access the file",
                              str(getattr(dst, "name", "")))

    installer.shutil.copyfileobj = always_fail
    installer.FILE_RETRY_DELAY = 0.01
    try:
        inst = run_installer(t4, tmp / "d.log")
    finally:
        installer.shutil.copyfileobj = real
        installer.FILE_RETRY_DELAY = 0.15
    meta_absent = not (t4 / "install.json").exists()
    # 每个文件：FILE_TRIES 次重试 + 1 次"改名挪开后重写"（文件存在且挪得动时会多试一次）
    want_calls = (len(FILES) - 1) * (installer.FILE_TRIES + 1)
    ok = (inst.error and "重试" in inst.error and meta_absent
          and calls["n"] == want_calls)
    check(ok, "彻底失败不写标记",
          "error=%r install.json 不存在=%s 尝试 %d 次"
          % (inst.error, meta_absent, calls["n"]))
    # ---- 5) 只读+允许删除的占用：不该拦人，改名挪开后照常装 ----
    #     v2.18.0 的真实事故：_internal/VCRUNTIME140.dll 被别的程序以这种句柄打开，
    #     写不进去但能改名，旧逻辑直接报「请先退出正在运行的程序」——用户被误导。
    t5 = tmp / "app5"
    run_installer(t5, tmp / "e1.log")
    (t5 / "version.txt").write_text("v0.0.0\n", encoding="utf-8")
    h = share_read_delete(t5 / "_internal/python313.dll")
    try:
        inst = run_installer(t5, tmp / "e2.log")
    finally:
        kernel32.CloseHandle(h)
    new_hash = hashlib.sha256((t5 / "_internal/python313.dll").read_bytes()).hexdigest()
    leftovers = [p.name for p in t5.rglob("*.setup-old*")]
    log_text = (tmp / "e2.log").read_text(encoding="utf-8", errors="replace")
    ok = (inst.done and not inst.error
          and new_hash == hashlib.sha256(FILES["_internal/python313.dll"]).hexdigest()
          and not leftovers
          and "改名挪开" in log_text)
    check(ok, "只读占用可绕过",
          "error=%r 内容已更新=%s 残留=%r"
          % (inst.error, new_hash == hashlib.sha256(
              FILES["_internal/python313.dll"]).hexdigest(), leftovers))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n%d 项检查，%d 项失败" % (5, fails))
sys.exit(1 if fails else 0)
