"""双击卡片图标 = 单独只启动这一项。

最难测的是「窗口类有没有 CS_DBLCLKS」：少了它系统根本不投递
WM_LBUTTONDBLCLK，界面上怎么点都没反应，而且不报错。所以这里发的是
**真实 Win32 消息序列**（DOWN / UP / DBLCLK / UP），不是直接调函数。
"""
import copy
import ctypes as c
import inspect
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '源码'))
import daily_launcher as a          # noqa: E402

CHECKS = 0
FAILED = []


def check(name, ok, detail=""):
    global CHECKS
    CHECKS += 1
    if ok:
        print("PASS: %s" % name)
    else:
        FAILED.append(name)
        print("FAIL: %s  %s" % (name, detail))


BASE = copy.deepcopy(a.DEFAULT_CONFIG)
BASE.update(json.loads((ROOT / 'config.json').read_text(encoding='utf-8-sig')))
BASE.update(ui_motion=False, ui_mica=False, ui_material="solid")
BASE['hidden_items'] = []            # 不依赖用户当前隐藏了谁
a.load_config = lambda: copy.deepcopy(BASE)
a.save_config = lambda _: None
a.save_state = lambda: None
a.App._discover_instances = lambda self: None
a.App._tick_update = lambda self: None
a.STATE.update(last_run_version=a.APP_VERSION)

ui = a.App()
ui.no_auto = ui.no_mutex = True
ui.page = 'main'
hwnd = ui.create()
a.user32.EnableWindow.argtypes = [c.c_void_p, c.c_int]
a.user32.EnableWindow(hwnd, False)
dc = a.user32.GetDC(hwnd)
ui.paint(dc)

DOWN, UP, DBL = 0x0201, 0x0202, 0x0203


def send(msg, x, y, wp=0):
    lp = ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)
    a.user32.SendMessageW(hwnd, msg, wp, lp)


def icon_xy(key):
    l, t, r, b = ui.rects['tiles'][key]
    return l + ui.S(30), t + ui.S(30)


def state_snapshot():
    return {
        'maaend': ui.maaend_on, 'maa': ui.maa_on,
        'maafgo': ui.maafgo_on, 'okww': ui.okww_on,
        'vm0': ui.chk.get(0), 'vm1': ui.chk.get(1),
    }


try:
    # ---- 1. 窗口类必须真的启用了双击 ---------------------------------------
    src = (ROOT / '源码' / 'daily_launcher.py').read_text(encoding='utf-8')
    check("窗口类注册了 CS_DBLCLKS（0x0008）",
          '0x0008' in src and 'wc.style' in src)

    # ---- 2. 命中区：图标可以，勾选框 / 卡片外 / 别的页面不行 ----------------
    ui.paint(dc)
    key = 'maa'
    ix, iy = icon_xy(key)
    check("图标中心能命中", ui.hit_task_icon(ix, iy) == key,
          '%s' % (ui.hit_task_icon(ix, iy),))
    l, t, r, b = ui.rects['tiles'][key]
    check("右上角勾选框不算图标区",
          ui.hit_task_icon(r - ui.S(23), t + ui.S(26)) is None)
    check("卡片外不算", ui.hit_task_icon(ix, ui.rects['card'][1] - 20) is None)
    check("空隙里不算", ui.hit_task_icon(l + ui.S(120), t + ui.S(80)) is None)
    ui.page = 'settings'
    check("别的页面不响应", ui.hit_task_icon(ix, iy) is None)
    ui.page = 'main'
    ui.paint(dc)

    # ---- 3. 真实双击消息序列 ------------------------------------------------
    calls = []
    orig_sole = type(ui).sole_start
    type(ui).sole_start = lambda self, k: calls.append(k)
    try:
        before = state_snapshot()
        x, y = icon_xy('maaend')
        send(DOWN, x, y, 1)
        send(UP, x, y)
        toggled = state_snapshot()
        send(DBL, x, y, 1)
        send(UP, x, y)
        after = state_snapshot()
        check("系统真的投递了 WM_LBUTTONDBLCLK（sole_start 被调用）",
              calls == ['maaend'], str(calls))
        check("第一下单击确实切过勾选（证明消息序列走通）",
              toggled['maaend'] != before['maaend'],
              '%s -> %s' % (before['maaend'], toggled['maaend']))
        check("双击后勾选被还原，不会被悄悄改掉",
              after == before, '%s -> %s' % (before, after))
        check("双击后 pressed 已清空", ui.pressed is None, str(ui.pressed))
    finally:
        type(ui).sole_start = orig_sole

    # 单击一次仍然正常切勾选（没被双击逻辑破坏）
    before = state_snapshot()
    x, y = icon_xy('maa')
    send(DOWN, x, y, 1)
    send(UP, x, y)
    check("单击仍然是切换勾选", state_snapshot()['maa'] != before['maa'])
    send(DOWN, x, y, 1)          # 切回来
    send(UP, x, y)

    # ---- 4. sole_start：白名单 / single / busy / 日志 -----------------------
    log_msgs = []
    ui.emit = lambda kind, *args: log_msgs.append(args[0]) if kind == 'log' else None
    do_calls = []
    orig_do = type(ui).do
    type(ui).do = lambda self, k: do_calls.append(k)
    try:
        ui.busy = False
        ui.sole_start('okww')
        check("sole_start 把 only 限成这一项", ui.run_only == {'okww'}, str(ui.run_only))
        check("sole_start 打开 single 标志", ui.single_run is True)
        check("sole_start 走的是原来的 start 入口", do_calls == ['start'], str(do_calls))
        check("状态栏写明单独启动了谁", 'ok-ww' in ui.status, ui.status)
        check("日志写明其余项本次跳过",
              any('其余项本次跳过' in str(m) for m in log_msgs), str(log_msgs))

        ui.run_only, ui.single_run = None, False
        log_msgs.clear()
        ui.busy = True
        ui.sole_start('maafgo')
        check("正在跑任务时拒绝双击启动",
              ui.run_only is None and ui.single_run is False,
              '%s / %s' % (ui.run_only, ui.single_run))
        check("拒绝时给了明确提示", '正在跑任务' in ui.status, ui.status)
        ui.busy = False

        ui.run_only, ui.single_run = None, False
        ui.sole_start('不存在的项')
        check("双击空白处不会误启动", ui.run_only is None and ui.single_run is False)
    finally:
        type(ui).do = orig_do

    # ---- 5. do("start") 把 single 交给 Runner 并清空 App 侧标志 -------------
    class FakeThread:
        def __init__(self, target=None, daemon=False):
            self.target = target

        def start(self):
            pass

    orig_thread = a.threading.Thread
    a.threading.Thread = FakeThread
    try:
        ui.run_only, ui.single_run = {'vm0'}, True
        ui.busy = False
        ui.runner.only = None
        ui.runner.single = False
        ui.do('start')
        check("Runner.only 收到白名单", ui.runner.only == {'vm0'}, str(ui.runner.only))
        check("Runner.single 收到单项标志", ui.runner.single is True)
        check("App 侧标志用完即清",
              ui.run_only is None and ui.single_run is False)
        ui.runner.only = None
        ui.runner.single = False
    finally:
        a.threading.Thread = orig_thread

    # ---- 6. Runner.run 的 single 分支：不分轮、不空等 -----------------------
    r = a.Runner(copy.deepcopy(BASE), lambda *args: None)
    r.single = True
    r.only = {'maaend'}
    seen = []
    r.hide_deskpets = None
    a.hide_deskpets = lambda cfg, log: seen.append('pet')
    a.restore_deskpets = lambda log: seen.append('restore')
    r.planned_rounds = lambda: (_ for _ in ()).throw(
        AssertionError('单项启动不该去算分轮'))
    r.start_monitor = lambda: False
    r._one_pass = lambda scope=None, monitor=True: seen.append(('pass', scope, monitor))
    r.emit = lambda *args: None
    r.monitor_on = False
    r.run()
    check("single 时直接一趟跑完，没走分轮编排",
          seen == ['pet', ('pass', None, True), 'restore'], str(seen))
    r.single = False

    # ---- 7. tips 与接线静态检查 ---------------------------------------------
    check("界面有双击 tips 文案", '双击图标 · 只跑这一项' in src)
    check("tips 画在全选 chip 左边（draw_shortcuts 内）",
          '双击图标 · 只跑这一项' in inspect.getsource(a.App.draw_shortcuts))
    check("双击分支会还原误切的勾选",
          'self.toggle("chk:" + k)' in src)
    check("文档里说明了为什么绕过分轮",
          '白等到超时' in src or '根本没启动' in src)
finally:
    a.user32.ReleaseDC(hwnd, dc)
    a.user32.DestroyWindow(hwnd)

print("\n%d 项检查，%d 项失败" % (CHECKS, len(FAILED)))
if FAILED:
    print("失败：" + "、".join(FAILED))
    sys.exit(1)
print("全部 PASS")
