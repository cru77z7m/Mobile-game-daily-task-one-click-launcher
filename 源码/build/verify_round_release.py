"""分轮模式下，每轮用完的模拟器实例必须立刻释放。

背景（2026-11-18 实测）：第 1 轮 vm0/vm1/MAA/MaaFgo 在 09:36 就跑完了，
但实例一直开到 11:28 MaaEnd 跑完，才由后台监视关掉 —— 中间终末地全程很卡。
根因是关闭动作只挂在 `_monitor_loop`，而监视要等所有轮次启动完才开始。

这里验证 `release_round_instances()` 的判据，以及 `run()` 里的调用时机。
"""
import copy
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


CFG = copy.deepcopy(a.DEFAULT_CONFIG)
CFG.update(json.loads((ROOT / 'config.json').read_text(encoding='utf-8-sig')))
CFG['instances'] = [{'index': 0, 'name': '明日方舟'},
                    {'index': 1, 'name': 'FGO'}]
CFG['maa']['instance_index'] = 0
CFG['maafgo']['emulator_index'] = 1
CFG['shutdown_emulator_when_done'] = True

orig = {
    'instance_running': a.instance_running,
    'shutdown_instance': a.shutdown_instance,
    'hide_deskpets': a.hide_deskpets,
    'restore_deskpets': a.restore_deskpets,
}

running = {0, 1}
closed = []


def fake_ir(cfg, idx):
    return idx in running


def fake_si(cfg, idx, log=None):
    if log:
        log("关闭 MuMu 实例 %s（模拟器以外的进程都保留）…" % idx)
    running.discard(idx)
    closed.append(idx)
    return True


a.instance_running = fake_ir
a.shutdown_instance = fake_si


def make_runner(cfg=None):
    r = a.Runner(copy.deepcopy(cfg or CFG), lambda *args: None)
    r.logs = []
    r.steps = []
    r.log = lambda m: r.logs.append(m)
    r.emit = lambda *args, **kw: None
    r.step = lambda k, s, d="": r.steps.append((k, s, d))
    return r


def reset(vms=(0, 1)):
    running.clear()
    running.update(vms)
    closed.clear()


try:
    # ---- 1. 后续轮次根本不需要模拟器 → 两台都关 -----------------------------
    reset()
    r = make_runner()
    r._booted_vms = {0, 1}
    rounds = [{'vm0', 'vm1', 'maa', 'maafgo'}, {'okww'}, {'maaend'}]
    n = r.release_round_instances(rounds, 1)
    check("后续只有 ok-ww / MaaEnd → 两台实例都关",
          n == 2 and sorted(closed) == [0, 1], '%s / %s' % (n, closed))
    check("关掉的记进 _closed_vms，后台监视不会再关一遍",
          r._closed_vms == {0, 1}, str(r._closed_vms))
    check("日志说明是「第 1 轮用完」并点明让资源",
          any('第 1 轮用完' in m and '让给后面的任务' in m for m in r.logs),
          str(r.logs))
    check("两台都在界面上标成已关闭",
          sorted(k for k, s, _d in r.steps if s == 'idle') == ['vm0', 'vm1'],
          str(r.steps))

    # ---- 2. 后续轮次还有 MAA → 必须留实例 0 ---------------------------------
    reset()
    r = make_runner()
    r._booted_vms = {0, 1}
    n = r.release_round_instances([{'vm0', 'vm1'}, {'maa'}], 1)
    check("后续有 MAA → 保留实例 0，只关 1",
          n == 1 and closed == [1], '%s / %s' % (n, closed))

    # ---- 3. 后续轮次还有 vm1 → 保留 1 ---------------------------------------
    reset()
    r = make_runner()
    r._booted_vms = {0, 1}
    n = r.release_round_instances([{'vm0'}, {'vm1'}], 1)
    check("后续有 vm1 → 保留实例 1，只关 0",
          n == 1 and closed == [0], '%s / %s' % (n, closed))

    # ---- 4. 后续轮次还有 MaaFgo → 需要 emulator_index（默认 1）--------------
    reset()
    r = make_runner()
    r._booted_vms = {0, 1}
    n = r.release_round_instances([{'vm0', 'vm1'}, {'maafgo'}], 1)
    check("后续有 MaaFgo → 保留它那个实例（1），只关 0",
          n == 1 and closed == [0], '%s / %s' % (n, closed))

    # ---- 5. 开关关掉就一台都不动 -------------------------------------------
    reset()
    off = copy.deepcopy(CFG)
    off['shutdown_emulator_when_done'] = False
    r = make_runner(off)
    r._booted_vms = {0, 1}
    n = r.release_round_instances([{'vm0', 'vm1'}, {'maaend'}], 1)
    check("shutdown_emulator_when_done=false → 不关任何实例",
          n == 0 and closed == [], '%s / %s' % (n, closed))

    # ---- 6. 已经关过的实例不重复关 -----------------------------------------
    reset()
    r = make_runner()
    r._booted_vms = {0, 1}
    r._closed_vms = {0}
    n = r.release_round_instances([{'vm0', 'vm1'}, {'maaend'}], 1)
    check("_closed_vms 里的实例跳过", n == 1 and closed == [1],
          '%s / %s' % (n, closed))

    # ---- 7. 实例本来就不在跑：不调 shutdown，但记进清单 ---------------------
    reset(vms=(1,))
    r = make_runner()
    r._booted_vms = {0, 1}
    n = r.release_round_instances([{'vm0', 'vm1'}, {'maaend'}], 1)
    check("已经不在跑的实例不重复发关闭命令",
          n == 1 and closed == [1] and 0 in r._closed_vms,
          '%s / %s / %s' % (n, closed, r._closed_vms))
    check("日志写明「已经不在跑了」",
          any('已经不在跑' in m for m in r.logs), str(r.logs))

    # ---- 8. 关闭失败：不记进已关清单，界面标 err ---------------------------
    reset()
    a.shutdown_instance = lambda cfg, idx, log=None: False
    r = make_runner()
    r._booted_vms = {0, 1}
    n = r.release_round_instances([{'vm0', 'vm1'}, {'maaend'}], 1)
    check("关闭失败时不假装成功",
          n == 0 and r._closed_vms == set(), '%s / %s' % (n, r._closed_vms))
    check("关闭失败在界面上标 err",
          any(s == 'err' for _k, s, _d in r.steps), str(r.steps))
    a.shutdown_instance = fake_si

    # ---- 9. release_instance 不重复关已释放的实例 --------------------------
    reset()
    r = make_runner()
    r._booted_vms = {0, 1}
    r._closed_vms = {0}
    r.release_instance('maa', 0, 'MAA')
    check("后台监视看到已释放的实例会跳过",
          closed == [] and any('已经关了' in m for m in r.logs),
          '%s / %s' % (closed, r.logs))

    # ---- 10. run() 的调用时机 ----------------------------------------------
    reset()
    r = make_runner()
    seq = []
    r.planned_rounds = lambda: [{'vm0', 'maa'}, {'okww'}, {'maaend'}]
    r._one_pass = lambda scope, monitor=True: seq.append(('pass', tuple(sorted(scope))))
    r._wait_round_done = lambda keys, i, total: (seq.append(('wait', i)) or True)
    r.release_round_instances = lambda rounds, i: (seq.append(('release', i)) or 1)
    r.start_monitor = lambda: (seq.append(('monitor',)) or True)
    a.hide_deskpets = lambda cfg, log=None: seq.append(('hide',))
    a.restore_deskpets = lambda log=None: seq.append(('restore',))
    r.run()
    # seq[0] 是开头收桌宠，第 1 轮的三步是 seq[1:4]
    check("第 1 轮：启动 → 等完成 → 立刻释放实例",
          seq[1:4] == [('pass', ('maa', 'vm0')), ('wait', 1), ('release', 1)],
          str(seq))
    check("第 2 轮（ok-ww）也等完成并释放",
          ('release', 2) in seq, str(seq))
    check("最后一轮之后不再 release，交给后台监视",
          ('release', 3) not in seq and ('monitor',) in seq, str(seq))

    # 失败即停时不该释放（现场要留着）
    reset()
    r = make_runner()
    seq2 = []
    r.planned_rounds = lambda: [{'vm0', 'maa'}, {'maaend'}]
    r._one_pass = lambda scope, monitor=True: seq2.append('pass')
    r._wait_round_done = lambda keys, i, total: False
    r.release_round_instances = lambda rounds, i: seq2.append('release')
    r.start_monitor = lambda: True
    r.run()
    check("这一轮没等到完成（失败/取消）就不释放实例",
          'release' not in seq2, str(seq2))

    # ---- 11. 静态接线 -------------------------------------------------------
    src_run = inspect.getsource(a.Runner.run)
    check("run() 里每轮结束调用 release_round_instances",
          'self.release_round_instances(rounds, i)' in src_run)
    check("调用在 _wait_round_done 之后",
          src_run.index('_wait_round_done') < src_run.index('release_round_instances'))
    check("_one_pass 记录本次真正拉起过的实例",
          '_booted_vms |=' in inspect.getsource(a.Runner._one_pass))
    check("release_instance 会跳过 _closed_vms",
          '_closed_vms' in inspect.getsource(a.Runner.release_instance))
    check("后台监视仍然保留兜底关闭",
          'shutdown_emulators_for_monitor' in inspect.getsource(a.Runner._monitor_loop))
finally:
    a.instance_running = orig['instance_running']
    a.shutdown_instance = orig['shutdown_instance']
    a.hide_deskpets = orig['hide_deskpets']
    a.restore_deskpets = orig['restore_deskpets']

print("\n%d 项检查，%d 项失败" % (CHECKS, len(FAILED)))
if FAILED:
    print("失败：" + "、".join(FAILED))
    sys.exit(1)
print("全部 PASS")
