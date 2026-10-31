# -*- coding: utf-8 -*-
"""一键日常启动器 —— 安装程序（文件夹版专用）

为什么要有它：
    文件夹版（onedir）启动不用解包，双击就是秒开；代价是一堆文件，不能像
    单文件版那样"拖个 exe 就完事"。所以给它配一个安装程序：铺文件、建快捷方式、
    在「应用和功能」里登记，将来升级/卸载都走它。

它做四件事：
    1. 把内嵌的 payload.zip（就是 onedir 那一整个文件夹）铺到安装目录
    2. 建桌面/开始菜单快捷方式（IShellLink，不依赖 PowerShell）
    3. 在 HKCU 写卸载登记项（不需要管理员权限）
    4. 升级安装时不动 config.json —— 用户的路径和勾选全保住

出错时：
    动手之前先体检（目标目录能写、要覆盖的文件没被占用），有问题当场说清楚
    "请先退出程序"，目录保持原样；铺文件时单个文件失败也会重试 3 次。
    以前是直接报 `PermissionError: [WinError 32] VCRUNTIME140.dll` 并撒手，
    留下一个新旧混杂、install.json 还写着旧版本的目录 —— 比没装更糟。

用法：
    双击                      图形界面安装
    /S                        静默安装（默认装到上次的目录，没有就用默认目录）
    /D=<目录>                 指定安装目录（必须写在最后也能认，这里不挑位置）
    /WAITPID=<pid>            等这个进程退出再动文件（程序内自动更新用）
    /RESTART                  装完把程序拉起来
    /NOSHORTCUT               不建快捷方式
    /LOG=<路径>               指定日志文件

注意 /D= 后面**不要加引号**（沿用 Inno Setup 的约定，程序内也按这个解析），
路径里有空格没关系，参数会原样取到行尾。
"""

import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile

# ----------------------------------------------------------------------------
# 常量 / 路径
# ----------------------------------------------------------------------------
APP_NAME = "一键日常启动器"
APP_PUBLISHER = "Cru77z7M"
APP_URL = ("https://github.com/cru77z7m/"
           "Mobile-game-daily-task-one-click-launcher")
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\DailyLauncher"
EXE_NAME = APP_NAME + ".exe"

IS_FROZEN = bool(getattr(sys, "frozen", False))
HERE = os.path.dirname(os.path.abspath(sys.executable if IS_FROZEN else __file__))
MEIPASS = getattr(sys, "_MEIPASS", HERE)
PAYLOAD = os.path.join(MEIPASS, "payload.zip")

LOG_PATH = os.path.join(os.environ.get("TEMP") or HERE, "daily-launcher-setup.log")

# 单个文件写不进去时的重试次数与间隔。杀毒软件、搜索索引、资源管理器预览
# 都会在文件刚被关掉的瞬间短暂持有句柄，等一下再来基本就过了。
FILE_TRIES = 3
FILE_RETRY_DELAY = 0.15


def log(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    try:
        if sys.stdout:
            print(line)
    except Exception:
        pass


# ----------------------------------------------------------------------------
# Win32
# ----------------------------------------------------------------------------
user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
ole32 = ctypes.WinDLL("ole32", use_last_error=True)

for _n, _t in (("HICON", wt.HANDLE), ("HBRUSH", wt.HANDLE), ("HPEN", wt.HANDLE),
               ("HFONT", wt.HANDLE), ("HDC", wt.HANDLE), ("HWND", wt.HANDLE),
               ("HINSTANCE", wt.HANDLE), ("HMENU", wt.HANDLE), ("HBITMAP", wt.HANDLE),
               ("HRGN", wt.HANDLE)):
    if not hasattr(wt, _n):
        setattr(wt, _n, _t)

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, ctypes.c_uint,
                             wt.WPARAM, wt.LPARAM)
CS_HREDRAW, CS_VREDRAW, CS_DBLCLKS = 0x0002, 0x0001, 0x0008
WS_OVERLAPPED, WS_CAPTION, WS_SYSMENU, WS_MINIMIZEBOX = 0x00000000, 0x00C00000, 0x00080000, 0x00020000
WS_CLIPCHILDREN, WS_CLIPSIBLINGS = 0x02000000, 0x04000000
WS_EX_APPWINDOW = 0x00040000
CW_USEDEFAULT = -2147483648
SW_SHOW, SW_SHOWNORMAL = 5, 1
WM_DESTROY, WM_CLOSE, WM_PAINT, WM_ERASEBKGND = 0x0002, 0x0010, 0x000F, 0x0014
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0200, 0x0201, 0x0202
WM_SETCURSOR, WM_KEYDOWN, WM_APP, WM_TIMER = 0x0020, 0x0100, 0x8000, 0x0113
DT_LEFT, DT_CENTER, DT_RIGHT = 0x0000, 0x0001, 0x0002
DT_VCENTER, DT_SINGLELINE, DT_END_ELLIPSIS = 0x0004, 0x0020, 0x8000
DT_NOPREFIX, DT_WORDBREAK = 0x0800, 0x0010
TRANSPARENT, PS_SOLID, NULL_BRUSH = 1, 0, 4
DEFAULT_CHARSET, CLEARTYPE_QUALITY = 1, 5

user32.CreateWindowExW.restype = wt.HWND
user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wt.HWND, wt.HMENU, wt.HINSTANCE, ctypes.c_void_p]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
user32.BeginPaint.restype = wt.HDC
user32.EndPaint.argtypes = [wt.HWND, ctypes.c_void_p]
user32.GetDC.restype = wt.HDC
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
user32.LoadImageW.restype = wt.HANDLE
user32.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int,
                              ctypes.c_int, wt.UINT]
user32.LoadCursorW.restype = wt.HANDLE
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.SendMessageW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
user32.SetTimer.restype = ctypes.c_size_t
user32.SetTimer.argtypes = [wt.HWND, ctypes.c_size_t, wt.UINT, ctypes.c_void_p]
user32.KillTimer.argtypes = [wt.HWND, ctypes.c_size_t]
user32.SetCapture.restype = wt.HWND
user32.MessageBoxW.restype = ctypes.c_int
user32.MessageBoxW.argtypes = [wt.HWND, wt.LPCWSTR, wt.LPCWSTR, wt.UINT]
user32.DrawTextW.restype = ctypes.c_int
user32.DrawTextW.argtypes = [wt.HDC, wt.LPCWSTR, ctypes.c_int, ctypes.c_void_p, wt.UINT]
user32.FillRect.argtypes = [wt.HDC, ctypes.c_void_p, wt.HBRUSH]
user32.FillRect.restype = ctypes.c_int
user32.SystemParametersInfoW.argtypes = [wt.UINT, wt.UINT, ctypes.c_void_p, wt.UINT]
user32.SetProcessDPIAware.restype = wt.BOOL
user32.GetDC.restype = wt.HDC
user32.GetDpiForSystem.restype = ctypes.c_uint
gdi32.CreateFontW.restype = wt.HFONT
gdi32.CreateFontW.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD,
                              wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD, wt.LPCWSTR]
gdi32.CreateSolidBrush.restype = wt.HBRUSH
gdi32.CreateSolidBrush.argtypes = [wt.DWORD]
gdi32.CreatePen.restype = wt.HPEN
gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wt.DWORD]
gdi32.SelectObject.restype = wt.HANDLE
gdi32.SelectObject.argtypes = [wt.HDC, wt.HANDLE]
gdi32.DeleteObject.argtypes = [wt.HANDLE]
gdi32.SetTextColor.argtypes = [wt.HDC, wt.DWORD]
gdi32.SetBkMode.argtypes = [wt.HDC, ctypes.c_int]
gdi32.RoundRect.restype = wt.BOOL
gdi32.RoundRect.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                            ctypes.c_int, ctypes.c_int, ctypes.c_int]
gdi32.CreateRoundRectRgn.restype = wt.HRGN
gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
gdi32.GetDeviceCaps.argtypes = [wt.HDC, ctypes.c_int]
shell32.ShellExecuteW.restype = ctypes.c_ssize_t
shell32.ShellExecuteW.argtypes = [wt.HWND, wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR,
                                  wt.LPCWSTR, ctypes.c_int]

WM_CLOSE_ = WM_CLOSE


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("style", wt.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH),
                ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR),
                ("hIconSm", wt.HICON)]


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [("hdc", wt.HDC), ("fErase", wt.BOOL), ("rcPaint", wt.RECT),
                ("fRestore", wt.BOOL), ("fIncUpdate", wt.BOOL),
                ("rgbReserved", ctypes.c_byte * 32)]


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def rgb(hexcolor):
    h = hexcolor.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return r | (g << 8) | (b << 16)


RAINBOW = {
    "bg": "#F4F6F9", "card": "#FFFFFF", "border": "#E4E8EE",
    "text": "#1B1F26", "text2": "#5A6373", "muted": "#98A1B0",
    "accent": "#2F6BFF", "accent_d": "#245BE0", "accent_l": "#EAF0FF",
    "ok": "#17B26A", "err": "#F04438",
    "ghost_bg": "#FFFFFF", "ghost_bg_h": "#F2F4F8",
    "track": "#EDF0F5", "line": "#F0F2F6",
}
C = {k: rgb(v) for k, v in RAINBOW.items()}


# ----------------------------------------------------------------------------
# 小工具
# ----------------------------------------------------------------------------
def payload_version():
    try:
        with zipfile.ZipFile(PAYLOAD) as z:
            return z.read("version.txt").decode("utf-8").strip()
    except Exception:
        return ""


def payload_bytes():
    try:
        with zipfile.ZipFile(PAYLOAD) as z:
            return sum(i.file_size for i in z.infolist())
    except Exception:
        return 0


def known_folder(csidl):
    buf = ctypes.create_unicode_buffer(260)
    shell32.SHGetFolderPathW.argtypes = [wt.HWND, ctypes.c_int, wt.HANDLE,
                                         wt.DWORD, wt.LPWSTR]
    if shell32.SHGetFolderPathW(None, csidl, None, 0, buf) == 0:
        return buf.value
    return ""


CSIDL_PROGRAMS = 0x0002
CSIDL_DESKTOPDIRECTORY = 0x0010


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def default_dir():
    """默认装哪儿：装过就装回原处（原地升级），没装过就 %LOCALAPPDATA%\\Programs\\名字"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            loc = str(winreg.QueryValueEx(k, "InstallLocation")[0] or "")
        if loc and os.path.isdir(loc):
            return loc
    except Exception:
        pass
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("USERPROFILE") or HERE
    return os.path.join(base, "Programs", APP_NAME)


def pid_alive(pid):
    """不建进程快照，直接 OpenProcess 查（安装程序里只需要知道死没死）"""
    if not pid:
        return False
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return False
    try:
        code = wt.DWORD()
        if kernel32.GetExitCodeProcess(h, ctypes.byref(code)):
            return code.value == 259      # STILL_ACTIVE
        return False
    finally:
        kernel32.CloseHandle(h)


kernel32.OpenProcess.restype = wt.HANDLE
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
kernel32.CloseHandle.argtypes = [wt.HANDLE]


# ----------------------------------------------------------------------------
# 快捷方式（IShellLink + IPersistFile，纯 ctypes，不依赖 PowerShell）
# ----------------------------------------------------------------------------
class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, s):
        s = s.strip("{}")
        a, b, c, d, e = s.split("-")
        g = cls()
        g.Data1 = int(a, 16)
        g.Data2 = int(b, 16)
        g.Data3 = int(c, 16)
        rest = bytes.fromhex(d + e)
        g.Data4 = (ctypes.c_ubyte * 8)(*rest)
        return g


CLSID_SHELLLINK = "00021401-0000-0000-C000-000000000046"
IID_ISHELLLINKW = "000214F9-0000-0000-C000-000000000046"
IID_IPERSISTFILE = "0000010B-0000-0000-C000-000000000046"


def _vtbl_call(ptr, index, restype, argtypes, *args):
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    fn = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtbl[index])
    return fn(ptr, *args)


def create_shortcut(lnk_path, target, workdir, desc="", icon=None):
    """建一个 .lnk。失败抛异常（调用方决定是提示还是忽略）"""
    ole32.CoInitialize(None)
    clsid = GUID.parse(CLSID_SHELLLINK)
    iid = GUID.parse(IID_ISHELLLINKW)
    p = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(ctypes.byref(clsid), None, 1,
                                ctypes.byref(iid), ctypes.byref(p))
    if hr != 0 or not p:
        raise OSError("CoCreateInstance 失败 hr=0x%08X" % (hr & 0xFFFFFFFF))
    try:
        # IShellLinkW：SetPath=20, SetWorkingDirectory=9, SetDescription=7, SetIconLocation=17
        _vtbl_call(p, 20, ctypes.c_long, [ctypes.c_wchar_p], target)
        _vtbl_call(p, 9, ctypes.c_long, [ctypes.c_wchar_p], workdir)
        if desc:
            _vtbl_call(p, 7, ctypes.c_long, [ctypes.c_wchar_p], desc)
        if icon:
            _vtbl_call(p, 17, ctypes.c_long, [ctypes.c_wchar_p, ctypes.c_int], icon, 0)
        iid_pf = GUID.parse(IID_IPERSISTFILE)
        pf = ctypes.c_void_p()
        hr = _vtbl_call(p, 0, ctypes.c_long,
                        [ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)],
                        ctypes.byref(iid_pf), ctypes.byref(pf))
        if hr != 0 or not pf:
            raise OSError("QueryInterface(IPersistFile) 失败 hr=0x%08X" % (hr & 0xFFFFFFFF))
        try:
            hr = _vtbl_call(pf, 6, ctypes.c_long, [ctypes.c_wchar_p, ctypes.c_int],
                            lnk_path, 1)
            if hr != 0:
                raise OSError("Save 失败 hr=0x%08X" % (hr & 0xFFFFFFFF))
        finally:
            _vtbl_call(pf, 2, ctypes.c_ulong, [])
    finally:
        _vtbl_call(p, 2, ctypes.c_ulong, [])


def make_shortcuts(target_dir, desktop=True, startmenu=True, desc=""):
    exe = os.path.join(target_dir, EXE_NAME)
    made = []
    jobs = []
    if desktop:
        jobs.append(known_folder(CSIDL_DESKTOPDIRECTORY))
    if startmenu:
        jobs.append(known_folder(CSIDL_PROGRAMS))
    for base in jobs:
        if not base:
            continue
        lnk = os.path.join(base, APP_NAME + ".lnk")
        try:
            create_shortcut(lnk, exe, target_dir, desc, exe)
            made.append(lnk)
        except Exception as e:
            log("建快捷方式失败 %s：%s" % (lnk, e))
    return made


# ----------------------------------------------------------------------------
# 卸载登记项
# ----------------------------------------------------------------------------
def register_uninstall(target_dir, version, size_bytes):
    import winreg
    exe = os.path.join(target_dir, EXE_NAME)
    sub = os.path.basename(target_dir.rstrip("\\"))
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0,
                                winreg.KEY_WRITE) as k:
            def put(name, value, kind=winreg.REG_SZ):
                winreg.SetValueEx(k, name, 0, kind, value)
            put("DisplayName", APP_NAME)
            put("DisplayVersion", version or "?")
            put("DisplayIcon", exe)
            put("Publisher", APP_PUBLISHER)
            put("InstallLocation", target_dir)
            put("InstallDate", time.strftime("%Y%m%d"))
            put("URLInfoAbout", APP_URL)
            put("UninstallString", '"%s" --uninstall' % exe)
            put("QuietUninstallString", '"%s" --uninstall' % exe)
            put("NoModify", 1, winreg.REG_DWORD)
            put("NoRepair", 1, winreg.REG_DWORD)
            put("EstimatedSize", max(1, int(size_bytes / 1024)), winreg.REG_DWORD)
            put("Comments", "手游日常一键启动器（文件夹版 · %s）" % sub)
        return True
    except Exception as e:
        log("写卸载登记项失败：%s" % e)
        return False


def unregister_uninstall():
    import winreg
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except Exception:
        pass


# ----------------------------------------------------------------------------
# 安装动作
# ----------------------------------------------------------------------------
class InstallError(Exception):
    """带「一句话说明」的安装错误。

    short 会显示在界面上，必须短到一眼能读完、并且能照做（例如「请先退出
    正在运行的程序」）；detail 只写日志，放具体哪个文件、Windows 原始错误。

    以前失败直接把 `PermissionError: [WinError 32] ...` 甩到界面上：用户看不懂，
    而且那时已经把一部分文件覆盖掉了 —— 目录里新旧混杂，install.json 还停在
    旧版本，比"没装"更糟。现在改为「先体检、再动文件」。
    """

    def __init__(self, short, detail=""):
        Exception.__init__(self, short)
        self.short = short
        self.detail = detail


def _why(e, path=""):
    """把 OSError 翻成人话（用于日志）。"""
    win = getattr(e, "winerror", None)
    if win in (32, 33):
        return "文件被占用（程序可能还在运行）"
    if win == 5:
        return "没有写入权限"
    if win == 112 or getattr(e, "errno", 0) == 28:
        return "磁盘空间不足"
    if isinstance(e, PermissionError):
        return "被占用或没有权限"
    if isinstance(e, NotADirectoryError):
        return "路径被同名文件挡住"
    return "%s: %s" % (type(e).__name__, e)


def _names(paths, limit=3):
    names = [os.path.basename(p) for p in paths[:limit]]
    return "、".join(names) + ("　等 %d 个" % len(paths) if len(paths) > limit else "")


class Installer(object):
    def __init__(self, target, want_shortcut=True, want_run=False, restart=False,
                 wait_pid=0):
        self.target = os.path.abspath(target)
        self.want_shortcut = want_shortcut
        self.want_run = want_run
        self.restart = restart
        self.wait_pid = wait_pid
        self.stage = "准备"
        self.pct = 0.0
        self.done = False
        self.error = ""
        self.thread = None
        self.cancel_request = False
        self.upgrade = os.path.isfile(os.path.join(self.target, "config.json"))
        self.version = payload_version()

    # ---- 主流程（在后台线程跑） ----
    def run(self):
        try:
            self._install()
        except InstallError as e:
            self.error = e.short
            log("安装失败：%s" % e.short)
            if e.detail:
                log("详情：\n%s" % e.detail)
        except Exception as e:
            self.error = "%s: %s" % (type(e).__name__, e)
            log("安装失败：%s" % self.error)

    def _wait_old(self):
        if not self.wait_pid:
            return
        self.stage = "等待旧进程退出"
        deadline = time.time() + 60
        while time.time() < deadline and pid_alive(self.wait_pid):
            time.sleep(0.2)
        time.sleep(0.4)                 # 单实例锁/文件句柄彻底松开
        log("旧进程 %s 已退出" % self.wait_pid)

    def _preflight(self, items):
        """不动任何文件，先确认这次装得进去。

        两件事必须提前查出来，否则会出现"铺到一半报错、目录里新旧混杂"：
          1. 安装目录能不能新建文件（ACL 保护、只读盘、路径被同名文件占）
          2. payload 要覆盖的每个已有文件能不能以写方式打开 —— 正在运行的
             程序会把 exe 和 _internal 下的 dll 映射成 image section，这时
             打开写入直接 PermissionError（典型现象：报 VCRUNTIME140.dll）。
        """
        self.stage = "检查安装目录"
        self.pct = 0
        probe = os.path.join(self.target, ".setup-write-test")
        try:
            with open(probe, "wb") as f:
                f.write(b"ok")
            os.remove(probe)
        except OSError as e:
            raise InstallError("安装目录不可写：%s" % _why(e, self.target),
                               "目录：%s\n%s" % (self.target, _why(e, self.target)))

        locked = []
        for item in items:
            if item.filename == "version.txt":
                continue
            dst = os.path.join(self.target, *item.filename.split("/"))
            if not os.path.isfile(dst):
                continue
            try:
                with open(dst, "r+b"):
                    pass
            except OSError as e:
                locked.append((dst, _why(e, dst)))
        if locked:
            raise InstallError(
                "请先退出正在运行的「%s」再装" % APP_NAME,
                "被占用的文件：\n" + "\n".join("  %s  <- %s" % (p, w)
                                              for p, w in locked[:12]))

    def _extract(self, z, items):
        """把 payload 铺到安装目录；单个文件失败会重试，最后才报错。"""
        total = max(1, len(items))
        failures = []
        for idx, item in enumerate(items):
            if self.cancel_request:
                raise InstallError("已取消安装")
            if item.filename == "version.txt":
                self.pct = (idx + 1) * 100.0 / total
                continue
            dst = os.path.join(self.target, *item.filename.split("/"))
            self.stage = "正在解压 %s" % os.path.basename(item.filename)
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
            except OSError as e:
                failures.append((dst, _why(e, dst)))
                self.pct = (idx + 1) * 100.0 / total
                continue
            last = None
            for attempt in range(FILE_TRIES):
                try:
                    with z.open(item) as src, open(dst, "wb") as out:
                        shutil.copyfileobj(src, out, 262144)
                    last = None
                    break
                except OSError as e:
                    last = e
                    if attempt + 1 < FILE_TRIES:
                        log("写入 %s 失败（%s），第 %d 次重试"
                            % (os.path.basename(dst), _why(e, dst), attempt + 2))
                        time.sleep(FILE_RETRY_DELAY * (attempt + 1))
            if last is not None:
                failures.append((dst, _why(last, dst)))
                log("写入失败：%s（%s）" % (dst, _why(last, dst)))
            self.pct = (idx + 1) * 100.0 / total
        if failures:
            raise InstallError(
                "%d 个文件没写进去，请退出程序后重试" % len(failures),
                "\n".join("  %s  <- %s" % (p, w) for p, w in failures[:12]))
        log("文件铺完（%d 个）" % len(items))

    def _install(self):
        log("开始安装：%s -> %s（升级=%s）"
            % (payload_version(), self.target, self.upgrade))
        self._wait_old()
        if not os.path.isfile(PAYLOAD):
            raise RuntimeError("安装包里的 payload.zip 不见了")
        os.makedirs(self.target, exist_ok=True)

        with zipfile.ZipFile(PAYLOAD) as z:
            items = [i for i in z.infolist() if not i.filename.endswith("/")]
            # 先体检：这一步只读，不碰任何文件。有问题就在这里停住，
            # 目录还是原样，用户关掉程序再装一次就行。
            self._preflight(items)
            self._extract(z, items)

        # 安装标记：程序里用它判断"这是装出来的"（卸载时会看）
        try:
            with open(os.path.join(self.target, "install.json"), "w",
                      encoding="utf-8") as f:
                json.dump({"version": self.version,
                           "installed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                           "installer": "setup"}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log("写 install.json 失败：%s" % e)

        self.stage = "创建快捷方式"
        self.pct = 97
        if self.want_shortcut:
            made = make_shortcuts(self.target, True, True,
                                  "一键跑完手游日常（文件夹版，秒开）")
            log("快捷方式：%s" % (made or "无"))
        self.stage = "登记卸载信息"
        register_uninstall(self.target, self.version, payload_bytes())
        self.pct = 100
        self.stage = "安装完成"
        self.done = True
        log("安装完成：%s" % self.target)
        if self.want_run or self.restart:
            self._launch()

    def _launch(self):
        exe = os.path.join(self.target, EXE_NAME)
        try:
            subprocess.Popen([exe], cwd=self.target, close_fds=True)
            log("已启动：%s" % exe)
        except Exception as e:
            log("启动失败：%s" % e)
            try:
                shell32.ShellExecuteW(None, "open", exe, None, self.target, SW_SHOWNORMAL)
            except Exception:
                pass


# ----------------------------------------------------------------------------
# 图形界面
# ----------------------------------------------------------------------------
class SetupUI(object):
    W, H = 560, 392

    def __init__(self, inst):
        self.inst = inst
        self.dpi = 96.0
        self.hwnd = None
        self.hover = None
        self.pressed = None
        self.hits = []
        self.quit = False
        self._fonts = {}
        self._wndproc = WNDPROC(self._proc)
        self.countdown = 0
        self.close_hint = ""
        self.want_shortcut = bool(inst.want_shortcut)
        self.want_run = bool(inst.want_run)

    # ---- 尺寸/绘制工具 ----
    def S(self, v):
        return int(round(v * self.dpi / 96.0))

    def font(self, size, bold=False):
        key = (size, bold)
        if key in self._fonts:
            return self._fonts[key]
        h = gdi32.CreateFontW(-int(round(size * self.dpi / 72.0)), 0, 0, 0,
                              700 if bold else 400, 0, 0, 0, DEFAULT_CHARSET,
                              0, 0, CLEARTYPE_QUALITY, 0, "Microsoft YaHei UI")
        self._fonts[key] = h
        return h

    def text(self, hdc, s, x, y, color, font, flags=0, box=None):
        gdi32.SelectObject(hdc, font)
        gdi32.SetTextColor(hdc, color)
        gdi32.SetBkMode(hdc, TRANSPARENT)
        if box:
            r = RECT(*[pt for pt in box])
            user32.DrawTextW(hdc, s, -1, ctypes.byref(r), flags)
        else:
            r = RECT(x, y, 4000, y + 40)
            user32.DrawTextW(hdc, s, -1, ctypes.byref(r), flags)

    def fill_round(self, hdc, rect, radius, fill, border=None, bw=1):
        x1, y1, x2, y2 = rect
        brush = gdi32.CreateSolidBrush(fill)
        if border:
            pen = gdi32.CreatePen(PS_SOLID, max(1, int(bw)), border)
        else:
            pen = gdi32.CreatePen(PS_SOLID, 1, fill)
        ob = gdi32.SelectObject(hdc, brush)
        op = gdi32.SelectObject(hdc, pen)
        gdi32.RoundRect(hdc, x1, y1, x2, y2, radius * 2, radius * 2)
        gdi32.SelectObject(hdc, ob)
        gdi32.SelectObject(hdc, op)
        gdi32.DeleteObject(brush)
        gdi32.DeleteObject(pen)

    def rect_fill(self, hdc, rect, color):
        brush = gdi32.CreateSolidBrush(color)
        r = RECT(*rect)
        user32.FillRect(hdc, ctypes.byref(r), brush)
        gdi32.DeleteObject(brush)

    def button(self, hdc, rect, label, key, kind="primary", enabled=True):
        x1, y1, x2, y2 = rect
        hot = self.hover == key and enabled
        if kind == "primary":
            fill = C["accent_d"] if (self.pressed == key and enabled) else (
                C["accent"] if not hot else rgb("#3D76FF"))
            fg, bd = rgb("#FFFFFF"), None
            if not enabled:
                fill, fg = rgb("#C7D3EE"), rgb("#FFFFFF")
        else:
            fill = C["ghost_bg_h"] if hot else C["ghost_bg"]
            fg, bd = C["text2"], C["border"]
        self.fill_round(hdc, rect, 8, fill, bd, 1)
        self.text(hdc, label, 0, 0, fg, self.font(10.5, True),
                  DT_CENTER | DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX,
                  box=(x1, y1, x2, y2))
        if enabled:
            self.hits.append((key, (x1, y1, x2, y2)))

    def check(self, hdc, x, y, label, key, on):
        s = self.S(15)
        box = (x, y, x + s, y + s)
        self.fill_round(hdc, box, 4, C["accent"] if on else C["card"],
                        C["accent"] if on else rgb("#C8CFDA"), 1.2)
        if on:
            # 手画一个对勾：两段折线
            pen = gdi32.CreatePen(PS_SOLID, max(2, self.S(2)), rgb("#FFFFFF"))
            op = gdi32.SelectObject(hdc, pen)
            gdi32.MoveToEx(hdc, x + self.S(4), y + self.S(8), None)
            gdi32.LineTo(hdc, x + self.S(6.5), y + self.S(10.5))
            gdi32.LineTo(hdc, x + self.S(11), y + self.S(4.5))
            gdi32.SelectObject(hdc, op)
            gdi32.DeleteObject(pen)
        self.text(hdc, label, x + s + self.S(7), 0, C["text2"], self.font(10.5),
                  DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX,
                  box=(x + s + self.S(7), y, x + self.S(300), y + s))
        self.hits.append((key, (x, y, x + s + self.S(160), y + s)))

    # ---- 布局 ----
    def layout(self):
        S = self.S
        self.hits = []
        W, H = S(self.W), S(self.H)
        self.box = {
            "browse": (W - S(112), S(164), W - S(28), S(194)),
            "install": (W - S(252), H - S(54), W - S(118), H - S(20)),
            "cancel": (W - S(110), H - S(54), W - S(26), H - S(20)),
            "chk_desktop": (S(28), S(208)),
            "chk_run": (S(28), S(236)),
            "progress": (S(28), S(266), W - S(28), S(276)),
        }
        return self.box

    # ---- 绘制 ----
    def paint(self, hdc):
        S = self.S
        b = self.layout()
        W, H = S(self.W), S(self.H)
        self.rect_fill(hdc, (0, 0, W, H), C["bg"])

        inst = self.inst
        # 卡片
        self.fill_round(hdc, (S(16), S(16), W - S(16), S(132)), 12,
                        C["card"], C["border"], 1)

        # 图标
        icon = None
        p = os.path.join(MEIPASS, "app.ico")
        if os.path.isfile(p):
            icon = user32.LoadImageW(None, p, 1, S(44), S(44), 0x0010 | 0x0040)
        if icon:
            user32.DrawIconEx(hdc, S(36), S(38), icon, S(44), S(44), 0, None, 0x0003)
        else:
            self.fill_round(hdc, (S(36), S(38), S(80), S(82)), 10, C["accent_l"])

        title = "安装 " + APP_NAME
        self.text(hdc, title, S(96), S(34), C["text"], self.font(16, True),
                  DT_SINGLELINE | DT_NOPREFIX)
        self.text(hdc, inst.version or "文件夹版", S(97), S(66), C["muted"],
                  self.font(10), DT_SINGLELINE | DT_NOPREFIX)
        tip = ("检测到已有安装，将原地升级（config.json 保留）" if inst.upgrade
               else "文件夹版 · 装好后双击就是秒开（启动不用解包）")
        self.text(hdc, tip, S(96), S(88), C["text2"], self.font(10.5),
                  DT_SINGLELINE | DT_NOPREFIX | DT_END_ELLIPSIS,
                  box=(S(96), S(88), W - S(40), S(110)))

        # 安装位置
        if not inst.done:
            self.text(hdc, "安装到", S(28), S(144), C["muted"], self.font(10),
                      DT_SINGLELINE | DT_NOPREFIX)
        box = (S(28), S(164), b["browse"][0] - S(10), S(194))
        if not inst.done:
            self.fill_round(hdc, box, 8, C["ghost_bg"],
                            C["accent"] if self.hover == "pathbox" else C["border"], 1)
            self.text(hdc, inst.target, 0, 0, C["text"], self.font(10),
                      DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX | DT_END_ELLIPSIS
                      | DT_LEFT, box=(box[0] + S(10), box[1], box[2] - S(10), box[3]))
            self.hits.append(("pathbox", (box[0], box[1], box[2], box[3])))
        bx = b["browse"]
        if not inst.done:
            self.button(hdc, (bx[0], bx[1], bx[2], bx[3]), "更改…", "browse", "ghost")

        if not inst.done:
            self.check(hdc, b["chk_desktop"][0], b["chk_desktop"][1],
                       "在桌面创建快捷方式", "chk_desktop", self.want_shortcut)
            self.check(hdc, b["chk_run"][0], b["chk_run"][1],
                       "安装完成后立即启动", "chk_run", self.want_run)
            # 进度条：没开始装的时候不画，免得界面上一根灰条让人以为卡住了
            pr = b["progress"]
            started = inst.thread is not None or inst.pct > 0
            if started:
                self.fill_round(hdc, (pr[0], pr[1], pr[2], pr[3] + S(2)), 5, C["track"])
                w = int((pr[2] - pr[0]) * max(0.0, min(100.0, inst.pct)) / 100.0)
                if w > 2:
                    self.fill_round(hdc, (pr[0], pr[1], pr[0] + w, pr[3] + S(2)),
                                    5, C["accent"] if not inst.error else C["err"])
            msg = inst.error or inst.stage
            color = C["err"] if inst.error else C["muted"]
            self.text(hdc, msg, 0, 0, color, self.font(10),
                      DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX | DT_END_ELLIPSIS
                      | DT_LEFT, box=(pr[0], S(284), W - S(96), S(306)))
            if inst.pct > 0 and not inst.error:
                self.text(hdc, "%.0f%%" % min(100, inst.pct), 0, 0, C["muted"],
                          self.font(10), DT_RIGHT | DT_SINGLELINE | DT_VCENTER
                          | DT_NOPREFIX,
                          box=(W - S(90), S(284), W - S(28), S(306)))
            busy = inst.thread is not None and not inst.done and not inst.error
            self.button(hdc, b["install"],
                        "安装中…" if busy else ("重试" if inst.error else "安装"),
                        "install", "primary", enabled=not busy)
            self.button(hdc, b["cancel"],
                        "取消" if not inst.done else "关闭",
                        "cancel", "ghost", enabled=True)
        else:
            self.text(hdc, "安装完成，双击桌面上的「%s」就能用。" % APP_NAME,
                      0, 0, C["ok"], self.font(11, True),
                      DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX,
                      box=(S(28), S(196), W - S(28), S(222)))
            self.text(hdc, inst.target, 0, 0, C["muted"], self.font(10),
                      DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX | DT_END_ELLIPSIS,
                      box=(S(28), S(226), W - S(28), S(248)))
            if inst.upgrade:
                self.text(hdc, "原配置（config.json）原样保留，路径和勾选没动。",
                          0, 0, C["muted"], self.font(10),
                          DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX,
                          box=(S(28), S(250), W - S(28), S(270)))
            self.button(hdc, (W - S(140), H - S(54), W - S(26), H - S(20)),
                        "完成", "cancel", "primary")

    # ---- 交互 ----
    def hit(self, x, y):
        for key, (x1, y1, x2, y2) in reversed(self.hits):
            if x1 <= x <= x2 and y1 <= y <= y2:
                return key
        return None

    def on_click(self, key):
        inst = self.inst
        if key in ("cancel", "close"):
            if inst.thread is not None and not inst.done and not inst.error:
                inst.cancel_request = True
                user32.PostMessageW(self.hwnd, WM_CLOSE_, 0, 0)
                return
            user32.PostMessageW(self.hwnd, WM_CLOSE_, 0, 0)
            return
        if key == "chk_desktop":
            self.want_shortcut = not self.want_shortcut
            inst.want_shortcut = self.want_shortcut
        elif key == "chk_run":
            self.want_run = not self.want_run
            inst.want_run = self.want_run
        elif key in ("pathbox", "browse"):
            if inst.thread is None:
                self.browse()
        elif key == "install":
            if inst.thread is None and not inst.done:
                self.start()
        user32.InvalidateRect(self.hwnd, None, True)

    def browse(self):
        """选目录：用 SHBrowseForFolder（系统原生的那个）"""
        BFFM_INITIALIZED, BFFM_SELCHANGED = 1, 2
        BIF_RETURNONLYFSDIRS, BIF_NEWDIALOGSTYLE = 0x0001, 0x0040

        class BROWSEINFOW(ctypes.Structure):
            _fields_ = [("hwndOwner", wt.HWND), ("pidlRoot", ctypes.c_void_p),
                        ("pszDisplayName", wt.LPWSTR), ("lpszTitle", wt.LPCWSTR),
                        ("ulFlags", wt.UINT), ("lpfn", ctypes.c_void_p),
                        ("lParam", wt.LPARAM), ("iImage", ctypes.c_int)]

        class ITEMIDLIST(ctypes.Structure):
            _fields_ = [("dummy", ctypes.c_byte)]

        shell32.SHBrowseForFolderW.argtypes = [ctypes.POINTER(BROWSEINFOW)]
        shell32.SHBrowseForFolderW.restype = ctypes.POINTER(ITEMIDLIST)
        shell32.SHGetPathFromIDListW.argtypes = [ctypes.POINTER(ITEMIDLIST), wt.LPWSTR]
        shell32.SHGetPathFromIDListW.restype = wt.BOOL
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]

        buf = ctypes.create_unicode_buffer(260)
        bi = BROWSEINFOW()
        bi.hwndOwner = self.hwnd
        bi.pszDisplayName = ctypes.cast(buf, wt.LPWSTR)
        bi.lpszTitle = "选择安装到哪个文件夹"
        bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE
        pidl = shell32.SHBrowseForFolderW(ctypes.byref(bi))
        if not pidl:
            return
        path = ctypes.create_unicode_buffer(1024)
        if shell32.SHGetPathFromIDListW(pidl, path):
            if path.value:
                self.inst.target = os.path.join(path.value, APP_NAME) \
                    if os.path.basename(path.value.rstrip("\\")).lower() != APP_NAME.lower() \
                    else path.value
                self.inst.upgrade = os.path.isfile(
                    os.path.join(self.inst.target, "config.json"))
        ole32.CoTaskMemFree(pidl)

    def start(self):
        inst = self.inst
        if not inst.target:
            return
        # 目标目录如果已经有别的 exe 同名但没关，直接装会失败 —— 先说清楚
        inst.stage = "准备安装"
        inst.pct = 0
        inst.error = ""
        inst.done = False
        inst.cancel_request = False
        inst.thread = threading.Thread(target=self._work, daemon=True)
        inst.thread.start()
        user32.SetTimer(self.hwnd, 2, 100, None)

    def _work(self):
        self.inst.run()
        try:
            user32.PostMessageW(self.hwnd, WM_APP, 0, 0)
        except Exception:
            pass

    # ---- 窗口过程 ----
    def _proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_PAINT:
            ps = PAINTSTRUCT()
            hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
            try:
                self.hits = []
                self.paint(hdc)
            finally:
                user32.EndPaint(hwnd, ctypes.byref(ps))
            return 0
        if msg == WM_ERASEBKGND:
            return 1
        if msg == WM_MOUSEMOVE:
            x = ctypes.c_short(lparam & 0xFFFF).value
            y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            k = self.hit(x, y)
            if k != self.hover:
                self.hover = k
                user32.InvalidateRect(hwnd, None, True)
            cid = 32649 if k in ("install", "cancel", "browse", "pathbox") else 32512
            user32.SetCursor(user32.LoadCursorW(None, ctypes.c_wchar_p(cid)))
            return 0
        if msg == WM_LBUTTONDOWN:
            x = ctypes.c_short(lparam & 0xFFFF).value
            y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            k = self.hit(x, y)
            if k:
                self.pressed = k
                user32.SetCapture(hwnd)
            return 0
        if msg == WM_LBUTTONUP:
            x = ctypes.c_short(lparam & 0xFFFF).value
            y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            user32.ReleaseCapture()
            k = self.hit(x, y)
            down = self.pressed
            self.pressed = None
            if k and k == down:
                self.on_click(k)
            return 0
        if msg == WM_TIMER:
            if wparam == 2:
                if self.inst.done or self.inst.error:
                    user32.KillTimer(hwnd, 2)
                    if self.inst.done:
                        user32.InvalidateRect(hwnd, None, True)
                else:
                    user32.InvalidateRect(hwnd, None, False)
            return 0
        if msg == WM_APP:
            user32.InvalidateRect(hwnd, None, True)
            return 0
        if msg == WM_CLOSE:
            busy = (self.inst.thread is not None and not self.inst.done
                    and not self.inst.error)
            if busy and not self.inst.cancel_request:
                r = user32.MessageBoxW(hwnd, "还在安装中，确定要退出吗？\n"
                                             "（未装完的文件可能残缺，需要重装一次）",
                                       "退出安装", 0x04 | 0x30)
                if r != 6:
                    return 0
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    # ---- 创建窗口 ----
    def show(self):
        try:
            ole32.CoInitialize(None)       # SHBrowseForFolder / IShellLink 都要
        except Exception:
            pass
        hdc = user32.GetDC(None)
        try:
            self.dpi = float(gdi32.GetDeviceCaps(hdc, 88)) or 96.0   # LOGPIXELSX
        finally:
            user32.ReleaseDC(None, hdc)

        hinst = kernel32.GetModuleHandleW(None)
        hinst = wt.HINSTANCE(hinst)
        cls = "DailyLauncherSetupWnd"
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.style = CS_HREDRAW | CS_VREDRAW
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = hinst
        wc.hCursor = user32.LoadCursorW(None, ctypes.c_wchar_p(32512))
        wc.hbrBackground = gdi32.CreateSolidBrush(C["bg"])
        wc.lpszClassName = cls
        iconp = os.path.join(MEIPASS, "app.ico")
        if os.path.isfile(iconp):
            wc.hIcon = user32.LoadImageW(None, iconp, 1, 32, 32, 0x0010)
            wc.hIconSm = wc.hIcon
        user32.RegisterClassExW(ctypes.byref(wc))

        style = WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX | WS_CLIPCHILDREN
        W, H = self.S(self.W), self.S(self.H)
        pad = self.S(8)
        user32.AdjustWindowRectEx.argtypes = [ctypes.POINTER(RECT), wt.DWORD, wt.BOOL, wt.DWORD]
        rc = RECT(0, 0, W, H)
        user32.AdjustWindowRectEx(ctypes.byref(rc), style, False, 0)
        ww, wh = rc.right - rc.left, rc.bottom - rc.top
        self.hwnd = user32.CreateWindowExW(
            0, cls, "安装 " + APP_NAME + " " + (self.inst.version or ""),
            style, CW_USEDEFAULT, CW_USEDEFAULT, ww, wh, None, None, hinst, None)
        if not self.hwnd:
            raise OSError("创建窗口失败：%s" % ctypes.get_last_error())
        user32.ShowWindow(self.hwnd, SW_SHOW)
        user32.UpdateWindow(self.hwnd)
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        return 0


user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.restype = ctypes.c_ssize_t
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.DestroyWindow.argtypes = [wt.HWND]
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.AdjustWindowRectEx.restype = wt.BOOL
user32.DrawIconEx.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, wt.HICON,
                              ctypes.c_int, ctypes.c_int, wt.UINT, wt.HANDLE, wt.UINT]
user32.SetCursor.restype = wt.HANDLE
user32.SetCursor.argtypes = [wt.HANDLE]
user32.ReleaseCapture.restype = wt.BOOL
user32.SetCapture.argtypes = [wt.HWND]
user32.InvalidateRect.argtypes = [wt.HWND, ctypes.c_void_p, wt.BOOL]
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
user32.UpdateWindow.argtypes = [wt.HWND]
gdi32.MoveToEx.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
gdi32.LineTo.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
kernel32.GetModuleHandleW.restype = wt.HMODULE
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]


def parse_args(argv):
    """认 /S /D= /WAITPID= /RESTART /NOSHORTCUT /LOG= 这几个（大小写不敏感）"""
    opt = {"silent": False, "dir": "", "waitpid": 0, "restart": False,
           "shortcut": None, "run": False, "log": ""}
    for raw in argv:
        a = raw.strip()
        low = a.lower()
        # 注意顺序：/shortcut 也以 /s 开头，得先认全称再认 /s
        if low in ("/silent", "-s", "/s", "-silent"):
            opt["silent"] = True
        elif low == "/shortcut":
            opt["shortcut"] = True
        elif low == "/noshortcut":
            opt["shortcut"] = False
        elif low == "/restart":
            opt["restart"] = True
        elif low == "/run":
            opt["run"] = True
        elif low.startswith("/d="):
            opt["dir"] = a[3:].strip().strip('"')
        elif low.startswith("/waitpid="):
            try:
                opt["waitpid"] = int(re.findall(r"\d+", a)[0])
            except Exception:
                opt["waitpid"] = 0
        elif low.startswith("/log="):
            opt["log"] = a[5:].strip().strip('"')
    return opt


def _fail_box(reason):
    """静默安装失败时弹一次窗。

    静默安装通常是程序自己更新时调的：旧程序已经退出，如果没有这个弹窗，
    用户只会看到"点了一下，程序没了"，不知道发生了什么、也不知道文件还在。
    """
    if os.environ.get("DL_SETUP_NO_UI"):
        log("（DL_SETUP_NO_UI 已设置，不弹窗）")
        return
    try:
        user32.MessageBoxW(
            None,
            "安装没有成功：%s\n\n"
            "原来的程序没有被破坏，重新打开就能用。\n"
            "想再试一次，可以手动运行安装包。\n\n"
            "日志：%s" % (reason, LOG_PATH),
            "安装 " + APP_NAME, 0x10)
    except Exception as e:
        log("弹窗失败：%s" % e)


def main():
    global LOG_PATH
    opt = parse_args(sys.argv[1:])
    if opt["log"]:
        LOG_PATH = opt["log"]
    target = opt["dir"] or default_dir()
    want_shortcut = opt["shortcut"]
    if want_shortcut is None:
        want_shortcut = not opt["silent"]      # 静默安装（自动更新）不建快捷方式
    inst = Installer(target, want_shortcut=want_shortcut,
                     want_run=opt["run"], restart=opt["restart"],
                     wait_pid=opt["waitpid"])
    inst.thread = None
    inst.cancel_request = False

    if opt["silent"]:
        log("静默安装 -> %s（shortcut=%s restart=%s waitpid=%s）"
            % (target, want_shortcut, opt["restart"], opt["waitpid"]))
        inst.run()
        if inst.error:
            log("安装失败：%s" % inst.error)
            # 静默安装一般是程序自己更新时调的：这时旧程序已退出，界面上
            # 什么都不会发生，用户只会觉得"点了一下就没反应了"。所以失败
            # 必须弹一次，至少告诉他程序没坏、可以重新装。
            _fail_box(inst.error)
            return 1
        if not inst.done:
            log("安装没有完成（原因未知）")
            _fail_box("安装没有完成")
            return 1
        return 0

    try:
        ui = SetupUI(inst)
        ui.want_shortcut = want_shortcut
        ui.want_run = opt["run"]
        return ui.show()
    except Exception as e:
        log("界面起不来：%s" % e)
        user32.MessageBoxW(None, "安装程序起不来：%s" % e, "安装 " + APP_NAME, 0x10)
        return 1


if __name__ == "__main__":
    sys.exit(main())
