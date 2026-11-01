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
cfg['custom_items']=[{'id':'demo','name':'自定义 · 测试脚本','enabled':True,'script':'','game':''},
 {'id':'off','name':'未勾选的自定义项目','enabled':False,'script':'','game':''},
 {'id':'hidden','name':'已隐藏项目','enabled':True,'script':'','game':''}]
cfg['hidden_items']=list(cfg.get('hidden_items',[]))+['custom:hidden']
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

from unittest.mock import patch
out=ROOT/'design/previews/round-dropdown';out.mkdir(exist_ok=True,parents=True)
try:
    ui.cfg.update(ui_material='solid',ui_mica=False);ui.refresh_effects();ui.page='tasks';ui.task_view='rounds';ui.finish_transition();paint()
    keys=ui.rects['task_controls']
    assert 'pl:custom:demo' in keys and 'pl:custom:off' in keys
    assert 'pl:custom:hidden' not in keys
    assert ui.pipeline_round_options()==['不参与（本次不启动）','第 1 轮','第 2 轮','第 3 轮','第 4 轮']
    u=a.user32;u.GetMenuItemCount.argtypes=[c.c_void_p];u.GetMenuItemCount.restype=c.c_int
    u.GetMenuState.argtypes=[c.c_void_p,c.c_uint,c.c_uint];u.GetMenuState.restype=c.c_uint
    captured=[]
    def select_four(menu,*args):
        assert u.GetMenuItemCount(menu)==5
        assert u.GetMenuState(menu,2,0)&8 # current=round 1, command id=2
        captured.append(menu);return 5 # directly choose round 4
    with patch.object(u,'TrackPopupMenuEx',select_four):
        assert ui.round_popup('custom:demo',1)==4
    assert u.GetMenuItemCount(captured[0])==-1 # menu destroyed
    with patch.object(u,'TrackPopupMenuEx',lambda *args:0):
        assert ui.round_popup('custom:demo',0) is None
    # Route actual WM click through the same UI handler, selecting round 4 directly.
    ui.round_popup=lambda raw,current:4
    ui.scroll=max(0,(ui.rects['task_controls']['pl:custom:demo'][1]-ui.rects['card'][1])//ui.S(1)-90);paint()
    click(ui.rects['task_controls']['pl:custom:demo']);paint()
    assert ui.cfg['pipeline']['assign']['custom:demo']==4
    assert 'custom:demo' in ui.cfg['pipeline']['order'] and ui.cfg['pipeline']['enabled']
    assert any('custom:demo' in rd for rd in ui.task_preview_rounds())
    before=copy.deepcopy(ui.cfg);ui.round_popup=lambda raw,current:None
    click(ui.rects['task_controls']['pl:custom:demo']);paint();assert ui.cfg==before
    ui.set_pipeline_round('custom:off',2)
    assert not any('custom:off' in rd for rd in ui.task_preview_rounds())
    ui.cfg['pipeline']['enabled']=False
    ui.set_pipeline_round('custom:demo',0)
    assert ui.cfg['pipeline']['enabled']
    assert 'custom:demo' not in ui.cfg['pipeline']['assign']
    ui.set_pipeline_round('custom:demo',4);paint();shot('custom-projects')
    # Current selected rounds survive serialization; no external tasks execute.
    recovered=json.loads(json.dumps(ui.cfg));assert recovered['pipeline']['assign']['custom:demo']==4
    for bad in (-1,5,'2',None):
        before=copy.deepcopy(ui.cfg);ui.set_pipeline_round('custom:demo',bad);assert before==ui.cfg
    cfg_empty=copy.deepcopy(cfg);cfg_empty['pipeline']={'enabled':True,'assign':{},'order':[]}
    events=[];calls=[];runner=a.Runner(cfg_empty,lambda *x:events.append(x))
    runner.log=lambda *x:None;runner._one_pass=lambda only,**kwargs:calls.append(only)
    runner.run();assert calls==[] and runner.planned_rounds()==[]
    cfg_empty['pipeline']['enabled']=False;runner.run();assert calls==[None]
    print('PASS: enabled empty plan starts nothing; disabled plan retains original launch path')
    print('PASS: native 5-item menu/current checkmark/cancel/destruction; direct round-4 WM click; custom visible/hidden/unchecked; serialization; invalid values')
finally:
    a.user32.ReleaseDC(hwnd,dc);a.user32.DestroyWindow(hwnd)
