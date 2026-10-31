# -*- coding: utf-8 -*-
"""列出指定进程的提权状态 / 完整性级别 / 父进程，用来判断 UAC 到底从哪来。

用法: python check_elev.py [关键字1 关键字2 ...]
"""
import ctypes, sys
from ctypes import wintypes

k32 = ctypes.windll.kernel32
adv = ctypes.windll.advapi32
ntd = ctypes.windll.ntdll

k32.OpenProcess.restype = wintypes.HANDLE
k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
adv.OpenProcessToken.restype = wintypes.BOOL
adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
adv.GetTokenInformation.restype = wintypes.BOOL
k32.GetCurrentProcess.restype = wintypes.HANDLE
k32.CloseHandle.restype = wintypes.BOOL
k32.CloseHandle.argtypes = [wintypes.HANDLE]

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TokenElevation = 20
TokenIntegrityLevel = 25
ERROR_ACCESS_DENIED = 5
ERROR_INVALID_PARAMETER = 87


class TOKEN_ELEVATION(ctypes.Structure):
    _fields_ = [("TokenIsElevated", wintypes.DWORD)]


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class TOKEN_MANDATORY_LABEL(ctypes.Structure):
    _fields_ = [("Label", SID_AND_ATTRIBUTES)]


def _snap():
    """返回 [(pid, name, ppid)] 的快照"""
    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Process32FirstW.restype = wintypes.BOOL
    k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32NextW.restype = wintypes.BOOL
    k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    out = []
    h = k32.CreateToolhelp32Snapshot(0x00000002, 0)
    if not h:
        return out
    pe = PROCESSENTRY32W()
    pe.dwSize = ctypes.sizeof(pe)
    if k32.Process32FirstW(h, ctypes.byref(pe)):
        while True:
            out.append((pe.th32ProcessID, pe.szExeFile, pe.th32ParentProcessID))
            if not k32.Process32NextW(h, ctypes.byref(pe)):
                break
    k32.CloseHandle(h)
    return out


def proc_info(pid):
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None, "OpenProcess fail %d" % ctypes.GetLastError()
    tok = wintypes.HANDLE()
    if not adv.OpenProcessToken(h, TOKEN_QUERY, ctypes.byref(tok)):
        k32.CloseHandle(h)
        return None, "OpenProcessToken fail %d" % ctypes.GetLastError()
    te = TOKEN_ELEVATION()
    sz = wintypes.DWORD(0)
    ok = adv.GetTokenInformation(tok, TokenElevation, ctypes.byref(te),
                                 ctypes.sizeof(te), ctypes.byref(sz))
    elevated = bool(te.TokenIsElevated) if ok else None
    # 完整性级别
    il = None
    buf = ctypes.create_string_buffer(64)
    ok2 = adv.GetTokenInformation(tok, TokenIntegrityLevel, buf, 64, ctypes.byref(sz))
    if ok2:
        p = ctypes.cast(buf, ctypes.POINTER(TOKEN_MANDATORY_LABEL))
        try:
            adv.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
            cnt = adv.GetSidSubAuthorityCount(p.contents.Label.Sid)[0]
            adv.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)
            il = adv.GetSidSubAuthority(p.contents.Label.Sid, cnt - 1)[0]
        except Exception:
            il = None
    k32.CloseHandle(tok)
    k32.CloseHandle(h)
    return (elevated, il), None


IL_NAME = {0x0000: "Untrusted", 0x1000: "Low", 0x2000: "Medium",
           0x2100: "MediumPlus", 0x3000: "High", 0x4000: "System"}


def main():
    keys = sys.argv[1:] or ["MuMu", "MAA", "BBchannel"]
    snap = {pid: (name, ppid) for pid, name, ppid in _snap()}
    rows = []
    for pid, (name, ppid) in sorted(snap.items()):
        if not any(k.lower() in name.lower() for k in keys):
            continue
        info, err = proc_info(pid)
        if info is None:
            rows.append((pid, name, ppid, "?", err))
        else:
            elev, il = info
            rows.append((pid, name, ppid,
                         "YES" if elev else "no",
                         "%s(0x%x)" % (IL_NAME.get(il, "?"), il if il is not None else -1)))
    print("%-24s %7s %-24s %-5s %s" % ("NAME", "PID", "PARENT", "ELEV", "INTEGRITY"))
    for pid, name, ppid, elev, extra in rows:
        pinfo = snap.get(ppid, ("?", 0))
        print("%-24s %7d %-24s %-5s %s" % (name, pid, "%s(%d)" % (pinfo[0], ppid), elev, extra))
    if not rows:
        print("(no process matched %s)" % keys)


if __name__ == "__main__":
    main()
