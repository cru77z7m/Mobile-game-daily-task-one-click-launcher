"""主界面轮次角标：排序、三种状态、绘制参数接线。

纯本地，不改 config.json，不启动任何任务。
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

# ---- 1. round_assign 的三种返回值 ----------------------------------------
try:
    ui.cfg['pipeline'] = {"enabled": False, "assign": {"maa": 1}, "order": []}
    check("没启用编排 → None（按老顺序）", ui.round_assign() is None)

    ui.cfg['pipeline'] = {"enabled": True, "assign": {}, "order": []}
    check("启用但没排轮次 → {}（不是 None）", ui.round_assign() == {})

    ui.cfg['pipeline'] = {"enabled": True,
                          "assign": {"maa": 1, "vm0": 2, "bad": 0, "x": "y"},
                          "order": []}
    got = ui.round_assign()
    check("启用且排了 → {key: 轮号}", got == {"maa": 1, "vm0": 2}, str(got))
    check("轮号 0 / 非数字被丢掉", "bad" not in got and "x" not in got, str(got))

    # ---- 2. main_rows：排序 ------------------------------------------------
    ui.cfg['pipeline'] = {"enabled": False, "assign": {"maa": 1}, "order": []}
    plain = ui.main_rows()
    raw = ui.instance_rows()
    check("未启用时 main_rows 不排序",
          [it['key'] for it in plain] == [it['key'] for it in raw])

    # 故意把轮次和原始顺序错开：原始顺序 maaend, vm0, vm1, maa, maafgo, okww
    ui.cfg['pipeline'] = {"enabled": True,
                          "assign": {"maaend": 3, "vm0": 1, "vm1": 1,
                                     "maa": 1, "maafgo": 1, "okww": 2},
                          "order": ["maaend", "vm0", "vm1", "maa", "maafgo", "okww"]}
    rows = ui.main_rows()
    keys = [it['key'] for it in rows]
    rounds = [ui.round_assign()[k] for k in keys]
    check("按轮次升序排（轮号序列非递减）",
          rounds == sorted(rounds), str(list(zip(keys, rounds))))
    check("第 1 轮排在最前，第 3 轮排最后",
          rounds[0] == 1 and rounds[-1] == 3, str(rounds))

    # 同一轮内部按名称
    first = [it['title'] for it in rows if ui.round_assign()[it['key']] == 1]
    check("同一轮内按名称排序", first == sorted(first), str(first))

    # ---- 3. 没排轮次的项目沉底 ---------------------------------------------
    ui.cfg['pipeline'] = dict(ui.cfg['pipeline'])
    ui.cfg['pipeline']['assign'] = {k: v for k, v in
                                    ui.cfg['pipeline']['assign'].items() if k != 'okww'}
    keys2 = [it['key'] for it in ui.main_rows()]
    check("没排轮次的项目沉到最后", keys2[-1] == 'okww', str(keys2))

    # ---- 4. 绘制时角标参数真的传下去了 -------------------------------------
    calls = []
    orig_tile = type(ui).draw_task_tile

    def spy(self, dc_, item, rect, step=0, round_no=0):
        calls.append((item['key'], step, round_no))
        return orig_tile(self, dc_, item, rect, step, round_no)

    type(ui).draw_task_tile = spy
    try:
        ui.cfg['pipeline']['assign'] = {"maaend": 3, "vm0": 1, "vm1": 1,
                                        "maa": 1, "maafgo": 1, "okww": 2}
        calls.clear()
        ui.paint(dc)
        seen = {k: r for k, _s, r in calls}
        check("启用编排：每张卡片都收到轮次",
              seen.get('maaend') == 3 and seen.get('okww') == 2
              and seen.get('maa') == 1, str(seen))
        check("启用编排：没有卡片还在收到序号",
              all(r != 0 for r in seen.values()), str(seen))

        ui.cfg['pipeline']['enabled'] = False
        calls.clear()
        ui.paint(dc)
        seen2 = {k: r for k, _s, r in calls}
        check("关闭编排：round_no 归零，回落到序号",
              all(r == 0 for r in seen2.values()), str(seen2))

        ui.cfg['pipeline']['enabled'] = True
        ui.cfg['pipeline']['assign'] = {"maaend": 1}
        calls.clear()
        ui.paint(dc)
        seen3 = {k: r for k, _s, r in calls}
        check("启用了但这项没排：round_no = -1（画「未排」）",
              seen3.get('okww') == -1 and seen3.get('maaend') == 1, str(seen3))
    finally:
        type(ui).draw_task_tile = orig_tile

    # ---- 5. 角标文字与顶部说明 ---------------------------------------------
    src = (ROOT / '源码' / 'ui_design.py').read_text(encoding='utf-8')
    check("角标会画「第 N 轮」", '"第%d轮"' in src)
    check("角标会画「未排」", '"未排"' in src)
    check("角标是胶囊（宽比高大），不是原来的方块",
          'bw, bh = S(36), S(17)' in src)

    main_src = (ROOT / '源码' / 'daily_launcher.py').read_text(encoding='utf-8')
    check("顶部说明改成「各轮 N 项」",
          "各轮 %s 项" in main_src and "每轮跑完再开下一轮" in main_src)
    check("不再用「每轮占哪几个序号」那套（排序后已无意义）",
          "_idx = {it[\"key\"]: i + 1" not in main_src)

    # ---- 6. 真实布局：同轮次的卡片能被圆点角标完整覆盖 ---------------------
    ui.cfg['pipeline']['assign'] = {"maaend": 3, "vm0": 1, "vm1": 1,
                                    "maa": 1, "maafgo": 1, "okww": 2}
    ui.paint(dc)
    check("每张卡片都有位置矩形",
          len(ui.rects['tiles']) == len(ui.rects['rows']))
    for key, r in ui.rects['tiles'].items():
        l, t, rr, bb = r
        check("卡片 %s 的角标放得下（宽 ≥ 36 逻辑像素）" % key,
              rr - l > ui.S(60), str(r))
        break                        # 只看第一张，其余同尺寸
finally:
    a.user32.ReleaseDC(hwnd, dc)
    a.user32.DestroyWindow(hwnd)

print("\n%d 项检查，%d 项失败" % (CHECKS, len(FAILED)))
if FAILED:
    print("失败：" + "、".join(FAILED))
    sys.exit(1)
print("全部 PASS")
