# -*- coding: utf-8 -*-
"""跑完终末地顺手关掉鹰角启动器（v2.20.1）的回归检查

最要紧的一条：**重跑清场里绝不能关启动器**。
2026-11-09 07:54 预任务失败是鹰角启动器冷启动渲染慢；08:47 重跑时窗口已
存在且渲染完成，49 秒就成功。要是重跑前把启动器也关了，每次重跑都会变成
冷启动，等于把已知能成功的路径堵死。

测什么：
  1. 版本 / 默认配置 / v6→v7 迁移（不覆盖用户值）
  2. 关闭函数：开关、无窗口、正常关、关不掉不强杀、尺寸过滤、日志
  3. 接线：_one_pass 里 close 在 finally、wait 在 try；
     _restart_maaend / close_maaend_game 里没有 close
  4. 真跑 _one_pass：成功/失败/抛异常/没启动 四种路径的行为
  5. 设置页有那一行、chip 跟配置走、pick_row 有分支

跑法：python build/verify_close_launcher.py
"""
import ast
import copy
import inspect
import os
import sys
import textwrap
import types

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


def calls_in(node, name):
    """AST 里所有名叫 name 的函数调用（模块级 foo() 和 self.foo() 都算）"""
    out = []
    for n in ast.walk(node):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        if ((isinstance(f, ast.Name) and f.id == name)
                or (isinstance(f, ast.Attribute) and f.attr == name)):
            out.append(n)
    return out


def src(fn):
    return textwrap.dedent(inspect.getsource(fn))


# ---- 1. 版本与配置 -------------------------------------------------------
check("APP_VERSION 至少是 v2.20.1",
      tuple(int(x) for x in D.APP_VERSION.lstrip("v").split(".")) >= (2, 20, 1),
      D.APP_VERSION)
check("CONFIG_VERSION 已升到 7", D.CONFIG_VERSION == 7, str(D.CONFIG_VERSION))
m0 = D.DEFAULT_CONFIG.get("maaend", {})
check("默认：跑完关掉鹰角启动器", m0.get("close_launcher_when_done") is True)
check("默认：窗口标题精确匹配", m0.get("launcher_window_title") == "鹰角启动器")

c1 = {"maaend": {"timeout": 999}}
notes = D.migrate_config(c1, 6)
check("v6→v7 补上新配置", c1["maaend"].get("close_launcher_when_done") is True
      and c1["maaend"].get("launcher_window_title") == "鹰角启动器")
check("v6→v7 不覆盖用户已有值", c1["maaend"].get("timeout") == 999)
check("v6→v7 写了迁移说明", any("鹰角启动器" in n for n in notes), str(notes)[:80])
c2 = {"maaend": {"close_launcher_when_done": False, "launcher_window_title": "自定义"}}
D.migrate_config(c2, 6)
check("用户关掉开关后迁移不覆盖", c2["maaend"]["close_launcher_when_done"] is False)
check("用户自定义标题不被覆盖", c2["maaend"]["launcher_window_title"] == "自定义")
notes7 = D.migrate_config({"maaend": {}}, 7)
check("已是 v7 不再重复迁移", not any("鹰角启动器" in n for n in notes7), str(notes7)[:80])


# ---- 2. 关闭函数 ---------------------------------------------------------
orig_find = D.find_windows_by
orig_pm = D.user32.PostMessageW
orig_kill = getattr(D, "run_hidden", None)
WIN = [(12345, "鹰角启动器", "Qt5158QWindowIcon")]


class FindStub(object):
    """按序列返回窗口，同时记下调用参数"""
    def __init__(self, seq):
        self.seq = list(seq)
        self.calls = []

    def __call__(self, *a, **kw):
        self.calls.append((a, kw))
        if len(self.seq) > 1:
            return self.seq.pop(0)
        return self.seq[0]


def run_close(cfg, seq, wait=0):
    stub = FindStub(seq)
    posted = []
    killed = []
    D.find_windows_by = stub
    D.user32.PostMessageW = lambda h, m, w, l: posted.append((h, m)) or 1
    D.run_hidden = lambda *a, **k: killed.append(a)
    logs = []
    try:
        n = D.close_hypergryph_launcher(cfg, logs.append, wait=wait)
    finally:
        D.find_windows_by = orig_find
        D.user32.PostMessageW = orig_pm
        if orig_kill is not None:
            D.run_hidden = orig_kill
    return n, stub, posted, killed, logs


base = {"maaend": {"close_launcher_when_done": True,
                   "launcher_window_title": "鹰角启动器"}}

n, stub, posted, killed, logs = run_close(
    {"maaend": {"close_launcher_when_done": False}}, [WIN])
check("开关关掉：返回 0", n == 0)
check("开关关掉：连窗口都不查", stub.calls == [], str(stub.calls))

n, stub, posted, killed, logs = run_close(base, [[]])
check("没有启动器窗口：返回 0", n == 0)
check("没有窗口时不发关闭消息", posted == [])

n, stub, posted, killed, logs = run_close(base, [WIN, []], wait=1)
check("正常关闭：返回关掉的窗口数", n == 1, str(n))
check("正常关闭：发的是 WM_CLOSE", posted == [(12345, 0x0010)], str(posted))
check("正常关闭：日志写明为什么关",
      any("显示电源请求" in x for x in logs), str(logs)[:110])
check("识别时传了尺寸下限（滤掉 1x1 隐藏窗）",
      all(kw.get("min_w", 0) >= 400 and kw.get("min_h", 0) >= 300
          for _a, kw in stub.calls), str(stub.calls[:1]))
check("标题用了精确正则",
      all(kw.get("title_regex") == r"^鹰角启动器$" for _a, kw in stub.calls),
      str(stub.calls[:1]))

n, stub, posted, killed, logs = run_close(base, [WIN], wait=0)
check("关不掉：返回 0", n == 0)
check("关不掉：不强杀进程", killed == [], str(killed))
check("关不掉：写了明确警告", any("不强杀" in x or "手动关掉" in x for x in logs),
      str(logs)[:110])

check("函数文档写明不能放进重跑清场",
      "重跑" in (D.close_hypergryph_launcher.__doc__ or "")
      and "不能" in (D.close_hypergryph_launcher.__doc__ or ""))


# ---- 3. 接线：AST 静态检查 -----------------------------------------------
t_pass = ast.parse(src(D.Runner._one_pass))
tries = [n for n in ast.walk(t_pass) if isinstance(n, ast.Try)]
try_node = None
for t in tries:
    if calls_in(ast.Module(body=t.finalbody, type_ignores=[]),
                "close_hypergryph_launcher"):
        try_node = t
        break
check("_one_pass 里 close 在 finally", try_node is not None)
if try_node:
    check("wait_maaend_done 在同一个 try 里",
          bool(calls_in(ast.Module(body=try_node.body, type_ignores=[]),
                        "wait_maaend_done")))

t_restart = ast.parse(src(D.Runner._restart_maaend))
check("★ 重跑清场 _restart_maaend 里没有关启动器",
      not calls_in(t_restart, "close_hypergryph_launcher"))
t_cg = ast.parse(src(D.close_maaend_game))
check("close_maaend_game 里没有关启动器",
      not calls_in(t_cg, "close_hypergryph_launcher"))


# ---- 4. 真跑 _one_pass ---------------------------------------------------
def fake_runner(wait_result, start_ok=True):
    cfg = copy.deepcopy(D.DEFAULT_CONFIG)
    cfg["instances"] = []
    cfg["hidden_items"] = []
    cfg["maaend"]["path"] = r"D:\fake\MaaEnd.exe"
    r = types.SimpleNamespace()
    r.cfg = cfg
    r.log = lambda *a, **k: None
    r.emit = lambda *a, **k: None
    r.step = lambda *a, **k: None
    r.cancel_steps = lambda *a, **k: None
    r.only = None
    r.skip = set()
    r.stop_flag = False
    r.failed = False
    r.start_maaend = lambda: start_ok
    def _wait():
        if isinstance(wait_result, Exception):
            raise wait_result
        return wait_result
    r.wait_maaend_done = _wait
    return r


def exercise(wait_result, start_ok=True):
    calls = []
    o_sync, o_pre = D.sync_instances, D.preflight
    o_close = D.close_hypergryph_launcher
    D.sync_instances = lambda cfg, log: False
    D.preflight = lambda cfg: ([], set())
    D.close_hypergryph_launcher = lambda cfg, log=None: calls.append(1)
    r = fake_runner(wait_result, start_ok)
    err = None
    try:
        D.Runner._one_pass(r, scope={"maaend"}, monitor=False)
    except Exception as e:
        err = e
    finally:
        D.sync_instances, D.preflight = o_sync, o_pre
        D.close_hypergryph_launcher = o_close
    return calls, err


calls, err = exercise(False)
check("真跑：wait 返回 False（失败/取消）→ 关一次", len(calls) == 1, str(calls))
calls, err = exercise(RuntimeError("boom"))
check("真跑：wait 抛异常 → finally 仍然关一次", len(calls) == 1,
      "err=%r calls=%s" % (err, calls))
calls, err = exercise(True, start_ok=False)
check("真跑：MaaEnd 压根没启动 → 不动启动器", calls == [], str(calls))


# ---- 5. 设置页 -----------------------------------------------------------
s_rows = src(D.App.settings_rows)
check("设置页有 close_launcher 行", '"close_launcher"' in s_rows)
check("设置页 chip 跟配置走", "close_launcher_when_done" in s_rows)
s_pick = src(D.App.pick_row)
check("pick_row 里有 close_launcher 分支（不会掉去弹选目录框）",
      'kind == "close_launcher"' in s_pick)
check("分支里会写配置", "close_launcher_when_done" in s_pick)

print("\n%d 项检查，%d 项失败" % (N, len(FAIL)))
if FAIL:
    for f in FAIL:
        print("  - " + f)
    sys.exit(1)
print("ALL PASS")
