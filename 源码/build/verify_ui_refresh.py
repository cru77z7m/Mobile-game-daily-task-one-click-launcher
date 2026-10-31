"""Run from project root with Python; no games launched or user config written.

Usage: python 源码/build/verify_ui_refresh.py [main|settings|custom|night|tasks|about] [scroll]
"""
import copy
import ctypes
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '源码'))
import ui_effects as effects

# Windows 10 must not even attempt to load dwmapi.
with patch.object(ctypes, 'WinDLL', side_effect=AssertionError('unexpected DLL load')):
    assert effects.apply_native_frame(1, build=19045) == 'unsupported'
with patch.object(ctypes, 'WinDLL', side_effect=OSError('missing DLL')):
    assert effects.apply_native_frame(1, build=22621) == 'unavailable'
    assert effects.system_preferences() == (False, False)

class Setter:
    def __init__(self, result):
        self.result, self.calls = result, []
    def __call__(self, hwnd, attr, value, size):
        self.calls.append((attr, ctypes.cast(value, ctypes.POINTER(ctypes.c_int))[0]))
        return self.result

class Dwm:
    def __init__(self, result):
        self.DwmSetWindowAttribute = Setter(result)
        self.DwmExtendFrameIntoClientArea = lambda *args: result

for enabled, hr, expected in [(True, 0, 'mica'), (False, 0, 'solid'),
                               (True, -2147024809, 'unavailable')]:
    d = Dwm(hr)
    with patch.object(ctypes, 'WinDLL', return_value=d):
        assert effects.apply_native_frame(1, enabled, 22621) == expected
    assert (38, 2 if enabled else 1) in d.DwmSetWindowAttribute.calls
assert effects.mix_color(0, 0xffffff, 0) == 0
assert effects.mix_color(0, 0xffffff, 1) == 0xffffff
print('PASS: Win10 gate / missing DLL / HRESULT failure / enable-disable / color endpoints')

import daily_launcher as app
cfg = copy.deepcopy(app.DEFAULT_CONFIG)
cfg.update(json.loads((ROOT / 'config.json').read_text(encoding='utf-8-sig')))
app.load_config = lambda: copy.deepcopy(cfg)
app.save_config = lambda c: None
app.save_state = lambda: None
app.cleanup_update_leftovers = lambda: None
app.App._discover_instances = lambda self: None
app.App._tick_update = lambda self: None
app.LOG_PATH = str(ROOT / 'design' / 'verification.log')
page = sys.argv[1] if len(sys.argv) > 1 else 'main'
scroll = sys.argv[2] if len(sys.argv) > 2 else '0'
app.STATE.update(last_run_version=app.APP_VERSION, config_version=app.CONFIG_VERSION)
ui = app.App()
for method in ('settings_rows', 'custom_rows', 'night_rows', 'main_rows', 'task_rows'):
    if hasattr(ui, method):
        for row in getattr(ui, method)():
            if not row['key'].startswith('sec:'):
                assert app.load_icon(row.get('icon')), row
for dpi in (96, 120, 144, 192):
    ui.dpi = dpi
    for pg in ('main', 'settings', 'custom', 'night', 'tasks', 'about'):
        ui.page = pg
        ui.layout(ui.S(960), ui.S(780))
        assert ui.rects['card'][3] < ui.rects['edit'][1]
        assert ui._scroll_max >= 0
print('PASS: generated icons load / layout at 100%, 125%, 150%, 200%')
original_create = app.App.create
def checked_create(self):
    hwnd = original_create(self)
    # Test windows do not accept accidental physical clicks during screenshots.
    app.user32.EnableWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    app.user32.EnableWindow(hwnd, False)
    app.user32.GetGuiResources.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    app.user32.GetGuiResources.restype = ctypes.c_uint
    process = ctypes.c_void_p(-1)
    hdc = app.user32.GetDC(hwnd)
    self.paint(hdc)  # Warm font/icon caches before measuring.
    before_handles = app.user32.GetGuiResources(process, 0)
    for _ in range(120):
        self.paint(hdc)
    after_handles = app.user32.GetGuiResources(process, 0)
    app.user32.ReleaseDC(hwnd, hdc)
    assert after_handles <= before_handles + 2, (before_handles, after_handles)
    print('PASS: 120 redraws, GDI handles %d -> %d; material=%s, alpha frames=%d' % (before_handles, after_handles, self.frame_effect, self._compositor.frames))
    if self.page == 'settings':
        rc = app.wt.RECT()
        app.user32.GetClientRect(hwnd, ctypes.byref(rc))
        self.layout(rc.right, rc.bottom)
        self.scroll = 0
        app.user32.SendMessageW(hwnd, app.WM_MOUSEWHEEL, ((-120) & 65535) << 16, 0)
        down = self.scroll
        app.user32.SendMessageW(hwnd, app.WM_MOUSEWHEEL, 120 << 16, 0)
        assert self._scroll_max == 0 or (down > 0 and self.scroll < down)
        self.scroll = min(int(scroll), self._scroll_max)
        before = self.cfg.get('ui_motion', True)
        self.pick_row('ui_motion')
        assert self.cfg['ui_motion'] != before
        self.pick_row('ui_motion')
        assert self.cfg['ui_motion'] == before
        print('PASS: native mouse-wheel messages / appearance toggle round trip')
    return hwnd
app.App.create = checked_create
sys.argv = [str(ROOT / '源码' / 'daily_launcher.py'), '--no-auto', '--no-elevate',
            '--no-task', '--shot', str(ROOT / 'design' / 'previews' / (page+'-'+scroll+'.png')),
            '--page', page, '--scroll', scroll]
raise SystemExit(app.main())
