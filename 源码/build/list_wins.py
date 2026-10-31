# -*- coding: utf-8 -*-
"""列出指定进程名拥有的窗口（不用 powershell，纯 ctypes）。

用法: python list_wins.py [关键字...]
"""
import ctypes, sys
from ctypes import wintypes as wt

u = ctypes.WinDLL("user32", use_last_error=True)
k = ctypes.WinDLL("kernel32", use_last_error=True)
u.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
u.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
u.GetClassNameW.restype = ctypes.c_int
u.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
u.GetWindowTextW.restype = ctypes.c_int
u.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM), wt.LPARAM]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                ("th32ProcessID", wt.DWORD), ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wt.DWORD), ("szExeFile", wt.WCHAR * 260)]


def procs():
    out = []
    k.CreateToolhelp32Snapshot.restype = wt.HANDLE
    h = k.CreateToolhelp32Snapshot(0x00000002, 0)
    if not h:
        return out
    pe = PROCESSENTRY32W()
    pe.dwSize = ctypes.sizeof(pe)
    if k.Process32FirstW(h, ctypes.byref(pe)):
        while True:
            out.append((int(pe.th32ProcessID), pe.szExeFile))
            if not k.Process32NextW(h, ctypes.byref(pe)):
                break
    k.CloseHandle(h)
    return out


keys = [a.lower() for a in (sys.argv[1:] or ["mumu", "maa", "bbchannel"])]
pids = {pid: name for pid, name in procs() if any(x in name.lower() for x in keys)}
rows = []
ENUM = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)


def cb(h, l):
    pid = wt.DWORD()
    u.GetWindowThreadProcessId(h, ctypes.byref(pid))
    if pid.value not in pids:
        return True
    cn = ctypes.create_unicode_buffer(256)
    u.GetClassNameW(h, cn, 256)
    n = u.GetWindowTextLengthW(h)
    b = ctypes.create_unicode_buffer(n + 2)
    u.GetWindowTextW(h, b, n + 2)
    r = wt.RECT()
    u.GetWindowRect(h, ctypes.byref(r))
    rows.append((pid.value, pids[pid.value], int(h) & 0xFFFFFFFF, cn.value, b.value,
                 bool(u.IsWindowVisible(h)), bool(u.IsIconic(h)),
                 r.right - r.left, r.bottom - r.top))
    return True


u.EnumWindows(ENUM(cb), 0)
if not rows:
    print("no window for", keys)
print("%-22s %-7s %-10s %-24s %-26s %-5s %-5s %s"
      % ("PROC", "PID", "HWND", "CLASS", "TITLE", "VIS", "ICON", "SIZE"))
for pid, pname, h, cls, title, vis, icon, w, hh in rows:
    print("%-22s %-7d %-10d %-24s %-26s %-5s %-5s %dx%d"
          % (pname, pid, h, cls[:24], (title or "(no title)")[:26], vis, icon, w, hh))
