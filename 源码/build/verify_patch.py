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
# 这一帧仍要 GDI 重画 + 场景差分，实测 50~60ms；只要不是整帧（150ms+）就算过
ok = same and t_idle < 110
fails += 0 if ok else 1
print('%s %-14s 无变化复用缓存 %.1f ms（画面一致=%s）'
      % ('PASS' if ok else 'FAIL', 'no-change', t_idle, same))

# ---- 快速扫过：一个消息循环里连来几个 MOUSEMOVE，中间扫过的行不能留底色 ----
# 旧实现每次都把 _hover_patch 覆盖掉，只有最后一对矩形被重算，前面扫过的行
# 就永远留在屏幕上（用户看到"扫过谁谁就上底色"）。这里不 paint，连着标 3 次，
# 最后只提交一帧，结果必须和"只有最后一个 hover"的整帧一致。
hover_on(None)
ui._force_full_paint = False
ui._hover_patch = None
paint()
paint()
sweep = ['start', 'night', 'edit']
ui._hover_from = None
for k in sweep:
    ui._hover_from = ui.hover
    ui.hover = k
    ui._hover_at = time.monotonic() - 1.0
    ui._mark_hover_patch()                 # 故意不 paint
marked = ui._hover_patch is not None
t0 = time.monotonic()
paint()
t_sweep = (time.monotonic() - t0) * 1000
got = frame_bytes()
ui._hover_patch = None
ui._hover_from = sweep[-2]
ui.hover = sweep[-1]
ui._hover_at = time.monotonic() - 1.0
ui._force_full_paint = True
paint()
ui._force_full_paint = False
ref = frame_bytes()
diff = sum(1 for i in range(0, len(got[0]), 4)
           if abs(got[0][i] - ref[0][i]) > 2
           or abs(got[0][i+1] - ref[0][i+1]) > 2
           or abs(got[0][i+2] - ref[0][i+2]) > 2)
pix = got[1] * got[2]
ok = marked and diff <= pix * 0.0005
fails += 0 if ok else 1
print('%s %-14s 连扫 3 项 %.1f ms | 差异像素 %d (%.4f%%) | 走补丁=%s'
      % ('PASS' if ok else 'FAIL', 'sweep', t_sweep, diff, diff * 100.0 / pix, marked))
if not ok:
    from PIL import Image, ImageChops
    W, H = got[1], got[2]
    Image.frombytes('RGBA', (W, H), got[0], 'raw', 'BGRA').convert('RGB').save(
        ROOT / 'design/sweep-patch.png')
    Image.frombytes('RGBA', (W, H), ref[0], 'raw', 'BGRA').convert('RGB').save(
        ROOT / 'design/sweep-full.png')
    ImageChops.difference(
        Image.frombytes('RGBA', (W, H), got[0], 'raw', 'BGRA').convert('RGB'),
        Image.frombytes('RGBA', (W, H), ref[0], 'raw', 'BGRA').convert('RGB')
    ).point(lambda v: min(255, v * 6)).save(ROOT / 'design/sweep-diff.png')

# ---- 关掉动画：hover 仍然只该重算那一块，否则每动一下就是 150ms ----
ui.cfg['ui_motion'] = False
hover_on(None)
ui._hover_patch = None
ui._force_full_paint = False
paint()
paint()
ui._hover_from = None
ui.hover = 'start'
ui._hover_at = time.monotonic()
ui._mark_hover_patch()
off_marked = ui._hover_patch is not None
t0 = time.monotonic()
paint()
t_off = (time.monotonic() - t0) * 1000
got = frame_bytes()
ui._hover_patch = None
ui._force_full_paint = True
t0 = time.monotonic()
paint()
ui._force_full_paint = False
t_full = (time.monotonic() - t0) * 1000
ref = frame_bytes()
ui.cfg['ui_motion'] = True
diff = sum(1 for i in range(0, len(got[0]), 4)
           if abs(got[0][i] - ref[0][i]) > 2
           or abs(got[0][i+1] - ref[0][i+1]) > 2
           or abs(got[0][i+2] - ref[0][i+2]) > 2)
pix = got[1] * got[2]
ok = off_marked and diff <= pix * 0.0005 and t_off < t_full * 0.6
fails += 0 if ok else 1
print('%s %-14s 关动画 hover %.1f ms（整帧 %.1f ms）| 差异像素 %d (%.4f%%) | 走补丁=%s'
      % ('PASS' if ok else 'FAIL', 'motion-off', t_off, t_full, diff,
         diff * 100.0 / pix, off_marked))


# ---- 动画进行中扫过，然后离开：一行底色都不许剩 ----
# 真机时序：MOUSEMOVE 与 WM_PAINT 交替，画的时候动画才刚开始（t≈0），于是
# "上一行"是按 1-t≈1 的**满色**画出来的。鼠标紧接着走到第三行，第二行就既不是
# hover 也不是 from，没人再重画它 —— 屏幕上留下一串擦不掉的底色，也就是用户
# 截图里"扫过谁谁就上底色"（v2.17.5 修的）。
# 两条断言：①扫描过程中，补丁帧必须和"同一状态的整帧重画"逐像素一致（漏一行就露）
#          ②鼠标离开、动画跑完，必须回到完全没有悬停的样子
ui.page = 'settings'
ui._hover_patch = None
ui._hover_tinted = set()
ui._hover_from = None
ui.hover = None
ui._hover_at = 0.0
ui._force_full_paint = False
paint()
paint()
rows2 = [it['key'] for it, _ry, _rh in ui.rects.get('rows', [])
         if not it['key'].startswith('sec:')][:4]
sweep2 = ['set:' + k for k in rows2]
for k in sweep2:
    ui._hover_from = ui.hover
    ui.hover = k
    ui._hover_at = time.monotonic()        # 动画刚开始：上一行还是满色
    ui._mark_hover_patch()
    paint()                                # 一次 MOUSEMOVE + 一次 WM_PAINT
mid = frame_bytes()

# 再让鼠标离开、动画跑完，确认不会换个方式留尾巴
ui._hover_from = ui.hover
ui.hover = None
ui._hover_at = time.monotonic()
settle_end = time.monotonic() + 0.30
while time.monotonic() < settle_end:
    time.sleep(0.016)
    ui._mark_hover_patch()
    paint()
after = frame_bytes()
ui._hover_patch = None
ui._hover_from = None
ui._hover_at = 0.0
ui._force_full_paint = True
paint()
ui._force_full_paint = False
clean = frame_bytes()

W2, H2 = mid[1], mid[2]
pix2 = W2 * H2


def ndiff(A, B):
    return sum(1 for i in range(0, len(A[0]), 4)
               if abs(A[0][i] - B[0][i]) > 2
               or abs(A[0][i+1] - B[0][i+1]) > 2
               or abs(A[0][i+2] - B[0][i+2]) > 2)


# 扫描过程中：被丢下的那几行（既不是 hover 也不是 from）此刻必须是干净的。
# 跟"完全没有悬停"的整帧比 —— 那些行在两帧里都该是同一张纯底色。
stale = 0
for k in sweep2[:-2]:
    for r in ui.hover_rects(k):
        l, t = max(0, int(r[0]) + 6), max(0, int(r[1]) + 6)
        rr, bb = min(mid[1], int(r[2]) - 6), min(mid[2], int(r[3]) - 6)
        for y in range(t, bb, 2):
            base_i = (y * mid[1]) * 4
            for x in range(l, rr, 2):
                i = base_i + x * 4
                if (abs(mid[0][i] - clean[0][i]) > 3
                        or abs(mid[0][i+1] - clean[0][i+1]) > 3
                        or abs(mid[0][i+2] - clean[0][i+2]) > 3):
                    stale += 1
d2 = ndiff(after, clean)       # 离开之后：不许留底色
d1 = stale
ok = d1 <= 50 and d2 <= pix2 * 0.0005
fails += 0 if ok else 1
print('%s %-14s 动画中扫过 %d 行 | 漏画 %d (%.4f%%) | 离开后残留 %d (%.4f%%)'
      % ('PASS' if ok else 'FAIL', 'sweep-anim', len(sweep2), d1,
         d1 * 100.0 / pix2, d2, d2 * 100.0 / pix2))
if not ok:
    from PIL import Image, ImageChops
    for tag, buf in (('mid', mid), ('same', same), ('after', after), ('clean', clean)):
        Image.frombytes('RGBA', (W2, H2), buf[0], 'raw', 'BGRA').convert('RGB').save(
            ROOT / ('design/sweep-anim-%s.png' % tag))
    ImageChops.difference(
        Image.frombytes('RGBA', (W2, H2), mid[0], 'raw', 'BGRA').convert('RGB'),
        Image.frombytes('RGBA', (W2, H2), same[0], 'raw', 'BGRA').convert('RGB')
    ).point(lambda v: min(255, v * 8)).save(ROOT / 'design/sweep-anim-diff.png')


print('\n%d 项检查，%d 项失败' % (len(cases) + 6, fails))
sys.exit(1 if fails else 0)
