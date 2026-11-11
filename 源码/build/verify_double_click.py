"""双击卡片图标 = 只打开那个程序，不跑任务、不和启动器联动。

两件事最容易写错、也最值得钉死：

1. 窗口类有没有 CS_DBLCLKS —— 少了它系统根本不投递 WM_LBUTTONDBLCLK，
   界面上怎么点都没反应，还不报错。所以这里发的是**真实 Win32 消息序列**。
2. 双击到底有没有偷偷走回启动器的任务链。新语义是「只 spawn 一次 exe，
   **不带任何参数**」：带 --autostart 就等于又去跑任务了，和多选+一键启动重复。
"""
import copy
import ctypes as c
import inspect
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

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


SRC = (ROOT / '源码' / 'daily_launcher.py').read_text(encoding='utf-8')

# 所有「exe」都用临时空文件，避免测试里误启动真实程序
TD = tempfile.mkdtemp(prefix='dbl_')


def fake_exe(name):
    p = os.path.join(TD, name)
    Path(p).write_bytes(b'MZ')
    return p


PATHS = {k: fake_exe(k + '.exe') for k in ('maaend', 'maa', 'maafgo', 'okww')}
GAME, SCRIPT = fake_exe('game.exe'), fake_exe('script.exe')
MUMU = os.path.join(TD, 'MuMu')
os.makedirs(os.path.join(MUMU, 'nx_main'), exist_ok=True)
MGR = os.path.join(MUMU, 'nx_main', 'MuMuManager.exe')
MAIN = os.path.join(MUMU, 'nx_main', 'MuMuNxMain.exe')
Path(MGR).write_bytes(b'MZ')
Path(MAIN).write_bytes(b'MZ')

BASE = copy.deepcopy(a.DEFAULT_CONFIG)
BASE.update(json.loads((ROOT / 'config.json').read_text(encoding='utf-8-sig')))
BASE.update(ui_motion=False, ui_mica=False, ui_material="solid")
BASE['hidden_items'] = []            # 不依赖用户当前隐藏了谁
for _k, _p in PATHS.items():
    BASE.setdefault(_k, {})['path'] = _p
BASE['mumu_root'] = MUMU
BASE['custom_items'] = [
    {'id': 'c1', 'name': '自定义', 'game': GAME, 'script': SCRIPT,
     'enabled': True},
]
a.load_config = lambda: copy.deepcopy(BASE)
a.save_config = lambda _: None
a.save_state = lambda: None
a.App._discover_instances = lambda self: None
a.App._tick_update = lambda self: None
a.STATE.update(last_run_version=a.APP_VERSION)

LAUNCH = copy.deepcopy(BASE)
LAUNCH['maaend'].update(autostart=True, instance='全套日常')
LAUNCH['maa'].update(auto_run=True)
LAUNCH['maafgo'].update(autostart=True)
LAUNCH['okww'].update(task='DailyTask', workdir=TD, python=SCRIPT)

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


orig = {
    'spawn': a.spawn, 'proc_running': a.proc_running,
    'manager_launch': a.manager_launch, 'plain_launch': a.plain_launch,
    'save_config': a.save_config,
}

try:
    # ---- 1. 窗口类必须真的启用了双击 ---------------------------------------
    check("窗口类注册了 CS_DBLCLKS（0x0008）",
          '0x0008' in SRC and 'wc.style' in SRC)

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

    before = state_snapshot()
    x, y = icon_xy('maa')
    send(DOWN, x, y, 1)
    send(UP, x, y)
    check("单击仍然是切换勾选", state_snapshot()['maa'] != before['maa'])
    send(DOWN, x, y, 1)
    send(UP, x, y)

    # 双击分支不看 busy：正在跑任务时也允许「只是把程序打开」
    seg = SRC[SRC.find('if msg == WM_LBUTTONDBLCLK'):]
    seg = seg[:900]
    check("双击分支不再被 busy 拦住", 'not self.busy' not in seg, seg[:200])
    check("双击仍会还原误切的勾选", 'self.toggle("chk:" + k)' in seg)

    # ---- 4. 路径解析：每类卡片只解析出自己那个 exe -------------------------
    for k in ('maaend', 'maa', 'maafgo', 'okww'):
        exes, vm, err = a.plain_launch_targets(LAUNCH, k)
        check("%s 只解析出自己的 exe，不带任何参数" % k,
              exes == [(PATHS[k], TD)] and vm is None and err is None,
              '%s / %s / %s' % (exes, vm, err))
    exes, vm, err = a.plain_launch_targets(LAUNCH, 'okww')
    check("ok-ww 走 ok-ww.exe，不走 pythonw main.py -t DailyTask",
          exes[0][0] == PATHS['okww'] and 'main.py' not in str(exes)
          and '-t' not in str(exes))
    exes, vm, err = a.plain_launch_targets(LAUNCH, 'custom:c1')
    check("自定义项 = 游戏 + 脚本两个路径，顺序正确",
          exes == [(GAME, TD), (SCRIPT, TD)] and vm is None and err is None,
          str(exes))
    exes, vm, err = a.plain_launch_targets(LAUNCH, 'vm1')
    check("模拟器卡只给出实例号，不解析脚本路径",
          exes == [] and vm == 1 and err is None, '%s / %s / %s' % (exes, vm, err))

    bad = copy.deepcopy(LAUNCH)
    bad['maaend'] = {'path': ''}
    check("路径没设会明确报错",
          '路径没设' in (a.plain_launch_targets(bad, 'maaend')[2] or ''))
    bad['maaend'] = {'path': os.path.join(TD, '不存在.exe')}
    check("文件不存在会明确报错",
          '找不到' in (a.plain_launch_targets(bad, 'maaend')[2] or ''))
    bad['mumu_root'] = ''
    check("MuMu 目录没设对会明确报错",
          'MuMu' in (a.plain_launch_targets(bad, 'vm0')[2] or ''))
    check("自定义项被删掉了会明确报错",
          '不存在' in (a.plain_launch_targets(LAUNCH, 'custom:zzz')[2] or ''))
    check("不认识的 key 会明确报错",
          '不认识' in (a.plain_launch_targets(LAUNCH, 'bogus')[2] or ''))

    # ---- 5. 真的执行：spawn 必须无参数 --------------------------------------
    spawned, logs = [], []
    a.spawn = lambda exe, wd, args=None: spawned.append((exe, wd, args))
    a.proc_running = lambda name: False
    a.manager_launch = lambda mgr, idx, timeout=180: (True, '{"errcode":0}')
    n, err = a.plain_launch(LAUNCH, 'maaend', logs.append)
    check("spawn 收到 exe 和工作目录",
          spawned and spawned[0][0] == PATHS['maaend'] and spawned[0][1] == TD,
          str(spawned))
    check("★ spawn 没带任何参数（不会 --autostart / --instance）",
          spawned and spawned[0][2] is None, str(spawned))
    check("返回打开了 1 个程序", n == 1 and err is None, '%s / %s' % (n, err))
    check("日志写明只打开程序、不带任务参数",
          any('不带任务参数' in m for m in logs), str(logs))

    for k in ('maa', 'maafgo', 'okww'):
        spawned.clear()
        logs.clear()
        n, err = a.plain_launch(LAUNCH, k, logs.append)
        check("%s 也是无参数打开，配置里的 auto_run/autostart 没被理睬" % k,
              n == 1 and len(spawned) == 1 and spawned[0][2] is None
              and spawned[0][0] == PATHS[k], str(spawned))

    spawned.clear()
    logs.clear()
    n, err = a.plain_launch(LAUNCH, 'custom:c1', logs.append)
    check("自定义项两个程序都打开、都无参数",
          n == 2 and len(spawned) == 2
          and all(x[2] is None for x in spawned), str(spawned))

    spawned.clear()
    logs.clear()
    n, err = a.plain_launch(LAUNCH, 'vm1', logs.append)
    check("模拟器走 MuMuManager IPC，不去 spawn 脚本",
          n == 1 and spawned == [] and err is None, str(spawned))
    a.manager_launch = lambda mgr, idx, timeout=180: (False, 'errcode -503')
    spawned.clear()
    n, err = a.plain_launch(LAUNCH, 'vm0', logs.append)
    check("IPC 失败时兜底直接拉主程序（只带 -v 实例号）",
          n == 1 and len(spawned) == 1 and spawned[0][2] == ['-v', '0'],
          str(spawned))
    a.manager_launch = lambda mgr, idx, timeout=180: (True, '{"errcode":0}')

    a.proc_running = lambda name: True
    spawned.clear()
    logs.clear()
    n, err = a.plain_launch(LAUNCH, 'maaend', logs.append)
    check("程序已在运行时不重复打开",
          n == 0 and spawned == [] and any('已在运行' in m for m in logs),
          '%s / %s' % (spawned, logs))

    a.proc_running = lambda name: False
    def boom(*_a, **_k):
        raise OSError('模拟启动失败')
    a.spawn = boom
    logs.clear()
    n, err = a.plain_launch(LAUNCH, 'maaend', logs.append)
    check("启动异常不会冒到界面，只写日志",
          n == 0 and any('失败' in m for m in logs), str(logs))

    # ---- 6. plain_launch 不含任何「任务链」调用 ------------------------------
    plsrc = inspect.getsource(a.plain_launch)
    for bad_call in ('preflight(', 'sync_instances(', 'maa_apply_config(',
                     'start_monitor(', 'hide_deskpets(',
                     'close_hypergryph_launcher(', 'self.step(', 'baseline[',
                     'wait_maaend_done(', 'maafgo_sync_device('):
        check("plain_launch 不碰任务链的 %s" % bad_call, bad_call not in plsrc)
    check("源码里双击相关不再有 --autostart 参数拼接",
          'args.append("--autostart")' not in plsrc)

    # ---- 7. sole_start 完全不联动启动器 --------------------------------------
    logs.clear()
    ui.ui_log = logs.append
    a.plain_launch = lambda cfg, k, log=None: (1, None)
    do_calls = []
    orig_do = type(ui).do
    type(ui).do = lambda self, k: do_calls.append(k)
    save_calls = []
    a.save_config = lambda cc: save_calls.append(cc)
    try:
        ui.busy = True                 # 故意设成忙：双击只是打开程序，不该被拦
        ui.run_only = None
        ui.status = ''
        ui.sole_start('okww')
        check("busy 时双击照样打开程序（不联动）",
              ui.busy is True and '已打开程序' in ui.status, ui.status)
        check("没有走 do('start')", do_calls == [], str(do_calls))
        check("没有设置 only 白名单", ui.run_only is None, str(ui.run_only))
        check("状态栏写明未启动任务", '未启动任务' in ui.status, ui.status)
        check("日志写明没改勾选和配置",
              any('没改勾选和配置' in m for m in logs), str(logs))
        check("没有写 config.json", save_calls == [], str(save_calls))

        logs.clear()
        a.plain_launch = lambda cfg, k, log=None: (0, '找不到 xxx.exe')
        ui.status = ''
        ui.sole_start('maa')
        check("打不开时不假装成功", '没能打开' in ui.status, ui.status)
        check("打不开时把原因写进日志",
              any('找不到 xxx.exe' in m for m in logs), str(logs))

        logs.clear()
        ui.status = '保持原样'
        ui.sole_start('不存在的项')
        check("双击空白/未知项不会误启动",
              ui.status == '保持原样' and logs == [], str(logs))
    finally:
        type(ui).do = orig_do
        ui.busy = False

    # ---- 8. single 机制已彻底删除 -------------------------------------------
    r = a.Runner(copy.deepcopy(BASE), lambda *args: None)
    check("Runner 不再有 single 字段", not hasattr(r, 'single'))
    check("Runner.run 源码里没有 single 分支",
          'self.single' not in inspect.getsource(a.Runner.run))
    check("App 不再有 single_run 字段", 'single_run' not in SRC)
    check("do('start') 不再传 single", 'runner.single' not in SRC)
    check("run_only 仍保留（夜间启动还要用）", 'self.run_only' in SRC)

    # ---- 9. tips 文案与文档 --------------------------------------------------
    check("tips 改成「只打开程序」", '双击图标 · 只打开程序' in SRC)
    check("旧文案「只跑这一项」已清除", '只跑这一项' not in SRC)
    check("tips 仍画在全选 chip 左边",
          '双击图标 · 只打开程序' in inspect.getsource(a.App.draw_shortcuts))
    rd = (ROOT / 'README.md').read_text(encoding='utf-8')
    check("README 写明双击只打开程序、不跑任务",
          '只打开程序' in rd and '不跑任务' in rd)
finally:
    a.user32.ReleaseDC(hwnd, dc)
    a.user32.DestroyWindow(hwnd)
    a.spawn = orig['spawn']
    a.proc_running = orig['proc_running']
    a.manager_launch = orig['manager_launch']
    a.plain_launch = orig['plain_launch']
    a.save_config = orig['save_config']
    shutil.rmtree(TD, ignore_errors=True)

print("\n%d 项检查，%d 项失败" % (CHECKS, len(FAILED)))
if FAILED:
    print("失败：" + "、".join(FAILED))
    sys.exit(1)
print("全部 PASS")
