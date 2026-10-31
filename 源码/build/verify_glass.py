"""Native navigation/ARGB integration checks; no real task or config changes."""
import copy
import ctypes as c
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'源码'))
import daily_launcher as a

cfg=copy.deepcopy(a.DEFAULT_CONFIG)
cfg.update(json.loads((ROOT/'config.json').read_text(encoding='utf-8-sig')))
cfg.update(ui_motion=True, ui_mica=True, ui_material="mica")
a.load_config=lambda:copy.deepcopy(cfg)
a.save_config=lambda _:None
a.save_state=lambda:None
a.App._discover_instances=lambda self:None
a.App._tick_update=lambda self:None
a.LOG_PATH=str(ROOT/'design/navigation-verification.log')
a.STATE.update(last_run_version=a.APP_VERSION)
ui=a.App()
ui.no_auto=ui.no_mutex=True
ui.page='main'
hwnd=ui.create()
a.user32.EnableWindow.argtypes=[c.c_void_p,c.c_int]
a.user32.EnableWindow(hwnd,False)
dc=a.user32.GetDC(hwnd)
out=ROOT/'design/previews/navigation'
out.mkdir(parents=True,exist_ok=True)

def paint():
    ui.paint(dc)
    try: c.windll.dwmapi.DwmFlush()
    except (OSError,AttributeError): pass

def shot(name):
    # Scene frames are exported directly from our renderer, independent of other
    # foreground applications. Material comparison shots use the native window.
    if name.startswith(('enter-', 'modal-')):
        from PIL import Image
        surface=ui._compositor.last_argb if ui.frame_effect in ("mica","tabbed","acrylic") and ui._compositor.last_argb else ui._last_scene
        info=a.BITMAPINFOHEADER()
        info.biSize=c.sizeof(info)
        info.biWidth,info.biHeight=surface.width,-surface.height
        info.biPlanes,info.biBitCount=1,32
        data=c.create_string_buffer(surface.width*surface.height*4)
        a.gdi32.SelectObject(surface.dc,surface.old)
        try:
            assert a.gdi32.GetDIBits(dc,surface.bitmap,0,surface.height,data,c.byref(info),0)
        finally:
            a.gdi32.SelectObject(surface.dc,surface.bitmap)
        path=out/(name+'.png')
        if surface is ui._compositor.last_argb:
            rgba=Image.frombytes('RGBA',(surface.width,surface.height),data.raw,'raw','BGRA')
            straight=Image.frombytes('RGBa',rgba.size,rgba.tobytes()).convert('RGBA')
            Image.alpha_composite(Image.new('RGBA',rgba.size,(241,243,251,255)),straight).convert('RGB').save(path)
        else:
            Image.frombytes('RGB',(surface.width,surface.height),data.raw,'raw','BGRX').save(path)
        return path
    a.user32.SetWindowPos(hwnd,a.wt.HWND(-1),0,0,0,0,0x0001|0x0002|0x0040)
    c.windll.dwmapi.DwmFlush()
    rect=a.wt.RECT()
    a.user32.GetWindowRect(hwnd,c.byref(rect))
    path=out/(name+'.png')
    a.screenshot(str(path),(rect.left,rect.top,rect.right-rect.left,rect.bottom-rect.top))
    return path

def click_nav(page):
    rect=dict(ui.nav_rects())[page]
    x,y=(rect[0]+rect[2])//2,(rect[1]+rect[3])//2
    lp=(y<<16)|x
    a.user32.SendMessageW(hwnd,a.WM_LBUTTONDOWN,1,lp)
    a.user32.SendMessageW(hwnd,a.WM_LBUTTONUP,0,lp)
    assert ui.page==page


from PIL import Image,ImageDraw
from ui_render import DibSurface
import hashlib
out=ROOT/'design/previews/v2.16.2';out.mkdir(exist_ok=True,parents=True)
def pixels(surface):
    a.gdi32.GdiFlush()
    d=DibSurface(dc,surface.width,surface.height);d.copy(surface.dc);a.gdi32.GdiFlush()
    data=c.string_at(d.bits,surface.width*surface.height*4);d.close();return data
try:
    for material in ('mica','tabbed','acrylic','solid'):
        ui.cfg.update(ui_material=material,ui_mica=material!='solid');ui.refresh_effects()
        assert ui.frame_effect==material
        for page in ('main','settings'):
            ui.page=page;ui.finish_transition();paint()
            surf=ui._last_scene if material=='solid' else ui._compositor.last_argb
            data=pixels(surf)
            if material!='solid':
                image=Image.frombytes('RGBa',(surf.width,surf.height),data,'raw','BGRa').convert('RGBA')
                assert image.getpixel((surf.width-1,0))[3]==32
                # Text remains opaque while card interiors reveal the material.
                alphas=image.getchannel('A').getextrema();assert alphas==(32,255),alphas
                bg=Image.new('RGBA',image.size);draw=ImageDraw.Draw(bg)
                for y in range(image.height):
                    q=y/image.height;draw.line((0,y,image.width,y),fill=(round(130+65*q),round(180-35*q),round(225-40*q),255))
                image=Image.alpha_composite(bg,image).convert('RGB')
            else:image=Image.frombytes('RGB',(surf.width,surf.height),data,'raw','BGRX')
            image.save(out/(material+'-'+page+'.png'))
            if material!='solid' and page=='settings':
                layer=ui._glass_text_layers[0]
                # 文字层是超采样尺寸（TEXT_SS 倍），先缩回客户区尺寸再裁
                mask=Image.frombytes('RGB',(layer.width,layer.height),pixels(layer),'raw','BGRX')
                if (layer.width,layer.height)!=(surf.width,surf.height):
                    mask=mask.reduce(max(1,layer.width//surf.width))
                box=(ui.rects['edit'][2]+4,ui.rects['card'][3]+1,ui.rects['card'][2],ui.rects['logcard'][1])
                assert mask.crop(box).getbbox() is None,('scrolling glyphs escaped clip',box)

        # Read the actual solid output DC; cached scene alone hid the previous bug.
        ui.page='main';ui.finish_transition();paint();ui.page='settings'
        old,_,direction=ui._transition;hashes=[]
        for progress in (.08,.5,.85):
            ui._transition=(old,time.monotonic()-.28*progress,direction);paint()
            if material=='solid':
                rc=a.wt.RECT();a.user32.GetClientRect(hwnd,c.byref(rc));tmp=DibSurface(dc,rc.right,rc.bottom);tmp.copy(dc);data=pixels(tmp);tmp.close()
            else:data=pixels(ui._compositor.last_argb)
            hashes.append(hashlib.sha256(data).hexdigest())
        assert len(set(hashes))==3,(material,hashes)
        ui.finish_transition();paint()
        print('PASS:',material,'surface alpha and three distinct presented animation frames')
    for i in range(8):
        ui.cfg['ui_motion']=False;ui.refresh_effects();ui.page='main';paint();assert ui._transition is None
        ui.cfg['ui_motion']=True;ui.refresh_effects();ui.page='settings';paint();assert ui._transition
        ui.finish_transition()
    print('PASS: animation survives eight disable/enable/material refresh cycles')

    # 回归：材质模式下弹窗要盖住页面文字（v2.16.1 的 bug：文字在独立层里，
    # 遮罩盖不住，弹窗上会浮着主界面的字）。
    def client_rgb():
        rc=a.wt.RECT();a.user32.GetClientRect(hwnd,c.byref(rc))
        tmp=DibSurface(dc,rc.right,rc.bottom);tmp.copy(dc);a.gdi32.GdiFlush()
        data=c.string_at(tmp.bits,rc.right*rc.bottom*4);tmp.close()
        return Image.frombytes('RGB',(rc.right,rc.bottom),data,'raw','BGRX')

    def dark(img,box,thr=150):
        return sum(1 for p in img.crop(box).convert('L').getdata() if p<thr)

    for material in ('mica','tabbed','acrylic','solid'):
        ui.cfg.update(ui_material=material,ui_mica=material!='solid');ui.refresh_effects()
        ui.prompt=None;ui.page='main';ui.finish_transition();paint()
        title=ui.rects['title']
        before=dark(client_rgb(),(title[0],title[1],title[2],title[3]))
        assert before>50,(material,'页面标题本应有字',before)
        ui.prompt={'until':time.time()+30,'left':5}
        ui.finish_modal_transition()   # 实色模式会走淡入过渡，这里直接看终态
        paint()
        img=client_rgb()
        after=dark(img,(title[0],title[1],title[2],title[3]))
        assert after==0,(material,'弹窗遮罩没盖住页面文字，残留像素',after)
        dlg=ui.rects['prompt']
        assert dark(img,(dlg[0],dlg[1],dlg[2],dlg[3]))>50,(material,'弹窗自己的字没画出来')
        ui.prompt=None;ui.finish_transition();paint()
    print('PASS: modal covers page text in every material')

finally:
    a.user32.ReleaseDC(hwnd,dc);a.user32.DestroyWindow(hwnd)
