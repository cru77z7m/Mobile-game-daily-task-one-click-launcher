"""Optional native cosmetics. All newer Windows APIs are resolved lazily.

Mica extends through the client area. ui_render supplies premultiplied ARGB
content; unsupported systems keep the conventional opaque GDI path.
"""
import ctypes
import sys


def system_preferences():
    """Fail closed for effects; never make startup depend on a registry/API."""
    motion, transparency, contrast = False, False, True
    try:
        u = ctypes.WinDLL('user32', use_last_error=True)
        enabled = ctypes.c_int()
        if u.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0):
            motion = bool(enabled.value)  # SPI_GETCLIENTAREAANIMATION

        class HIGHCONTRAST(ctypes.Structure):
            _fields_ = [('size', ctypes.c_uint), ('flags', ctypes.c_uint),
                        ('scheme', ctypes.c_void_p)]
        hc = HIGHCONTRAST()
        hc.size = ctypes.sizeof(hc)
        if u.SystemParametersInfoW(0x0042, hc.size, ctypes.byref(hc), 0):
            contrast = bool(hc.flags & 1)
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as k:
            transparency = bool(winreg.QueryValueEx(k, 'EnableTransparency')[0])
    except (OSError, AttributeError, ImportError):
        pass
    return motion and not contrast, transparency and not contrast


def apply_native_frame(hwnd, enabled=True, build=None, material='mica'):
    """Returns mica / solid / unsupported / unavailable; HRESULTs are checked.

    Public DWMWA_SYSTEMBACKDROP_TYPE requires Windows 11 build 22621.
    No undocumented 1029 attribute or Windows 10 accent policy is used.
    """
    try:
        if build is None:
            build = sys.getwindowsversion().build
        if build < 22621:
            return 'unsupported'
        dwm = ctypes.WinDLL('dwmapi', use_last_error=True)
        setter = dwm.DwmSetWindowAttribute
        setter.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
        setter.restype = ctypes.c_long
        corner = ctypes.c_int(2)  # DWMWCP_ROUND (optional)
        setter(hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner))
        material = material if material in ('mica', 'tabbed', 'acrylic', 'solid') else 'mica'
        enabled = enabled and material != 'solid'
        value = ctypes.c_int({'mica':2, 'tabbed':4, 'acrylic':3}.get(material, 1) if enabled else 1)
        hr = setter(hwnd, 38, ctypes.byref(value), ctypes.sizeof(value))
        if hr != 0:
            return 'unavailable'
        class MARGINS(ctypes.Structure):
            _fields_ = [('left', ctypes.c_int), ('right', ctypes.c_int),
                        ('top', ctypes.c_int), ('bottom', ctypes.c_int)]
        extend = dwm.DwmExtendFrameIntoClientArea
        extend.argtypes = [ctypes.c_void_p, ctypes.POINTER(MARGINS)]
        extend.restype = ctypes.c_long
        margins = MARGINS(*([-1]*4 if enabled else [0]*4))
        if extend(hwnd, ctypes.byref(margins)) != 0:
            value.value = 1
            setter(hwnd, 38, ctypes.byref(value), ctypes.sizeof(value))
            extend(hwnd, ctypes.byref(MARGINS(0, 0, 0, 0)))
            return 'unavailable'
        # Keep this app's light palette and the native material consistent.
        light = ctypes.c_int(0)
        setter(hwnd, 20, ctypes.byref(light), ctypes.sizeof(light))
        return material if enabled else 'solid'
    except (OSError, AttributeError, ValueError):
        return 'unavailable'


def mix_color(a, b, amount):
    t = max(0.0, min(1.0, amount))
    return sum(round(((a >> n) & 255) * (1-t) + ((b >> n) & 255) * t) << n
               for n in (0, 8, 16))


class AnimationClock:
    """Process-local high resolution only while a visible transition is active."""
    def __init__(self):
        self.dll = None
        self.active = False
        try:
            self.dll = ctypes.WinDLL('winmm')
            self.dll.timeBeginPeriod.argtypes = [ctypes.c_uint]
            self.dll.timeEndPeriod.argtypes = [ctypes.c_uint]
        except (OSError, AttributeError):
            self.dll = None

    def start(self):
        if self.dll and not self.active:
            self.active = self.dll.timeBeginPeriod(1) == 0

    def stop(self):
        if self.dll and self.active:
            self.dll.timeEndPeriod(1)
            self.active = False
