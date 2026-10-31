# -*- coding: utf-8 -*-
"""用「大肥鱼大头」生成软件图标：居中裁切 -> 多尺寸 .ico

源图只有 116x116，所以：
  · 16/24/32/48 —— 从源图直接降采样（小尺寸最清晰，资源管理器/任务栏用这些）
  · 64/128/256 —— 放大，仅在“大图标”视图和 Alt+Tab 里用到，软一点无妨
"""
import os
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "icon_257.png")     # 用户给的大头图
OUT_ICO = os.path.join(HERE, "mumu.ico")
PREVIEW = os.path.join(HERE, "icon_preview.png")

SIZES = [16, 24, 32, 48, 64, 128, 256]


def trim_alpha(im, thr=8):
    """裁掉四周全透明的空白"""
    a = im.split()[-1]
    bbox = a.point(lambda v: 255 if v > thr else 0).getbbox()
    return im.crop(bbox) if bbox else im


def to_square(im, pad_ratio=0.03):
    """补成正方形，四周留一点边距"""
    w, h = im.size
    side = max(w, h)
    side = int(side * (1 + pad_ratio * 2))
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(im, ((side - w) // 2, (side - h) // 2), im)
    return canvas


def main():
    im = Image.open(SRC).convert("RGBA")
    print("源图:", im.size)
    im = trim_alpha(im)
    print("裁空白后:", im.size)
    im = to_square(im)
    print("补成方形:", im.size)

    frames = {}
    for s in SIZES:
        # 缩小用 LANCZOS；放大同样用 LANCZOS（比 NEAREST/BICUBIC 平滑）
        frames[s] = im.resize((s, s), Image.LANCZOS)

    # ICO：把 256 作为主图，其余尺寸一起塞进去
    frames[256].save(OUT_ICO, format="ICO",
                     sizes=[(s, s) for s in SIZES])
    print("已生成:", OUT_ICO, os.path.getsize(OUT_ICO), "字节")

    # 预览图：浅底 + 深底两行，放大 3~4 倍最近邻展示
    cell, gap = 110, 14
    sheet = Image.new("RGB", (len(SIZES) * (cell - 20) + gap * len(SIZES) + 20,
                              (cell - 20) * 2 + gap * 3 + 20), (245, 247, 251))
    dark = Image.new("RGB", sheet.size, (28, 30, 38))
    for row, bg in ((0, sheet), (1, dark)):
        x = 10
        for s in SIZES:
            z = s if s >= 96 else s * (4 if s <= 32 else 2)
            big = frames[s].resize((z, z), Image.NEAREST)
            bg.paste(big, (x, 10 + row * ((cell - 20) + gap)), big)
            x += z + gap
    sheet.paste(dark, (0, (cell - 20) + gap))
    sheet.save(PREVIEW)
    print("预览:", PREVIEW)


if __name__ == "__main__":
    main()
