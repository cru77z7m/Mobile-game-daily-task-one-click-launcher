# -*- coding: utf-8 -*-
"""校验「hover 局部刷新」的补丁结果必须和整帧重算逐像素一致。

跑法：python 源码/build/verify_patch.py
- 先在主界面画一帧（hover 为空）当底；
- 再把 hover 指到某个控件，走 patch 路径画一帧；
- 然后关掉 patch 走整帧路径画同一状态；
- 两张 ARGB 必须一致（差几级以内），否则说明补丁矩形漏了东西。
"""
import ctypes as c
import copy
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '源码'))
import daily_launcher as a

cfg = copy.deepcopy(a.DEFAULT_CONFIG)
cfg.update(json.loads((ROOT / 'config.json').read_text(encoding='utf-8-sig')))
cfg.update(ui_motion=True, ui_mica=True, ui_material='mica')
a.load_config = lambda: copy.deepcopy(cfg)
a.save_config = lambda _: None
a.save_state = lambda: None
a.App._discover_instances = lambda self: None
a.App._tick_update = lambda self: None
a.LOG_PATH = str(ROOT / 'design/patch-verification.log')
a.STATE.update(last_run_version=a.APP_VERSION)

ui = a.App()
ui.no_auto = ui.no_mutex = True
ui.page = 'main'
hwnd = ui.create()
a.user32.EnableWindow.argtypes = [c.c_void_p, c.c_int]
a.user32.EnableWindow(hwnd, False)
dc = a.user32.GetDC(hwnd)


def frame_bytes():
    """取最近一帧合成出来的 ARGB（预乘）原始数据。"""
    s = ui._compositor.last_argb
    assert s is not None, '材质模式下应当有整帧 ARGB'
    return c.string_at(s.bits, s.width * s.height * 4), s.width, s.height


def paint():
    ui.paint(dc)
    try:
        c.windll.dwmapi.DwmFlush()
    except (OSError, AttributeError):
        pass


def hover_on(key):
    ui._hover_from = None
    ui.hover = key
    ui._hover_at = time.monotonic() - 1.0     # 动画早已走完，取值稳定


if ui.frame_effect not in ('mica', 'tabbed', 'acrylic'):
    print('本机没进材质模式（frame_effect=%s），跳过' % ui.frame_effect)
    sys.exit(0)

# 1) 整帧底稿
hover_on(None)
paint()
paint()                                        # 第二帧预热，字体/图标缓存都就位

fails = 0
cases = []
for key in ('start', 'night', 'chk:vm0', 'nav:settings'):
    rects = ui.hover_rects(key)
    if not rects:
        print('!! %-14s 翻不出矩形，跳过' % key)
        continue
    # 每一轮都先回到「没有 hover」的整帧底稿，模拟鼠标从空白处移进来
    hover_on(None)
    ui._hover_patch = None
    paint()

    # 2) patch 路径
    hover_on(key)
    pad = ui.S(8)
    ui._hover_patch = [(r[0] - pad, r[1] - pad, r[2] + pad, r[3] + pad) for r in rects]
    ui._hover_patch_serial = ui._paint_serial
    t0 = time.monotonic()
    paint()
    t_patch = (time.monotonic() - t0) * 1000
    patch_px = frame_bytes()
    used_patch = ui._compositor.prepared is not None

    # 3) 整帧路径（同一状态）—— 强制整帧，别让它偷偷走自动补丁
    hover_on(key)
    ui._hover_patch = None
    ui._force_full_paint = True
    t0 = time.monotonic()
    paint()
    ui._force_full_paint = False
    t_full = (time.monotonic() - t0) * 1000
    full_px = frame_bytes()

    if patch_px[1:] != full_px[1:]:
        print('!! %s 尺寸不一致' % key)
        fails += 1
        continue
    p, f = patch_px[0], full_px[0]
    diff = sum(1 for i in range(0, len(p), 4) if abs(p[i] - f[i]) > 2
               or abs(p[i + 1] - f[i + 1]) > 2 or abs(p[i + 2] - f[i + 2]) > 2)
    pix = patch_px[1] * patch_px[2]
    ok = diff <= pix * 0.0005
    if not ok:
        from PIL import Image, ImageChops
        W, H = patch_px[1], patch_px[2]
        ib = Image.frombytes('RGBA', (W, H), p, 'raw', 'BGRA')
        ic = Image.frombytes('RGBA', (W, H), f, 'raw', 'BGRA')
        d = ImageChops.difference(ib.convert('RGB'), ic.convert('RGB'))
        key_slug = key.replace(':', '_')
        (ROOT / 'design').mkdir(exist_ok=True)
        ib.convert('RGB').save(ROOT / ('design/patch-%s.png' % key_slug))
        d.point(lambda v: min(255, v * 8)).save(ROOT / ('design/diff-%s.png' % key_slug))
    fails += 0 if ok else 1
    cases.append((key, t_patch, t_full, diff, ok))
    print('%s %-14s patch %6.1f ms | full %6.1f ms | 差异像素 %d (%.4f%%) | patch=%s'
          % ('PASS' if ok else 'FAIL', key, t_patch, t_full, diff,
             diff * 100.0 / pix, used_patch))


# ---- 连续移动：A → B 只走补丁，最终画面必须和整帧一致（验证 _hover_from 有没有漏擦）----
hover_on(None)
ui._hover_patch = None
paint()
pad = ui.S(8)


def patch_to(key, prev):
    rects = ui.hover_rects(key) + ui.hover_rects(prev)
    ui._hover_patch = [(r[0] - pad, r[1] - pad, r[2] + pad, r[3] + pad) for r in rects]
    ui._hover_patch_serial = ui._paint_serial
    ui._hover_from = prev
    ui.hover = key
    ui._hover_at = time.monotonic() - 1.0
    paint()


patch_to('chk:vm0', None)
patch_to('chk:vm1', 'chk:vm0')
seq = frame_bytes()
ui._hover_patch = None
hover_on('chk:vm1')
ui._hover_from = 'chk:vm0'
paint()
ref = frame_bytes()
diff = sum(1 for i in range(0, len(seq[0]), 4)
           if abs(seq[0][i] - ref[0][i]) > 2 or abs(seq[0][i+1] - ref[0][i+1]) > 2
           or abs(seq[0][i+2] - ref[0][i+2]) > 2)
pix = seq[1] * seq[2]
ok = diff <= pix * 0.0005
fails += 0 if ok else 1
print('%s %-14s 连续移动 A→B | 差异像素 %d (%.4f%%)'
      % ('PASS' if ok else 'FAIL', 'sequence', diff, diff * 100.0 / pix))


# ---- 自动补丁：状态文字变了，只有那一小块该重算 ----
def state_patch_case(name, mutate):
    hover_on(None)
    ui._force_full_paint = False
    ui._hover_patch = None
    paint()                                   # 整帧底稿
    mutate()
    t0 = time.monotonic()
    paint()                                   # 应走自动补丁
    t_auto = (time.monotonic() - t0) * 1000
    auto = frame_bytes()
    mutate()
    ui._force_full_paint = True
    t0 = time.monotonic()
    paint()
    t_full = (time.monotonic() - t0) * 1000
    full = frame_bytes()
    ui._force_full_paint = False
    p, f = auto[0], full[0]
    diff = sum(1 for i in range(0, len(p), 4)
               if abs(p[i]-f[i]) > 2 or abs(p[i+1]-f[i+1]) > 2 or abs(p[i+2]-f[i+2]) > 2)
    pix = auto[1] * auto[2]
    ok = diff <= pix * 0.0005
    if not ok:
        from PIL import Image, ImageChops
        W, H = auto[1], auto[2]
        ia = Image.frombytes('RGBA', (W, H), p, 'raw', 'BGRA').convert('RGB')
        ib = Image.frombytes('RGBA', (W, H), f, 'raw', 'BGRA').convert('RGB')
        ia.save(ROOT / ('design/auto-%s-auto.png' % name))
        ib.save(ROOT / ('design/auto-%s-full.png' % name))
        ImageChops.difference(ia, ib).point(lambda v: min(255, v*6)).save(
            ROOT / ('design/auto-%s-diff.png' % name))
    print('%s %-14s 自动补丁 %6.1f ms | 整帧 %6.1f ms | 差异像素 %d (%.4f%%)'
          % ('PASS' if ok else 'FAIL', name, t_auto, t_full, diff, diff*100.0/pix))
    return 0 if ok else 1


fails += state_patch_case('status', lambda: setattr(ui, 'status', '正在启动 MAA…'))
fails += state_patch_case('step', lambda: ui.steps.__setitem__('vm0', ('run', '进行中')))

# ---- 什么都没变：不重算，但要复用缓存再提交一次（窗口被遮挡后重画靠它）----
hover_on(None)
ui._force_full_paint = False
paint()
ref0 = frame_bytes()
t0 = time.monotonic()
paint()
t_idle = (time.monotonic() - t0) * 1000
same = ref0[0] == frame_bytes()[0]
ok = same and t_idle < 60
fails += 0 if ok else 1
print('%s %-14s 无变化复用缓存 %.1f ms（画面一致=%s）'
      % ('PASS' if ok else 'FAIL', 'no-change', t_idle, same))


print('\n%d 项检查，%d 项失败' % (len(cases)+3, fails))
sys.exit(1 if fails else 0)
