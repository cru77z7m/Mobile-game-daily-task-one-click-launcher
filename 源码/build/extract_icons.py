# -*- coding: utf-8 -*-
"""从 exe 里提取图标，统一裁成 64x64 的单帧 .ico，放到 源码/assets/icons/

用法：
    python extract_icons.py           # 提取全部
    python extract_icons.py --list    # 只列出各 exe 有哪些尺寸

为什么不走 Win32：
  FindResourceW 在 LoadLibraryEx(LOAD_LIBRARY_AS_DATAFILE) 拿到的句柄上会返回
  ERROR_RESOURCE_TYPE_NOT_FOUND(1813)，即使 EnumResourceNames 刚枚举出过那些 ID。
  所以这里直接解析 PE 的 .rsrc 段，反而更稳，也不需要管理员。
"""
import io
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
OUT_DIR = os.path.join(SRC, "assets", "icons")

RT_ICON = 3
RT_GROUP_ICON = 14


# ---------------------------------------------------------------------------
# 极简 PE 解析：只为了拿到资源段
# ---------------------------------------------------------------------------
def _u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


class PE(object):
    def __init__(self, data):
        self.d = data
        if data[:2] != b"MZ":
            raise ValueError("不是 PE 文件")
        e = _u32(data, 0x3C)
        if data[e:e + 4] != b"PE\0\0":
            raise ValueError("PE 头不对")
        coff = e + 4
        nsec = _u16(data, coff + 2)
        opt_size = _u16(data, coff + 16)
        opt = coff + 20
        magic = _u16(data, opt)
        dd = opt + (96 if magic == 0x10B else 112)
        self.res_rva = _u32(data, dd + 2 * 8)
        self.res_size = _u32(data, dd + 2 * 8 + 4)
        self.sections = []
        s = opt + opt_size
        for i in range(nsec):
            base = s + i * 40
            vsize = _u32(data, base + 8)
            va = _u32(data, base + 12)
            rsize = _u32(data, base + 16)
            rptr = _u32(data, base + 20)
            self.sections.append((va, max(vsize, rsize), rptr))

    def off(self, rva):
        for va, size, rptr in self.sections:
            if va <= rva < va + size:
                return rva - va + rptr
        raise ValueError("RVA 不在任何段内: %#x" % rva)

    # -- 资源树遍历 -----------------------------------------------------------
    def _dir(self, base):
        """返回 [(id_or_None, is_dir, value)]"""
        out = []
        named, ids = _u16(self.d, base + 12), _u16(self.d, base + 14)
        for i in range(named + ids):
            o = base + 16 + i * 8
            name = _u32(self.d, o)
            val = _u32(self.d, o + 4)
            out.append((None if name & 0x80000000 else name,
                        bool(val & 0x80000000), val & 0x7FFFFFFF))
        return out

    def resources(self, rtype):
        """{name_id: bytes}"""
        if not self.res_rva:
            return {}
        root = self.off(self.res_rva)
        res = {}
        for tid, is_dir, val in self._dir(root):
            if not is_dir or tid != rtype:
                continue
            for nid, is_dir2, val2 in self._dir(root + val):
                if not is_dir2 or nid is None:
                    continue
                for _lid, is_dir3, val3 in self._dir(root + val2):
                    if is_dir3:
                        continue
                    de = root + val3
                    rva = _u32(self.d, de)
                    size = _u32(self.d, de + 4)
                    res[nid] = self.d[self.off(rva):self.off(rva) + size]
                    break   # 只取第一种语言
        return res


# ---------------------------------------------------------------------------
# 组图标 -> ICO
# ---------------------------------------------------------------------------
def group_icons(path):
    """返回 [(w, h, ico_bytes)]，按尺寸从大到小"""
    pe = PE(open(path, "rb").read())
    images = pe.resources(RT_ICON)
    groups = pe.resources(RT_GROUP_ICON)
    out = []
    for _gid, grp in groups.items():
        if len(grp) < 6:
            continue
        _r, _t, count = struct.unpack_from("<HHH", grp, 0)
        parts = []
        for i in range(count):
            off = 6 + i * 14
            if off + 14 > len(grp):
                break
            bw, bh, cc, _rsv, planes, bpp, _nb, nid = struct.unpack_from(
                "<BBBBHHIH", grp, off)
            img = images.get(nid)
            if not img:
                continue
            parts.append((bw or 256, bh or 256, cc, planes, bpp, img))
        if not parts:
            continue
        head = struct.pack("<HHH", 0, 1, len(parts))
        dirs, body = b"", b""
        offset = 6 + 16 * len(parts)
        for (w, h, cc, planes, bpp, img) in parts:
            dirs += struct.pack("<BBBBHHII", 0 if w >= 256 else w,
                                0 if h >= 256 else h, cc, 0, planes, bpp,
                                len(img), offset + len(body))
            body += img
        out.append((max(p[0] for p in parts), max(p[1] for p in parts),
                    head + dirs + body))
    out.sort(key=lambda x: -x[0])
    return out


def to_square_ico(ico_bytes, size=64):
    """取最大一帧，等比缩到 size×size 后居中（非正方形不拉扁）"""
    from PIL import Image
    im = Image.open(io.BytesIO(ico_bytes)).convert("RGBA")
    im.thumbnail((size, size), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(im, ((size - im.width) // 2, (size - im.height) // 2), im)
    buf = io.BytesIO()
    canvas.save(buf, format="ICO", sizes=[(size, size)])
    return buf.getvalue()


def png_to_ico(png_path, size=64, pad=0.92):
    """网图/生成图 -> 正方形 ico；pad 控制留白比例（1.0 顶满）"""
    from PIL import Image
    im = Image.open(png_path).convert("RGBA")
    side = int(size * pad)
    im.thumbnail((side, side), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(im, ((size - im.width) // 2, (size - im.height) // 2), im)
    buf = io.BytesIO()
    canvas.save(buf, format="ICO", sizes=[(size, size)])
    return buf.getvalue()


TARGETS = [
    ("maaend", r"D:\Download\MaaEnd-win-x86_64-v2.3.0\MaaEnd.exe"),
    ("maa", r"G:\qq\1121382008\FileRecv\MAA-v6.16.3-win-x64\MAA.exe"),
    ("maafgo", r"D:\Download\MaaFgo-win-x86_64-v2.0.10-MXU\MaaFgo.exe"),
    ("okww", r"D:\Download\ok-ww\ok-ww.exe"),
    ("launcher", r"D:\tools\一键日常启动器\一键日常启动器.exe"),
]


def main():
    only_list = "--list" in sys.argv
    if not only_list:
        os.makedirs(OUT_DIR, exist_ok=True)
    for key, path in TARGETS:
        if not os.path.isfile(path):
            print("%-8s MISSING %s" % (key, path))
            continue
        try:
            icons = group_icons(path)
        except Exception as e:
            print("%-8s ERR %s" % (key, e))
            continue
        if not icons:
            print("%-8s 没有图标资源" % key)
            continue
        sizes = sorted({(w, h) for w, h, _b in icons}, reverse=True)
        if only_list:
            print("%-8s 尺寸: %s" % (key, sizes))
            continue
        w, h, raw = icons[0]
        ico = to_square_ico(raw, 64)
        dst = os.path.join(OUT_DIR, key + ".ico")
        with open(dst, "wb") as f:
            f.write(ico)
        print("%-8s 取 %dx%d -> %s.ico (%d B)" % (key, w, h, key, len(ico)))


if __name__ == "__main__":
    main()
