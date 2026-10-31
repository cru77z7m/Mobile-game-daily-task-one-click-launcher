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

try:
    paint()
    ui._compositor.probe_alpha=True
    paint()
    probe=ui._compositor.last_probe
    assert 0<probe[0][3]<probe[1][3]<255,probe
    assert all(max(pixel[:3])<=pixel[3] for pixel in probe),probe
    print('PASS: actual ARGB buffer has translucent, premultiplied background/panel pixels',probe)
    # Tile hit-testing must distinguish left/right cards on the same row.
    for key,rect in ui.rects['tiles'].items():
        assert ui.hit((rect[0]+rect[2])//2,(rect[1]+rect[3])//2)=='chk:'+key
    assert ui.hit(ui.S(60),ui.S(510)) is None
    print('PASS: both task columns and sidebar whitespace hit-testing')
    click_nav('settings')
    assert ui._transition is not None and ui._transition[2]==1
    frames=[]
    previous,_,direction=ui._transition
    for i in range(11):
        ui._transition=(previous,time.monotonic()-0.28*(i/10),direction)
        paint()
        frames.append(shot('enter-%02d'%i))
    assert ui._transition is None
    click_nav('main')
    assert ui._transition is not None and ui._transition[2]==-1
    paint()
    # Rapid reversal clones the currently displayed scene rather than flashing.
    click_nav('about')
    assert ui._transition is not None
    ui.finish_transition()
    paint()
    ui.motion_allowed=False
    click_nav('settings')
    assert ui._transition is None
    ui.motion_allowed=True
    ui.cfg['ui_motion']=False
    click_nav('main')
    assert ui._transition is None
    ui.cfg['ui_motion']=True
    print('PASS: actual WM_LBUTTON navigation, forward/back, reversal, reduced motion')
    # Warm caches on every page before counting native resources.
    for pg in ('main','settings','custom','night','tasks','about'):
        ui.page=pg
        ui.finish_transition()
        paint()
    a.user32.GetGuiResources.argtypes=[c.c_void_p,c.c_uint]
    before=a.user32.GetGuiResources(c.c_void_p(-1),0)
    for _ in range(12):
        for pg in ('main','settings','about'):
            ui.page=pg
            paint()
            if ui._transition:
                old,_,direction=ui._transition
                ui._transition=(old,time.monotonic()-.29,direction)
                paint()
    after=a.user32.GetGuiResources(c.c_void_p(-1),0)
    assert after<=before+2,(before,after)
    print('PASS: 36 page transitions; GDI handles %d -> %d'%(before,after))
    ui.page='main'
    ui.finish_transition()
    # Compare real native material enabled vs fully opaque fallback.
    paint()
    assert ui.frame_effect=='mica',ui.frame_effect
    shot('mica-enabled')
    ui.frame_effect=a.apply_native_frame(hwnd,False)
    assert ui.frame_effect=='solid'
    paint()
    shot('opaque-fallback')
    ui.frame_effect=a.apply_native_frame(hwnd,True,19045)
    assert ui.frame_effect=='unsupported'
    paint()
    shot('win10-branch')
    ui.frame_effect=a.apply_native_frame(hwnd,True)
    ui._compositor.available=False
    paint()
    assert ui.frame_effect=='solid'
    ui._compositor.available=True
    print('PASS: full-client Mica + disabled + simulated Win10 opaque rendering')
    from PIL import Image
    images=[Image.open(path).convert('RGB') for path in frames]
    assert images[0].tobytes()!=images[-1].tobytes()
    images[0].save(ROOT/'design/previews/page-transition.gif',save_all=True,
                   append_images=images[1:],duration=[600]+[28]*9+[1000],loop=0)
    print('Saved renderer transition frames and GIF; native material comparison screenshots')

    # Refinement regressions: sidebar owns module navigation; About is a flow document.
    forbidden={'custom_page','night_page','task_page','about_page','sec:about','sec:more'}
    assert not forbidden.intersection(row['key'] for row in ui.settings_rows())
    for dpi in (96,120,144,168,192):
        ui.dpi=dpi
        for height in (640,780):
            ui.page='about'
            ui.finish_transition()
            ui.layout(ui.S(960),ui.S(height))
            g,blocks,links=ui._about
            for _,rect,rows in blocks:
                assert rows[0][3][1]>=rect[1]+36
                assert rows[-1][3][3]<=rect[3]-10
                for row,next_row in zip(rows,rows[1:]):
                    assert row[3][3]<=next_row[3][1]
            assert g['cfg'][1]>blocks[-1][1][3]
            assert g['hint'][1]>=g['cfg'][3]
            ui.scroll=ui._scroll_max
            ui.layout(ui.S(960),ui.S(height))
            assert ui._about[0]['hint'][3]<=ui.rects['card'][3]/(dpi/96)
    ui.dpi=168
    ui.page='main'
    ui.finish_transition()
    paint()
    hero=ui.rects['hero']
    assert ui.hit(hero[2]-ui.S(80),hero[1]+ui.S(40)) is None
    print('PASS: settings deduplication, decorative slogan hit, About flow at five DPIs/two heights')

    # Opening/closing work on prompt assignment, including timeout and cancel paths.
    ui.frame_effect=a.apply_native_frame(hwnd,True)
    # v2.16.2：材质模式下弹窗不淡入，直接不透明呈现
    ui.prompt={'until':time.time()+600,'left':5}
    assert ui._modal_transition is None
    paint()
    shot('modal-instant')
    ui.prompt=None
    ui.finish_modal_transition()
    paint()
    # 实色模式保留 220ms 过渡，逐帧导出
    ui.cfg.update(ui_material='solid',ui_mica=False)
    ui.refresh_effects()
    paint()
    modal_frames=[]
    ui.prompt={'until':time.time()+600,'left':5}
    assert ui._modal_transition and ui._modal_transition[2]
    old,_,opening,dialog=ui._modal_transition
    for i in range(7):
        ui._modal_transition=(old,time.monotonic()-.22*(i/6),opening,dialog)
        paint()
        modal_frames.append(shot('modal-open-%02d'%i))
    assert ui._modal_transition is None
    ui.answer_prompt(False)
    assert ui.prompt is None and ui._modal_transition and not ui._modal_transition[2]
    assert ui.hit(ui.rects['start'][0]+5,ui.rects['start'][1]+5)=='modal_transition'
    old,_,opening,dialog=ui._modal_transition
    for i in range(7):
        ui._modal_transition=(old,time.monotonic()-.22*(i/6),opening,dialog)
        paint()
        modal_frames.append(shot('modal-close-%02d'%i))
    assert ui._modal_transition is None
    saved_do=ui.do
    actions=[]
    ui.do=lambda key:actions.append(key)
    ui.prompt={'until':time.time()-1,'left':0}
    ui.finish_modal_transition()
    paint()
    ui._tick_prompt()
    ui._tick_prompt()
    assert actions==['start'],actions
    assert ui._modal_transition and not ui._modal_transition[2]
    ui.do=saved_do
    ui.finish_modal_transition()
    paint()
    # 回到材质模式跑 16 轮：这一步会反复走「合并不透明画面」的新路径，专门盯 GDI 泄漏
    ui.cfg.update(ui_material='mica',ui_mica=True)
    ui.refresh_effects()
    paint()
    before=a.user32.GetGuiResources(c.c_void_p(-1),0)
    for _ in range(16):
        ui.prompt={'until':time.time()+600,'left':5}
        paint()
        ui.finish_modal_transition()
        paint()
        ui.prompt=None
        paint()
        ui.finish_modal_transition()
        paint()
    after=a.user32.GetGuiResources(c.c_void_p(-1),0)
    assert after<=before+2,(before,after)
    ui.cfg['ui_motion']=False
    ui.prompt={'until':time.time()+600,'left':5}
    assert ui._modal_transition is None
    ui.prompt=None
    assert ui._modal_transition is None
    ui.cfg['ui_motion']=True
    images=[Image.open(path).convert('RGB') for path in modal_frames]
    images[0].save(ROOT/'design/previews/startup-dialog-transition.gif',save_all=True,
                   append_images=images[1:],duration=[500]+[36]*5+[700]+[36]*6+[900],loop=0)
    print('PASS: popup opening/cancel/timeout exactly once/reduced motion; 16 cycles GDI %d -> %d'%(before,after))
    # v2.16: all three startup choices, action labels and native material enum values.
    assert dict((r['key'],r.get('icon')) for r in ui.task_rows())['t_hint']=='ui_info'
    assert dict((r['key'],r.get('icon')) for r in ui.task_rows())['t_reset']=='ui_update'
    assert dict((p,title) for p,_,title in ui.NAV)['tasks']=='安排自动任务'
    for name,number in [('mica',2),('tabbed',4),('acrylic',3),('solid',1)]:
        ui.cfg.update(ui_material=name,ui_mica=name!='solid')
        ui.refresh_effects()
        assert ui.frame_effect==name,(name,ui.frame_effect)
        getter=c.windll.dwmapi.DwmGetWindowAttribute
        getter.argtypes=[c.c_void_p,c.c_uint,c.c_void_p,c.c_uint]
        value=c.c_int()
        assert getter(hwnd,38,c.byref(value),c.sizeof(value))==0
        assert value.value==number,(name,value.value)
    ui.cfg.update(ui_material='mica',ui_mica=True,ui_motion=True);ui.refresh_effects()
    row=next(row for row in ui.settings_rows() if row['key']=='ui_motion')
    assert ui.setting_button(row)[:2]==('当前：开启','点击关闭')
    ui.pick_row('ui_motion')
    assert ui.setting_button(row)[:2]==('当前：关闭','点击开启')
    ui.pick_row('ui_motion')
    saved_do=ui.do;saved_night=ui.night_start;choices=[]
    ui.do=lambda key:choices.append(key)
    ui.night_start=lambda:choices.append('night')
    for key,expected in [('prompt_all','start'),('prompt_night','night'),('prompt_cancel',None)]:
        choices.clear();ui.prompt={'until':time.time()+600,'left':5}
        ui.finish_modal_transition();paint()
        rect=ui.rects[key]
        assert ui.hit((rect[0]+rect[2])//2,(rect[1]+rect[3])//2)==key
        saved_do(key);ui._tick_prompt()
        assert choices==([] if expected is None else [expected]),(key,choices)
        ui.finish_modal_transition();paint()
    ui.do=saved_do;ui.night_start=saved_night
    ui.finish_transition();ui.finish_modal_transition()
    assert not ui._animation_clock.active
    print('PASS: native Mica/Tabbed/Acrylic/Solid enums; state/action labels; three startup choices; clock cleanup')
finally:
    a.user32.ReleaseDC(hwnd,dc)
    a.user32.DestroyWindow(hwnd)
