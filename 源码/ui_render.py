"""GDI scene snapshots and public buffered-paint alpha composition.

No layered windows, color keys, screen captures, or third-party runtime.
"""
import ctypes as c
from ctypes import wintypes as w

gdi = c.WinDLL('gdi32', use_last_error=True)
gdi.CreateCompatibleDC.argtypes = [c.c_void_p]
gdi.CreateCompatibleDC.restype = c.c_void_p
gdi.CreateCompatibleBitmap.argtypes = [c.c_void_p, c.c_int, c.c_int]
gdi.CreateCompatibleBitmap.restype = c.c_void_p
gdi.SelectObject.argtypes = [c.c_void_p, c.c_void_p]
gdi.SelectObject.restype = c.c_void_p
gdi.DeleteObject.argtypes = [c.c_void_p]
gdi.DeleteDC.argtypes = [c.c_void_p]
gdi.BitBlt.argtypes = [c.c_void_p, c.c_int, c.c_int, c.c_int, c.c_int,
                       c.c_void_p, c.c_int, c.c_int, w.DWORD]


class Blend(c.Structure):
    _fields_ = [('op', c.c_ubyte), ('flags', c.c_ubyte),
                ('alpha', c.c_ubyte), ('format', c.c_ubyte)]


class PaintParams(c.Structure):
    _fields_ = [('size', w.DWORD), ('flags', w.DWORD),
                ('exclude', c.c_void_p), ('blend', c.POINTER(Blend))]


class Surface:
    def __init__(self, target, width, height):
        self.width, self.height = width, height
        self.dc = gdi.CreateCompatibleDC(target)
        self.bitmap = gdi.CreateCompatibleBitmap(target, width, height)
        self.old = gdi.SelectObject(self.dc, self.bitmap)
        if not self.dc or not self.bitmap:
            self.close()
            raise OSError('Cannot allocate scene buffer')

    def copy(self, source):
        return gdi.BitBlt(self.dc, 0, 0, self.width, self.height, source, 0, 0, 0x00CC0020)

    def clone(self):
        out = Surface(self.dc, self.width, self.height)
        out.copy(self.dc)
        return out

    def close(self):
        if self.dc:
            if self.old:
                gdi.SelectObject(self.dc, self.old)
            if self.bitmap:
                gdi.DeleteObject(self.bitmap)
            gdi.DeleteDC(self.dc)
        self.dc = self.bitmap = self.old = None


class DibSurface(Surface):
    class Header(c.Structure):
        _fields_=[('size',w.DWORD),('width',c.c_long),('height',c.c_long),
                  ('planes',w.WORD),('depth',w.WORD),('compression',w.DWORD),
                  ('bytes',w.DWORD),('x',c.c_long),('y',c.c_long),('colors',w.DWORD),('important',w.DWORD)]

    def __init__(self,target,width,height):
        self.width,self.height=width,height
        self.dc=gdi.CreateCompatibleDC(target)
        header=self.Header();header.size=c.sizeof(header)
        header.width,header.height=width,-height
        header.planes,header.depth=1,32
        self.bits=c.c_void_p()
        gdi.CreateDIBSection.argtypes=[c.c_void_p,c.c_void_p,c.c_uint,c.POINTER(c.c_void_p),c.c_void_p,c.c_uint]
        gdi.CreateDIBSection.restype=c.c_void_p
        self.bitmap=gdi.CreateDIBSection(target,c.byref(header),0,c.byref(self.bits),None,0)
        self.old=gdi.SelectObject(self.dc,self.bitmap)
        if not self.bitmap:
            self.close()
            raise OSError('Cannot allocate ARGB scene')

    def clear(self):
        c.memset(self.bits,0,self.width*self.height*4)

    def clone(self):
        result=DibSurface(self.dc,self.width,self.height)
        result.copy(self.dc)
        return result


class Compositor:
    def __init__(self):
        self.theme = self.alpha = None
        self.available = False
        self.frames = 0
        self.last_argb=None
        self.animation_pair=None
        self.animation_canvas=None
        try:
            dll = c.WinDLL('msimg32', use_last_error=True)
            self.alpha = dll.AlphaBlend
            self.alpha.argtypes = [c.c_void_p] + [c.c_int]*4 + [c.c_void_p] + [c.c_int]*4 + [Blend]
            self.alpha.restype = w.BOOL
            theme = c.WinDLL('uxtheme', use_last_error=True)
            theme.BufferedPaintInit.restype = c.c_long
            theme.BeginBufferedPaint.argtypes = [c.c_void_p, c.POINTER(w.RECT), c.c_int,
                                                 c.POINTER(PaintParams), c.POINTER(c.c_void_p)]
            theme.BeginBufferedPaint.restype = c.c_void_p
            theme.EndBufferedPaint.argtypes = [c.c_void_p, w.BOOL]
            theme.EndBufferedPaint.restype = c.c_long
            theme.BufferedPaintSetAlpha.argtypes = [c.c_void_p, c.POINTER(w.RECT), c.c_ubyte]
            theme.BufferedPaintSetAlpha.restype = c.c_long
            theme.GetBufferedPaintBits.argtypes = [c.c_void_p, c.POINTER(c.c_void_p), c.POINTER(c.c_int)]
            theme.GetBufferedPaintBits.restype = c.c_long
            if theme.BufferedPaintInit() == 0:
                self.theme = theme
                self.available = True
        except (OSError, AttributeError):
            pass

    def blend(self, target, source, rect, alpha, dx=0, source_alpha=False):
        if not self.alpha:
            return False
        l, t, r, b = map(int, rect)
        if r <= l or b <= t:
            return True
        return bool(self.alpha(target, l+int(dx), t, r-l, b-t,
                               source, l, t, r-l, b-t, Blend(0, 0, int(alpha), int(source_alpha))))

    def present(self, target, source, width, height, regions, mica, animation=None):
        """Premultiply in native AlphaBlend, then copy ARGB buffer to DWM.

        First normalize legacy GDI pixels to opaque ARGB in a source DIB.
        Then AlphaBlend with AC_SRC_ALPHA calculates premultiplied RGB and alpha.
        Setting only destination alpha would leave RGB unpremultiplied.

        mica=False 时走不透明路径；此时如果文字在独立层里（材质模式），
        必须先把文字合回场景，否则 BitBlt 出去的画面上一个字都没有。
        """
        if not mica:
            layers = getattr(self, 'text_layers', None)
            if layers:
                flat = self.flatten(source, width, height)
                if flat is None:
                    return False
                try:
                    return bool(gdi.BitBlt(target, 0, 0, width, height,
                                           flat.dc, 0, 0, 0x00CC0020))
                finally:
                    flat.close()
            return bool(gdi.BitBlt(target, 0, 0, width, height, source, 0, 0, 0x00CC0020))
        if not self.available:
            return False
        if animation and self.last_argb:
            return self.present_animation(target,source,width,height,animation)
        prepared = self.prepare(source, width, height, regions)
        if prepared is None:
            return False
        rect = w.RECT(0, 0, width, height)
        params = PaintParams(c.sizeof(PaintParams), 1, None, None)
        dc = c.c_void_p()
        buffer = self.theme.BeginBufferedPaint(target, c.byref(rect), 2, c.byref(params), c.byref(dc))
        if not buffer:
            prepared.close()
            return False
        try:
            gdi.BitBlt(dc, 0, 0, width, height, prepared.dc, 0, 0, 0x00CC0020)
            if getattr(self, 'probe_alpha', False):
                self.last_probe = [tuple((c.c_ubyte*4).from_address(prepared.bits.value+4*(y*width+x)))
                    for x,y in ((width-1,0),(min(40,width-1),min(40,height-1)))]
            self.save_argb(prepared.dc,width,height)
            self.frames += 1
        finally:
            prepared.close()
        return self.theme.EndBufferedPaint(buffer, True) == 0

    def save_argb(self,dc,width,height):
        if self.last_argb and (self.last_argb.width,self.last_argb.height)!=(width,height):
            self.last_argb.close();self.last_argb=None
        if self.last_argb is None:
            self.last_argb=DibSurface(dc,width,height)
        self.last_argb.copy(dc)

    def prepare(self,source,width,height,regions):
        """Shape-aware glass: pale surfaces transmit DWM, ink stays opaque.

        Work runs once per endpoint; animated frames only blend cached DIBs.
        Exact canvas pixels remain almost clear, including rounded corners.
        """
        from PIL import Image, ImageChops
        result=DibSurface(source,width,height)
        result.copy(source)
        gdi.GdiFlush()
        rgb=Image.frombytes('RGB',(width,height),c.string_at(result.bits,width*height*4),'raw','BGRX')
        r,g,b=rgb.split()
        light=ImageChops.darker(ImageChops.darker(r,g),b)
        surface={'mica':168,'tabbed':154,'acrylic':140}.get(getattr(self,'material','mica'),168)
        lut=[255 if x<=205 else round(255+(surface-255)*(x-205)/30) if x<235 else surface for x in range(256)]
        alpha=light.point(lut)
        diff=ImageChops.difference(rgb,Image.new('RGB',rgb.size,(241,243,251)))
        dr,dg,db=diff.split()
        canvas=ImageChops.lighter(ImageChops.lighter(dr,dg),db).point([255]+[0]*255)
        alpha.paste(32,mask=canvas)
        rgb.putalpha(alpha)
        rgb=self.overlay_text(rgb,width,height)
        # RGBa performs true premultiplication in Pillow's compiled pixel loop.
        data=rgb.convert('RGBa').tobytes('raw','BGRa')
        c.memmove(result.bits,data,len(data))
        return result

    def overlay_text(self,rgb,width,height):
        """把独立文字层合到场景图上（已经是 RGBA，返回 RGBA）。

        文字当"印在面板上的墨"，**像素一律不透明**。

        为什么不能直接 alpha_composite：面板本身是半透明的（alpha≈168），
        如果把字也做成半透明，笔画边缘的过渡像素就会让壁纸透进来 —— 边缘一像素
        壁纸色、一像素面板色，看上去就是毛刺/锯齿（实色模式没有这个问题，因为
        面板不透明，边缘只跟面板色混合）。所以这里把字的覆盖率只用来跟面板色混合，
        合成后的 alpha 直接拉满，等于"字印在磨砂玻璃上"。

        数学：ink 是"文字色 × 覆盖率"（GDI 在黑底上画的），于是
            out = 文字色*覆盖率 + 面板色*(1-覆盖率) = ink + 面板色*(1-覆盖率)
        两次 LUT + 一次 add，全在 C 层做，单帧只有毫秒级。
        """
        from PIL import Image, ImageChops
        layers=getattr(self,'text_layers',None)
        if not layers:
            return rgb
        sw,sh=layers[0].width,layers[0].height
        coverage=Image.frombytes('RGB',(sw,sh),c.string_at(layers[0].bits,sw*sh*4),'raw','BGRX').getchannel('R')
        ink=Image.frombytes('RGB',(sw,sh),c.string_at(layers[1].bits,sw*sh*4),'raw','BGRX')
        # 文字层是超采样尺寸（见 daily_launcher.TEXT_SS），先缩回原尺寸。
        # reduce(Box) 正好等于「2x2 四个像素取平均」，也就是标准的超采样降采样。
        factor=max(1,sw//width) if width else 1
        if factor>1 and (sw,sh)!=(width,height):
            coverage=coverage.reduce(factor)
            ink=ink.reduce(factor)
        base=rgb.convert('RGB')
        # 面板色按 (1-覆盖率) 衰减，再叠上墨色
        inv=coverage.point(lambda v: 255-v)
        inv=Image.merge('RGB',(inv,inv,inv))
        out=ImageChops.add(ink,ImageChops.multiply(base,inv))
        # 有字的地方 alpha 拉满；没字的地方保留场景原来的透明度（磨砂玻璃）
        inked=coverage.point(lambda v: 255 if v else 0)
        out_alpha=Image.composite(Image.new('L',coverage.size,255),
                                  rgb.getchannel('A'),inked)
        result=out.convert('RGBA')
        result.putalpha(out_alpha)
        return result

    def flatten(self,source,width,height):
        """合成一张不透明画面：场景 + 文字层。给模态弹窗/实色回退用。"""
        from PIL import Image
        result=DibSurface(source,width,height)
        result.copy(source)
        gdi.GdiFlush()
        rgb=Image.frombytes('RGB',(width,height),c.string_at(result.bits,width*height*4),'raw','BGRX')
        # 必须是 alpha=255：DWM 会照 alpha 合成，全 0 的话 BitBlt 出去等于全透明
        rgb=self.overlay_text(rgb.convert('RGBA'),width,height)
        c.memmove(result.bits,rgb.tobytes('raw','BGRA'),width*height*4)
        return result

    def present_animation(self,target,source,width,height,animation):
        generation,progress,offset,regions,kind,split=animation
        if self.animation_pair is None or self.animation_pair[0]!=generation:
            self.finish_animation()
            incoming=self.prepare(source,width,height,regions)
            if incoming is None:
                return False
            self.animation_pair=(generation,self.last_argb.clone(),incoming)
            self.animation_canvas=DibSurface(target,width,height)
        _,old,new=self.animation_pair
        canvas=self.animation_canvas;canvas.clear()
        if kind=='page':
            # Fluent fade-through: one cached ARGB blend per frame, no text/GDI redraw.
            if progress<.3:
                opacity=(1-progress/.3)**2
                self.blend(canvas.dc,old.dc,(0,0,width,height),round(255*opacity),source_alpha=True)
            else:
                opacity=1-(1-(progress-.3)/.7)**3
                self.blend(canvas.dc,new.dc,(0,0,width,height),round(255*opacity),offset,source_alpha=True)
        else:
            self.blend(canvas.dc,old.dc,(0,0,width,height),round(255*(1-progress)),source_alpha=True)
            self.blend(canvas.dc,new.dc,(0,0,width,height),round(255*progress),source_alpha=True)
        # Navigation stays stationary and crisp during page transitions.
        if kind=='page':
            gdi.BitBlt(canvas.dc,0,0,split,height,new.dc,0,0,0x00CC0020)
        rect=w.RECT(0,0,width,height)
        params=PaintParams(c.sizeof(PaintParams),1,None,None)
        dc=c.c_void_p()
        buffer=self.theme.BeginBufferedPaint(target,c.byref(rect),2,c.byref(params),c.byref(dc))
        if not buffer:
            return False
        gdi.BitBlt(dc,0,0,width,height,canvas.dc,0,0,0x00CC0020)
        self.save_argb(canvas.dc,width,height)
        self.frames+=1
        return self.theme.EndBufferedPaint(buffer,True)==0

    def finish_animation(self):
        if self.animation_pair:
            self.animation_pair[1].close();self.animation_pair[2].close()
            self.animation_pair=None
        if self.animation_canvas:
            self.animation_canvas.close();self.animation_canvas=None

    def close(self):
        self.finish_animation()
        if self.last_argb:
            self.last_argb.close();self.last_argb=None
        if self.theme:
            self.theme.BufferedPaintUnInit()
            self.theme = None
        self.available = False
