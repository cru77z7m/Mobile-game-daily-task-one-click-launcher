"""MaaEnd / MaaFgo 的「跑完了」判定：tasks-completed 不等于成功。

真实事故（2026-11-02）：MaaEnd 连续 12 个 task failure，09:36:47 stop_agent 并写出
kind: tasks-completed，启动器据此判「任务已完成」，接着就开了第 2 轮模拟器。

本用例只碰临时目录里的假日志，不启动任何游戏或脚本。
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

fails = 0


def check(ok, name, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + (("  " + detail) if detail and not ok else ""))
    if not ok:
        fails += 1


def ts(delta):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + delta))


def app_log(path, start_ts, done_ts, extra=""):
    path.write_text(
        "%s INFO  [App] 加载完成, 项目: MaaEnd\n"
        "%s INFO  [Task] 实例 全套日常: 开始执行任务, 数量: 17\n"
        "%s%s DEBUG [App] 收到 state-changed，已刷新运行时状态, kind: tasks-completed\n"
        % (start_ts, start_ts, extra, done_ts), encoding="utf-8")


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
    app_log(d1 / "2026-11-02-1.log", s1, e1)
    tauri_log(d1 / "mxu-tauri.log", [])
    ok, reasons, info = a.mxu_run_verdict(tmp / "clean", "debug", s1, e1, 300)
    check(ok and not reasons and info["seconds"] == 1800,
          "干净的一轮判成功", repr((ok, reasons, info)))

    # ---------- 2) 纯函数：本轮有 task failure ----------
    d2 = tmp / "fail" / "debug"
    d2.mkdir(parents=True)
    s2, e2 = ts(-3600), ts(-1200)
    app_log(d2 / "2026-11-02-1.log", s2, e2)
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
    app_log(d3 / "2026-11-02-1.log", s3, e3)
    tauri_log(d3 / "mxu-tauri.log", [(ts(-3000), "YesterdayTask")])   # 早于本轮开始
    ok, reasons, info = a.mxu_run_verdict(tmp / "old", "debug", s3, e3, 300,
                                          since_ts=s3)
    check(ok and info["fails"] == 0, "只数本轮之后的失败", repr((ok, info)))

    # ---------- 4) 按大小轮转出来的归档也要算 ----------
    d4 = tmp / "rot" / "debug"
    d4.mkdir(parents=True)
    s4, e4 = ts(-3600), ts(-1200)
    app_log(d4 / "2026-11-02-1.log", s4, e4)
    tauri_log(d4 / "mxu-tauri.log", [])                                  # 当前文件干净
    f = d4 / "mxu-tauri_2026-11-02_10-42-28.log"
    tauri_log(f, [(ts(-3000), "AutoCollect")])
    ok, reasons, info = a.mxu_run_verdict(tmp / "rot", "debug", s4, e4, 300)
    check((not ok) and info["fails"] == 1, "轮转归档里的失败也算", repr((ok, info)))

    # ---------- 5) 跑得太短也算失败 ----------
    d5 = tmp / "short" / "debug"
    d5.mkdir(parents=True)
    s5, e5 = ts(-600), ts(-420)          # 只有 3 分钟
    app_log(d5 / "2026-11-02-1.log", s5, e5)
    tauri_log(d5 / "mxu-tauri.log", [])
    ok, reasons, info = a.mxu_run_verdict(tmp / "short", "debug", s5, e5, 300)
    check((not ok) and "低于下限" in reasons[0] and info["seconds"] == 180,
          "耗时低于下限判失败", repr((ok, reasons, info)))
    ok2, _r2, _i2 = a.mxu_run_verdict(tmp / "short", "debug", s5, e5, 0)
    check(ok2, "下限设 0 时只看失败", repr(ok2))

    # ---------- 6) 集成：wait_maaend_done 失败即返回 False 并置 failed ----------
    a.LOG_PATH = str(tmp / "verdict.log")
    a.maaend_game_running = lambda cfg: False

    def run_wait(work, timeout=25):
        """在后台跑 wait_maaend_done，同时按"真的在跑"的节奏写日志"""
        dbg = work / "debug"
        dbg.mkdir(parents=True, exist_ok=True)
        start = ts(0)
        app_log(dbg / "2026-11-02-1.log", start, start)      # 先只有启动行
        (dbg / "2026-11-02-1.log").write_text(
            "%s INFO  [Task] 实例 全套日常: 开始执行任务, 数量: 17\n" % start,
            encoding="utf-8")
        cfg = {"maaend": {"path": str(work / "MaaEnd.exe"), "log_dir": "debug",
                          "timeout": 30, "wait_game_close": False,
                          "min_run_seconds": 0, "check_failures": True,
                          "stop_on_failure": True},
               "instances": [], "custom_items": []}
        r = a.Runner(cfg, lambda *x: None)
        out = {}

        def body():
            out["ret"] = r.wait_maaend_done()
        th = threading.Thread(target=body, daemon=True)
        th.start()
        time.sleep(0.6)
        app_log(dbg / "2026-11-02-1.log", start, ts(2400))
        tauri_log(dbg / "mxu-tauri.log", [(ts(1200), "DeliveryJobs")])
        th.join(timeout)
        out["alive"] = th.is_alive()
        return r, out

    work = tmp / "app1"
    r, out = run_wait(work)
    check(out.get("alive") is False and out["ret"] is False
          and r.failed and "MaaEnd" in r.fail_reason and "1 个任务失败" in r.fail_reason,
          "MaaEnd 失败 → wait 返回 False、failed 置位",
          repr((out, r.failed, r.fail_reason)))

    # ---------- 7) 集成：干净的一轮照旧算成功 ----------
    work2 = tmp / "app2"
    dbg2 = work2 / "debug"
    dbg2.mkdir(parents=True)
    s7 = ts(0)
    (dbg2 / "2026-11-02-1.log").write_text(
        "%s INFO  [Task] 实例 全套日常: 开始执行任务, 数量: 17\n" % s7, encoding="utf-8")
    cfg2 = {"maaend": {"path": str(work2 / "MaaEnd.exe"), "log_dir": "debug",
                       "timeout": 30, "wait_game_close": False,
                       "min_run_seconds": 0},
            "instances": [], "custom_items": []}
    r2 = a.Runner(cfg2, lambda *x: None)
    box = {}


    def body2():
        box["ret"] = r2.wait_maaend_done()
    th = threading.Thread(target=body2, daemon=True)
    th.start()
    time.sleep(0.6)
    app_log(dbg2 / "2026-11-02-1.log", s7, ts(2400))
    th.join(25)
    check(box.get("ret") is True and not r2.failed,
          "干净的一轮仍判成功", repr((box, r2.failed, r2.fail_reason)))

    # ---------- 8) stop_on_failure=false 时只记失败、不阻断 ----------
    work3 = tmp / "app3"
    dbg3 = work3 / "debug"
    dbg3.mkdir(parents=True)
    s8 = ts(0)
    (dbg3 / "2026-11-02-1.log").write_text(
        "%s INFO  [Task] 实例 全套日常: 开始执行任务, 数量: 17\n" % s8, encoding="utf-8")
    cfg3 = {"maaend": {"path": str(work3 / "MaaEnd.exe"), "log_dir": "debug",
                       "timeout": 30, "wait_game_close": False,
                       "min_run_seconds": 0, "stop_on_failure": False},
            "instances": [], "custom_items": []}
    r3 = a.Runner(cfg3, lambda *x: None)
    box3 = {}


    def body3():
        box3["ret"] = r3.wait_maaend_done()
    th = threading.Thread(target=body3, daemon=True)
    th.start()
    time.sleep(0.6)
    app_log(dbg3 / "2026-11-02-1.log", s8, ts(2400))
    tauri_log(dbg3 / "mxu-tauri.log", [(ts(1200), "GiftOperator")])
    th.join(25)
    check(box3.get("ret") is True and r3.failed is False,
          "stop_on_failure=false 不阻断", repr((box3, r3.failed, r3.fail_reason)))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n%d 项检查，%d 项失败" % (8, fails))
sys.exit(1 if fails else 0)
