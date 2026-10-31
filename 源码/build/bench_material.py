# -*- coding: utf-8 -*-
"""材质模式单帧合成耗时拆解（只读诊断，不启动界面）。

跑法：
    python 源码/build/bench_material.py [宽 高 轮数]

会打印 prepare() 总耗时，以及内部各步骤的耗时占比，
用来判断卡顿到底来自 where。
"""
import ctypes as c
import os
import sys
import time
from ctypes import wintypes as w

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw, ImageFont
from ui_render import DibSurface, Compositor, gdi

gdi.CreateCompatibleDC.argtypes = [c.c_void_p]
gdi.CreateCompatibleDC.restype = c.c_void_p
gdi.CreateCompatibleBitmap.argtypes = [c.c_void_p, c.c_int, c.c_int]
gdi.CreateCompatibleBitmap.restype = c.c_void_p

W = int(sys.argv[1]) if len(sys.argv) > 1 else 2560
H = int(sys.argv[2]) if len(sys.argv) > 2 else 1356
N = int(sys.argv[3]) if len(sys.argv) > 3 else 10


def font(px):
    for name in ("msyh.ttc", "msyh.ttf", "simhei.ttf"):
        p = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name)
        if os.path.isfile(p):
            return ImageFont.truetype(p, px)
    return ImageFont.load_default()


def build_scene(screen):
    """画一张和主界面差不多的场景：浅色面板 + 深色文字块。"""
    su = DibSurface(screen, W, H)
    img = Image.new("RGB", (W, H), (243, 244, 248))          # 窗口底色
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((24, 12, W - 20, H - 60), 16, fill=(241, 243, 251))   # 主卡片
    d.rounded_rectangle((28, 120, 196, H - 80), 14, fill=(238, 241, 250))    # 侧栏
    d.rounded_rectangle((212, 96, W - 28, 300), 16, fill=(249, 250, 253))    # hero
    f = font(18)
    for i in range(24):
        y = 330 + i * 42
        if y > H - 120:
            break
        d.rounded_rectangle((212, y, W - 40, y + 34), 10, fill=(252, 252, 255))
        d.text((232, y + 7), "任务项 %02d  ·  启动 MuMu 并执行日常" % i, font=f, fill=(60, 66, 86))
    img = img.convert("RGBA")
    su.bits and c.memmove(su.bits, img.tobytes("raw", "BGRA"), W * H * 4)
    return su


def build_text_layers(screen, ss):
    """两张超采样文字层：coverage（白字）+ ink（彩色字）。"""
    conv = DibSurface(screen, W * ss, H * ss)
    ink = DibSurface(screen, W * ss, H * ss)
    f = font(18 * ss)
    m = Image.new("RGB", (W * ss, H * ss), (0, 0, 0))
    md = ImageDraw.Draw(m)
    for i in range(24):
        y = 330 + i * 42
        if y > H - 120:
            break
        md.text((232 * ss, (y + 7) * ss),
                "任务项 %02d  ·  启动 MuMu 并执行日常" % i, font=f, fill=(255, 255, 255))
    for i in range(10):
        md.text((40 * ss, (200 + i * 30) * ss), "导航项 %d" % i, font=f, fill=(255, 255, 255))
    c.memmove(conv.bits, m.tobytes("raw", "BGRX"), W * ss * H * ss * 4)
    c.memmove(ink.bits, m.tobytes("raw", "BGRX"), W * ss * H * ss * 4)
    return conv, ink


def main():
    screen = gdi.CreateCompatibleDC(None)
    comp = Compositor()
    comp.material = "mica"
    if not comp.available:
        print("BufferedPaint 不可用，本机没法测材质路径")
        return
    scene = build_scene(screen)
    ss = 2
    lay = build_text_layers(screen, ss)
    comp.text_layers = lay

    # 预热
    for _ in range(2):
        s = comp.prepare(scene.dc, W, H, [])
        s.close()
    gdi.GdiFlush()

    # 整体
    t0 = time.perf_counter()
    for _ in range(N):
        s = comp.prepare(scene.dc, W, H, [])
        s.close()
    total = (time.perf_counter() - t0) / N

    # 拆解：alpha 图
    from PIL import Image, ImageChops
    t0 = time.perf_counter()
    for _ in range(N):
        rgb = Image.frombytes("RGB", (W, H), c.string_at(scene.bits, W * H * 4), "raw", "BGRX")
        r, g, b = rgb.split()
        light = ImageChops.darker(ImageChops.darker(r, g), b)
        alpha = light.point([255 if x <= 205 else round(255 + (168 - 255) * (x - 205) / 30) if x < 235 else 168 for x in range(256)])
        diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, (241, 243, 251)))
        dr, dg, db = diff.split()
        canvas = ImageChops.lighter(ImageChops.lighter(dr, dg), db).point([255] + [0] * 255)
        alpha.paste(32, mask=canvas)
        rgb.putalpha(alpha)
    t_alpha = (time.perf_counter() - t0) / N

    # 拆解：文字层
    t0 = time.perf_counter()
    for _ in range(N):
        rgb2 = Image.new("RGBA", (W, H))
        out = comp.overlay_text(rgb2, W, H)
    t_text = (time.perf_counter() - t0) / N

    # 拆解：预乘 + 回写
    t0 = time.perf_counter()
    for _ in range(N):
        rgb3 = Image.new("RGBA", (W, H), (240, 240, 240, 200))
        data = rgb3.convert("RGBa").tobytes("raw", "BGRa")
        dst = DibSurface(screen, W, H)
        c.memmove(dst.bits, data, len(data))
        dst.close()
    t_pre = (time.perf_counter() - t0) / N

    print("窗口 %dx%d，文字层 %d 倍，%d 次平均" % (W, H, ss, N))
    print("  prepare 总计      %7.1f ms   (上限约 %.1f fps)" % (total * 1000, 1 / total))
    print("  其中 alpha 图     %7.1f ms" % (t_alpha * 1000))
    print("  其中 文字层合成   %7.1f ms" % (t_text * 1000))
    print("  其中 预乘+回写    %7.1f ms" % (t_pre * 1000))
    print("  其余(拷贝/分配)   %7.1f ms" % ((total - t_alpha - t_text - t_pre) * 1000))
    for s in (scene, lay[0], lay[1]):
        s.close()


if __name__ == "__main__":
    main()
