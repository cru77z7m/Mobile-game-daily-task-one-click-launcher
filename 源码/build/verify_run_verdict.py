"""MaaEnd / MaaFgo 的「跑完了」判定与「失败自动重跑」。

真实事故（2026-11-02）：MaaEnd 连续 10 个 task failure，09:36:47 stop_agent 并写出
kind: tasks-completed，启动器据此判「任务已完成」，接着就开了第 2 轮模拟器。

本用例只碰临时目录里的假日志，不启动任何游戏或脚本，也不杀任何真实进程。
"""
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '源码'))
import daily_launcher as a

CHECKS = 10
fails = 0


def check(ok, name, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + (("  " + detail) if detail and not ok else ""))
    if not ok:
        fails += 1


def ts(delta):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + delta))


def write_app(path, lines):
    path.write_text("".join(lines), encoding="utf-8")


def start_line(t):
    return "%s INFO  [Task] 实例 全套日常: 开始执行任务, 数量: 17\n" % t


def done_line(t):
    return "%s DEBUG [App] 收到 state-changed，已刷新运行时状态, kind: tasks-completed\n" % t


def append_top(path, text):
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)


def tauri_log(path, stamps):
    lines = []
    for t, task in stamps:
        lines.append("[%s][%s][INFO][mxu_lib::commands::telemetry] [telemetry] "
                     "task failure event_id=x run_id=y task_id=1 task=%s"
                     % (t[:10], t[11:], task))
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


tmp = Path(tempfile.mkdtemp(prefix="verdict_"))
try:
    # ---------- 1) 纯函数：干净的一轮 ----------
    d1 = tmp / "clean" / "debug"
    d1.mkdir(parents=True)
    s1, e1 = ts(-3600), ts(-1800)
    write_app(d1 / "2026-11-02-1.log", [start_line(s1), done_line(e1)])
    tauri_log(d1 / "mxu-tauri.log", [])
    ok, reasons, info = a.mxu_run_verdict(tmp / "clean", "debug", s1, e1, 300)
    check(ok and not reasons and info["seconds"] == 1800,
          "干净的一轮判成功", repr((ok, reasons, info)))

    # ---------- 2) 纯函数：本轮有 task failure ----------
    d2 = tmp / "fail" / "debug"
    d2.mkdir(parents=True)
    s2, e2 = ts(-3600), ts(-1200)
    write_app(d2 / "2026-11-02-1.log", [start_line(s2), done_line(e2)])
    tauri_log(d2 / "mxu-tauri.log",
              [(ts(-3000), "DijiangRewards"), (ts(-2400), "GiftOperator")])
    ok, reasons, info = a.mxu_run_verdict(tmp / "fail", "debug", s2, e2, 300)
    check((not ok) and info["fails"] == 2
          and info["tasks"] == ["DijiangRewards", "GiftOperator"]
          and "2 个任务失败" in reasons[0],
          "有 task failure 判失败", repr((ok, reasons, info)))

    # ---------- 3) 上一轮的失败不能算到这一轮头上 ----------
    d3 = tmp / "old" / "debug"
    d3.mkdir(parents=True)
    s3, e3 = ts(-1800), ts(-600)
    write_app(d3 / "2026-11-02-1.log", [start_line(s3), done_line(e3)])
    tauri_log(d3 / "mxu-tauri.log", [(ts(-3000), "YesterdayTask")])   # 早于本轮开始
    ok, reasons, info = a.mxu_run_verdict(tmp / "old", "debug", s3, e3, 300,
                                          since_ts=s3)
    check(ok and info["fails"] == 0, "只数本轮之后的失败", repr((ok, info)))

    # ---------- 4) 按大小轮转出来的归档也要算 ----------
    d4 = tmp / "rot" / "debug"
    d4.mkdir(parents=True)
    s4, e4 = ts(-3600), ts(-1200)
    write_app(d4 / "2026-11-02-1.log", [start_line(s4), done_line(e4)])
    tauri_log(d4 / "mxu-tauri.log", [])                                  # 当前文件干净
    tauri_log(d4 / "mxu-tauri_2026-11-02_10-42-28.log", [(ts(-3000), "AutoCollect")])
    ok, reasons, info = a.mxu_run_verdict(tmp / "rot", "debug", s4, e4, 300)
    check((not ok) and info["fails"] == 1, "轮转归档里的失败也算", repr((ok, info)))

    # ---------- 5) 跑得太短也算失败 ----------
    d5 = tmp / "short" / "debug"
    d5.mkdir(parents=True)
    s5, e5 = ts(-600), ts(-420)          # 只有 3 分钟
    write_app(d5 / "2026-11-02-1.log", [start_line(s5), done_line(e5)])
    tauri_log(d5 / "mxu-tauri.log", [])
    ok, reasons, info = a.mxu_run_verdict(tmp / "short", "debug", s5, e5, 300)
    check((not ok) and "低于下限" in reasons[0] and info["seconds"] == 180,
          "耗时低于下限判失败", repr((ok, reasons, info)))
    ok2, _r2, _i2 = a.mxu_run_verdict(tmp / "short", "debug", s5, e5, 0)
    check(ok2, "下限设 0 时只看失败", repr(ok2))

    # ---------- 集成工具 ----------
    a.LOG_PATH = str(tmp / "verdict.log")
    a.maaend_game_running = lambda cfg: False

    def new_runner(work, **maaend):
        dbg = work / "debug"
        dbg.mkdir(parents=True, exist_ok=True)
        cfg = {"maaend": dict({"path": str(work / "MaaEnd.exe"), "log_dir": "debug",
                               "timeout": 25, "wait_game_close": False,
                               "min_run_seconds": 0, "check_failures": True,
                               "stop_on_failure": True, "max_retries": 0,
                               "retry_delay": 0, "retry_close_game": False},
                              **maaend),
               "instances": [], "custom_items": []}
        r = a.Runner(cfg, lambda *x: None)
        lines = []
        r.log = lambda m: lines.append(m)
        r._kill_app = lambda exe, label, wait=20: True
        return r, dbg, lines

    def run_attempts(r, dbg, lines, plans, timeout=40):
        """在后台跑 wait_maaend_done，按 plans 逐次写日志

        plans 里每项是一次尝试：(有失败?, 任务名)；第 1 次的 start 由调用方先写好，
        后续每次由假的 start_maaend 追加新的 start 行。
        """
        app = dbg / "2026-11-02-1.log"
        tauri = dbg / "mxu-tauri.log"
        base = 0
        attempts = {"n": 0}

        def fake_start():
            attempts["n"] += 1
            k = attempts["n"]
            append_top(app, start_line(ts(10000 * k)))
            base_now = 10000 * k
            return True

        r.start_maaend = fake_start
        out = {}

        def body():
            out["ret"] = r.wait_maaend_done()
        th = threading.Thread(target=body, daemon=True)
        th.start()
        for i, (has_fail, task) in enumerate(plans):
            n = i + 1
            # 等第 n 次尝试真正开始（日志里会出现第 n 条"监视 MaaEnd 日志"）
            t0 = time.time()
            while sum(1 for x in lines if x.startswith("监视 MaaEnd 日志")) < n:
                if time.time() - t0 > timeout or not th.is_alive():
                    break
                time.sleep(0.05)
            off = 10000 * (i + 1) if i else 0
            if has_fail:
                append_top(tauri, "[%s][%s][INFO][x] [telemetry] task failure "
                                  "event_id=x run_id=y task_id=1 task=%s\n"
                           % (ts(off + 1200)[:10], ts(off + 1200)[11:], task))
            append_top(app, done_line(ts(off + 2400)))
        th.join(timeout)
        out["alive"] = th.is_alive()
        return out

    # ---------- 6) 集成：max_retries=0 时失败直接返回 False ----------
    r6, dbg6, lines6 = new_runner(tmp / "app6")
    out6 = run_attempts(r6, dbg6, lines6, [(True, "DeliveryJobs")])
    check(out6.get("alive") is False and out6["ret"] is False and r6.failed
          and "1 个任务失败" in r6.fail_reason,
          "max_retries=0：失败不重跑，直接判失败",
          repr((out6, r6.failed, r6.fail_reason)))

    # ---------- 7) 集成：干净的一轮照旧算成功 ----------
    r7, dbg7, lines7 = new_runner(tmp / "app7")
    out7 = run_attempts(r7, dbg7, lines7, [(False, "")])
    check(out7.get("ret") is True and not r7.failed,
          "干净的一轮仍判成功", repr((out7, r7.failed, r7.fail_reason)))

    # ---------- 8) stop_on_failure=false 且不重跑时只记失败、不阻断 ----------
    r8, dbg8, lines8 = new_runner(tmp / "app8", stop_on_failure=False)
    out8 = run_attempts(r8, dbg8, lines8, [(True, "GiftOperator")])
    check(out8.get("ret") is True and r8.failed is False,
          "stop_on_failure=false 不阻断", repr((out8, r8.failed)))

    # ---------- 9) 失败后自动重跑，第二次成功 ----------
    r9, dbg9, lines9 = new_runner(tmp / "app9", max_retries=1)
    out9 = run_attempts(r9, dbg9, lines9, [(True, "DijiangRewards"), (False, "")])
    retried = any("自动重跑" in x for x in lines9)
    check(out9.get("ret") is True and not r9.failed and retried
          and any("(第 2/2 次)" in x or "第 2/2 次" in x for x in lines9),
          "失败后自动重跑，第二次成功",
          repr((out9, r9.failed, r9.fail_reason, retried)))

    # ---------- 10) 重跑也没成 → 判失败并写明重跑过 ----------
    r10, dbg10, lines10 = new_runner(tmp / "app10", max_retries=1)
    out10 = run_attempts(r10, dbg10, lines10,
                         [(True, "DijiangRewards"), (True, "SellProduct")])
    check(out10.get("ret") is False and r10.failed
          and "已自动重跑 1 次" in r10.fail_reason,
          "重跑也没成 → 停下并写明重跑次数",
          repr((out10, r10.failed, r10.fail_reason)))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n%d 项检查，%d 项失败" % (CHECKS, fails))
sys.exit(1 if fails else 0)
