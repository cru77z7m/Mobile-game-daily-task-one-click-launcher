# -*- coding: utf-8 -*-
"""把 assets/_tmp 里的原始 png 整理成 96x96 的 .ico，放在 assets/icons/

只处理需要额外加工的两张游戏图标（App Store 的方形底板），
把它们切成圆角，好和 exe 里提取的透明角色头像并排时观感一致。
"""
import io
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
ICON_DIR = os.path.join(SRC, "assets", "icons")
TMP = os.path.join(HERE, "_icon_src")   # 下载的原图，不进 exe

SIZE = 96
RADIUS = 0.24          # 圆角半径 / 边长，接近 iOS squircle 观感


def round_square(im, size=SIZE, radius=RADIUS):
    im = im.convert("RGBA")
    side = int(size * 0.96)
    im = im.resize((side, side), Image.LANCZOS)
    # 圆角遮罩
    mask = Image.new("L", (side * 4, side * 4), 0)
    d = ImageDraw.Draw(mask)
    r = int(side * 4 * radius)
    d.rounded_rectangle([0, 0, side * 4 - 1, side * 4 - 1], radius=r, fill=255)
    mask = mask.resize((side, side), Image.LANCZOS)
    im.putalpha(mask)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(im, ((size - side) // 2, (size - side) // 2), im)
    return canvas


def save_ico(im, name):
    buf = io.BytesIO()
    im.save(buf, format="ICO", sizes=[(SIZE, SIZE)])
    dst = os.path.join(ICON_DIR, name + ".ico")
    with open(dst, "wb") as f:
        f.write(buf.getvalue())
    print("%-11s -> %s (%d B)" % (name, dst, os.path.getsize(dst)))


def make_cfg_icon(size=SIZE):
    """画一个「配置文件」图标：浅蓝圆角底 + 白纸 + 折角 + 三条代码线"""
    S = 4                      # 超采样倍数，缩回去边缘更干净
    n = size * S
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    # 底板
    d.rounded_rectangle([0, 0, n - 1, n - 1], radius=int(n * 0.24), fill=(234, 240, 255, 255))

    # 纸：留出四周约 22% 的边距
    m = int(n * 0.22)
    w = n - m * 2
    fold = int(w * 0.34)
    paper = [m, m, m + w, m + w]
    d.rounded_rectangle(paper, radius=int(n * 0.05), fill=(255, 255, 255, 255))
    # 折角
    d.polygon([(m + w - fold, m), (m + w, m + fold), (m + w - fold, m + fold)],
              fill=(198, 210, 235, 255))
    # 三条线，长度递减
    lx1, lx2 = m + int(w * 0.16), m + w - int(w * 0.16)
    lh = max(2, int(n * 0.045))
    for i, frac in enumerate((1.0, 0.82, 0.55)):
        y = m + int(w * 0.46) + i * int(w * 0.20)
        d.rounded_rectangle([lx1, y, lx1 + int((lx2 - lx1) * frac), y + lh],
                            radius=lh // 2, fill=(120, 140, 176, 255))

    return im.resize((size, size), Image.LANCZOS)


def main():
    jobs = [
        ("arknights.png", "arknights"),   # 实例 0 · 明日方舟
        ("fgo_jp.png", "fgo"),           # 实例 1 · 命运-冠位指定
    ]
    for src, name in jobs:
        p = os.path.join(TMP, src)
        if not os.path.isfile(p):
            print("MISSING", p)
            continue
        save_ico(round_square(Image.open(p)), name)

    save_ico(make_cfg_icon(), "cfg")


if __name__ == "__main__":
    main()
