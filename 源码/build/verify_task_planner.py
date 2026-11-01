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
# 窗口必须落在工作区里：任务栏放顶部时，用整屏尺寸算 y 会把标题栏压到任务栏底下
work=a.wt.RECT()
a.user32.SystemParametersInfoW(0x0030,0,c.byref(work),0)
if work.right>work.left and work.bottom>work.top:
    r=a.wt.RECT()
    a.user32.GetWindowRect(hwnd,c.byref(r))
    assert r.left>=work.left and r.top>=work.top,(r.left,r.top,work.left,work.top)
    assert r.right<=work.right and r.bottom<=work.bottom,(r.right,r.bottom,work.right,work.bottom)
    print('PASS: window inside work area (%d,%d)-(%d,%d)'%(work.left,work.top,work.right,work.bottom))
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


import copy
out=ROOT/'design/previews/task-planner';out.mkdir(parents=True,exist_ok=True)
def click(rect):
    x,y=(rect[0]+rect[2])//2,(rect[1]+rect[3])//2
    lp=(y<<16)|x
    a.user32.SendMessageW(hwnd,a.WM_LBUTTONDOWN,1,lp);a.user32.SendMessageW(hwnd,a.WM_LBUTTONUP,0,lp)
try:
    ui.cfg.update(ui_material='solid',ui_mica=False);ui.refresh_effects();ui.page='tasks';ui.finish_transition();paint()
    assert getattr(ui,'task_view','scripts')=='scripts'
    assert len([g for g in ui.rects['task_groups'] if g[0]=='tool'])==4
    assert not any(it['key'].startswith('pl:') for it,_,_ in ui.rects['rows'])
    shot('scripts')
    old=ui.cfg['maa'].get('auto_run',True)
    click(ui.rects['task_controls']['t_flag:maa.auto_run']);paint()
    assert ui.cfg['maa']['auto_run']!=old
    # Side by side controls must never route to the same row by y alone.
    for key,q in ui.rects['task_controls'].items():
        if q[1]>=ui.rects['card'][1] and q[3]<=ui.rects['card'][3] and key not in ui.rects['disabled_rows']:
            assert ui.hit((q[0]+q[2])//2,(q[1]+q[3])//2)=='set:'+key,key
    click(ui.rects['task_tabs']['rounds']);paint()
    assert ui.task_view=='rounds' and ui.page=='tasks'
    assert not any(it['key'].startswith('t_flag:') for it,_,_ in ui.rects['rows'])
    ui.cfg.setdefault('pipeline',{})['enabled']=False;paint()
    opened=[];a.pick_folder=lambda *args:opened.append(1)
    click(ui.rects['task_controls']['pl_enabled']);paint()
    assert ui.cfg['pipeline']['enabled'] and not opened
    ui.round_popup=lambda raw,current:4
    q=ui.rects['task_controls']['pl:maa'];before=ui.cfg['pipeline']['assign'].get('maa',0);click(q);paint()
    assert ui.cfg['pipeline']['assign'].get('maa',0)==4
    shot('rounds')
    ui.scroll=ui._scroll_max;paint();shot('rounds-bottom')
    for material in ('mica','tabbed','acrylic'):
        ui.cfg.update(ui_material=material,ui_mica=True);ui.refresh_effects()
        for view in ('scripts','rounds'):
            ui.task_view=view;ui.scroll=0;paint();assert ui.frame_effect==material
            shot(material+'-'+view)
    for dpi in (96,120,144,168,192):
        ui.dpi=dpi
        for view in ('scripts','rounds'):
            ui.task_view=view;ui.scroll=0;ui.layout(ui.S(960),ui.S(640))
            assert ui.rects['card'][3]<ui.rects['edit'][1]<ui.rects['logcard'][1]
            qs=list(ui.rects['task_controls'].values())
            for i,q in enumerate(qs):
                assert q[2]-q[0]>ui.S(260)
                for other in qs[i+1:]:
                    assert max(q[0],other[0])>=min(q[2],other[2]) or max(q[1],other[1])>=min(q[3],other[3])
    print('PASS: four tool cards, separate views, real native clicks, left/right hit tests, round assignment, five DPIs')
finally:
    a.user32.ReleaseDC(hwnd,dc);a.user32.DestroyWindow(hwnd)
