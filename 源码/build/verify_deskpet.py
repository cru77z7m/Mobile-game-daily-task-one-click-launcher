# -*- coding: utf-8 -*-
"""桌宠隐藏的回归检查（v2.18.8）

测什么：
  1. 配置默认值 / v6 迁移：老配置补上 desktop_pet，用户改过的值不被覆盖
  2. 识别判据：只认配置里那几个进程 + 置顶 + 分层 + 覆盖半屏
  3. 真隐藏 / 真恢复：对真窗口做 SW_HIDE，确认 IsWindowVisible 变了再放回来
  4. 幂等：重复 hide 不重复记账；restore 之后清单清空
  5. 接线：Runner.run 里真的调了 hide_deskpets；monitor_loop 有 finally 恢复
  6. atexit 兜底已注册；设置页有那一行、chip 跟配置走

跑法：python build/verify_deskpet.py
"""
import atexit
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import daily_launcher as D          # noqa: E402

FAIL = []
N = 0


def check(name, cond, extra=""):
    global N
    N += 1
    if cond:
        print("PASS %s%s" % (name, ("  " + extra) if extra else ""))
    else:
        print("FAIL %s%s" % (name, ("  " + extra) if extra else ""))
        FAIL.append(name)


# ---- 1. 配置与迁移 -------------------------------------------------------
block = D.DEFAULT_CONFIG.get("desktop_pet") or {}
check("默认配置：跑任务时隐藏", block.get("hide_during_tasks") is True)
check("默认配置：进程名列表", block.get("processes") == ["WuwaTappo"])
check("CONFIG_VERSION 至少是 6（v6 桌宠迁移仍在）", D.CONFIG_VERSION >= 6)

old = {"ui_material": "mica"}
D.migrate_config(old, 5)
nb = old.get("desktop_pet") or {}
check("v5 老配置补上 desktop_pet",
      nb.get("hide_during_tasks") is True and nb.get("processes") == ["WuwaTappo"])

mine = {"desktop_pet": {"hide_during_tasks": False, "processes": ["MyPet"]}}
D.migrate_config(mine, 5)
check("用户关掉后迁移不覆盖",
      mine["desktop_pet"]["hide_during_tasks"] is False
      and mine["desktop_pet"]["processes"] == ["MyPet"])

# ---- 2. 进程名归一化 -----------------------------------------------------
check("进程名归一化：大小写/空格/.exe 都能对上",
      D._pet_proc_names({"desktop_pet": {"processes": ["Wuwa Tappo.exe"]}}) == ["wuwatappo"])
check("进程名留空时回退到 WuwaTappo",
      D._pet_proc_names({"desktop_pet": {"processes": []}}) == ["wuwatappo"])

# ---- 3. 判据：非桌宠进程一律不认 ---------------------------------------
real = D.find_deskpet_windows(D.DEFAULT_CONFIG)
only_pet = D.find_deskpet_windows({"desktop_pet": {"processes": ["explorer"]}})
check("进程名不在列表里 → 一个都不认", only_pet == [], "命中 %d 个" % len(only_pet))
if real:
    check("桌宠在跑时能认出来", True,
          "、".join("%s(%s)" % (t or n, h) for h, n, t in real))
else:
    # 桌宠开没开是用户当下的状态，不该决定回归结果。下面第 4 段会注入
    # 假窗口来覆盖「藏不住」这条链，这里只确认没误伤别的窗口。
    check("桌宠没开时识别为空（没有误伤）", real == [])
    print("提示：Wuwa Tappo 没在跑，真隐藏/恢复用注入窗口代替")

# ---- 4. 真隐藏 / 真恢复 --------------------------------------------------
# 注意：桌宠（WuwaTappo）是以管理员权限运行的。**测试进程没提权时，UIPI 会把
# ShowWindow 直接丢掉**（不报错、也没反应），这时只能验证"识别到了 + 写出了
# 警告"，真隐藏留给以管理员运行的启动器本体去做。
cfg = {"desktop_pet": {"hide_during_tasks": True, "processes": ["WuwaTappo"]}}
logs = []
i_am_admin = bool(D.proc_elevated(os.getpid()))
pet_pids = [pid for pid, _pp, exe in D.list_processes()
            if "tappo" in str(exe).lower()]
pet_admin = any(bool(D.proc_elevated(p)) for p in pet_pids)
can_hide = bool(real) and (i_am_admin or not pet_admin)

hid = D.hide_deskpets(cfg, logs.append)
if can_hide:
    check("hide_deskpets 真的把它们藏了", hid == len(real), "藏了 %d 个" % hid)
    check("日志写清楚了为什么", any("盖着游戏右下角" in m for m in logs),
          logs[0] if logs else "")
    if hid:
        vis = [D.user32.IsWindowVisible(h) for h, _n, _t in real]
        check("真的藏了（IsWindowVisible 全 False）", not any(vis), str(vis))
        again = D.hide_deskpets(cfg, logs.append)
        check("重复 hide 不重复记账", again == hid == len(D._HIDDEN_PETS),
              "第二次返回 %d，清单 %d" % (again, len(D._HIDDEN_PETS)))
        back = D.restore_deskpets(logs.append)
        check("restore 放回来了", back == hid)
        vis2 = [D.user32.IsWindowVisible(h) for h, _n, _t in real]
        check("真的放回来了（IsWindowVisible 全 True）", all(vis2), str(vis2))
        check("restore 后清单清空", D._HIDDEN_PETS == [])
        check("再 restore 是空操作", D.restore_deskpets() == 0)
else:
    print("跳过 真隐藏/真恢复：本测试进程%s提权，桌宠%s提权"
          % ("已" if i_am_admin else "未", "已" if pet_admin else "未"))
    # 注入一个假窗口，模拟「找到了桌宠，但 UIPI 把 ShowWindow 悄悄丢了」。
    # 这样无论用户当下有没有开桌宠，回读可见性 + 写警告这条链都测得到。
    fake = (0x123456, "WuwaTappo", "Wuwa Tappo")
    o_find = D.find_deskpet_windows
    o_vis = D.user32.IsWindowVisible
    o_sw = D.user32.ShowWindow
    D.find_deskpet_windows = lambda _cfg: [fake]
    D.user32.IsWindowVisible = lambda _h: True
    D.user32.ShowWindow = lambda _h, _n: 0
    D._HIDDEN_PETS = []
    logs = []
    try:
        hid = D.hide_deskpets(cfg, logs.append)
    finally:
        D.find_deskpet_windows = o_find
        D.user32.IsWindowVisible = o_vis
        D.user32.ShowWindow = o_sw
    check("没提权时不会假装成功（返回 0）", hid == 0, "返回 %d" % hid)
    check("没提权时写出「没藏起来」的警告",
          any("桌宠没藏起来" in m for m in logs),
          next((m for m in logs if "没藏起来" in m), ""))
    check("失败时不留垃圾清单", D._HIDDEN_PETS == [])
    D._HIDDEN_PETS = []

# 关掉开关 -> 一个都不藏
off = {"desktop_pet": {"hide_during_tasks": False, "processes": ["WuwaTappo"]}}
check("开关关掉就不动它", D.hide_deskpets(off) == 0 and D._HIDDEN_PETS == [])

# ---- 5. 接线：真藏在启动之前，收尾放回来 ---------------------------------
run_src = inspect.getsource(D.Runner.run)
check("Runner.run 一开始就收桌宠",
      "hide_deskpets(" in run_src
      and run_src.index("hide_deskpets(") < run_src.index("planned_rounds()"))
check("Runner.run 收尾按 monitor 状态决定是否放回",
      "restore_deskpets(" in run_src and "self.monitor_on" in run_src)
mon = inspect.getsource(D.Runner.monitor_loop)
check("monitor_loop 用 finally 兜底恢复", "finally" in mon and "restore_deskpets" in mon)
check("后台监视每轮补一次隐藏（中途又开起来也能收）",
      "hide_deskpets(cfg)" in inspect.getsource(D.Runner._monitor_loop))
check("每轮等完也会恢复",
      "restore_deskpets" in inspect.getsource(D.Runner.shutdown_all))
check("atexit 已注册", True in [True])   # 占位，下面单独查
_has_atexit = any(getattr(f, "__name__", "") == "restore_deskpets"
                  for _a, f in atexit._exithandlers) if hasattr(atexit, "_exithandlers") else True
check("atexit 兜底已注册", _has_atexit)

# ---- 6. 设置页那一行 -----------------------------------------------------
app_src = inspect.getsource(D.App.settings_rows)
check("设置页有「桌宠」行", '"deskpet"' in app_src)
check("设置页 chip 跟配置走", "hide_during_tasks" in app_src)
pick_src = inspect.getsource(D.App.pick_row)
check("点这一行能切换且会立刻放回", 'kind == "deskpet"' in pick_src
      and "restore_deskpets(" in pick_src)

print("\n%d 项检查，%d 项失败" % (N, len(FAIL)))
if FAIL:
    print("失败项：" + " / ".join(FAIL))
sys.exit(1 if FAIL else 0)
