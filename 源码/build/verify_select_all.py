"""全选按钮的作用范围：只能动「日常控制台里看得见的那些」，隐藏项一个都不许碰。

这条以前没测过 —— toggle_all / all_checked 是硬编码处理 5 组内置开关
（maaend / maa / maafgo / okww + 全部实例），完全不看 hidden_items。
"""
import copy
import ctypes as c
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
cfg = copy.deepcopy(BASE)
# 加两个自定义项，验证全选是否覆盖到它们
cfg['custom_items'] = [
    {'id': 'demo', 'name': '自定义 · 示例脚本', 'enabled': True, 'script': '', 'game': ''},
]
cfg['hidden_items'] = []
a.load_config = lambda: copy.deepcopy(cfg)
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


def set_all(on):
    ui._apply_checks(on)


def visible():
    return [it['key'] for it in ui.instance_rows()]


def state():
    return {
        'maaend': ui.maaend_on, 'maa': ui.maa_on,
        'maafgo': ui.maafgo_on, 'okww': ui.okww_on,
        'vm0': ui.chk.get(0), 'vm1': ui.chk.get(1),
        'custom:demo': ui.chk_custom.get('demo'),
    }


try:
    print('--- 基线：全部可见时全选应该正常工作 ---')
    ui.cfg['hidden_items'] = []
    ui._round_map = None
    set_all(False)
    check('全部未勾时 all_checked 为 False', ui.all_checked() is False)
    ui.toggle_all()
    check('点一次全选：全部勾上', all(v for v in state().values()), str(state()))
    check('再点一次：全部取消', (ui.toggle_all() or True) and
          not any(v for v in state().values()), str(state()))

    print('\n--- 隐藏 okww，其余可见 ---')
    ui.cfg['hidden_items'] = ['okww']
    print('   可见项:', visible())
    check('okww 不在可见列表里', 'okww' not in visible(), str(visible()))

    # 场景 A：隐藏前 okww 是取消状态，其余全勾
    set_all(True)
    ui.okww_on = False
    ui.cfg['okww']['enabled'] = False
    check('隐藏的 okww 未勾选，不影响「已全选」判定',
          ui.all_checked() is True, 'all_checked=%s' % ui.all_checked())

    before = state()
    ui.toggle_all()
    after = state()
    check('隐藏的 okww 没被这次点击改动',
          after['okww'] == before['okww'], '前 %s 后 %s' % (before['okww'], after['okww']))
    check('可见项确实被取消（按钮语义没反）',
          not any(after[k] for k in visible() if k in after),
          str({k: after[k] for k in visible() if k in after}))

    # 场景 B：再点一次，可见项全勾回，okww 仍然不动
    ui.toggle_all()
    after2 = state()
    check('第二次点：可见项全部勾上',
          all(after2[k] for k in visible() if k in after2), str(after2))
    check('第二次点：隐藏的 okww 依旧没被碰', after2['okww'] is False, str(after2))

    # 场景 C：隐藏的 okww 是勾选状态，点全选 → 取消可见项，okww 保持勾选
    ui.cfg['hidden_items'] = ['okww']
    ui.okww_on = True
    ui.cfg['okww']['enabled'] = True
    set_all(True)
    ui.toggle_all()
    after3 = state()
    check('隐藏项本来是勾的：点全选不会把它取消', after3['okww'] is True, str(after3))
    check('可见项被取消', not any(after3[k] for k in visible() if k in after3), str(after3))

    print('\n--- 隐藏一个实例 vm0 ---')
    ui.cfg['hidden_items'] = ['vm0']
    print('   可见项:', visible())
    set_all(True)
    ui.chk[0] = False
    ui.cfg['instances'][0]['enabled'] = False
    check('隐藏的 vm0 未勾选，不影响「已全选」判定',
          ui.all_checked() is True, 'all_checked=%s' % ui.all_checked())
    ui.toggle_all()
    check('隐藏的 vm0 没被改动', ui.chk.get(0) is False, str(ui.chk.get(0)))
    check('隐藏的 vm1 也被处理（它是可见的）',
          ui.chk.get(1) is False, str(ui.chk.get(1)))

    print('\n--- 自定义项也属于「看得见的」 ---')
    ui.cfg['hidden_items'] = []
    set_all(True)
    ui.chk_custom['demo'] = False
    check('自定义项取消后 all_checked 应为 False',
          ui.all_checked() is False, str(ui.chk_custom))
    ui.toggle_all()
    check('点全选能把它勾回来', ui.chk_custom.get('demo') is True,
          str(ui.chk_custom))

    print('\n--- 计数与文案 ---')
    ui.cfg['hidden_items'] = ['okww', 'vm0']
    ui._round_map = None
    logs = []
    ui.emit = lambda kind, *args: logs.append(args[0]) if kind == 'log' else None
    set_all(False)
    ui.toggle_all()
    n_vis = len(visible())
    check('日志里的数量只算可见项',
          ('%d 项' % n_vis) in ui.status, 'status=%r 可见 %d 项' % (ui.status, n_vis))
    check('日志写明了隐藏的那几项没动',
          any('未动' in str(m) for m in logs), str(logs)[-160:])

    print('\n--- 全被隐藏时不能反着来 ---')
    ui.cfg['hidden_items'] = ['maaend', 'maa', 'maafgo', 'okww', 'vm0', 'vm1', 'custom:demo']
    ui._round_map = None
    check('一个都不显示时 all_checked 为 False（空集不能算全选）',
          ui.all_checked() is False)
    snap = state()
    ui.toggle_all()
    check('一个都不显示时点全选是空操作',
          state() == snap, '%s -> %s' % (snap, state()))
finally:
    a.user32.ReleaseDC(hwnd, dc)
    a.user32.DestroyWindow(hwnd)

print("\n%d 项检查，%d 项失败" % (CHECKS, len(FAILED)))
if FAILED:
    print("失败：" + "、".join(FAILED))
    sys.exit(1)
print("全部 PASS")
