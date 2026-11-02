# -*- coding: utf-8 -*-
"""
一键日常启动器
------------------------------------------------
打开即自动启动：MaaEnd（终末地）先跑 -> 两个 MuMu 实例 -> MAA（明日方舟）-> MaaFgo（FGO，等游戏起来再开始）-> ok-ww（鸣潮每日任务）
启动过程中可以随时点「取消启动」中止后续步骤。
跑完之后在后台盯日志：MAA + MaaFgo 都完成就关模拟器、ok-ww 完成就关鸣潮，四个程序本身都不退出。

依赖：只用 Python 标准库 + Windows GDI/USER32（ctypes 自绘界面），无需 tkinter / 第三方包。
配置：同目录 config.json（界面里点「设置」可以改各程序的路径）
"""

import time as _boot_time            # 启动计时用：越早拿到时间戳越好
_BOOT_T = _boot_time.time()

import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from ui_effects import system_preferences, apply_native_frame, mix_color, AnimationClock
from ui_design import VisualShell
from ui_render import Compositor

import zipfile        # 只给"从发布包里挑 exe"用，见 extract_new_exe()

_T_IMP = _boot_time.time()          # 导入全部完成
_TMARK = {}                         # --timing 用的分阶段时间戳

# ----------------------------------------------------------------------------
# 基础
# ----------------------------------------------------------------------------
APP_NAME = "一键日常启动器"
APP_VERSION = "v2.18.6"
APP_TITLE = APP_NAME
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
comdlg32 = ctypes.WinDLL("comdlg32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

# 兼容不同 Python 版本 wintypes 里缺失的类型别名
for _n, _t in (
    ("UINT_PTR", ctypes.c_size_t),
    ("LONG_PTR", ctypes.c_ssize_t),
    ("HGDIOBJ", wt.HANDLE),
    ("HBITMAP", wt.HANDLE),
    ("HFONT", wt.HANDLE),
    ("HICON", wt.HANDLE),
    ("HBRUSH", wt.HANDLE),
    ("HPEN", wt.HANDLE),
    ("HINSTANCE", wt.HANDLE),
    ("HMENU", wt.HANDLE),
    ("HDC", wt.HANDLE),
    ("HWND", wt.HANDLE),
):
    if not hasattr(wt, _n):
        setattr(wt, _n, _t)


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR = app_dir()

# 两种发布形态，代码里到处要分：
#   onefile —— 单文件 exe，双击即用；但每次启动都要把整包（5.6MB）解到 %TEMP%，
#              冷启动多花两三百毫秒，还留下临时目录。
#   onedir  —— 文件夹版：exe 旁边一个 _internal 目录，启动不用解包（秒开）；
#              装的时候由「安装程序」铺好，更新也走安装程序。
# 判断依据就是 exe 旁边有没有 _internal（PyInstaller onedir 的固定产物名）。
FROZEN = bool(getattr(sys, "frozen", False))
ONEDIR = bool(FROZEN and os.path.isdir(os.path.join(APP_DIR, "_internal")))
# 安装程序铺的文件，用来判断"这是装出来的"还是"解压出来随便放的"
INSTALL_MARK = os.path.join(APP_DIR, "install.json")


def _pick_config(base):
    """配置文件位置：本目录优先；跑源码调试时退回上一级（项目根）

    否则「跑源码」和「跑 exe」会各读写一份 config.json，勾选状态对不上，
    排查起来非常迷惑（踩过一次）。
    """
    here = os.path.join(base, "config.json")
    if os.path.isfile(here):
        return here
    up = os.path.join(os.path.dirname(os.path.abspath(base)), "config.json")
    if os.path.isfile(up):
        return up
    return here


CONFIG_PATH = _pick_config(APP_DIR)
LOG_PATH = os.path.join(APP_DIR, "launcher.log")

# 程序自己的内部状态（配置结构版本号、上次运行用的是哪版）。
# 这些**不是用户配置**：用户既不该看、也不该改，所以单独放一个文件，
# 免得跟 config.json 里那些路径/勾选混在一起被人手滑改坏。
# 跟 config.json 同目录 —— 它可能被 _pick_config 指到上一级去。
STATE_PATH = os.path.join(os.path.dirname(CONFIG_PATH), "launcher.state.json")
STATE = {}                  # load_state() 之后填充；save_state() 整体写回
STATE_FIX = False           # 主状态文件读不了（靠 .bak 或默认值救的），下次顺手修回来

# 旁边有没有 config.json —— 只用于记日志；"要不要走设置向导"看 config_ready()，
# 因为用户可能第一次打开、看一眼就关掉，留下一个"全空但存在"的配置。
CONFIG_EXISTED = os.path.isfile(CONFIG_PATH)

# FGO 版本 → 安卓包名。设置页可以循环切换；不在表里的服直接改 config.json
# 的 maafgo.game_package（MaaFgo 只认包名，不认服名）。
FGO_PACKAGES = [
    ("B服", "com.bilibili.fatego"),
    ("日服", "com.aniplex.fategrandorder"),
]

# MuMu 新建实例时的默认名字（只影响界面显示，认不出的就用「实例N」）
INSTANCE_DEFAULT_NAMES = {0: "明日方舟", 1: "命运-冠位指定"}

# 开机询问「要只跑手游日常吗」的倒计时秒数（到点自动按默认开跑）
PROMPT_SECONDS = 5

# 自定义实例最多加几个（设置页行高有限，多了会挤掉日志区）
MAX_CUSTOM = 4

# 每帧耗时打点：设了 DL_TIMING=1 就在 launcher.log 里记 gdi/present 各多少毫秒。
# 只用来定位材质模式卡顿，正常运行时零开销。
DEBUG_TIMING = bool(os.environ.get("DL_TIMING"))


# ----------------------------------------------------------------------------
# 配置
# ----------------------------------------------------------------------------
# 配置结构版本：升级 exe 时靠它判断要不要跑迁移。
# 只做"加字段/改语义"的小步升级，每次 bump 都要在 migrate_config() 里补一段。
# 这个值存在 launcher.state.json 里，**不写进 config.json**（用户不该动它）。
CONFIG_VERSION = 4                # v2.18.6：任务失败判定写进配置

# ---- 自动更新 ----
# 只查 Releases API 的 latest，不要 token（公开仓库匿名够用，60 次/小时/ip）。
UPDATE_REPO = "cru77z7m/Mobile-game-daily-task-one-click-launcher"
UPDATE_API = "https://api.github.com/repos/%s/releases/latest" % UPDATE_REPO
UPDATE_PAGE = "https://github.com/%s/releases" % UPDATE_REPO
UPDATE_UA = "daily-launcher-updater"          # GitHub API 要求带 UA，不带直接 403
UPDATE_DIR = os.path.join(APP_DIR, "_update")  # 下载包解压在这儿，装完下次启动清掉
# 安装程序不往 _update 里放：它安装时会清理安装目录，把自己正在跑的那个文件
# 留在那儿只会让清理失败。扔 %TEMP% 里，装完/重启后系统自己会收拾。
UPDATE_TMP = os.path.join(tempfile.gettempdir(), "daily-launcher-setup")

# 「关于」页的信息。**写死在程序里**，不写进 config.json ——
# 这是作者信息，不该让使用者（或随手改配置的人）改掉。
# 要换地址/改署名就改这里，重新打包一次。
ABOUT_INFO = {
    "author": "Cru77z7M",
    "author_page": "https://space.bilibili.com/5707907",
    # 项目主页（下载新版都在这里）
    "project": ("https://github.com/cru77z7m/"
                "Mobile-game-daily-task-one-click-launcher/releases"),
    "issues": ("https://github.com/cru77z7m/"
               "Mobile-game-daily-task-one-click-launcher/issues"),
    # 留空就不显示这一行
    "group": "",
}

DEFAULT_CONFIG = {
    "ui_material": "mica",
    "ui_mica": True,        # Full-client Win11 material; Win10 uses opaque rendering.
    "ui_motion": True,      # Also respects SPI_GETCLIENTAREAANIMATION.
    # 首次运行时是空的：靠「首次使用向导」让用户点设置页选目录。
    # 这里绝不能写死作者机器上的路径——把程序发给别人时，那些路径根本不存在，
    # 打开就是满屏「找不到 xxx.exe」，看起来像程序坏了。
    "mumu_root": "",
    # 只是占位：真正启动时 sync_instances() 会按 MuMu 里实际存在的实例重建这份列表，
    # 免得新用户只建了 1 个实例、却在这里干等实例1 超时。
    "instances": [
        {"index": 0, "name": "模拟器", "enabled": True, "package": ""},
    ],
    "maa": {
        "enabled": True,
        "path": "",
        "auto_run": True,
        "fix_connect": True,
        "instance_index": 0,          # MAA 连哪台 MuMu（设置页可改）
    },
    # MaaEnd（终末地）：最优先跑，等它的任务链跑完、终末地关掉，
    # 再启动两个 MuMu 实例 + MAA + MaaFgo（FGO，取代原来的独立 BBchannel）。
    "maaend": {
        "enabled": True,
        "path": "",
        "instance": "全套日常",       # config/mxu-MaaEnd.json 里的实例名
        "autostart": True,            # 加 --autostart，开起来就直接开跑
        "quit_after_run": False,      # 加 --quit-after-run：跑完自动退出 MaaEnd
        "wait_game_close": True,      # 等终末地窗口消失再继续
        "game_window_class": "UnityWndClass",
        "game_window_title": "Endfield",
        "log_dir": "debug",
        "timeout": 7200,              # 等任务完成的总上限（秒）· 实测全套日常约 85 分钟
        "game_close_timeout": 300,    # 任务完成后等游戏退出的上限（秒）
        "start_next_if_timeout": True,
        "check_failures": True,       # 本轮出现 task failure 就算失败（tasks-completed 不代表成功）
        "min_run_seconds": 300,       # 短于这个时长也当失败：起来就崩的任务链只跑几十秒
        "stop_on_failure": True,      # 判定失败就停下，不开后面的轮次（现场留着给人看）
    },
    # MaaFgo（FGO 助手，取代原来的独立 BBchannel）：
    # 实例 1 就绪 → 没开游戏就先用 MuMu 打开 → 等游戏进程起来 → 再带 --autostart 启动它
    "maafgo": {
        "enabled": True,
        "path": "",
        "instance": "默认设置",        # config/mxu-MaaFgo.json 里的实例名
        "autostart": True,             # 加 --autostart，起来就开跑任务
        "quit_after_run": False,       # 加 --quit-after-run：任务跑完自动退出
        "emulator_index": 1,           # FGO 在哪台 MuMu 实例上
        "game_package": "com.bilibili.fatego",
        "launch_game": True,           # 游戏没开就用 MuMu 自己打开
        "game_wait": 240,              # 等游戏进程起来的上限（秒）
        "check_failures": True,        # 同上：MXU 壳的 tasks-completed 不等于成功
        "min_run_seconds": 180,
        "stop_on_failure": True,
        "settle": 10,                  # 起来后再等几秒过启动画面
        "sync_device_address": True,   # 把 MaaFgo 里记的 adb 地址改成实际端口
    },
    "okww": {
        "enabled": True,
        "path": "",                    # 只用来显示/定位，实际不启动它
        # ok-ww.exe 是 pyappify 壳，不一定把参数转给 python；直接用它自带的解释器
        "python": "",
        "workdir": "",
        "task": "DailyTask",           # 每日任务（一条龙：开游戏/登录/月卡/声骸/领奖/邮件）
        "headless": False,             # True=加 --headless 不显示界面
        "exit_after": False,           # True=加 -e 跑完退出游戏和应用
        "wait_start": 60,              # 等界面出来的上限（秒）
        "debug_log": True,             # 用自带入口开 debug 日志（否则看不到"任务完成"标记）
        "entry": "_launcher_auto.py",  # 上面那个入口的文件名（启动器每次重写）
        "close_game_when_done": True,  # 每日任务完成后只关游戏，ok-ww 自己留着
        "game_window_class": "UnrealWindow",
        "game_exe": "Client-Win64-Shipping.exe",
    },
    # 等 MAA + MaaFgo 的任务跑完，就把模拟器关掉省资源（程序进程都不动）
    "shutdown_emulator_when_done": True,
    "monitor_poll": 20,                # 多久看一次日志（秒）
    "monitor_max_hours": 10,           # 监视最长等多久
    "timeouts": {"boot": 300, "adb": 180},
    "close_tools_with_emulator": False,
    "auto_start_on_launch": True,
    # 打开软件 3 秒后悄悄查一次 GitHub 有没有新版：**不弹窗**，
    # 只在状态栏右边显示一句可点的提示。关掉就设 false。
    "check_update_on_launch": True,
    # 打开就自动启动之前，先问一句"要不要只跑手游日常"（5 秒不回答按默认全跑）。
    # 嫌烦就设 false：变成直接开跑，不弹询问卡。
    "night_prompt": True,
    "disable_updater": True,
    "require_admin": True,
    # 实例都起来之后怎么处理「MuMu模拟器」那个主窗口：
    #   hide     隐藏（默认，进程还在，任务栏也看不到，模拟器照常跑）
    #   minimize 最小化到任务栏
    #   keep     不动它
    "mumu_main_window": "hide",
    # 用户自定义的主界面项目（给自己想加的游戏用）：
    #   {"id": "c1712...", "name": "显示名", "script": "脚本.exe", "game": "游戏启动.exe", "enabled": true}
    # 这些项目**没有适配**：启动器只负责把游戏和脚本打开，
    # 不自动点任务、不检测任务完成、也不关它们。
    "custom_items": [],
    # 被用户从主界面删掉的项，键是 maaend / maa / maafgo / okww / vm0 / custom:<id>
    "hidden_items": [],
    # ⚠ 这里**只放用户的东西**（路径、开关、勾选、自定义项）。
    # 版本号这类程序内部状态在 launcher.state.json；
    # 作者信息写死在 ABOUT_INFO。以前这两样混在这儿，用户一改就出事。
}


def config_ready(cfg):
    """路径是不是指得像样了：至少有一个脚本 exe 设好了

    不能只看 config.json 存不存在——用户可能第一次打开、看了一眼就关掉，
    于是留下一个"全空但存在"的配置，下次打开就会带着空路径自动开跑，
    满屏「找不到 xxx.exe」。所以按内容判断。
    """
    for k in ("maaend", "maa", "maafgo", "okww"):
        if ((cfg.get(k, {}) or {}).get("path") or "").strip():
            return True
    return False


def _backup_config(tag):
    """升级前把老配置留一份，出问题能翻回去"""
    if not os.path.isfile(CONFIG_PATH):
        return ""
    dst = "%s.%s.bak" % (CONFIG_PATH, tag)
    try:
        shutil.copy2(CONFIG_PATH, dst)
        return dst
    except Exception:
        return ""


def load_state():
    """读程序的内部状态（配置结构版本、上次运行版本）

    坏了 / 丢了都不要紧：当作全新状态处理，最多多做一次"补默认值"，
    用户的路径和勾选一律不受影响 —— 这正是把它跟 config.json 分开的好处。
    """
    global STATE_FIX
    STATE_FIX = False
    st = {"config_version": 1, "last_run_version": ""}
    for path in (STATE_PATH, STATE_PATH + ".bak"):
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
        except Exception as e:
            log_line("状态文件读取失败（%s）：%s" % (os.path.basename(path), e))
            if path == STATE_PATH:
                STATE_FIX = True       # 主文件坏了，等下用 .bak 或默认值重写它
            continue
        if not isinstance(data, dict):
            continue
        for k in st:
            if k in data:
                st[k] = data[k]
        break
    try:
        st["config_version"] = max(1, int(st.get("config_version") or 1))
    except Exception:
        st["config_version"] = 1
    st["last_run_version"] = str(st.get("last_run_version") or "")
    return st


def save_state():
    """原子写内部状态（就两个字段，整份重写）"""
    tmp = STATE_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(STATE, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, STATE_PATH)
        try:
            shutil.copy2(STATE_PATH, STATE_PATH + ".bak")
        except Exception:
            pass
    except Exception as e:
        log_line("状态文件保存失败: %s" % e)
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except Exception:
            pass


def migrate_config(cfg, ver=None):
    """把老版本的 config.json 整理成当前结构

    原则：**只补缺的字段、只搬走程序内部的东西，绝不覆盖用户填的值**。
    覆盖 exe 升级时用户唯一不能丢的就是路径和勾选。

    ver 要传**从文件 / 状态里读到的旧版本号**（不能传合并后的 cfg，
    那时版本号已经是新的了，永远判不出"需要迁移"）。
    返回改动说明列表（空列表 = 不用动）。
    """
    notes = []
    try:
        ver = int(ver if ver is not None else 1)
    except Exception:
        ver = 1

    # v2 → v3：config.json 只留"用户的东西"。
    # 版本号搬去 launcher.state.json（load_config 里已经搬过了），
    # 作者信息改由程序里的 ABOUT_INFO 提供 —— 放在配置里等于谁都能改，
    # 改完「关于」页显示的就是假的了。
    moved = [k for k in ("config_version", "last_run_version", "about") if k in cfg]
    for k in moved:
        cfg.pop(k, None)
    if moved:
        notes.append("config.json 里不再保存 %s：版本号改存 launcher.state.json，"
                     "作者信息写死在程序里" % " / ".join(moved))
    # v4（v2.18.6）：「跑完了」不再等于「跑成了」。这几个键在 DEFAULT_CONFIG 里有默认值，
    # 但老 config.json 里没有 —— 补进来，用户翻配置时能看见、能自己调。
    # 用版本号而不是"键是否存在"来判断：load_config 已经把 DEFAULT_CONFIG 合并进来了，
    # 看 cfg 永远"存在"，判不出来。
    if ver < 4:
        for _sec, _extra in (("maaend", {}), ("maafgo", {"min_run_seconds": 180})):
            _d = cfg.get(_sec)
            if not isinstance(_d, dict):
                continue
            _vals = {"check_failures": True, "min_run_seconds": 300,
                     "stop_on_failure": True}
            _vals.update(_extra)
            for _k, _v in _vals.items():
                _d.setdefault(_k, _v)
        notes.append("任务失败判定已开启：MaaEnd / MaaFgo 本轮有 task failure 就算失败并停下"
                     "（maaend.stop_on_failure=false 可关掉）")

    # v2.18：启动编排。默认关闭 = 保持"一趟跑完"的老行为，不打扰老用户。
    if "pipeline" not in cfg:
        cfg["pipeline"] = {"enabled": False, "assign": {}, "order": []}
        notes.append("启动编排：默认关闭（所有勾选项一趟跑完）")

    return notes


def load_config():
    """读配置：主文件坏了自动退到 .bak，两边都读不了才用默认值

    勾选记忆就存在这个文件里，所以读失败等于"用户的选择全丢"，
    必须留一条后路。

    **升级 exe 时这个文件不会被覆盖**：它就躺在 exe 旁边，换版本/换名字
    都不影响。读进来之后只做「补字段」，用户填的路径和勾选一律保留；
    真要改结构就先备份成 config.json.v<旧版本>.bak，再按 migrate 的说明改。

    这个文件里**只有用户的东西**。版本号在 launcher.state.json，
    作者信息在代码里的 ABOUT_INFO —— 老版本混在 config.json 里的那些，
    这里会顺手搬家 + 清掉。
    """
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    STATE.clear()
    STATE.update(load_state())

    merged = False
    data = {}
    for path in (CONFIG_PATH, CONFIG_PATH + ".bak"):
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
        except Exception as e:
            log_line("配置读取失败（%s）：%s" % (os.path.basename(path), e))
            continue
        if not isinstance(data, dict):
            log_line("配置格式不对（不是 JSON 对象），跳过：%s"
                     % os.path.basename(path))
            data = {}
            continue
        for k, v in data.items():
            dv = cfg.get(k)
            if isinstance(dv, dict):
                if isinstance(v, dict):
                    # 子项逐个合并：新增字段用默认值，已有的用用户的值
                    dv.update(v)
                else:
                    log_line("配置项 %s 应该是对象，实际是 %s，保留默认值"
                             % (k, type(v).__name__))
            else:
                cfg[k] = v
        merged = True
        if path != CONFIG_PATH:
            log_line("主配置读不了，已用 config.json.bak 恢复勾选和路径")
            save_config(cfg)                 # 顺手把主文件修回来
        break

    if not merged:
        save_config(cfg)
        if STATE.get("config_version") != CONFIG_VERSION:
            STATE["config_version"] = CONFIG_VERSION
            save_state()
        return cfg

    # ---- 老 config.json 里可能还留着程序内部状态（v3 之前是混在一起的）----
    try:
        legacy_ver = int(data.get("config_version") or 0)
    except Exception:
        legacy_ver = 0
    legacy_last = str(data.get("last_run_version") or "")
    ver_old = max(int(STATE.get("config_version") or 1), legacy_ver, 1)

    state_dirty = False
    if legacy_last and not STATE.get("last_run_version"):
        STATE["last_run_version"] = legacy_last     # 搬家：别让升级提示失效
        state_dirty = True

    # ---- 从老版本升级上来：先备份原文件，再整理，用户的值原样保留 ----
    notes = migrate_config(cfg, ver_old)
    if notes:
        bak = _backup_config("v%d" % ver_old)
        for n in notes:
            log_line("配置整理：" + n)
        if bak:
            log_line("老配置已备份：%s" % os.path.basename(bak))
        save_config(cfg)
    if int(STATE.get("config_version") or 1) != CONFIG_VERSION:
        STATE["config_version"] = CONFIG_VERSION
        state_dirty = True
    if state_dirty or STATE_FIX:
        save_state()
    return cfg

def save_config(cfg):
    """原子写 + 留一份 .bak

    原来是 open(path,"w") 直接覆盖：写到一半断电/崩溃会留下半个 JSON，
    下次启动读失败就用回默认配置——用户勾了半天的选项全没了。
    这里先写 .tmp、fsync 落盘，再把旧的备份成 .bak，最后 os.replace 原子替换。
    """
    tmp = CONFIG_PATH + ".tmp"
    bak = CONFIG_PATH + ".bak"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, CONFIG_PATH)          # 原子替换，不会出现半个文件
        try:
            shutil.copy2(CONFIG_PATH, bak)    # 成功之后才更新副本 = 永远是最新的一份
        except Exception:
            pass
    except Exception as e:
        log_line("配置保存失败: %s" % e)
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except Exception:
            pass


_log_lock = threading.Lock()


def merge_rects(rects, gap=2):
    """把一堆 (l,t,r,b) 合成尽量少的几块，重叠或挨着的直接并起来。

    局部刷新是按矩形重算的，矩形越少越省：同一行被拆成七八条小条，
    每条都要走一遍抠图 + LUT + 文字合成，比整块慢得多。
    """
    out = []
    for r in sorted(rects, key=lambda v: (v[1], v[0])):
        l, t, rr, b = r
        for o in out:
            if (l <= o[2] + gap and o[0] <= rr + gap
                    and t <= o[3] + gap and o[1] <= b + gap):
                o[0] = min(o[0], l)
                o[1] = min(o[1], t)
                o[2] = max(o[2], rr)
                o[3] = max(o[3], b)
                break
        else:
            out.append([l, t, rr, b])
    # 并完一轮可能又能跟前面的并上，重复到稳定为止（数量是几十的量级，很快）
    changed = True
    while changed and len(out) > 1:
        changed = False
        for i in range(len(out)):
            for j in range(i + 1, len(out)):
                a, b2 = out[i], out[j]
                if (a[0] <= b2[2] + gap and b2[0] <= a[2] + gap
                        and a[1] <= b2[3] + gap and b2[1] <= a[3] + gap):
                    a[0] = min(a[0], b2[0])
                    a[1] = min(a[1], b2[1])
                    a[2] = max(a[2], b2[2])
                    a[3] = max(a[3], b2[3])
                    out.pop(j)
                    changed = True
                    break
            if changed:
                break
    return [(int(r[0]), int(r[1]), int(r[2]), int(r[3])) for r in out]


def log_line(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    try:
        with _log_lock:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass


def open_url(url):
    """用系统默认浏览器打开一个网址；失败返回错误串"""
    if not url:
        return "没有链接"
    try:
        # ShellExecuteW 的 "open" 会交给默认浏览器，比 webbrowser 模块可靠
        rc = shell32.ShellExecuteW(None, "open", url, None, None, 1)
        # ShellExecuteW 返回值 > 32 表示成功
        if int(rc or 0) <= 32:
            return "系统拒绝了打开请求（%s）" % rc
        return ""
    except Exception as e:
        return "%s: %s" % (type(e).__name__, e)


# ----------------------------------------------------------------------------
# 自动更新（GitHub Releases）
# ----------------------------------------------------------------------------
def ver_tuple(tag):
    """v2.11.0 / 2.11 / V2.11.0-beta 都变成 (2, 11, 0)，认不出就当 (0,)"""
    nums = re.findall(r"\d+", str(tag or ""))
    if not nums:
        return (0,)
    return tuple(int(n) for n in nums[:4])


def is_newer(tag, base=None):
    """tag 是不是比当前版本新（按数字段比较，不按字符串）"""
    return ver_tuple(tag) > ver_tuple(base or APP_VERSION)


# ----------------------------------------------------------------------------
# 极简 HTTP —— 只用 Windows 自带的 winhttp.dll
#
# 为什么不用 urllib：urllib 走 HTTPS 要 ssl → 打包会捎上 libcrypto(8MB) 和
# libssl(1.6MB) 两个 DLL。onefile 每次启动都要把它们解压到临时目录，
# 光这两个就多花两三百毫秒。WinHTTP 是系统组件，零体积、还自带系统代理和 TLS1.2+。
# ----------------------------------------------------------------------------
winhttp = ctypes.WinDLL("winhttp", use_last_error=True)

WINHTTP_ACCESS_TYPE_DEFAULT_PROXY = 0
WINHTTP_FLAG_SECURE = 0x00800000
WINHTTP_OPTION_REDIRECT_POLICY = 88
# 注意取值：0=NEVER、1=DISALLOW、2=ALLOW、3=禁止 https→http 降级。
# 写 0 会"一个重定向都不跟"——GitHub 的下载地址全是 302，会拿到 0 字节。
WINHTTP_OPTION_REDIRECT_POLICY_ALLOW = 2
WINHTTP_QUERY_STATUS_CODE = 19
WINHTTP_QUERY_CONTENT_LENGTH = 5


class HttpError(RuntimeError):
    """HTTP 状态码 >= 400（GitHub 限流时是 403/429）"""

    def __init__(self, code):
        self.code = int(code)
        RuntimeError.__init__(self, "HTTP %d" % self.code)


# ⚠ WinHTTP 返回的是 HINTERNET（64 位指针），必须写死 restype，
#   不然 ctypes 会按 32 位 int 截断，句柄当场失效。
winhttp.WinHttpOpen.argtypes = [wt.LPCWSTR, wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD]
winhttp.WinHttpOpen.restype = ctypes.c_void_p
winhttp.WinHttpConnect.argtypes = [ctypes.c_void_p, wt.LPCWSTR, ctypes.c_ushort, wt.DWORD]
winhttp.WinHttpConnect.restype = ctypes.c_void_p
winhttp.WinHttpOpenRequest.argtypes = [ctypes.c_void_p, wt.LPCWSTR, wt.LPCWSTR,
                                       wt.LPCWSTR, wt.LPCWSTR,
                                       ctypes.POINTER(wt.LPCWSTR), wt.DWORD]
winhttp.WinHttpOpenRequest.restype = ctypes.c_void_p
winhttp.WinHttpSetTimeouts.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int]
winhttp.WinHttpSetTimeouts.restype = wt.BOOL
winhttp.WinHttpSetOption.argtypes = [ctypes.c_void_p, wt.DWORD, ctypes.c_void_p, wt.DWORD]
winhttp.WinHttpSetOption.restype = wt.BOOL
winhttp.WinHttpSendRequest.argtypes = [ctypes.c_void_p, wt.LPCWSTR, wt.DWORD,
                                       ctypes.c_void_p, wt.DWORD, wt.DWORD, ctypes.c_size_t]
winhttp.WinHttpSendRequest.restype = wt.BOOL
winhttp.WinHttpReceiveResponse.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
winhttp.WinHttpReceiveResponse.restype = wt.BOOL
winhttp.WinHttpQueryHeaders.argtypes = [ctypes.c_void_p, wt.DWORD, wt.LPCWSTR,
                                        ctypes.c_void_p, ctypes.POINTER(wt.DWORD),
                                        wt.LPCWSTR]
winhttp.WinHttpQueryHeaders.restype = wt.BOOL
winhttp.WinHttpReadData.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.DWORD,
                                    ctypes.POINTER(wt.DWORD)]
winhttp.WinHttpReadData.restype = wt.BOOL
winhttp.WinHttpCloseHandle.argtypes = [ctypes.c_void_p]
winhttp.WinHttpCloseHandle.restype = wt.BOOL


def _http_query(req, what):
    """取一个响应头/状态行里的数字字段"""
    buf = ctypes.create_unicode_buffer(64)
    n = wt.DWORD(ctypes.sizeof(buf))
    if not winhttp.WinHttpQueryHeaders(req, what, None, buf, ctypes.byref(n), None):
        return ""
    return buf.value


def _http_open(url, timeout=15, extra_headers=None):
    """发 GET、等响应头。返回 (req, [句柄...])，调用方负责关

    extra_headers：额外的请求头（下载断点续传要带 Range），换行自己拼好传进来。
    """
    m = re.match(r"(?i)(https?)://([^/:]+)(?::(\d+))?(/.*)?$", url or "")
    if not m:
        raise RuntimeError("地址不对：%s" % url)
    https = m.group(1).lower() == "https"
    host = m.group(2)
    port = int(m.group(3) or (443 if https else 80))
    path = m.group(4) or "/"
    sess = winhttp.WinHttpOpen(UPDATE_UA, WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
                               None, None, 0)
    if not sess:
        raise OSError("WinHttpOpen 失败（err=%s）" % ctypes.get_last_error())
    conn = None
    try:
        ms = int(timeout * 1000)
        winhttp.WinHttpSetTimeouts(sess, ms, ms, ms, ms)
        conn = winhttp.WinHttpConnect(sess, host, port, 0)
        if not conn:
            raise OSError("连不上 %s（err=%s）" % (host, ctypes.get_last_error()))
        req = winhttp.WinHttpOpenRequest(
            conn, "GET", path, None, None, None,
            WINHTTP_FLAG_SECURE if https else 0)
        if not req:
            raise OSError("请求创建失败（err=%s）" % ctypes.get_last_error())
        # 跟随重定向：GitHub 的下载地址会 302 到 objects.githubusercontent.com
        policy = wt.DWORD(WINHTTP_OPTION_REDIRECT_POLICY_ALLOW)
        winhttp.WinHttpSetOption(req, WINHTTP_OPTION_REDIRECT_POLICY,
                                 ctypes.byref(policy), ctypes.sizeof(policy))
        headers = ("User-Agent: %s\r\nAccept: application/vnd.github+json\r\n"
                   % UPDATE_UA)
        if extra_headers:
            headers += extra_headers.rstrip("\r\n") + "\r\n"
        if not winhttp.WinHttpSendRequest(req, headers, -1, None, 0, 0, 0):
            raise OSError("发不出请求（err=%s）" % ctypes.get_last_error())
        if not winhttp.WinHttpReceiveResponse(req, None):
            raise OSError("没有响应（err=%s）" % ctypes.get_last_error())
        try:
            code = int(_http_query(req, WINHTTP_QUERY_STATUS_CODE) or 0)
        except Exception:
            code = 0
        if code >= 400:
            winhttp.WinHttpCloseHandle(req)
            raise HttpError(code)
        return req, [req, conn, sess]
    except Exception:
        if conn:
            winhttp.WinHttpCloseHandle(conn)
        winhttp.WinHttpCloseHandle(sess)
        raise


def _http_chunks(req, size=65536):
    """一块一块往外吐响应体"""
    n = wt.DWORD(0)
    buf = ctypes.create_string_buffer(size)
    while True:
        if not winhttp.WinHttpReadData(req, buf, size, ctypes.byref(n)):
            raise OSError("读取中断（err=%s）" % ctypes.get_last_error())
        if not n.value:
            return
        yield buf.raw[:n.value]


def http_get_text(url, timeout=8):
    req, handles = _http_open(url, timeout)
    try:
        return b"".join(_http_chunks(req)).decode("utf-8", "replace")
    finally:
        for h in handles:
            winhttp.WinHttpCloseHandle(h)


def http_json(url, timeout=8):
    return json.loads(http_get_text(url, timeout))


def find_latest_release(timeout=8):
    """查 GitHub 上最新的 Release，返回一个 dict（查不到就抛异常，由调用方兜）

    发布包现在有三种，按名字认（build_launcher.py 就是照这个名字产物命名的）：
        ...-setup-x64.exe   安装程序 → 装出来是文件夹版（秒开）
        ...-portable-x64.zip 免安装文件夹版
        ...-windows-x64.zip  单文件版（老版本自动更新只认这个，必须留着）
    """
    data = http_json(UPDATE_API, timeout)
    if not isinstance(data, dict):
        raise RuntimeError("GitHub 返回的不是对象")
    tag = str(data.get("tag_name") or "").strip()
    setup = zip_single = zip_portable = zip_any = None
    for a in (data.get("assets") or []):
        if not isinstance(a, dict) or not a.get("browser_download_url"):
            continue
        name = str(a.get("name") or "")
        low = name.lower()
        if low.endswith(".exe") and ("setup" in low or "install" in low or "安装" in name):
            setup = setup or a
        elif low.endswith(".zip"):
            if "portable" in low:
                zip_portable = zip_portable or a
            elif "windows" in low or "single" in low or "onefile" in low:
                zip_single = zip_single or a
            zip_any = zip_any or a

    def info(a):
        a = a or {}
        return {"url": str(a.get("browser_download_url") or ""),
                "asset": str(a.get("name") or ""),
                "size": int(a.get("size") or 0)}

    # 文件夹版：优先安装程序（装完还是文件夹版，且能保留 config.json）
    # 单文件版：优先单文件 zip，这样老用户升级过来的行为不变；
    #           实在没有 zip 就用安装程序原地装成文件夹版。
    if ONEDIR:
        order = [("setup", setup), ("zip", zip_portable), ("zip", zip_single or zip_any)]
    else:
        order = [("zip", zip_single or zip_any), ("setup", setup)]
    kind, pick = "none", {}
    for k, a in order:
        if a:
            kind, pick = k, info(a)
            break
    return {
        "tag": tag,
        "name": str(data.get("name") or tag),
        "kind": kind,
        "url": pick.get("url", ""),
        "asset": pick.get("asset", ""),
        "size": pick.get("size", 0),
        "page": str(data.get("html_url") or UPDATE_PAGE),
        "published": str(data.get("published_at") or "")[:10],
        # 备用：万一主选那条下不了（比如只看 zip 的老脚本），界面上能提示去哪手动下
        "setup": info(setup),
        "portable": info(zip_portable),
    }



def download_file(url, dst, on_progress=None, timeout=60, retries=4):
    """流式下载，每 64KB 回调一次 (已下, 总大小)；总大小未知时给 0

    为什么要断点续传：GitHub 在国内经常 20~40 KB/s，10 MB 的安装程序要下好几分钟，
    中途一次卡顿（WinHTTP 读超时 err=12002）就得从头再来。这里每次失败后用
    Range 头接着下，最多试 retries 次；服务器不认 Range（返回 200）就老实重下。
    """
    got = os.path.getsize(dst) if os.path.isfile(dst) else 0
    last = None
    for attempt in range(retries + 1):
        try:
            extra = ("Range: bytes=%d-" % got) if got else None
            req, handles = _http_open(url, timeout, extra)
            try:
                code = 0
                try:
                    code = int(_http_query(req, WINHTTP_QUERY_STATUS_CODE) or 0)
                except Exception:
                    code = 0
                try:
                    clen = int(_http_query(req, WINHTTP_QUERY_CONTENT_LENGTH) or 0)
                except Exception:
                    clen = 0
                if got and code != 206:
                    # 服务器没理我们的 Range：那就只能整份重下
                    got = 0
                total = (got + clen) if clen else 0
                with open(dst, "ab" if got else "wb") as f:
                    for chunk in _http_chunks(req):
                        f.write(chunk)
                        got += len(chunk)
                        if on_progress:
                            on_progress(got, total)
            finally:
                for h in handles:
                    winhttp.WinHttpCloseHandle(h)
            return got
        except HttpError as e:
            # 416 = 服务器说你已经下完了（Range 起点越界），当成成功
            if getattr(e, "code", 0) == 416 and got:
                return got
            last = e
        except Exception as e:
            last = e
        if attempt < retries:
            time.sleep(1.5 * (attempt + 1))
    raise last if last else OSError("下载失败")


def extract_new_exe(zip_path, out_dir):
    """从发布包里挑出 exe 解到 out_dir，返回解出来的路径

    发布包结构是「exe + README.md」平铺；万一以后加了子目录也能找得到。
    """
    os.makedirs(out_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        cand = [n for n in z.namelist()
                if n.lower().endswith(".exe") and not n.endswith("/")]
        if not cand:
            raise RuntimeError("压缩包里没找到 exe")
        want = os.path.basename(sys.executable)
        pick = next((n for n in cand if os.path.basename(n) == want), None)
        if pick is None:
            pick = min(cand, key=lambda n: n.count("/"))
        z.extract(pick, out_dir)
        return os.path.join(out_dir, *pick.split("/"))


def _short_net_err(e):
    """把 urllib/socket 的一堆英文异常翻成一句人话"""
    msg = str(e) or type(e).__name__
    low = msg.lower()
    if "timed out" in low or "timeout" in low:
        return "连不上 GitHub（超时），挂代理或换网络再试"
    if "getaddrinfo" in low or "name or service" in low:
        return "DNS 解析失败，检查网络"
    if "certificate" in low:
        return "证书校验失败（可能被代理拦截）"
    if "connection" in low and ("refused" in low or "reset" in low or "aborted" in low):
        return "连接被拒绝/中断"
    return msg[:70]


def pid_alive(pid):
    try:
        return any(p == int(pid) for p, _pp, _n in list_processes())
    except Exception:
        return False


def apply_update_cli(args):
    """--apply-update <目标exe> <旧进程pid> [--no-launch]

    自己（新版的 exe）从 _update 目录跑起来，等旧进程退出后把自己复制过去。
    为什么要这么绕：Windows 下正在运行的 exe 换不掉（文件被锁），
    所以只能"另起一个进程等它退出，再替换"。
    """
    try:
        i = args.index("--apply-update")
        target = os.path.abspath(args[i + 1])
        old_pid = int(args[i + 2])
    except Exception:
        return 2
    no_launch = "--no-launch" in args
    me = os.path.abspath(sys.executable)
    if os.path.normcase(me) == os.path.normcase(target):
        log_line("更新中止：更新程序和目标路径是同一个文件")
        return 2

    deadline = time.time() + 40
    while time.time() < deadline and pid_alive(old_pid):
        time.sleep(0.3)
    time.sleep(0.5)                       # 让单实例锁、文件句柄彻底放开

    bak = target + ".old"
    try:
        if os.path.isfile(bak):
            os.remove(bak)
    except Exception:
        pass
    try:
        os.replace(target, bak)            # 老版本先改名留底，出问题能回滚
    except Exception as e:
        log_line("更新失败：老 exe 改不动（%s）" % e)
        return 3
    try:
        shutil.copy2(me, target)
    except Exception as e:
        log_line("更新失败：新 exe 写不进去（%s），已回滚" % e)
        try:
            os.replace(bak, target)
        except Exception:
            pass
        return 4
    log_line("更新完成：已替换为新版 exe（老版本备份为 %s）"
             % os.path.basename(bak))
    if not no_launch:
        try:
            subprocess.Popen([target], close_fds=True)
        except Exception:
            try:
                os.startfile(target)
            except Exception as e:
                log_line("更新后自动启动失败，请手动双击：%s" % e)
    return 0


def run_setup_silent(setup_path, wait_pid=None, restart=True):
    """跑「安装程序」的静默安装，把当前目录原地升级

    为什么更新不再自己换文件：文件夹版是 exe + _internal 一整个目录，
    一边跑一边替换自己等于自杀（DLL 全被锁着）。交给安装程序来做最干净：
    它从 %TEMP% 跑，等我们退出 → 铺新文件（config.json 原样不动）→ 再把我们拉起来。
    """
    if not os.path.isfile(setup_path):
        raise RuntimeError("安装程序不见了，请重新下载")
    args = [setup_path, "/S", "/D=" + APP_DIR]
    if wait_pid:
        args.append("/WAITPID=%d" % int(wait_pid))
    if restart:
        args.append("/RESTART")
    subprocess.Popen(args, close_fds=True)
    return args


def _known_folder(csidl):
    """系统文件夹（桌面/开始菜单）——不能直接用 %USERPROFILE%，可能被 OneDrive 重定向"""
    buf = ctypes.create_unicode_buffer(260)
    try:
        shell32.SHGetFolderPathW.argtypes = [wt.HWND, ctypes.c_int, wt.HANDLE,
                                             wt.DWORD, wt.LPWSTR]
        shell32.SHGetFolderPathW.restype = ctypes.c_long
        if shell32.SHGetFolderPathW(None, csidl, None, 0, buf) == 0:
            return buf.value
    except Exception:
        pass
    return ""


CSIDL_PROGRAMS = 0x0002
CSIDL_DESKTOPDIRECTORY = 0x0010
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\DailyLauncher"


def shortcut_paths():
    """安装程序建的那两个快捷方式（桌面 / 开始菜单）"""
    out = []
    for base, sub in ((_known_folder(CSIDL_DESKTOPDIRECTORY), ""),
                      (_known_folder(CSIDL_PROGRAMS), "")):
        if base:
            out.append(os.path.join(base, APP_NAME + ".lnk"))
    return out


def uninstall_cli(args):
    """--uninstall：把自己删干净（快捷方式、卸载登记项、计划任务、安装目录）

    卸载程序没单独做一个 exe —— 就长在程序里，少一个需要维护的文件。
    最后一步得等本进程退出才删得掉，所以交给 cmd 延迟 rmdir。
    --dry-run 只打印要删什么，不真删（自检用）。
    """
    dry = "--dry-run" in args
    if not FROZEN:
        print("源码模式（没打包）不执行卸载，这是开发目录")
        return 2
    if not ONEDIR and not os.path.isfile(INSTALL_MARK):
        # 单文件版可能是"随便放的一个 exe"，删整个目录太危险
        print("这不是安装出来的文件夹版，卸载请直接删 exe 文件")
        if not dry:
            return 2
    if len(APP_DIR.rstrip("\\")) < 8:
        print("安装目录看起来像盘符根目录，拒绝卸载：%s" % APP_DIR)
        return 2
    if not dry:
        user32.MessageBoxW.restype = ctypes.c_int
        user32.MessageBoxW.argtypes = [wt.HWND, wt.LPCWSTR, wt.LPCWSTR, wt.UINT]
        r = user32.MessageBoxW(
            None,
            "要卸载《%s》吗？\n\n安装目录：%s\n\n"
            "会一起删掉：程序文件、桌面和开始菜单的快捷方式、"
            "「应用和功能」里的登记项、免 UAC 计划任务。\n"
            "config.json（各程序的路径和勾选）也会一起删掉。"
            % (APP_NAME, APP_DIR),
            "卸载 " + APP_NAME,
            0x04 | 0x30 | 0x100 | 0x02)          # YESNO | 警告图标 | 置前 | 默认"否"
        if r != 6:                                # IDYES
            print("取消卸载")
            return 1

    gone = []
    for p in shortcut_paths():
        try:
            if os.path.isfile(p):
                os.remove(p)
                gone.append(p)
        except Exception as e:
            print("删不掉快捷方式 %s：%s" % (p, e))
    try:
        import winreg
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
        gone.append("HKCU\\" + UNINSTALL_KEY)
    except FileNotFoundError:
        pass
    except Exception as e:
        print("删不掉卸载登记项：%s" % e)
    try:
        # 用 PowerShell 而不是 schtasks.exe：本机把 schtasks 列进了黑名单，
        # 而且 ensure_task() 本来也是走 PowerShell 注册的，两边保持一致。
        ps = ("$ErrorActionPreference='SilentlyContinue'; "
              "Unregister-ScheduledTask -TaskName '%s' -Confirm:$false" % TASK_NAME)
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                            "-WindowStyle", "Hidden", "-Command", ps],
                           capture_output=True, creationflags=CREATE_NO_WINDOW,
                           timeout=30)
        gone.append("计划任务 %s" % TASK_NAME)
    except Exception as e:
        print("删不掉计划任务：%s" % e)
    print("已清理：\n  " + "\n  ".join(gone or ["（没有需要清理的）"]))
    log_line("卸载：已清理 %s" % "；".join(gone or ["无"]))
    if dry:
        print("dry-run：不动 %s" % APP_DIR)
        return 0
    # 等本进程退出后整目录删掉。ping 当 sleep 用：不依赖 timeout.exe、不吃 stdin。
    subprocess.Popen('ping -n 3 127.0.0.1 >nul & rmdir /s /q "%s"' % APP_DIR,
                     shell=True, close_fds=True, creationflags=CREATE_NO_WINDOW)
    print("程序退出后删除：%s" % APP_DIR)
    if "--quiet" not in args:
        user32.MessageBoxW.restype = ctypes.c_int
        user32.MessageBoxW.argtypes = [wt.HWND, wt.LPCWSTR, wt.LPCWSTR, wt.UINT]
        user32.MessageBoxW(
            None,
            "已从本机移除《%s》。\n\n程序目录会在关掉这个提示后自动删除：\n%s"
            % (APP_NAME, APP_DIR),
            "卸载完成", 0x40 | 0x100 | 0x0)     # 信息图标 | 置前
    return 0


def cleanup_update_leftovers():
    """清掉上次更新留下的 _update 目录和 *.old 备份（删不掉就算了，下次再试）"""
    try:
        if os.path.isdir(UPDATE_DIR):
            shutil.rmtree(UPDATE_DIR, ignore_errors=True)
    except Exception:
        pass
    # 单文件版更新留下的 exe.old / 夹在旁边的旧 exe
    try:
        for name in os.listdir(APP_DIR):
            low = name.lower()
            if not (low.endswith(".exe.old") or low.endswith(".old") or low.endswith(".bak.tmp")):
                continue
            p = os.path.join(APP_DIR, name)
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    os.remove(p)
            except Exception:
                pass
    except Exception:
        pass


# ----------------------------------------------------------------------------
# 进程 / 环境工具
# ----------------------------------------------------------------------------
def run_hidden(args, timeout=90):
    """静默执行命令，返回 (returncode, stdout+stderr)"""
    try:
        p = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
        out = p.stdout.decode("utf-8", "replace") if p.stdout else ""
        return p.returncode, out
    except subprocess.TimeoutExpired:
        return -1, "timeout"
    except Exception as e:
        return -1, str(e)


def mumu_manager(mumu_root):
    return os.path.join(mumu_root, "nx_main", "MuMuManager.exe")


def detect_adb(mumu_root):
    base = os.path.join(mumu_root, "nx_device")
    best, best_ver = None, None
    if os.path.isdir(base):
        for name in os.listdir(base):
            exe = os.path.join(base, name, "shell", "adb.exe")
            if os.path.isfile(exe):
                try:
                    ver = tuple(int(x) for x in name.split("."))
                except Exception:
                    ver = (0,)
                if best_ver is None or ver > best_ver:
                    best, best_ver = exe, ver
    return best or os.path.join(base, "12.0", "shell", "adb.exe")


def read_adb_port(mumu_root, index):
    cfg = os.path.join(
        mumu_root, "vms", "MuMuPlayer-12.0-%d" % index, "configs", "vm_config.json"
    )
    try:
        with open(cfg, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return int(data["vm"]["nat"]["port_forward"]["adb"]["host_port"])
    except Exception:
        return 16384 + 32 * index


def list_vm_info(mgr, timeout=30):
    rc, out = run_hidden([mgr, "info", "-v", "all"], timeout)
    if rc != 0:
        return {}
    out = out.strip()
    i = out.find("{")
    if i > 0:
        out = out[i:]
    try:
        data = json.loads(out)
    except Exception:
        return {}
    res = {}
    for k, v in data.items():
        try:
            res[int(k)] = v
        except Exception:
            pass
    return res


def proc_running(exe_name):
    """用 Toolhelp 枚举进程，判断某个 exe 是否在跑"""
    TH32CS_SNAPPROCESS = 0x00000002

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wt.DWORD),
            ("cntUsage", wt.DWORD),
            ("th32ProcessID", wt.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wt.DWORD),
            ("cntThreads", wt.DWORD),
            ("th32ParentProcessID", wt.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wt.DWORD),
            ("szExeFile", wt.WCHAR * 260),
        ]

    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap in (0, -1):
        return False
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        target = exe_name.lower()
        while ok:
            if entry.szExeFile.lower() == target:
                return True
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
        return False
    finally:
        kernel32.CloseHandle(snap)


def spawn(exe, workdir, args=None):
    return subprocess.Popen(
        [exe] + list(args or []),
        cwd=workdir,
        creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
        close_fds=True,
    )


def list_processes():
    """返回 [(pid, ppid, exe_name)]"""
    TH32CS_SNAPPROCESS = 0x00000002

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wt.DWORD),
            ("cntUsage", wt.DWORD),
            ("th32ProcessID", wt.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wt.DWORD),
            ("cntThreads", wt.DWORD),
            ("th32ParentProcessID", wt.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wt.DWORD),
            ("szExeFile", wt.WCHAR * 260),
        ]

    res = []
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap in (0, -1):
        return res
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            res.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID),
                        entry.szExeFile))
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return res


def mumu_main(mumu_root):
    return os.path.join(mumu_root, "nx_main", "MuMuNxMain.exe")


def proc_elevated(pid):
    """目标进程是否处于提权状态（True/False/None=取不到）

    这是排查 UAC 的关键：MuMu 的设备进程由 MuMuNxMain 拉起，
    父进程没提权的话，设备进程就会自己弹一次 UAC。
    """
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    TOKEN_QUERY = 0x0008
    TokenElevation = 20
    if not hasattr(kernel32, "OpenProcess") or kernel32.OpenProcess.restype is not wt.HANDLE:
        kernel32.OpenProcess.restype = wt.HANDLE
        kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    advapi32.OpenProcessToken.restype = wt.BOOL
    advapi32.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
    advapi32.GetTokenInformation.restype = wt.BOOL

    class TOKEN_ELEVATION(ctypes.Structure):
        _fields_ = [("TokenIsElevated", wt.DWORD)]

    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return None
    try:
        tok = wt.HANDLE()
        if not advapi32.OpenProcessToken(h, TOKEN_QUERY, ctypes.byref(tok)):
            return None
        try:
            te = TOKEN_ELEVATION()
            sz = wt.DWORD(0)
            if not advapi32.GetTokenInformation(tok, TokenElevation,
                                                ctypes.byref(te),
                                                ctypes.sizeof(te),
                                                ctypes.byref(sz)):
                return None
            return bool(te.TokenIsElevated)
        finally:
            kernel32.CloseHandle(tok)
    finally:
        kernel32.CloseHandle(h)


def proc_pids(exe_name):
    """返回同名进程的 pid 列表"""
    tgt = exe_name.lower()
    return [pid for pid, _ppid, name in list_processes()
            if name.lower() == tgt]


def kill_pids(pids, log=None):
    """结束给定 pid（先 taskkill /f，失败再由调用方处理）"""
    for pid in pids:
        try:
            subprocess.run(["taskkill", "/f", "/pid", str(pid)],
                           creationflags=CREATE_NO_WINDOW,
                           capture_output=True, timeout=20)
        except Exception as e:
            if log:
                log("  结束进程 %d 失败：%s" % (pid, e))


MAIN_EXE = "MuMuNxMain.exe"
_hidden_main_hwnds = []          # 本次进程隐藏过的主程序窗口，用于"显示"时还原


# 这些类名不是 MuMu 的界面窗口（Qt 内部消息窗、CEF 离屏窗、输入法窗…），一律跳过
_WINDOW_CLASS_BLOCK = (
    "chrome_", "ime", "msctfime", "static", "base_power", "shellwindow",
    "nvopengl", "temp_d3d", "vbox", "virtualbox", "hiddenwindow",
    "pyinstaller", "toolbar", "tooltips", "#32768", "progman",
)


def find_main_windows(visible_only=True, min_w=300, min_h=200):
    """找 MuMu 主程序的界面窗口，返回 [(hwnd, title, class)]

    MuMu 是 Qt 程序，进程里塞了一堆消息窗口和离屏窗口：
      Qt5156QWindowToolSaveBits  "MuMu模拟器"  可见   <- 真正看见的那个
      Qt5156QWindowIcon          "MuMu模拟器"  隐藏   <- Qt 的属主工具窗
      Chrome_WidgetWin_0         （CEF 离屏）  隐藏
    所以按"类名不在黑名单 + 尺寸够大"（+ 需要时"可见"）来筛。
    注意不能按 GW_OWNER 过滤——真正看得见的那个窗恰恰是有属主的。
    """
    pids = set(proc_pids(MAIN_EXE))
    if not pids:
        return []
    res = []

    def cb(h, l):
        try:
            pid = wt.DWORD(0)
            user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if pid.value not in pids:
                return True
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(h, cls, 256)
            if cls.value.lower().startswith(_WINDOW_CLASS_BLOCK):
                return True
            if visible_only and not user32.IsWindowVisible(h):
                return True
            r = wt.RECT()
            user32.GetWindowRect(h, ctypes.byref(r))
            if (r.right - r.left) < min_w or (r.bottom - r.top) < min_h:
                return True
            n = user32.GetWindowTextLengthW(h)
            buf = ctypes.create_unicode_buffer(n + 2)
            user32.GetWindowTextW(h, buf, n + 2)
            res.append((h, buf.value, cls.value))
        except Exception:
            pass
        return True

    try:
        user32.EnumWindows(ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)(cb), 0)
    except Exception:
        return []
    return res


def main_window_visible():
    return bool(find_main_windows(visible_only=True))


def _show_hwnds(hwnds, log=None, tag=""):
    for h in hwnds:
        user32.ShowWindow(h, 9 if user32.IsIconic(h) else 1)   # SW_RESTORE / SW_SHOWNORMAL
        try:
            user32.SetForegroundWindow(h)
        except Exception:
            pass
    time.sleep(0.4)
    ok = [h for h in hwnds if user32.IsWindowVisible(h)]
    if log:
        if ok:
            log("已显示 MuMu 主程序窗口%s（%d 个）" % (tag, len(ok)))
        else:
            log("✗ 窗口没能显示出来%s（可能被 UIPI 挡住：请用提权后的启动器操作）" % tag)
    return bool(ok)


def set_main_window(show, log=None):
    """显示 / 隐藏 MuMu 主程序窗口（进程不动，模拟器照常运行）

    show=False -> SW_HIDE：任务栏里也消失，进程还在，MuMu 的 IPC 照常可用。
    show=True  -> 优先还原本次隐藏过的窗口；没有记录就按类名挑内容窗口显示。

    注意：必须和 MuMu 同权限等级才改得动。MuMu 是提权进程时，
    低权限进程调 ShowWindow 会被 UIPI 静默拦掉（返回 0、看起来没效果），
    所以这些操作都只在提权后的启动器里做。
    """
    if show:
        known = [h for h in _hidden_main_hwnds if user32.IsWindow(h)]
        if known:
            out = _show_hwnds(known, log)
            _hidden_main_hwnds[:] = []
            return out
        # 没有记录（比如换了个新进程）：只放内容窗口，别把 Qt 的属主工具窗也弹出来
        cand = find_main_windows(visible_only=False)
        pick = [(h, t, c) for h, t, c in cand if "qwindowicon" not in c.lower()]
        targets = [h for h, _t, _c in (pick or cand)]
        if not targets:
            if log:
                log("没有找到 MuMu 主程序窗口（进程可能没开）")
            return False
        return _show_hwnds(targets, log, "（按类名推断）")

    targets = find_main_windows(visible_only=True)
    if not targets:
        if log:
            log("MuMu 主程序窗口已经不在了")
        return False
    for h, _title, _cls in targets:
        user32.ShowWindow(h, 0)                # SW_HIDE
        if h not in _hidden_main_hwnds:
            _hidden_main_hwnds.append(h)
    time.sleep(0.4)
    left = [h for h, _t, _c in find_main_windows(visible_only=True)]
    if log:
        if left:
            log("✗ 窗口没能隐藏（%d 个还可见）" % len(left))
        else:
            log("已隐藏 MuMu 主程序窗口（%s）· 模拟器照常运行"
                % "、".join(t or "无标题" for _h, t, _c in targets))
    return not left


def minimize_main_window(log=None):
    targets = find_main_windows(visible_only=True)
    if not targets:
        return False
    for h, _t, _c in targets:
        user32.ShowWindow(h, 6)                # SW_MINIMIZE
        if h not in _hidden_main_hwnds:
            _hidden_main_hwnds.append(h)
    time.sleep(0.4)
    left = find_main_windows(visible_only=True)
    if log:
        log("已最小化 MuMu 主程序窗口" if not left
            else "✗ 窗口没能最小化")
    return not left


def _main_window_worker(mode, log, wait=120):
    """后台等主程序窗口冒头再收起来

    MuMu 的窗口是异步弹的（启动后可能几十秒才出现，也可能这次压根不弹），
    所以不能直接上手就藏——先盯着，看见了再收，收完再补看几秒防止它二次弹出。
    """
    deadline = time.time() + wait
    hid = False
    act = minimize_main_window if mode == "minimize" else (
        lambda lg=None: set_main_window(False, lg))
    while time.time() < deadline:
        if find_main_windows(visible_only=True):
            act(log)
            hid = True
            for _ in range(8):          # 补刀：Qt 分两步建窗，可能刚藏完又弹一个
                time.sleep(1.0)
                if find_main_windows(visible_only=True):
                    act(log)
            break
        time.sleep(1.0)
    if not hid and log:
        log("主程序窗口 %d 秒内没弹出，本次没动它（想收起点「隐藏 MuMu」）" % wait)


# ----------------------------------------------------------------------------
# MaaEnd（终末地助手）：启动 + 读它的日志判断"任务链跑完了没"
# ----------------------------------------------------------------------------
# MaaEnd 是 MXU 壳的 MaaFramework 应用，命令行支持（从 exe 里扒出来的）：
#     MaaEnd.exe --autostart [-i/--instance "实例名"] [-q/--quit-after-run]
# 运行日志写在 <MaaEnd目录>/debug/<YYYY-MM-DD>-<N>.log，关键事件：
#     开始：INFO  [Task] 实例 XXX: 开始执行任务, 数量: N
#     完成：DEBUG [App] 收到 state-changed，已刷新运行时状态, kind: tasks-completed
# 任务链最后一项是 CloseGamePC（MaaEnd 里勾了"任务完成后关闭游戏"），
# 所以"任务完成 + 终末地窗口消失"就是可以接着开 MuMu 的信号。
MAAEND_LOG_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-\d+\.log$")
MAAEND_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
MAAEND_MARK_DONE = "kind: tasks-completed"
MAAEND_MARK_START = "开始执行任务"


def maaend_log_files(root, sub="debug"):
    """返回 debug 目录下的日志文件，按修改时间从旧到新排"""
    d = os.path.join(root, sub)
    if not os.path.isdir(d):
        return []
    files = [os.path.join(d, f) for f in os.listdir(d)
             if MAAEND_LOG_RE.match(f)]
    files.sort(key=lambda p: os.path.getmtime(p))
    return files


def maaend_scan(files, bytes_each=1048576):
    """扫日志尾部，返回 (last_start_ts, last_done_ts, 备注)

    每次只看文件末尾一段，避免几十 MB 的日志把轮询拖慢。
    """
    last_start = last_done = None
    note = ""
    for path in files[-3:]:                      # 只看最近 3 个（跨天/滚动）
        try:
            size = os.path.getsize(path)
            with open(path, "rb") as f:
                f.seek(max(0, size - bytes_each))
                tail = f.read().decode("utf-8", "replace")
        except Exception as e:
            note = "%s 读取失败：%s" % (os.path.basename(path), e)
            continue
        for line in tail.splitlines():
            m = MAAEND_TS_RE.match(line)
            if not m:
                continue
            ts = m.group(1)
            if MAAEND_MARK_DONE in line:
                last_done = ts
            elif MAAEND_MARK_START in line:
                last_start = ts
                note = line.split("]")[-1].strip()[:60]
    return last_start, last_done, note


MAAEND_MARK_FAIL = "task failure"        # MXU 壳的 telemetry 行：某个 task 失败
MXU_TAURI_RE = re.compile(r"^mxu-tauri.*\.log$")
MXU_TAURI_TS_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2})\]\[(\d{2}:\d{2}:\d{2})\]")


def mxu_tauri_files(root, sub="debug"):
    """MXU 壳（MaaEnd / MaaFgo）的 tauri 日志，含按大小轮转出来的归档

    mxu-tauri.log 只按大小轮转（实测到 1MB 就改名成 mxu-tauri_2026-11-02_10-42-28.log），
    一轮任务里可能被切好几次 —— 失败计数必须把归档一起算，否则只看当前文件会漏掉
    前半程的失败。
    """
    d = os.path.join(root, sub)
    if not os.path.isdir(d):
        return []
    files = [os.path.join(d, f) for f in os.listdir(d) if MXU_TAURI_RE.match(f)]
    files.sort(key=lambda p: os.path.getmtime(p))
    return files


def mxu_fail_scan(root, sub="debug", since=None, bytes_each=1048576):
    """数 since（含）之后出现过多少次 task failure

    只看这些日志每个文件末尾 1MB：轮转文件本身约 1MB，够用；
    当前文件在长任务里可能十几 MB，但失败一定发生在近期，尾巴够覆盖。
    返回 (次数, 首次时间, 最后时间, 失败任务名列表)
    """
    n = 0
    first = last = None
    tasks = []
    for path in mxu_tauri_files(root, sub)[-3:]:
        try:
            size = os.path.getsize(path)
            with open(path, "rb") as f:
                f.seek(max(0, size - bytes_each))
                tail = f.read().decode("utf-8", "replace")
        except Exception:
            continue
        for line in tail.splitlines():
            if MAAEND_MARK_FAIL not in line:
                continue
            m = MXU_TAURI_TS_RE.match(line)
            if not m:
                continue
            ts = "%s %s" % (m.group(1), m.group(2))
            if since and ts < since:
                continue
            n += 1
            if first is None:
                first = ts
            last = ts
            t = re.search(r"\btask=(\S+)", line)
            if t and t.group(1) not in tasks:
                tasks.append(t.group(1))
    return n, first, last, tasks


def mxu_run_verdict(root, sub, start_ts, done_ts, min_seconds=0, check_fail=True,
                    since_ts=None):
    """判断这一轮 MXU 任务（MaaEnd / MaaFgo）算成功还是失败

    **关键：「tasks-completed」只说明任务链跑完了，失败也会发这个标记** ——
    某个 task 失败后 MaaEnd 会自己 stop_agent，同一秒写出 tasks-completed
    （2026-11-02 实测：09:29~09:36 连续 12 个 task failure，09:36:47 stop_agent
    并写 tasks-completed，启动器据此判定"任务已完成"）。所以还要再问两句：

      1) 本轮期间（start_ts 之后）有没有 task failure
      2) 总耗时够不够长（跑 3 分钟就"完成"肯定是崩了，而不是干完了）

    返回 (ok, reasons, info)。reasons 是给人看的中文句子，info 里带原始数据。
    """
    reasons = []
    info = {"fails": 0, "tasks": [], "seconds": None,
            "first_fail": None, "last_fail": None}
    if start_ts and done_ts:
        try:
            a = time.mktime(time.strptime(start_ts, "%Y-%m-%d %H:%M:%S"))
            b = time.mktime(time.strptime(done_ts, "%Y-%m-%d %H:%M:%S"))
            secs = int(b - a)
            if 0 <= secs < 86400:
                info["seconds"] = secs
        except (ValueError, OverflowError):
            pass
    if check_fail:
        since = since_ts or start_ts
        n, first, last, tasks = mxu_fail_scan(root, sub, since=since)
        info.update(fails=n, tasks=tasks, first_fail=first, last_fail=last)
        if n:
            head = "、".join(tasks[:4])
            if len(tasks) > 4:
                head += " 等"
            reasons.append("本轮有 %d 个任务失败（%s）"
                           % (n, head or "日志里没记任务名"))
    if min_seconds and info["seconds"] is not None and info["seconds"] < min_seconds:
        reasons.append("只跑了 %d 分 %d 秒，低于下限 %d 分（多半是起来就崩了）"
                       % (info["seconds"] // 60, info["seconds"] % 60,
                          int(min_seconds // 60)))
    return (not reasons), reasons, info


def find_windows_by(class_regex=None, title_regex=None, min_w=0, min_h=0):
    """按类名/标题正则找顶层可见窗口，返回 [(hwnd, title, class)]"""
    cres = re.compile(class_regex, re.I) if class_regex else None
    tres = re.compile(title_regex, re.I) if title_regex else None
    res = []

    def cb(h, l):
        try:
            if not user32.IsWindowVisible(h):
                return True
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(h, cls, 256)
            if cres and not cres.search(cls.value):
                return True
            r = wt.RECT()
            user32.GetWindowRect(h, ctypes.byref(r))
            if min_w and (r.right - r.left) < min_w:
                return True
            if min_h and (r.bottom - r.top) < min_h:
                return True
            n = user32.GetWindowTextLengthW(h)
            buf = ctypes.create_unicode_buffer(n + 2)
            user32.GetWindowTextW(h, buf, n + 2)
            title = buf.value
            if tres and not tres.search(title):
                return True
            res.append((h, title, cls.value))
        except Exception:
            pass
        return True

    try:
        user32.EnumWindows(ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)(cb), 0)
    except Exception:
        return []
    return res


def maaend_game_running(cfg):
    """终末地游戏窗口在不在（MaaEnd 用 UnityWndClass / Endfield 匹配它）"""
    m = cfg.get("maaend", {})
    return bool(find_windows_by(m.get("game_window_class", "UnityWndClass"),
                                m.get("game_window_title", "Endfield"),
                                min_w=200, min_h=150))


def maafgo_sync_device(exe, instance_name, port, log=None):
    """把 MaaFgo 配置里记的目标设备地址改成当前实际端口

    MaaFgo（MXU 壳）把上次连的设备记在 config/mxu-MaaFgo.json 的
    instances[].savedDevice.adbDeviceAddress（形如 127.0.0.1:16416）。
    MuMu 每次启动都会重写端口，不改这里就会连到上一个实例或者连不上。
    只在 MaaFgo 没运行时改，否则它退出时会用自己的内存值覆盖回去。
    """
    cfg_path = os.path.join(os.path.dirname(exe), "config", "mxu-MaaFgo.json")
    if not os.path.isfile(cfg_path):
        if log:
            log("提示：没找到 MaaFgo 配置 %s，跳过设备地址对齐" % cfg_path)
        return False
    if proc_running(os.path.basename(exe)):
        return False
    try:
        with open(cfg_path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception as e:
        if log:
            log("MaaFgo 配置读取失败：%s" % e)
        return False

    addr = "127.0.0.1:%d" % int(port)
    changed = []
    for inst in data.get("instances", []):
        if instance_name and inst.get("name") != instance_name:
            continue
        dev = inst.setdefault("savedDevice", {})
        if dev.get("adbDeviceAddress") != addr:
            dev["adbDeviceAddress"] = addr
            changed.append(inst.get("name") or inst.get("id"))
    if not changed:
        return False
    try:
        tmp = cfg_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, cfg_path)
    except Exception as e:
        if log:
            log("MaaFgo 配置写入失败：%s" % e)
        return False
    if log:
        log("已把 MaaFgo 设备地址对齐到 %s（%s）" % (addr, "、".join(changed)))
    return True


# -- ok-ww（鸣潮）------------------------------------------------------------
OKWW_TITLE = "OK-WW"


def okww_windows():
    """找 ok-ww 的主窗口，返回 [(hwnd, title)]

    ok-ww 是 Qt 程序，主窗口标题取自 config.py 的 gui_title（"OK-WW"）。
    用它判断"是否已经开着一个实例"最简单——比去查 pythonw 命令行可靠。
    """
    res = []

    def cb(h, l):
        try:
            if not user32.IsWindowVisible(h):
                return True
            n = user32.GetWindowTextLengthW(h)
            if n <= 0:
                return True
            buf = ctypes.create_unicode_buffer(n + 4)
            user32.GetWindowTextW(h, buf, n + 4)
            t = buf.value or ""
            if OKWW_TITLE.lower() in t.lower():
                res.append((h, t))
        except Exception:
            pass
        return True

    try:
        user32.EnumWindows(ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)(cb), 0)
    except Exception:
        return []
    return res


def okww_running():
    return bool(okww_windows())


# -- 选目录（设置页用）--------------------------------------------------------
ole32 = ctypes.WinDLL("ole32", use_last_error=True)


class BROWSEINFOW(ctypes.Structure):
    _fields_ = [
        ("hwndOwner", wt.HWND),
        ("pidlRoot", ctypes.c_void_p),
        ("pszDisplayName", wt.LPWSTR),
        ("lpszTitle", wt.LPCWSTR),
        ("ulFlags", wt.UINT),
        ("lpfn", ctypes.c_void_p),
        ("lParam", wt.LPARAM),
        ("iImage", ctypes.c_int),
    ]


shell32.SHBrowseForFolderW.argtypes = [ctypes.POINTER(BROWSEINFOW)]
shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, wt.LPWSTR]
shell32.SHGetPathFromIDListW.restype = wt.BOOL
ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]


def pick_folder(owner, title="选择文件夹"):
    """弹系统文件夹选择框；返回选中的路径，取消返回 ""

    用 SHBrowseForFolderW 而不是 IFileDialog：后者要写一堆 COM 接口声明，
    前者在 ctypes 下三个 API 就够。BIF_NEWDIALOGSTYLE 让它是可调整大小的新式框，
    但必须先 CoInitialize，否则对话框可能不显示。
    """
    BIF_RETURNONLYFSDIRS = 0x0001
    BIF_EDITBOX = 0x0010
    BIF_NEWDIALOGSTYLE = 0x0040
    try:
        ole32.CoInitialize(None)
    except Exception:
        pass
    name_buf = ctypes.create_unicode_buffer(1024)
    bi = BROWSEINFOW()
    bi.hwndOwner = owner
    bi.pidlRoot = None
    bi.pszDisplayName = ctypes.cast(name_buf, wt.LPWSTR)
    bi.lpszTitle = title
    bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_EDITBOX | BIF_NEWDIALOGSTYLE
    bi.lpfn = None
    bi.lParam = 0
    bi.iImage = 0
    pidl = shell32.SHBrowseForFolderW(ctypes.byref(bi))
    if not pidl:
        return ""
    try:
        out = ctypes.create_unicode_buffer(1024)
        if shell32.SHGetPathFromIDListW(pidl, out) and out.value:
            return out.value
        return name_buf.value
    finally:
        ole32.CoTaskMemFree(pidl)


# ============ 选 exe 的两段式流程 ======================================
# 为什么不用系统的"打开文件"框：
# - `GetOpenFileNameW`（comdlg32）：实测这台机器上直接返回错误 87，框都弹不出来；
# - `IFileDialog`（Vista+ COM）：能创建、Show 也确实弹出了可见的「打开」框，
#   但整条链路（选完 → GetResult → GetDisplayName）在自动化环境里很难验证，
#   风险不值得赌。
# 唯一实测 100% 可靠的是 `SHBrowseForFolder`（选文件夹）——设置页里 5 个路径
# 全靠它，从来没出过问题。
#
# 所以改成两段式：**先选文件夹 → 再从该目录的 exe 里挑一个**。
# 交互和其它 5 项「选路径」完全一致，用户不用学新东西。


def list_exes_in(folder):
    """列出目录下的 exe（排除卸载器），按"最像主程序"排序"""
    out = []
    try:
        for f in os.listdir(folder):
            low = f.lower()
            if low.endswith(".exe") and not low.startswith("unins"):
                out.append(os.path.join(folder, f))
    except Exception:
        return []
    base = os.path.basename(folder).lower()

    def rank(p):
        n = os.path.basename(p).lower()
        same = 0 if n.startswith(base) else 1
        return (same, len(n), n)

    out.sort(key=rank)
    return out



def pick_exe_folder(owner, title="选一个程序"):
    """选文件夹，返回路径；用户取消返回 ""

    只用 SHBrowseForFolder —— 实测这台机器上只有它能稳定弹出可见的对话框。
    """
    return pick_folder(owner, title)



def find_exe(folder, name, depth=3):
    """在 folder 及往下 depth 层里找可执行文件；找不到返回 ""

    MAA 这类解压包常常多套一层（MAA-v6.16.3-win-x64\\MAA.exe），
    用户挑目录时往往挑的是外层，所以不能只看第一层。
    """
    if not folder or not os.path.isdir(folder):
        return ""
    direct = os.path.join(folder, name)
    if os.path.isfile(direct):
        return direct
    want = name.lower()
    try:
        for root, dirs, files in os.walk(folder):
            rel = os.path.relpath(root, folder)
            if rel != "." and len(rel.split(os.sep)) > depth:
                dirs[:] = []
                continue
            for f in files:
                if f.lower() == want:
                    return os.path.join(root, f)
    except Exception:
        pass
    return ""


def apply_path_choice(kind, cfg, folder):
    """把设置页选的目录写进配置，返回要显示的一句话"""
    folder = os.path.normpath(folder)

    if kind == "mumu":
        mgr = find_exe(folder, "MuMuManager.exe", depth=2)
        if not mgr:
            return "这个目录里没找到 MuMuManager.exe（应该在 nx_main 下），没改"
        root = os.path.dirname(os.path.dirname(mgr))
        cfg["mumu_root"] = root
        idxs = discover_instance_indexes(root)
        if idxs:
            sync_instances(cfg, None)
            return "MuMu 目录已设为 %s（发现 %d 个实例：%s）" % (
                root, len(idxs), "、".join("实例%d" % i for i in idxs))
        return ("MuMu 目录已设为 %s，但 vms 里没看到实例 —— "
                "先打开 MuMu 新建一个实例，再回来点启动" % root)

    if kind == "okww":
        exe = find_exe(folder, "ok-ww.exe", depth=1)
        if not exe:
            return "这个目录里没找到 ok-ww.exe，没改"
        base = os.path.dirname(exe)
        py = os.path.join(base, "data", "apps", "ok-ww", "python", "pythonw.exe")
        wd = os.path.join(base, "data", "apps", "ok-ww", "working")
        if not os.path.isfile(py):
            return "ok-ww.exe 找到了，但没看到自带的 pythonw.exe（先启动一次 ok-ww 让它自己装），没改"
        if not os.path.isdir(wd):
            return "ok-ww.exe 找到了，但 working 目录还没生成（先启动一次 ok-ww），没改"
        cfg["okww"]["path"] = exe
        cfg["okww"]["python"] = py
        cfg["okww"]["workdir"] = wd
        return "ok-ww 已设为 %s" % base

    names = {"maaend": "MaaEnd.exe", "maa": "MAA.exe", "maafgo": "MaaFgo.exe"}
    label = {"maaend": "MaaEnd", "maa": "MAA", "maafgo": "MaaFgo"}
    want = names.get(kind)
    if not want:
        return "不认识的类型：%s" % kind
    exe = find_exe(folder, want)
    if not exe:
        return "这个目录及下面三层里都没找到 %s，没改" % want
    cfg.setdefault(kind, {})["path"] = exe
    tip = _init_tip(kind, exe)
    return "%s 已设为 %s%s" % (label[kind], exe, tip)


def _init_tip(kind, exe):
    """选了 exe 之后，顺手看一眼它有没有初始化过

    MAA 解压后从没启动 → 没有 config\\gui.json；MaaEnd/MaaFgo 同理。
    这种情况下启动器只能把它拉起来，没法让它"自动开始任务"，
    不如当场说清楚，别等跑完了才发现脚本在界面里干等。
    """
    base = os.path.dirname(exe)
    if kind == "maa":
        d = os.path.join(base, "config")
        if not (os.path.isfile(os.path.join(d, "gui.new.json"))
                or os.path.isfile(os.path.join(d, "gui.json"))):
            return "；⚠ 这个 MAA 还没初始化过，先手动打开一次、配好连接和任务"
        return ""
    if kind in ("maaend", "maafgo"):
        j = os.path.join(base, "config",
                         "mxu-%s.json" % ("MaaEnd" if kind == "maaend" else "MaaFgo"))
        if not os.path.isfile(j):
            return "；⚠ 还没初始化过，先手动打开一次、配好要跑的实例"
    if kind == "okww":
        wd = os.path.join(base, "data", "apps", "ok-ww", "working")
        if not os.path.isfile(os.path.join(wd, "main.py")):
            return "；⚠ 还没初始化过，先手动启动一次 ok-ww 让它释放环境"
    return ""


# ----------------------------------------------------------------------------
# 环境自检 / 实例自动发现
#
# 换一台机器跑，最容易出问题的不是路径本身，而是"路径对了但里面没东西"：
# MuMu 只建了 1 个实例、MAA 解压后从没启动过（没有 config\gui.json）、
# ok-ww 没先跑过一次（没有自带 python）、实例里没装对应游戏。
# 这些都不会报错，只会安静地卡住或跳过，所以点启动前先体检一遍。
# ----------------------------------------------------------------------------
def discover_instance_indexes(mumu_root):
    """列出 MuMu 里实际存在的实例号

    直接看 vms\\MuMuPlayer-12.0-N 目录，不依赖 MuMu 主程序在跑
    （MuMuManager info 在没开主程序时经常读不到东西）。
    """
    base = os.path.join(mumu_root or "", "vms")
    out = []
    try:
        if os.path.isdir(base):
            for name in os.listdir(base):
                m = re.match(r"^MuMuPlayer-12\.0-(\d+)$", name, re.I)
                if m and os.path.isdir(os.path.join(base, name)):
                    out.append(int(m.group(1)))
    except Exception:
        pass
    return sorted(set(out))


def sync_instances(cfg, log=None):
    """按 MuMu 实际有的实例重建 cfg["instances"]

    返回 True = 有改动，调用方要刷新界面。
    读不到实例（路径没设 / 目录不存在）时原样返回，绝不清空用户的列表。
    已有条目的名字和勾选状态按实例号继承，所以"记住上次勾选"不会被冲掉。
    """
    idxs = discover_instance_indexes(cfg.get("mumu_root", ""))
    if not idxs:
        return False
    old = {}
    for i in cfg.get("instances", []) or []:
        try:
            old[int(i.get("index"))] = i
        except Exception:
            pass
    new = []
    for i in idxs:
        prev = old.get(i) or {}
        new.append({
            "index": i,
            "name": prev.get("name") or INSTANCE_DEFAULT_NAMES.get(i) or ("实例%d" % i),
            "enabled": bool(prev.get("enabled", True)),
            "package": prev.get("package", ""),
        })
    same = ([int(i.get("index", -1)) for i in cfg.get("instances", []) or []]
            == idxs)
    cfg["instances"] = new
    if not same and log:
        log("MuMu 里实际有 %d 个实例：%s（已按实际情况更新界面）"
            % (len(idxs), "、".join("实例%d" % i for i in idxs)))

    # 实例号越界（典型：只建了 1 台，默认配置里 MaaFgo 写的是实例 1）
    # → 回落到现有实例，否则自检会一直报"实例1 不存在"，新手根本不知道该改哪
    for sec, field, label in (("maa", "instance_index", "MAA"),
                              ("maafgo", "emulator_index", "MaaFgo")):
        cur = (cfg.get(sec, {}) or {}).get(field)
        try:
            cur_i = int(cur)
        except Exception:
            cur_i = None
        if cur_i is not None and cur_i not in idxs:
            cfg.setdefault(sec, {})[field] = idxs[0]
            same = False
            if log:
                log("%s 原来连的实例%d 不存在，先改成实例%d（设置页可以再换）"
                    % (label, cur_i, idxs[0]))
    return not same


def _mxu_names(path):
    """读 MXU 壳（MaaEnd / MaaFgo）配置里的实例名列表"""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return [i.get("name") for i in data.get("instances", []) if i.get("name")]
    except Exception:
        return []


def preflight(cfg):
    """启动前自检

    返回 (issues, skip)：
      issues = [(level, text)]，level ∈ err / warn / ok，直接往日志里打
      skip   = 这次要跳过的项，键是 vm0 / vm1 / maa / maafgo / maaend / okww

    原则：能救的就跳过该项、把其它项照跑（比如 MaaEnd 路径错，不该连累模拟器）；
    救不了又必须的（MuMu 目录没设）就让整轮停下来。
    """
    issues = []
    skip = set()

    def add(level, text, *keys):
        issues.append((level, text))
        for k in keys:
            skip.add(k)

    # ---- MuMu ----
    root = (cfg.get("mumu_root") or "").strip()
    mgr = mumu_manager(root) if root else ""
    if not root:
        add("err", "还没设置 MuMu 模拟器目录：点「设置」→「MuMu 模拟器目录」→「选择」",
            *["vm%d" % i for i in _cfg_indexes(cfg)], "maa", "maafgo")
    elif not os.path.isfile(mgr):
        add("err", "MuMu 目录里找不到 nx_main\\MuMuManager.exe（选的可能是旧版本或外层目录）：%s"
            % root, *["vm%d" % i for i in _cfg_indexes(cfg)], "maa", "maafgo")
    else:
        idxs = discover_instance_indexes(root)
        if not idxs:
            add("err", "MuMu 里一个实例都没找到（%s\\vms 是空的）：先在 MuMu 里新建实例"
                % root, "maa", "maafgo")
        else:
            for inst in cfg.get("instances", []) or []:
                idx = int(inst.get("index", -1))
                if idx not in idxs:
                    add("err", "实例%d 在 MuMu 里不存在（实际只有 %s），这一项跳过"
                        % (idx, "、".join(str(i) for i in idxs)), "vm%d" % idx)

    # ---- MaaEnd（PC 端游戏，不需要模拟器）----
    m = cfg.get("maaend", {}) or {}
    if m.get("enabled", False):
        p = (m.get("path") or "").strip()
        if not p or not os.path.isfile(p):
            add("err", "找不到 MaaEnd.exe：%s（点「设置」→ MaaEnd →「选择」）"
                % (p or "未设置"), "maaend")
        else:
            j = os.path.join(os.path.dirname(p), "config", "mxu-MaaEnd.json")
            if not os.path.isfile(j):
                add("warn", "MaaEnd 还没初始化过（缺 config\\mxu-MaaEnd.json）："
                            "建议先手动打开一次 MaaEnd 配好「全套日常」再交给启动器", "maaend")
            else:
                names = _mxu_names(j)
                want = (m.get("instance") or "").strip()
                if want and names and want not in names:
                    add("warn", "MaaEnd 里没有叫「%s」的实例（现有：%s），"
                                "请在 config.json 改 maaend.instance" % (want, "、".join(names)))

    # ---- MAA ----
    a = cfg.get("maa", {}) or {}
    if a.get("enabled", True):
        p = (a.get("path") or "").strip()
        if not p or not os.path.isfile(p):
            add("err", "找不到 MAA.exe：%s（点「设置」→ MAA →「选择」）"
                % (p or "未设置"), "maa")
        else:
            d = os.path.join(os.path.dirname(p), "config")
            if not (os.path.isfile(os.path.join(d, "gui.new.json"))
                    or os.path.isfile(os.path.join(d, "gui.json"))):
                add("warn", "MAA 还没初始化过（config 里没有 gui.json）："
                            "先手动打开一次 MAA，配好连接与任务，否则它不会自动开跑", "maa")
            idx = int(a.get("instance_index", 0))
            # 只有 MuMu 目录确认可用时，实例号越界才是真问题
            # （目录都没设时已经报过 MuMu 那条了，再报一遍只会让人更迷）
            if mgr and os.path.isfile(mgr) and idx not in _cfg_indexes(cfg):
                add("err", "MAA 设的连接实例 %d 不在实例列表里（现有 %s）"
                    % (idx, "、".join(str(i) for i in _cfg_indexes(cfg)) or "无"), "maa")

    # ---- MaaFgo ----
    f = cfg.get("maafgo", {}) or {}
    if f.get("enabled", True):
        p = (f.get("path") or "").strip()
        if not p or not os.path.isfile(p):
            add("err", "找不到 MaaFgo.exe：%s（点「设置」→ MaaFgo →「选择」）"
                % (p or "未设置"), "maafgo")
        else:
            j = os.path.join(os.path.dirname(p), "config", "mxu-MaaFgo.json")
            if not os.path.isfile(j):
                add("warn", "MaaFgo 还没初始化过（缺 config\\mxu-MaaFgo.json）："
                            "先手动打开一次，勾好要跑的任务", "maafgo")
            else:
                names = _mxu_names(j)
                want = (f.get("instance") or "").strip()
                if want and names and want not in names:
                    add("warn", "MaaFgo 里没有叫「%s」的实例（现有：%s），"
                                "请在 config.json 改 maafgo.instance" % (want, "、".join(names)))
        idx = int(f.get("emulator_index", 1))
        if mgr and os.path.isfile(mgr) and idx not in _cfg_indexes(cfg):
            add("err", "MaaFgo 设的连接实例 %d 不在实例列表里（现有 %s）"
                % (idx, "、".join(str(i) for i in _cfg_indexes(cfg)) or "无"), "maafgo")
        pkg = (f.get("game_package") or "").strip()
        if not pkg:
            add("warn", "MaaFgo 没设游戏包名（maafgo.game_package），"
                        "启动器不会帮你开游戏，请手动在实例里开好 FGO")

    # ---- ok-ww（PC 端游戏，不需要模拟器）----
    w = cfg.get("okww", {}) or {}
    if w.get("enabled", True):
        py = (w.get("python") or "").strip()
        wd = (w.get("workdir") or "").strip()
        if not wd or not os.path.isdir(wd):
            add("err", "ok-ww 的 working 目录不存在：%s（先手动启动一次 ok-ww.exe 让它释放环境）"
                % (wd or "未设置"), "okww")
        elif not os.path.isfile(os.path.join(wd, "main.py")):
            add("err", "ok-ww 的 working 目录里没有 main.py：%s" % wd, "okww")
        elif not py or not os.path.isfile(py):
            add("err", "找不到 ok-ww 自带的 pythonw.exe：%s（先手动启动一次 ok-ww.exe）"
                % (py or "未设置"), "okww")

    # ---- 权限 / 全局 ----
    if not is_admin():
        issues.append(("warn", "当前不是管理员权限：MuMu 设备进程可能自己弹 UAC，"
                               "模拟器有启动失败风险"))
    return issues, skip


def _cfg_indexes(cfg):
    out = []
    for i in cfg.get("instances", []) or []:
        try:
            out.append(int(i.get("index")))
        except Exception:
            pass
    return out


# -- 任务完成检测（MAA / MaaFgo / ok-ww）--------------------------------------
LOG_TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})")
MAA_DONE_MARK = "任务已全部完成"          # MAA GUI: TaskQueueViewModel
MAACORE_DONE_MARK = "AllTasksCompleted"  # MaaCore 兜底
MXU_DONE_MARK = "tasks-completed"        # MXU 壳（MaaEnd / MaaFgo 共用）
MXU_START_MARK = "开始执行任务"           # MXU 每开一段任务都会打一条
OKWW_DONE_MARK = "end running onetime_task"   # ok-ww（需 debug=True 才写）

MUMU_DATE_LOG_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-\d+\.log$")


def parse_log_ts(line):
    """从日志行里抠 'YYYY-MM-DD HH:MM:SS'，返回 epoch 秒；抠不到返回 None

    三种日志的时间格式各不相同，但都能被同一正则命中：
      [2026-10-29 10:42:10.475][INF][...]   MAA
      2026-10-29 15:36:12 DEBUG [App] ...   MaaFgo / MaaEnd
      2026-10-29 16:04:21,582 INFO ...      ok-ww
    """
    m = LOG_TS_RE.search(line)
    if not m:
        return None
    try:
        return time.mktime(time.strptime(m.group(1) + " " + m.group(2),
                                         "%Y-%m-%d %H:%M:%S"))
    except Exception:
        return None


def scan_logs(files, marker, since, bytes_each=786432):
    """在日志尾部找 marker，只认时间戳 >= since 的行；返回最新的命中时间

    只看文件末尾一段，几十 MB 的 asst.log 也不会把轮询拖死。
    since 用"该程序本次启动的时刻"，这样上一轮留下的旧标记不会被当成这一轮。
    """
    hit = None
    for path in files:
        try:
            size = os.path.getsize(path)
            with open(path, "rb") as f:
                f.seek(max(0, size - bytes_each))
                tail = f.read().decode("utf-8", "replace")
        except Exception:
            continue
        for line in tail.splitlines():
            if marker not in line:
                continue
            ts = parse_log_ts(line)
            if ts is None or ts < since:
                continue
            if hit is None or ts > hit:
                hit = ts
    return hit


def scan_logs_multi(files, markers, since, bytes_each=786432):
    """一次扫完日志尾部，返回 {marker: 最新命中时间}（没命中是 None）

    MaaFgo 的任务链是**分段**跑的：一段跑完打 tasks-completed，
    十几秒后又打一条「开始执行任务」开下一段。只看 tasks-completed
    会把中间那段的结束当成全部结束（实测 17:39:27 与 17:41:50 差 2 分 23 秒）。
    所以要把"最后一次开始"的时间也一起取出来做比较。
    """
    hits = {m: None for m in markers}
    for path in files:
        try:
            size = os.path.getsize(path)
            with open(path, "rb") as f:
                f.seek(max(0, size - bytes_each))
                tail = f.read().decode("utf-8", "replace")
        except Exception:
            continue
        for line in tail.splitlines():
            ts = parse_log_ts(line)
            if ts is None or ts < since:
                continue
            for m in markers:
                if m in line:
                    if hits[m] is None or ts > hits[m]:
                        hits[m] = ts
                    break
    return hits


def _recent_files(folder, pattern, limit=4):
    """某个目录下匹配 pattern 的日志，按修改时间从新到旧取前 limit 个"""
    if not os.path.isdir(folder):
        return []
    out = []
    try:
        for name in os.listdir(folder):
            if not pattern.match(name):
                continue
            p = os.path.join(folder, name)
            if os.path.isfile(p):
                out.append((os.path.getmtime(p), p))
    except Exception:
        return []
    out.sort(reverse=True)
    return [p for _m, p in out[:limit]]


def maa_log_files(cfg):
    """MAA 的 GUI 日志：<MAA 目录>\\debug\\gui.log（轮转后是 gui.bak.log）"""
    exe = cfg.get("maa", {}).get("path", "")
    folder = os.path.join(os.path.dirname(exe), "debug")
    return _recent_files(folder, re.compile(r"^gui.*\.log$"))


def maa_core_log_files(cfg):
    """MaaCore 的流水日志（几十 MB，只在 GUI 那句没命中时才扫兜底标记）"""
    exe = cfg.get("maa", {}).get("path", "")
    folder = os.path.join(os.path.dirname(exe), "debug")
    return _recent_files(folder, re.compile(r"^asst.*\.log$"), limit=2)


def maafgo_log_files(cfg):
    """MaaFgo 的 MXU 日志：<目录>\\debug\\2026-10-29-4.log"""
    exe = cfg.get("maafgo", {}).get("path", "")
    folder = os.path.join(os.path.dirname(exe), "debug")
    return _recent_files(folder, MUMU_DATE_LOG_RE)


def okww_log_files(cfg):
    """ok-ww 的日志：<working>\\logs\\ok-script.log"""
    wd = cfg.get("okww", {}).get("workdir", "")
    folder = os.path.join(wd, "logs")
    return _recent_files(folder, re.compile(r"^ok-script.*\.log$"))


def find_unreal_windows(cfg, min_w=400, min_h=300):
    """找鸣潮（ok-ww 控制的那个 PC 游戏）的主窗口"""
    w = cfg.get("okww", {})
    cls = w.get("game_window_class", "UnrealWindow")
    return find_windows_by(cls, None, min_w=min_w, min_h=min_h)


def close_game_window(cfg, log=None, wait=12):
    """给游戏主窗口发 WM_CLOSE，让它自己正常退出（不是强杀）

    ok-ww 侧只要 Basic Options 的 "Exit App when Game Exits" 是关着的，
    游戏退出后它只弹一条 "Game Exited" 通知，界面留着，正是我们要的效果。
    """
    wins = find_unreal_windows(cfg)
    if not wins:
        if log:
            log("没找到鸣潮的游戏窗口（可能已经关了）")
        return False
    for h, title, cls in wins:
        user32.PostMessageW(h, WM_CLOSE, 0, 0)
        if log:
            log("已向游戏窗口发关闭消息：%s（%s）" % (title or "无标题", cls))
    # 等它真的退；还在就等下一轮或强杀
    t0 = time.time()
    while time.time() - t0 < wait:
        if not find_unreal_windows(cfg):
            if log:
                log("鸣潮已退出")
            return True
        time.sleep(1.0)
    if log:
        log("⚠ 游戏窗口还开着，直接结束进程")
    run_hidden(["taskkill", "/F", "/IM",
                cfg.get("okww", {}).get("game_exe", "Client-Win64-Shipping.exe")], 30)
    return not find_unreal_windows(cfg)


def shutdown_instance(cfg, idx, log=None):
    """只关某一个 MuMu 实例（比如 FGO 那个），别的实例和四个程序都不动

    MAA / MaaFgo 是 ADB 控制器，实例关掉后它们会显示"设备断开"，
    但进程、窗口、日志全都还在——正好留着查结果。
    """
    mgr = mumu_manager(cfg.get("mumu_root", ""))
    if not os.path.isfile(mgr):
        if log:
            log("✗ 找不到 MuMuManager.exe，无法关闭实例 %s" % idx)
        return False
    if log:
        log("关闭 MuMu 实例 %s（模拟器以外的进程都保留）…" % idx)
    rc, out = run_hidden([mgr, "control", "-v", str(idx), "shutdown"], 120)
    if rc != 0 and log:
        log("  MuMuManager 返回 %s：%s" % (rc, (out or "").strip()[:120]))
    # 等它真的退干净，别让后面的判断看到还是"在跑"
    for _ in range(20):
        if not instance_running(cfg, idx):
            break
        time.sleep(1.0)
    alive = instance_running(cfg, idx)
    if alive:
        if log:
            log("  实例 %s 还没退干净，再等一轮" % idx)
        time.sleep(5.0)
        alive = instance_running(cfg, idx)
    if log:
        log("实例 %s 已关闭" % idx if not alive else "⚠ 实例 %s 仍在运行" % idx)
    return not alive


def instance_running(cfg, idx):
    """实例是否还在跑：读它的 adb 端口配置，能连上并 boot_completed=1 就算在跑"""
    root = cfg.get("mumu_root", "")
    adb = detect_adb(root)
    port = read_adb_port(root, idx)
    if not adb or not port:
        return False
    s = "127.0.0.1:%d" % port
    rc, out = run_hidden([adb, "-s", s, "shell", "getprop", "sys.boot_completed"], 8)
    return rc == 0 and (out or "").strip() == "1"


def shutdown_emulators(cfg, log=None):
    """只关 MuMu 模拟器实例，不动 MAA / MaaFgo / MaaEnd / ok-ww 进程

    MAA、MaaFgo 是 ADB 控制器，实例关掉后它们会显示"设备断开"，
    但进程和窗口都还在，日志也都留着——正是要用来看结果的状态。
    """
    mgr = mumu_manager(cfg.get("mumu_root", ""))
    if not os.path.isfile(mgr):
        if log:
            log("✗ 找不到 MuMuManager.exe，无法关闭实例")
        return False
    if log:
        log("关闭 MuMu 模拟器实例（进程保留）…")
    rc, out = run_hidden([mgr, "control", "-v", "all", "shutdown"], 120)
    if rc != 0 and log:
        log("  MuMuManager 返回异常：%s" % (out or "").strip()[:120])
    time.sleep(3.0)
    if proc_pids("MuMuNxDevice.exe") and log:
        log("  仍有设备进程残留，强制结束模拟器进程")
        run_hidden(["taskkill", "/F", "/IM", "MuMuNxDevice.exe"], 30)
    if log:
        log("模拟器已关闭")
    return True



# -- 界面图标 ---------------------------------------------------------------
# 图标都是 96px 单帧 ico，放在 源码/assets/icons/ 下：
#   maaend/maa/maafgo/okww  ——  从各自 exe 的 RT_GROUP_ICON 里扒的（build/extract_icons.py）
#   arknights/fgo           ——  App Store 官方 512 图标，切圆角（build/make_game_icons.py）
#   mumu                    ——  MuMuNxMain.exe 的图标
#   launcher                ——  本程序自己的图标
LR_LOADFROMFILE = 0x0010
IMAGE_ICON = 1
DI_NORMAL = 0x0003

_ICON_CACHE = {}
_PIL_ICON_CACHE = {}


def assets_dir(*parts):
    """优先 PyInstaller 的解包目录（onefile 时是 sys._MEIPASS），其次源码目录"""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        p = os.path.join(base, "assets", *parts)
        if os.path.exists(p):
            return p
    return os.path.join(APP_DIR, "assets", *parts)


def load_icon(name, px=96):
    """加载 assets/icons/<name>.ico，返 HICON；缺失返回 None（有缓存）"""
    if not name:
        return None
    key = (name, px)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    h = None
    p = assets_dir("icons", name + ".ico")
    if os.path.isfile(p):
        try:
            h = user32.LoadImageW(None, p, IMAGE_ICON, px, px, LR_LOADFROMFILE)
        except Exception:
            h = None
    _ICON_CACHE[key] = h
    return h


_ICON_DIAG_N = [0]


def _write_icon_diag():
    """--diag-icon：一次性把 Pillow 的真实状态写进 icon_diag.txt（排障专用）"""
    import traceback
    out = ["APP_DIR=%s" % APP_DIR,
           "_MEIPASS=%s" % getattr(sys, "_MEIPASS", None)]
    try:
        import PIL
        from PIL import Image
        out.append("Pillow %s  file=%s" % (getattr(PIL, "__version__", "?"),
                                           getattr(PIL, "__file__", "?")))
        try:
            Image.init()
            out.append("init 后 .ico 注册为 %r" % (Image.registered_extensions().get(".ico"),))
            out.append("Image.OPEN 里有 ICO: %r" % ("ICO" in Image.OPEN,))
        except Exception:
            out.append("init 失败: " + traceback.format_exc().replace("\n", " | "))
        try:
            import PIL.IcoImagePlugin as _ico
            out.append("import IcoImagePlugin OK file=%s" % getattr(_ico, "__file__", "frozen"))
            out.append("_accept 正常头 = %r" % (_ico._accept(b"\x00\x00\x01\x00"),))
        except Exception:
            out.append("import IcoImagePlugin 失败: " + traceback.format_exc().replace("\n", " | "))
        src = assets_dir("icons", "launcher.ico")
        if os.path.isfile(src):
            with open(src, "rb") as f:
                head = f.read(8)
            out.append("src=%s size=%d head=%s" % (src, os.path.getsize(src), head.hex()))
        else:
            out.append("src 不存在: %s" % src)
        try:
            im = Image.open(src)
            out.append("Image.open(路径) OK format=%s size=%s" % (im.format, im.size))
        except Exception:
            out.append("Image.open(路径) 失败: " + traceback.format_exc().replace("\n", " | "))
        try:
            with open(src, "rb") as f:
                im = Image.open(f)
            out.append("Image.open(文件对象) OK format=%s size=%s" % (im.format, im.size))
        except Exception:
            out.append("Image.open(文件对象) 失败: " + traceback.format_exc().replace("\n", " | "))
    except Exception:
        out.append("import PIL 失败: " + traceback.format_exc().replace("\n", " | "))
    try:
        with open(os.path.join(APP_DIR, "icon_diag.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(out))
    except Exception:
        pass


def _icon_diag(msg):
    """图标加载失败时留证据：正常路径不写；只记前 6 条，别刷屏"""
    if _ICON_DIAG_N[0] >= 6:
        return
    _ICON_DIAG_N[0] += 1
    try:
        with open(LOG_PATH, "a", encoding="utf-8", errors="replace") as f:
            f.write("[%s] icon: %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass


def _draw_icon_gdi(hdc, name, x, y, px):
    """PIL 通道不可用时的退路：DrawIconEx（最近邻缩放，有锯齿，但至少不是空白）"""
    h = load_icon(name, px)
    if not h:
        _icon_diag("%s: LoadImageW 失败 %s" % (name, assets_dir("icons", name + ".ico")))
        return False
    try:
        return bool(user32.DrawIconEx(hdc, int(round(x)), int(round(y)), h,
                                      px, px, 0, None, DI_NORMAL))
    except Exception as e:
        _icon_diag("%s: DrawIconEx %s: %s" % (name, type(e).__name__, e))
        return False


def draw_icon(hdc, name, x, y, size):
    """把图标画到 (x, y)，边长 size（都是物理像素）

    以前用 DrawIconEx + HALFTONE，但 **DrawIconEx 会忽略 SetStretchBltMode**：
    96px 的 ico 缩到 24px 时直接最近邻丢像素，侧边栏那排图标就是一片方块锯齿。
    现在改用 Pillow 的 LANCZOS 缩到目标尺寸、预乘 alpha 存进一张 32 位位图，
    再 AlphaBlend 贴上去 —— 缩放开销只在第一次（按 name+size 缓存）。

    v2.17.7：Pillow 通道任何一步出错都会记一行 `icon:` 到 launcher.log 并退回
    DrawIconEx。之前这里 `except: return False` 把异常整个吞掉，打包版里 17 个
    图标一起消失却查不出原因（PYZ 里明明有 PIL）—— 兜底和证据都要留。
    """
    if not name:                       # 没有图标的行（分组标题/摘要行）不该把绘制整块带崩
        return False
    px = max(8, int(round(size)))
    key = (name, px)
    surf = _PIL_ICON_CACHE.get(key)
    if surf is None:
        src = assets_dir("icons", name + ".ico")
        if not os.path.isfile(src):
            _icon_diag("%s: 资源缺失 %s" % (name, src))
            _PIL_ICON_CACHE[key] = False
            return _draw_icon_gdi(hdc, name, x, y, px)
        try:
            from PIL import Image
            from ui_render import DibSurface
            im = Image.open(src).convert("RGBA")
            if im.size != (px, px):
                im = im.resize((px, px), Image.LANCZOS)
            surf = DibSurface(None, px, px)
            data = im.convert("RGBa").tobytes("raw", "BGRa")   # 预乘，AlphaBlend 要这个
            ctypes.memmove(surf.bits, data, len(data))
        except Exception as e:
            _icon_diag("%s: PIL 通道失败 %s: %s" % (name, type(e).__name__, e))
            _PIL_ICON_CACHE[key] = False
            return _draw_icon_gdi(hdc, name, x, y, px)
        _PIL_ICON_CACHE[key] = surf
    if surf is False:
        return _draw_icon_gdi(hdc, name, x, y, px)
    try:
        ok = bool(msimg32.AlphaBlend(hdc, int(round(x)), int(round(y)), px, px,
                                     surf.dc, 0, 0, px, px,
                                     BLENDFUNCTION(0, 0, 255, 1)))
        if not ok:
            _icon_diag("%s: AlphaBlend 返回 0 err=%s" % (name, ctypes.get_last_error()))
        return ok
    except Exception as e:
        _icon_diag("%s: AlphaBlend %s: %s" % (name, type(e).__name__, e))
        return False


def handle_main_window_after_boot(cfg, log):
    """实例就绪后按 config.json 的 mumu_main_window 处理主程序窗口

    hide（默认）/ minimize / keep。等待时长用 mumu_main_window_wait（默认 120 秒）。
    放在后台线程里，不拖慢启动流程的收尾。
    """
    mode = str(cfg.get("mumu_main_window", "hide")).lower()
    if mode in ("keep", "none", "off", "false"):
        return
    try:
        wait = int(cfg.get("mumu_main_window_wait", 120))
    except Exception:
        wait = 120
    mode = "minimize" if mode in ("min", "minimize") else "hide"
    threading.Thread(target=_main_window_worker,
                     args=(mode, log, wait), daemon=True).start()


def proc_start_time(pid):
    """取进程创建时间（100ns 单位）；取不到返回 0"""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return 0
    try:
        c = wt.FILETIME()
        e = wt.FILETIME()
        k = wt.FILETIME()
        u = wt.FILETIME()
        if kernel32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e),
                                    ctypes.byref(k), ctypes.byref(u)):
            return (c.dwHighDateTime << 32) | c.dwLowDateTime
        return 0
    finally:
        kernel32.CloseHandle(h)


def cleanup_orphan_vmm(log):
    """清理多余的 MuMuVMMSVC 进程，只保留最新那个。

    MuMuVMMSVC 是 MuMu 用 PsExec 以 SYSTEM 身份拉起的（不是注册服务），
    它崩过一次（事件日志：MuMuVMMDDU.dll 访问违例）就会留下孤儿进程。
    之后 MuMu 按进程名找 VMM 时找到的是那个死掉的，OpenProcess 拿
    ACCESS_DENIED，虚拟机就再也起不来：
        vm_vboxmanager.log: VERR_POCO_ACCESS_DENIED
                            VERR_NEED_ADMIN_ERROR (-30109)
    """
    procs = list_processes()
    vmm = [(pid, ppid, name) for pid, ppid, name in procs
           if name.lower() == "mumuvmmsvc.exe"]
    if len(vmm) < 2:
        return 0

    vmm.sort(key=lambda x: (proc_start_time(x[0]), x[0]))
    keep = vmm[-1]
    killed = 0
    failed = 0
    for pid, ppid, _ in vmm[:-1]:
        rc, out = run_hidden(["taskkill", "/F", "/PID", str(pid)], 20)
        if rc == 0:
            killed += 1
            log("已清理多余的 MuMuVMMSVC（PID %d），保留最新的 PID %d"
                % (pid, keep[0]))
        else:
            failed += 1
    if failed and not killed:
        log("有 %d 个旧的 MuMuVMMSVC 在跑，清理失败（权限不足），已跳过" % failed)
    return killed


def mumu_vm_error(mumu_root, index, lines=120):
    """从 MuMu 自己的日志里取最后一条错误，用于失败时给可读原因"""
    p = os.path.join(mumu_root, "vms", "MuMuPlayer-12.0-%d" % index,
                     "data", "exportLogs", "vm_vboxmanager.log")
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            tail = f.readlines()[-lines:]
    except Exception:
        return ""
    hits = [x.strip() for x in tail if "[Error]" in x]
    return hits[-1][:280] if hits else ""


def kill_updater(log):
    """结束卡住的更新器进程（它的弹窗崩掉会在主界面留下灰色蒙版，全界面点不动）"""
    killed = 0
    for pid, ppid, name in list_processes():
        if name.lower() == "mumunxupdater.exe":
            rc, _ = run_hidden(["taskkill", "/F", "/PID", str(pid)], 20)
            if rc == 0:
                killed += 1
    if killed:
        log("已结束卡住的 MuMu 更新器（%d 个）" % killed)
    return killed


def disable_updater(mumu_root, log):
    """把 MuMuNxUpdater.exe 改名，彻底不再弹更新框。

    原因：nx_updater_config.json 里写了强制更新版本 6.8.8.0，本机是 6.6.1.0，
    每次开 MuMu 都会弹更新提示；这个弹窗程序一崩（ucrtbase 0xc0000409），
    主界面就被灰色蒙版盖住、完全点不动。
    """
    exe = os.path.join(mumu_root, "nx_main", "MuMuNxUpdater.exe")
    off = exe + ".disabled"
    if not os.path.isfile(exe):
        return False
    try:
        if os.path.exists(off):
            os.remove(off)
        os.rename(exe, off)
        log("已禁用 MuMu 自动更新（MuMuNxUpdater.exe -> .disabled），不会再弹更新框")
        return True
    except Exception as e:
        log("禁用更新器失败（%s），将只结束残留进程" % e)
        return False


def manager_launch(mgr, index, timeout=180):
    """用 MuMuManager 的 IPC 启动实例（主程序在跑时才有效）"""
    rc, out = run_hidden([mgr, "control", "-v", str(index), "launch"], timeout)
    ok = False
    try:
        i = out.find("{")
        data = json.loads(out[i:]) if i >= 0 else {}
        ok = int(data.get("errcode", -1)) == 0
    except Exception:
        ok = rc == 0 and "-503" not in out
    return ok, out

def is_admin():
    """当前进程是否已提权"""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def elevate_self():
    """用 runas 重新启动自己；成功拉起返回 True（调用方应立刻退出）"""
    exe = sys.executable
    if getattr(sys, "frozen", False):
        args = subprocess.list2cmdline(sys.argv[1:])
    else:
        args = subprocess.list2cmdline([os.path.abspath(__file__)] + sys.argv[1:])
    try:
        rc = shell32.ShellExecuteW(None, "runas", exe, args, APP_DIR, 1)
        return int(rc or 0) > 32
    except Exception:
        return False


# ----------------------------------------------------------------------------
# MAA 配置：启动后直接运行任务 + 连接地址对齐实例 0
# ----------------------------------------------------------------------------

TASK_NAME = "DailyLauncher"

# 一次调用完成「查询 + 触发」：任务存在就以最高权限启动它并返回 0，
# 否则返回 1。这样双击 exe 时也不会弹 UAC。
_PS_TASK_CMD = (
    "$ErrorActionPreference='Stop'; "
    "$t = Get-ScheduledTask -TaskName '%s' -ErrorAction SilentlyContinue; "
    "if ($t) { Start-ScheduledTask -TaskName '%s' | Out-Null; exit 0 } "
    "else { exit 1 }"
)


_PS_ENSURE_TASK = (
    "$ErrorActionPreference='Stop'; "
    "$exe='%s'; $dir='%s'; $name='%s'; "
    "$t=Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue; "
    "$need=$true; "
    "if ($t -and $t.Actions.Count -gt 0 -and $t.Actions[0].Execute -eq $exe) { $need=$false }; "
    "if ($need) { "
    "  $a=New-ScheduledTaskAction -Execute $exe -WorkingDirectory $dir; "
    "  $s=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
    "-StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero); "
    "  $p=New-ScheduledTaskPrincipal -UserId (\"$env:USERDOMAIN\\$env:USERNAME\") "
    "-LogonType Interactive -RunLevel Highest; "
    "  Register-ScheduledTask -TaskName $name -Action $a -Principal $p -Settings $s -Force | Out-Null; "
    "  Write-Output 'CREATED' "
    "} else { Write-Output 'OK' }; "
    "Get-ScheduledTask -TaskName 'MuMuLauncher' -ErrorAction SilentlyContinue | ForEach-Object { "
    "Unregister-ScheduledTask -TaskName 'MuMuLauncher' -Confirm:$false; Write-Output 'REMOVED-OLD' }"
)


def ensure_task(name=TASK_NAME):
    """管理员身份下，把计划任务对齐到"当前这个 exe"

    免 UAC 全靠这条计划任务，但版本/目录一换（比如从 MuMu一键启动
    改名成 一键日常启动器），任务还指着旧 exe，就会静默失效。
    所以每次以管理员身份跑起来时顺手校正一次；不是管理员直接跳过。
    """
    if not is_admin():
        return False
    try:
        cmd = _PS_ENSURE_TASK % (sys.executable, APP_DIR, name)
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
            creationflags=CREATE_NO_WINDOW, capture_output=True, timeout=90)
        out = (r.stdout or b"").decode("utf-8", "replace").strip()
        err = (r.stderr or b"").decode("gbk", "replace").strip()
        log_line("ensure_task: rc=%s out=%s err=%s" % (r.returncode, out[:120], err[:200]))
        return r.returncode == 0
    except Exception as e:
        log_line("ensure_task 异常：%s: %s" % (type(e).__name__, e))
        return False


def trigger_task(name=TASK_NAME):
    """存在同名计划任务 -> 用它把自己以最高权限拉起来（不弹 UAC）。

    两条路，先快后慢：
      1. `schtasks /run` —— 百来毫秒，绝大多数机器都行（实测 0.1s）；
      2. PowerShell 的 Start-ScheduledTask —— 一定能用，但光加载 ScheduledTasks
         模块就要 2~5 秒（v2.14.0 之前只走这条，双击到窗口要 10 秒，被用户投诉）。
    只有第 1 条被安全策略拦了（rc≠0）才走第 2 条。
    """
    t0 = time.time()
    try:
        r = subprocess.run(["schtasks", "/run", "/tn", name],
                           creationflags=CREATE_NO_WINDOW,
                           capture_output=True, timeout=8)
        if r.returncode == 0:
            log_line("trigger: task=%s schtasks 成功（%.0f ms）"
                     % (name, (time.time() - t0) * 1000))
            return True
        log_line("trigger: schtasks 不可用（rc=%s），退回 PowerShell"
                 % r.returncode)
    except Exception as e:
        log_line("trigger: schtasks 异常 %s: %s，退回 PowerShell"
                 % (type(e).__name__, e))
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             _PS_TASK_CMD % (name, name)],
            creationflags=CREATE_NO_WINDOW,
            capture_output=True, timeout=60,
        )
        ok = r.returncode == 0
        log_line("trigger: task=%s rc=%s ok=%s 总耗时 %.0f ms out=%r err=%r"
                 % (name, r.returncode, ok, (time.time() - t0) * 1000,
                    (r.stdout or b"")[:160], (r.stderr or b"")[:300]))
        return ok
    except Exception as e:
        log_line("trigger: 调用 PowerShell 异常 %s: %s" % (type(e).__name__, e))
        return False

def maa_apply_config(maa_exe, port, instance_index, auto_run, fix_connect, note):
    cfg_dir = os.path.join(os.path.dirname(maa_exe), "config")
    new_cfg = os.path.join(cfg_dir, "gui.new.json")
    old_cfg = os.path.join(cfg_dir, "gui.json")
    path = new_cfg if os.path.isfile(new_cfg) else (old_cfg if os.path.isfile(old_cfg) else None)
    if not path:
        note.append("找不到 MAA 配置文件（config/gui.new.json），跳过自动运行设置")
        return False
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception as e:
        note.append("MAA 配置解析失败：%s" % e)
        return False

    changed = []
    try:
        cur = data.get("Current") or "Default"
        conf = data.get("Configurations", {}).get(cur)
        if conf is None:
            note.append("MAA 配置里没有 %s 这一套设置" % cur)
            return False
        gui = conf.setdefault("Gui", {})

        # 「启动后直接运行任务」两个方向都要写：
        #   开  → RunDirectly = true（和以前一样）
        #   关  → RunDirectly = false（用户在「安排自动任务」里关了它，
        #         就真的别让 MAA 自己跑起来）
        startup = gui.setdefault("StartUpSettings", {})
        want_run = bool(auto_run)
        if startup.get("RunDirectly") is not want_run:
            startup["RunDirectly"] = want_run
            changed.append("启动后直接运行任务" if want_run else "取消「启动后直接运行任务」")

        if fix_connect:
            conn = gui.setdefault("ConnectSettings", {})
            addr = "127.0.0.1:%d" % port
            if conn.get("Address") != addr:
                conn["Address"] = addr
                changed.append("连接地址 → %s" % addr)
            extras = conn.setdefault("Extras", {}).setdefault("MuMuEmulator12", {})
            if extras.get("InstanceIndex") != instance_index:
                extras["InstanceIndex"] = instance_index
                changed.append("MuMu 实例索引 → %d" % instance_index)

        if changed:
            bak = path + ".launcher-bak"
            if not os.path.isfile(bak):
                try:
                    with open(path, "rb") as src, open(bak, "wb") as dst:
                        dst.write(src.read())
                except Exception:
                    pass
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            note.append("MAA 配置已更新：" + "、".join(changed))
        else:
            note.append("MAA 配置已就绪（自动运行已开启）")
        return True
    except Exception as e:
        note.append("写 MAA 配置失败：%s" % e)
        return False


# ----------------------------------------------------------------------------
# 启动流程（后台线程）
# ----------------------------------------------------------------------------
class Runner:
    def __init__(self, cfg, emit):
        self.cfg = cfg
        self.emit = emit  # emit(kind, *args)
        self.stop_flag = False
        self._spawned = None      # 随主程序一起拉起的实例号
        self.baseline = {}        # 各程序"本次启动"时刻，用于区分上一轮日志
        self.done = {}            # 各程序的任务完成检测结果
        self.monitor_on = False   # 后台完成监视是否已启动
        self.skip = set()         # 自检认为"这次跑不了"的项（vm0/maa/maafgo/maaend/okww）
        self.only = None          # 本次只跑这些项（开机点「是」时由 App 设置）
        # 任务侧判定为失败（不是用户取消）。失败和取消必须分开：
        # 取消是"我不想跑了"，失败是"跑了但没成"—— 后者要停下并叫人来看，
        # 而不是默默开下一轮把别的游戏也拉起来。
        self.failed = False
        self.fail_reason = ""

    def cancel(self):
        if not self.stop_flag:
            self.stop_flag = True
            self.log("收到取消，正在停止后续步骤…")

    def log(self, msg):
        log_line(msg)
        self.emit("log", msg)

    def step(self, key, state, detail=""):
        self.emit("step", key, state, detail)

    def cancel_steps(self, keys, detail="已取消"):
        for k in keys:
            self.step(k, "idle", detail)

    # -- MaaEnd（终末地）---------------------------------------------------
    def start_maaend(self):
        """启动 MaaEnd 并自动开始任务

        MaaEnd 走 Win32 控制器（抓的是 PC 上的终末地窗口），和模拟器抢鼠标键盘，
        所以必须让它先跑完，再开 MuMu。它自己要求管理员权限，我们的启动器已经
        提权，子进程直接继承，不会再弹一次 UAC。
        """
        m = self.cfg.get("maaend", {})
        if not m.get("enabled", False):
            self.step("maaend", "idle", "已关闭")
            self.log("MaaEnd 已关闭（config.json 里 maaend.enabled 打开它）")
            return True

        exe = m.get("path", "")
        if not os.path.isfile(exe):
            self.step("maaend", "err", "路径不对")
            self.log("✗ 找不到 MaaEnd.exe：%s" % exe)
            return False

        if proc_running(os.path.basename(exe)):
            self.step("maaend", "run", "已在运行")
            self.log("MaaEnd 已在运行，直接监视它的任务进度")
            return True

        args = []
        if m.get("autostart", True):
            args.append("--autostart")
        inst = (m.get("instance") or "").strip()
        if inst:
            args += ["--instance", inst]
        if m.get("quit_after_run", False):
            args.append("--quit-after-run")

        self.emit("status", "启动 MaaEnd…")
        try:
            spawn(exe, os.path.dirname(exe), args)
        except Exception as e:
            self.step("maaend", "err", "启动失败")
            self.log("✗ MaaEnd 启动失败：%s" % e)
            return False
        self.step("maaend", "run", "任务进行中…")
        self.log("MaaEnd 已启动：%s %s" % (os.path.basename(exe), " ".join(args)))
        return True

    def wait_maaend_done(self):
        """读 MaaEnd 日志等「任务链跑完」，再等终末地窗口关掉

        判据两条都要满足：
          1) 日志里出现 kind: tasks-completed（MaaEnd 自己认为本轮任务结束了）
          2) 终末地游戏窗口消失（任务链末项是 CloseGamePC，勾了才会关）
        第 2 条给一个上限时间，超时就放行并记一行日志，免得卡死后面的流程。
        """
        m = self.cfg.get("maaend", {})
        exe = m.get("path", "")
        root = os.path.dirname(exe or ".")
        logdir = m.get("log_dir", "debug")
        total = int(m.get("timeout", 5400))
        game_wait = int(m.get("game_close_timeout", 300))
        need_game = bool(m.get("wait_game_close", True))

        t0 = time.time()
        files = maaend_log_files(root, logdir)
        known_done = None
        last_start = None
        if files:                       # 记录启动前已有的"完成"标记，别误判旧进度
            _, known_done, _ = maaend_scan(files)
        self.log("监视 MaaEnd 日志：%s" % os.path.join(root, logdir))

        done_ts = None
        # 整轮里有没有真的见到终末地窗口。任务链末项 CloseGamePC 会把游戏关掉，
        # 等我们去看的时候窗口早就没了 —— 以前一律报"可能是这轮没开游戏"，
        # 把"游戏跑过又被关掉"说成了"压根没开"，出错时非常误导。
        ever_seen = maaend_game_running(self.cfg)
        while time.time() - t0 < total:
            if self.stop_flag:
                self.step("maaend", "idle", "已取消")
                return False
            files = maaend_log_files(root, logdir)
            if files:
                st, dn, note = maaend_scan(files)
                if st:
                    last_start = st
                if dn and dn != known_done:
                    done_ts = dn
                    break
                if last_start:
                    el = int(time.time() - t0)
                    self.step("maaend", "run", "已跑 %d 分 %02d 秒"
                              % (el // 60, el % 60))
            if not ever_seen and maaend_game_running(self.cfg):
                ever_seen = True
            time.sleep(5.0)

        if not done_ts:
            self.step("maaend", "err", "等待超时")
            self.log("✗ %d 分钟内没等到 MaaEnd 任务完成（config.json 里调 maaend.timeout）"
                     % (total // 60))
            if not m.get("start_next_if_timeout", True):
                return False
            self.log("  按配置继续启动后面的 MuMu / MAA / MaaFgo")
            return True

        # ⚠ 「tasks-completed」只代表任务链跑完了 —— 失败的 task 也会发这个标记
        #   （失败后 MaaEnd 自己 stop_agent，同一秒写出 tasks-completed）。
        #   所以再问两句：本轮有没有 task failure、整体耗时够不够。
        floor_ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t0 - 120))
        ok, reasons, info = mxu_run_verdict(
            root, logdir, last_start, done_ts,
            int(m.get("min_run_seconds", 300)),
            bool(m.get("check_failures", True)),
            since_ts=max(last_start or "", floor_ts))
        secs = info.get("seconds")
        fails = info.get("fails") or 0
        if secs is not None:
            self.log("MaaEnd 任务链结束：耗时 %d 分 %d 秒，失败 %d 个任务%s"
                     % (secs // 60, secs % 60, fails,
                        ("（%s）" % "、".join(info["tasks"][:4]))
                        if info.get("tasks") else ""))
        else:
            self.log("MaaEnd 任务链结束（%s），失败 %d 个任务" % (done_ts, fails))

        if not ok:
            for r in reasons:
                self.log("✗ " + r)
            self.step("maaend", "err", "任务有失败")
            self.log("  游戏留在现场不动它，先看一眼卡在哪（MaaEnd 的 debug\\on_error 里有截图）")
            if bool(m.get("stop_on_failure", True)):
                self.failed = True      # failed 只在这条路径上置位，别让配置关掉的也停
                self.fail_reason = "MaaEnd " + "；".join(reasons)
                self.emit("status", "MaaEnd 任务失败")
                self.log("—— 「失败即停」：本轮到此为止，后面的轮次不会开始 ——")
                return False
            self.log("提示：maaend.stop_on_failure=false，仍继续启动后面的流程")
            self.emit("status", "MaaEnd 任务有失败，继续")
            return True

        self.log("MaaEnd 任务已完成（%s）" % done_ts)
        self.step("maaend", "ok", "任务完成")

        if not need_game:
            return True
        self.emit("status", "等终末地关闭…")
        gt0 = time.time()
        seen = False
        while time.time() - gt0 < game_wait:
            if self.stop_flag:
                self.step("maaend", "idle", "已取消")
                return False
            alive = maaend_game_running(self.cfg)
            if alive:
                seen = True
                el = int(time.time() - gt0)
                self.step("maaend", "ok", "任务完成 · 等游戏退出 %ds" % el)
                time.sleep(3.0)
                continue
            if seen or ever_seen:
                self.log("终末地已关闭，可以开始启动模拟器了")
                return True
            if time.time() - gt0 > 45:      # 整轮都没见着游戏窗口
                self.log("提示：这一轮始终没见到终末地窗口 —— MaaEnd 没把游戏拉起来，"
                         "或者起来就被关掉了，继续下一步")
                return True
            time.sleep(3.0)
        self.log("⚠ 等了 %d 秒终末地还没关，先继续后面的流程" % game_wait)
        return True

    # -- 单实例 -------------------------------------------------------------
    def ensure_main(self, first_idx):
        """确保 MuMu 主程序（mainnx）在跑。

        MuMuManager 的 control launch 必须先连上 mainnx 的 IPC，主程序没开时
        它自己拉不起来（返回 -503 mainnx connect failed）。而 MuMu 主程序必须
        带实例号才常驻：MuMuNxMain.exe -v <实例号>（MuMu 自己的桌面快捷方式就是
        这么写的），不带参数会立刻退出。
        """
        admin = is_admin()
        pids = proc_pids("MuMuNxMain.exe")
        if pids:
            elev = [proc_elevated(p) for p in pids]
            if admin and any(e is False for e in elev):
                # 主程序没提权 => 它拉起的 MuMuNxDevice 会自己弹一次 UAC。
                # 这是"启动器明明提权了却还在弹 UAC"的唯一来源。
                if proc_pids("MuMuNxDevice.exe"):
                    self.log("MuMu 主程序未提权，但已有实例在跑，先不动它")
                    self.log("  提示：关掉所有实例后再启动一次，就不会再弹 UAC 了")
                    self._spawned = None
                    return True
                self.log("MuMu 主程序不是提权状态（它拉起的设备进程会弹 UAC），重启为提权版本…")
                kill_pids(pids + proc_pids("MuMuNxService.exe"), self.log)
                for _ in range(24):
                    if not proc_pids("MuMuNxMain.exe"):
                        break
                    time.sleep(0.5)
                time.sleep(1.0)
            else:
                tag = "已提权" if admin else "启动器未提权（设备进程可能弹 UAC）"
                self.log("MuMu 主程序已在运行（%s）" % tag)
                self._spawned = None
                return True
            if proc_pids("MuMuNxMain.exe"):
                # 没杀掉，只能沿用：别让后面误以为实例是自己拉起来的
                self.log("MuMu 主程序没能重启为提权版本，沿用现有进程（实例启动时可能弹 UAC）")
                self._spawned = None
                return True

        main = mumu_main(self.cfg["mumu_root"])
        if not os.path.isfile(main):
            self.log("✗ 找不到 MuMuNxMain.exe：%s" % main)
            return False

        self.emit("status", "启动 MuMu 主程序…")
        try:
            spawn(main, os.path.dirname(main), ["-v", str(first_idx)])
        except Exception as e:
            self.log("✗ MuMuNxMain.exe 启动失败：%s" % e)
            return False

        t0 = time.time()
        while time.time() - t0 < 25 and not proc_running("MuMuNxMain.exe"):
            time.sleep(0.5)
        if not proc_running("MuMuNxMain.exe"):
            self.log("✗ MuMu 主程序没能起来（MuMuNxMain.exe 不在进程里）")
            self.log("  先手动双击一次 MuMu 图标看看能不能打开；打不开就把 launcher.log 发出来")
            return False

        self._spawned = first_idx
        self.log("MuMu 主程序已启动（同时拉起实例%d）" % first_idx)
        time.sleep(3.0)          # 给 mainnx 一点时间把 IPC 准备好
        return True

    # -- 单实例 -------------------------------------------------------------
    def launch_instance(self, inst, mgr, info):
        idx = int(inst["index"])
        key = "vm%d" % idx
        port = read_adb_port(self.cfg["mumu_root"], idx)
        name = inst.get("name") or ("实例%d" % idx)
        self.emit("port", idx, port)

        st = info.get(idx, {})
        if st.get("is_android_started"):
            self.log("实例%d（%s）已在运行，跳过启动" % (idx, name))
            return port

        if idx == self._spawned:
            # 这台是随主程序一起拉起来的，不用再发一次启动
            self.step(key, "run", "开机中…")
            self.log("实例%d（%s）随主程序一起启动中…" % (idx, name))
        elif st.get("is_process_started"):
            self.step(key, "run", "开机中…")
            self.log("实例%d（%s）已在启动中，等它开机" % (idx, name))
        else:
            self.step(key, "run", "启动中")
            self.log("启动 MuMu 实例%d（%s）…" % (idx, name))
            # 主程序已在跑，走 MuMuManager 的 IPC（MuMu 自己的正常方式）
            ok, out = manager_launch(mgr, idx)
            if not ok:
                self.log("  IPC 启动失败：%s" % out.strip()[:160])
                main = mumu_main(self.cfg["mumu_root"])
                if os.path.isfile(main):
                    self.log("  改用 MuMuNxMain.exe -v %d 直接拉起" % idx)
                    try:
                        spawn(main, os.path.dirname(main), ["-v", str(idx)])
                    except Exception as e:
                        self.log("  ✗ 兜底启动也失败：%s" % e)

        time.sleep(1.5)
        return port

    def wait_ready(self, ports, mgr):
        """以 ADB 能否执行命令为最终判据（比 is_android_started 可靠）

        MuMu 每次启动都会重新分配 NAT 端口转发并重写 vm_config.json，
        所以等待期间必须持续跟随端口，否则会盯着一个已作废的号等到超时
        （实测：配置写 16384，启动后变 16385，界面就一直卡在"启动中"）。
        ports 会被就地更新成实际连通的端口，MAA 用这个值才不会连错。
        """
        adb = detect_adb(self.cfg["mumu_root"])
        limit = int(self.cfg.get("timeouts", {}).get("boot", 300))
        deadline = time.time() + limit
        pending = dict(ports)
        last_info = 0.0
        while pending and time.time() < deadline and not self.stop_flag:
            for idx in list(pending):
                real = read_adb_port(self.cfg["mumu_root"], idx)
                if real and real != pending[idx]:
                    self.log("实例%d 端口由 %d 变为 %d，改连新端口"
                             % (idx, pending[idx], real))
                    pending[idx] = real
                    ports[idx] = real
                    self.emit("port", idx, real)
                serial = "127.0.0.1:%d" % pending[idx]
                run_hidden([adb, "connect", serial], 20)
                rc, out = run_hidden(
                    [adb, "-s", serial, "shell", "getprop", "sys.boot_completed"], 20
                )
                if out.strip() == "1":
                    port_ok = pending.pop(idx)
                    ports[idx] = port_ok
                    self.log("实例%d 已就绪（%s）" % (idx, serial))
                    self.step("vm%d" % idx, "ok", "已就绪 · %d" % port_ok)
            if pending and time.time() - last_info > 5:
                last_info = time.time()
                info = list_vm_info(mgr)
                for idx in pending:
                    booting = info.get(idx, {}).get("is_android_started")
                    self.step("vm%d" % idx, "run", "安卓开机中…" if booting else "启动中…")
            if pending:
                time.sleep(2.0)
        return pending

    # -- 主流程 -------------------------------------------------------------
    # ---------- 启动编排：分轮 ----------
    def item_label(self, key):
        """给日志/状态栏用的人话名字"""
        if key in ("maaend", "maa", "maafgo", "okww"):
            return {"maaend": "MaaEnd", "maa": "MAA",
                    "maafgo": "MaaFgo", "okww": "ok-ww"}[key]
        if key.startswith("vm"):
            return "实例" + key[2:]
        if key.startswith("custom:"):
            cid = key[7:]
            for it in self.cfg.get("custom_items", []) or []:
                if str(it.get("id")) == cid:
                    return it.get("name") or "自定义"
            return "自定义"
        return key

    def planned_rounds(self):
        """把项目按 config.pipeline 分轮；没编排过返回 None（= 老行为：一趟跑完）

        pipeline 结构：
            {"enabled": true,
             "assign": {"maaend": 1, "vm0": 2, "maa": 2, "maafgo": 2, "okww": 3},
             "order":  ["maaend", "vm0", "maa", "maafgo", "okww"]}

        轮号从 1 开始；不在 assign 里的项不参与分轮（这一趟不会被启动）。
        轮内顺序由 order 决定，order 里没有的排在后面。
        """
        pl = self.cfg.get("pipeline") or {}
        if not pl.get("enabled"):
            return None
        buckets = {}
        for key, r in (pl.get("assign") or {}).items():
            try:
                r = int(r)
            except Exception:
                continue
            if r > 0:
                buckets.setdefault(r, []).append(key)
        if not buckets:
            return []
        rank = {k: i for i, k in enumerate(pl.get("order") or [])}
        return [sorted(buckets[r], key=lambda k: rank.get(k, 10 ** 6))
                for r in sorted(buckets)]

    def run(self):
        """入口：配了编排就一轮一轮跑，没配就照旧一趟跑完"""
        try:
            self.stop_flag = False
            self.failed = False
            self.fail_reason = ""
            self.emit("busy", True)
            rounds = self.planned_rounds()
            if rounds is None:
                self._one_pass(None)
                return
            if not rounds:
                self.log("分轮执行已开启，但没有分配项目：本次不启动任何项目")
                self.emit("status", "没有已编排项目，本次不启动")
                return
            total = len(rounds)
            self.log("启动编排：共 %d 轮，一轮的任务真跑完了才开下一轮" % total)
            for i, keys in enumerate(rounds, 1):
                if self.stop_flag:
                    break
                names = "、".join(self.item_label(k) for k in keys)
                self.log("—— 第 %d/%d 轮：%s ——" % (i, total, names))
                self.emit("status", "第 %d/%d 轮 · 启动中…" % (i, total))
                self._one_pass(set(keys), monitor=False)
                if self.stop_flag or self.failed:
                    break
                if i < total and not self._wait_round_done(set(keys), i, total):
                    break
            if self.failed:
                # 失败时绝不静默往下走：把原因摊在状态栏和日志里，等人处理
                self.log("✗ 已暂停：%s" % (self.fail_reason or "任务失败"))
                self.log("  后面的轮次没有启动。看一眼现场、修好后重新点「开始」")
                self.emit("status", "任务失败，已暂停后续轮次")
                return
            if not self.stop_flag:
                self.log("—— 全部轮次已启动 ——")
                if self.start_monitor():
                    self.emit("status", "就绪 · 后台等任务完成")
                else:
                    self.emit("status", "就绪")
        except Exception:
            self.log("✗ 异常：\n" + traceback.format_exc())
            self.emit("status", "出错了，看日志")
        finally:
            self.emit("busy", False)

    def _wait_round_done(self, keys, i, total):
        """等这一轮的任务真的跑完，再放行下一轮

        判据和后台监视一致：MAA / MaaFgo / ok-ww 看日志里的完成标记。
        MaaEnd 在 _one_pass 里已经同步等过（跑完才返回），MuMu 实例算"起来即完成"。
        等不到就按 pipeline_round_timeout_hours 超时放行，免得整晚卡死在一轮上。
        """
        cfg = self.cfg
        poll = max(5, int(cfg.get("monitor_poll", 20)))
        limit = float(cfg.get("pipeline_round_timeout_hours", 4)) * 3600
        need = [k for k in ("maa", "maafgo", "okww")
                if k in keys and k in self.baseline]
        if not need:
            return True
        self.log("第 %d 轮还在跑（%s），等它完成再开第 %d 轮"
                 % (i, "、".join(self.item_label(k) for k in need), i + 1))
        self.emit("status", "第 %d/%d 轮 · 等任务完成…" % (i, total))
        done = {k: False for k in need}
        t0 = time.time()
        while time.time() - t0 < limit:
            if self.stop_flag:
                return False
            time.sleep(poll)
            for k in need:
                if done[k]:
                    continue
                if k == "maa":
                    ts = scan_logs(maa_log_files(cfg), MAA_DONE_MARK,
                                   self.baseline[k])
                    if ts is None:
                        ts = scan_logs(maa_core_log_files(cfg), MAACORE_DONE_MARK,
                                       self.baseline[k])
                    ok = bool(ts)
                elif k == "maafgo":
                    quiet = float(cfg.get("maafgo", {}).get("quiet", 60))
                    hits = scan_logs_multi(maafgo_log_files(cfg),
                                           (MXU_START_MARK, MXU_DONE_MARK),
                                           self.baseline[k])
                    st, ts = hits.get(MXU_START_MARK), hits.get(MXU_DONE_MARK)
                    ok = bool(ts and (st is None or ts >= st)
                              and time.time() - ts >= quiet)
                    if ok:
                        # MaaFgo 也是 MXU 壳，tasks-completed 同样会在失败后发出来
                        mg = cfg.get("maafgo", {})
                        mroot = os.path.dirname(mg.get("path", "") or ".")
                        floor = time.strftime(
                            "%Y-%m-%d %H:%M:%S",
                            time.localtime(float(self.baseline[k]) - 120))
                        vok, vreasons, _vi = mxu_run_verdict(
                            mroot, mg.get("log_dir", "debug"), st, ts,
                            int(mg.get("min_run_seconds", 180)),
                            bool(mg.get("check_failures", True)),
                            since_ts=max(st or "", floor))
                        if not vok:
                            for r in vreasons:
                                self.log("✗ MaaFgo " + r)
                            self.step(k, "err", "任务有失败")
                            if bool(mg.get("stop_on_failure", True)):
                                self.failed = True
                                self.fail_reason = "MaaFgo " + "；".join(vreasons)
                                self.log("—— 「失败即停」：第 %d 轮到此为止 ——" % i)
                                self.emit("status", "MaaFgo 任务失败，已暂停")
                                return False
                            self.log("提示：maafgo.stop_on_failure=false，继续往下走")
                else:
                    ok = bool(scan_logs(okww_log_files(cfg), OKWW_DONE_MARK,
                                        self.baseline[k]))
                if ok:
                    done[k] = True
                    self.step(k, "ok", "任务已完成")
                    self.log("✓ %s 任务已完成（第 %d 轮）"
                             % (self.item_label(k), i))
            if all(done.values()):
                self.log("—— 第 %d/%d 轮完成 ——" % (i, total))
                return True
            self.emit("status", "第 %d/%d 轮 · 等 %s…"
                      % (i, total, "、".join(self.item_label(k)
                                             for k in need if not done[k])))
        self.log("⚠ 第 %d 轮等了 %.0f 小时还没等到全部完成标记，先开下一轮"
                 % (i, limit / 3600))
        return True

    def _one_pass(self, scope=None, monitor=True):
        """跑一趟：把 scope 里的项目按固定顺序启动（None = 按勾选全跑）

        分轮编排时由 run() 每轮调一次。这里**只负责启动**，不等任务跑完 ——
        "这一轮什么时候算完"在 _wait_round_done() 里判定。
        """
        cfg = self.cfg
        try:

            # 1) 先按 MuMu 里"实际存在"的实例对齐列表。
            #    新用户通常只建了 1 个实例，配置里却写着 0 和 1，
            #    结果实例1 白等 5 分钟超时、MaaFgo 直接跳过，看着莫名其妙。
            if sync_instances(cfg, self.log):
                self.emit("sync")

            # 2) 体检：把"路径对了却跑不起来"的原因提前说清楚
            self.emit("status", "启动前自检…")
            issues, self.skip = preflight(cfg)
            for lv, text in issues:
                self.log(("✗ " if lv == "err" else "⚠ ") + text)
            for k in sorted(self.skip):
                self.step(k, "err", "自检未通过")
            nerr = sum(1 for lv, _ in issues if lv == "err")
            if nerr:
                self.log("自检有 %d 个问题：标出来的项这次跳过，其余照常跑" % nerr)

            # 本次限定范围：开机时点了「否」就只跑《今晚的手游日常》（only 非空）。
            # 只影响这一轮，不改勾选、不写 config.json。
            only = self.only
            # 用户从主界面删掉的行：这次也不参与
            hidden = set(cfg.get("hidden_items", []) or [])
            if only:
                self.log("本次只跑：%s；其余项本次跳过（勾选未改动）"
                         % "、".join(sorted(only)))

            # 没勾的项 / 不在本次范围内的项 / 被删掉的行，
            # 在界面上标成「本次跳过」，不然看起来像卡在那儿没动
            for inst in cfg.get("instances", []):
                key = "vm%d" % int(inst["index"])
                if (not inst.get("enabled", True) or key in hidden
                        or (only is not None and key not in only)):
                    self.step(key, "idle", "本次跳过")
            for key in ("maaend", "maa", "maafgo", "okww"):
                if (not cfg.get(key, {}).get("enabled", True) or key in hidden
                        or (only is not None and key not in only)):
                    self.step(key, "idle", "本次跳过")

            def want(key, default=True):
                """这一项这次要不要跑：属于本轮 + 勾了 + 在本次范围内 + 没被删 + 自检没否掉"""
                if scope is not None and key not in scope:
                    return False
                if only is not None:
                    return key in only and key not in self.skip
                if key in hidden:
                    return False
                return (bool(cfg.get(key, {}).get("enabled", default))
                        and key not in self.skip)

            def vm_on(inst):
                key = "vm%d" % int(inst["index"])
                if scope is not None and key not in scope:
                    return False
                if only is not None:
                    return key in only and key not in self.skip
                if key in hidden:
                    return False
                return inst.get("enabled", True) and key not in self.skip

            picked = []
            if want("maaend", False):
                picked.append("MaaEnd")
            for inst in cfg.get("instances", []):
                if vm_on(inst):
                    picked.append("实例%d(%s)" % (int(inst["index"]),
                                                 inst.get("name") or "模拟器"))
            for key, label in (("maa", "MAA"), ("maafgo", "MaaFgo"),
                               ("okww", "ok-ww")):
                if want(key):
                    picked.append(label)
            for it in cfg.get("custom_items", []) or []:
                ckey = "custom:%s" % it.get("id")
                if ckey in hidden:
                    continue
                if only is not None and ckey not in only:
                    continue
                if it.get("enabled", True):
                    picked.append("自定义:%s" % (it.get("name") or "项目"))

            if not picked:
                self.log("这一轮没有可执行的项（都没勾，或自检没过），不做任何操作")
                self.emit("status", "就绪（没有可执行的项）")
                self.emit("busy", False)
                return

            self.log(("本次范围（%d 项）：%s" if only else "按上次的勾选启动（%d 项）：%s")
                     % (len(picked), "、".join(picked)))

            # ---- 第一优先：MaaEnd（终末地）跑完再动模拟器 ----
            # 它用 Win32 控制器直接抓 PC 上的游戏窗口，会把鼠标键盘占住，
            # 和 MuMu 同时跑必然互相打断，所以这里串行等它收工。
            if want("maaend", False):
                self.emit("status", "MaaEnd（终末地）优先…")
                if self.start_maaend():
                    if not self.wait_maaend_done():
                        if self.failed:      # 失败和取消是两回事，状态栏别说错
                            self.emit("status", "MaaEnd 任务失败，已暂停")
                        else:
                            self.emit("status", "已取消")
                        return
                if self.stop_flag:
                    self.cancel_steps(["vm%d" % int(i["index"])
                                       for i in cfg.get("instances", [])]
                                      + ["maa", "maafgo", "okww"])
                    self.emit("status", "已取消")
                    return

            self.emit("status", "正在检查环境…")
            mumu_root = cfg.get("mumu_root", "")
            mgr = mumu_manager(mumu_root)
            mumu_ok = bool(mumu_root) and os.path.isfile(mgr)
            if not mumu_ok:
                self.log("跳过所有模拟器相关步骤（MuMu 目录没设对，先在「设置」里选）")
            else:
                self.emit("status", "检查 MuMu 状态…")
                kill_updater(self.log)                  # 卡住的更新器会留灰色蒙版
                if cleanup_orphan_vmm(self.log):
                    time.sleep(1.0)
                if cfg.get("disable_updater", True):
                    disable_updater(mumu_root, self.log)

            ports, left, info = {}, {}, {}
            insts = ([i for i in cfg.get("instances", []) if vm_on(i)]
                     if mumu_ok else [])
            self._spawned = None
            if insts:
                info = list_vm_info(mgr)
                if not info:
                    self.log("提示：读取不到实例列表，按配置继续")

                first = int(insts[0]["index"])
                if not self.ensure_main(first):
                    for inst in insts:
                        self.step("vm%d" % int(inst["index"]), "err", "主程序未启动")
                    self.emit("status", "MuMu 主程序没能启动")
                    return
                info = list_vm_info(mgr) or info

                for inst in insts:
                    ports[int(inst["index"])] = self.launch_instance(inst, mgr, info)

                self.emit("status", "等待安卓开机…")
                left = self.wait_ready(ports, mgr)
                if self.stop_flag:
                    self.cancel_steps(["vm%d" % i for i in sorted(left)])
                    self.log("已取消：不再等待剩余实例，也不再启动 MAA / MaaFgo")
                    self.emit("status", "已取消")
                    return
                for idx in sorted(left):
                    self.step("vm%d" % idx, "err", "启动超时")
                    self.log("✗ 实例%d 没等到就绪（可在 config.json 调大 timeouts.boot）" % idx)
                    err = mumu_vm_error(mumu_root, idx)
                    if err:
                        self.log("  MuMu 日志：%s" % err)

                for inst in insts:
                    idx = int(inst["index"])
                    if idx in left:
                        continue
                    pkg = (inst.get("package") or "").strip()
                    if pkg:
                        self.log("实例%d 打开应用 %s" % (idx, pkg))
                        run_hidden(
                            [mgr, "control", "-v", str(idx), "app", "launch", "-pkg", pkg],
                            60,
                        )
                    time.sleep(0.3)

            if self.stop_flag:
                self.cancel_steps(["maa", "maafgo", "okww"])
                self.emit("status", "已取消")
                return

            # ---- MAA：连哪台实例由 maa.instance_index 决定（设置页可改）----
            maa = cfg.get("maa", {})
            if want("maa"):
                mi = int(maa.get("instance_index", 0))
                self.step("maa", "run", "准备中")
                maa_exe = maa.get("path", "")
                if not os.path.isfile(maa_exe):
                    self.step("maa", "err", "路径不对")
                    self.log("✗ 找不到 MAA.exe：%s" % maa_exe)
                elif proc_running(os.path.basename(maa_exe)):
                    self.step("maa", "ok", "已在运行")
                    self.log("MAA 已在运行，跳过")
                elif mi in left:
                    self.step("maa", "err", "实例%d未就绪" % mi)
                    self.log("✗ 实例%d 没起来，跳过 MAA" % mi)
                else:
                    self.emit("status", "启动 MAA…")
                    note = []
                    port_m = ports.get(mi) or read_adb_port(mumu_root, mi)
                    maa_apply_config(
                        maa_exe,
                        port_m,
                        mi,
                        bool(maa.get("auto_run", True)),
                        bool(maa.get("fix_connect", True)),
                        note,
                    )
                    for n in note:
                        self.log(n)
                    try:
                        self.baseline["maa"] = time.time()
                        spawn(maa_exe, os.path.dirname(maa_exe))
                        self.step("maa", "ok",
                                  "已启动 · 自动开始任务" if maa.get("auto_run", True)
                                  else "已启动 · 等你手动开始")
                        self.log("MAA 已启动（等待模拟器完成后自动开始任务）")
                    except Exception as e:
                        self.step("maa", "err", "启动失败")
                        self.log("✗ MAA 启动失败：%s" % e)

            # ---- MaaFgo（FGO）：要等实例就绪、游戏开起来才能开跑 ----
            if not self.stop_flag and want("maafgo"):
                self.emit("status", "MaaFgo（FGO）…")
                self.start_maafgo(ports, left)

            # ---- ok-ww（鸣潮）：PC 前台独占，排在最后 ----
            if not self.stop_flag and want("okww"):
                self.emit("status", "ok-ww（鸣潮每日任务）…")
                self.start_okww()

            # ---- 用户自己加的项目（未适配）：只负责把游戏和脚本打开 ----
            self.start_custom_items(only, hidden, scope)

            # 实例就绪后按配置处理「MuMu模拟器」主窗口（隐藏 / 最小化 / 不动）
            if insts and len(left) < len(insts) and not self.stop_flag:
                handle_main_window_after_boot(cfg, self.log)

            if self.stop_flag:
                self.emit("status", "已取消")
                self.log("已取消")
            else:
                self.log("—— 本批启动完成 ——")
                if monitor and self.start_monitor():
                    self.emit("status", "就绪 · 后台等任务完成")
                elif not monitor:
                    pass
                else:
                    self.emit("status", "就绪")
        except Exception:
            self.log("✗ 异常：\n" + traceback.format_exc())
            self.emit("status", "出错了，看日志")
            self.stop_flag = True          # 出异常就别再往下跑下一轮了

    # -- MaaFgo（FGO）-------------------------------------------------------
    def emu_game_pid(self, idx, pkg, port=None):
        """查模拟器里这个包在不在跑，返回 pid 字符串（空=没跑）"""
        root = self.cfg.get("mumu_root", "")
        adb = detect_adb(root)
        p = port or getattr(self, "ports", {}).get(idx) or read_adb_port(root, idx)
        if not p:
            return ""
        serial = "127.0.0.1:%d" % p
        run_hidden([adb, "connect", serial], 15)
        for cmd in ("pidof %s" % pkg, "ps -A | grep %s" % pkg):
            rc, out = run_hidden([adb, "-s", serial, "shell", cmd], 20)
            txt = (out or "").strip()
            if txt and "not found" not in txt and "no such" not in txt.lower():
                return txt.splitlines()[0][:80]
        return ""

    def start_custom_items(self, only=None, hidden=None, scope=None):
        """用户自己加的项目：启动器只负责把游戏和脚本打开

        这些项目**没有适配**，所以：
          - 不会自动点"开始任务"，任务要在脚本自己的界面里点；
          - 不检测任务完成，行状态不会变成"完成"；
          - 跑完也不会帮你关游戏或关脚本。
        界面和 README 里都写明了这一点，免得以为坏了。
        """
        hidden = hidden or set()
        for it in self.cfg.get("custom_items", []) or []:
            cid = it.get("id")
            key = "custom:%s" % cid
            name = it.get("name") or "自定义"
            if key in hidden:
                self.step(key, "idle", "已从主界面删除")
                continue
            if scope is not None and key not in scope:
                continue
            if only is not None and key not in only:
                self.step(key, "idle", "本次跳过")
                continue
            if not it.get("enabled", True):
                self.step(key, "idle", "本次跳过")
                continue
            game = (it.get("game") or "").strip()
            script = (it.get("script") or "").strip()
            if not game and not script:
                self.step(key, "err", "没设路径")
                self.log("✗ 自定义「%s」既没设脚本路径也没设游戏路径，跳过" % name)
                continue
            self.step(key, "run", "打开中")
            try:
                if game:
                    if os.path.isfile(game):
                        spawn(game, os.path.dirname(game))
                        self.log("自定义「%s」：已打开游戏 %s"
                                 % (name, os.path.basename(game)))
                        time.sleep(6)          # 给游戏一点启动时间
                    else:
                        self.log("✗ 自定义「%s」的游戏文件不存在：%s" % (name, game))
                if script:
                    if os.path.isfile(script):
                        spawn(script, os.path.dirname(script))
                        self.log("自定义「%s」：已打开脚本 %s"
                                 % (name, os.path.basename(script)))
                    else:
                        self.log("✗ 自定义「%s」的脚本不存在：%s" % (name, script))
                self.step(key, "ok", "已打开")
                self.log("自定义「%s」是未适配项：启动器只帮你打开，"
                         "不会自动点任务、也不检测完成 —— "
                         "任务请在脚本自己的界面里点开始。" % name)
            except Exception as e:
                self.step(key, "err", "打开失败")
                self.log("✗ 自定义「%s」打开失败：%s" % (name, e))

    def start_maafgo(self, ports, left=None):
        """启动 MaaFgo（FGO 助手），并且等游戏真起来了才让它开始任务

        顺序：实例就绪 -> 没开游戏就用 MuMu 自己打开 -> 轮询 pidof 等游戏进程 ->
        把 MaaFgo 里记的 adb 地址改成实际端口（会漂移）-> 带 --autostart 启动。
        这样 MaaFgo 一上来看到的就是已经开着游戏，不会对着黑屏瞎点。
        """
        m = self.cfg.get("maafgo", {})
        if not m.get("enabled", True):
            self.step("maafgo", "idle", "已关闭")
            self.log("MaaFgo 已关闭（config.json 里 maafgo.enabled 打开它）")
            return
        if self.stop_flag:
            self.cancel_steps(["maafgo"])
            return

        exe = m.get("path", "")
        if not os.path.isfile(exe):
            self.step("maafgo", "err", "路径不对")
            self.log("✗ 找不到 MaaFgo.exe：%s" % exe)
            return

        idx = int(m.get("emulator_index", 1))
        pkg = (m.get("game_package") or "").strip()
        if left and idx in left:
            self.step("maafgo", "err", "实例%d 未就绪" % idx)
            self.log("✗ 实例%d 没起来，跳过 MaaFgo" % idx)
            return

        port = ports.get(idx) or read_adb_port(self.cfg.get("mumu_root", ""), idx)

        # 1) 游戏没开就先开（MuMu 自己的 app launch，比自己拼 am start 稳）
        if pkg and m.get("launch_game", True):
            pid = self.emu_game_pid(idx, pkg, port)
            if pid:
                self.log("实例%d 里 %s 已在运行（pid %s）" % (idx, pkg, pid))
            else:
                self.step("maafgo", "run", "打开游戏…")
                mgr = mumu_manager(self.cfg.get("mumu_root", ""))
                self.log("实例%d 里没看到 %s，用 MuMu 打开游戏" % (idx, pkg))
                rc, out = run_hidden(
                    [mgr, "control", "-v", str(idx), "app", "launch", "-pkg", pkg], 90)
                if rc != 0:
                    self.log("  打开游戏返回异常：%s" % (out or "").strip()[:120])

        # 2) 等游戏进程真起来
        if pkg:
            limit = int(m.get("game_wait", 240))
            settle = int(m.get("settle", 10))
            t0 = time.time()
            ok = False
            while time.time() - t0 < limit and not self.stop_flag:
                pid = self.emu_game_pid(idx, pkg, port)
                if pid:
                    ok = True
                    break
                el = int(time.time() - t0)
                self.step("maafgo", "run", "等游戏启动 %ds" % el)
                if el and el % 20 < 4:
                    self.log("  等待 %s 在实例%d 启动… %ds" % (pkg, idx, el))
                time.sleep(4.0)
            if ok:
                self.log("游戏已启动（pid %s），再等 %d 秒过启动画面" % (pid, settle))
                self.step("maafgo", "run", "游戏已启动，稳定中…")
                for _ in range(max(0, settle)):
                    if self.stop_flag:
                        break
                    time.sleep(1.0)
            else:
                self.log("⚠ 等了 %d 秒没检测到 %s，仍然启动 MaaFgo（它自己会尝试拉起）"
                         % (limit, pkg))

        if self.stop_flag:
            self.cancel_steps(["maafgo"])
            return

        # 3) 对齐 MaaFgo 配置里记的设备地址（端口会漂移，否则连错实例）
        if m.get("sync_device_address", True) and port:
            maafgo_sync_device(exe, m.get("instance", ""), port, self.log)

        # 4) 启动
        if proc_running(os.path.basename(exe)):
            self.step("maafgo", "ok", "已在运行")
            self.log("MaaFgo 已在运行，跳过启动")
            return

        args = []
        if m.get("autostart", True):
            args.append("--autostart")
        inst = (m.get("instance") or "").strip()
        if inst:
            args += ["--instance", inst]
        if m.get("quit_after_run", False):
            args.append("--quit-after-run")

        self.step("maafgo", "run", "启动中")
        try:
            self.baseline["maafgo"] = time.time()
            spawn(exe, os.path.dirname(exe), args)
            self.step("maafgo", "ok", "已启动 · 自动开始任务")
            self.log("MaaFgo 已启动：%s %s" % (os.path.basename(exe), " ".join(args)))
        except Exception as e:
            self.step("maafgo", "err", "启动失败")
            self.log("✗ MaaFgo 启动失败：%s" % e)

    # -- ok-ww（鸣潮）-------------------------------------------------------
    def start_okww(self):
        """启动 ok-ww，并让它一上来就自动开始「每日任务」

        ok-ww.exe 是 pyappify 的壳（Rust），它启动的是
        data\\apps\\ok-ww\\working\\main.py；命令行参数不一定被转发，所以这里
        直接用 ok-ww 自带的 pythonw.exe 跑 main.py，参数确定可达：

            main.py -t DailyTask      启动后立刻开始「每日任务」
                     -h               无界面（headless）
                     -e               跑完退出游戏和应用

        每日任务本身是一条龙：启动游戏 → 登录 → 领月卡 → 刷声骸 →
        领日常任务奖励 → 领邮件（DailyTask 内部串起了这些子任务）。

        它操作的是 PC 上的鸣潮窗口（Client-Win64-Shipping.exe / UnrealWindow），
        和 MaaEnd 一样抢前台，所以排在整条流程的最后。
        """
        m = self.cfg.get("okww", {})
        if not m.get("enabled", True):
            self.step("okww", "idle", "已关闭")
            self.log("ok-ww 已关闭（config.json 里 okww.enabled 打开它）")
            return
        if self.stop_flag:
            self.cancel_steps(["okww"])
            return

        workdir = m.get("workdir", "")
        py = m.get("python", "")
        if not os.path.isdir(workdir):
            self.step("okww", "err", "目录不对")
            self.log("✗ 找不到 ok-ww 的 working 目录：%s" % workdir)
            return
        if not os.path.isfile(py):
            self.step("okww", "err", "python 路径不对")
            self.log("✗ 找不到 ok-ww 自带的 pythonw.exe：%s" % py)
            return
        if not os.path.isfile(os.path.join(workdir, "main.py")):
            self.step("okww", "err", "main.py 缺失")
            self.log("✗ %s 下没有 main.py" % workdir)
            return

        # 已经有实例开着就别再起——ok-ww 有单实例互斥量，硬起会等 5 秒后报错退出
        if okww_running():
            self.step("okww", "ok", "已在运行")
            self.log("ok-ww 已在运行，跳过启动（要自动开始请先关掉它）")
            return

        task = (m.get("task") or "DailyTask").strip()
        entry = (m.get("entry") or "").strip()
        if m.get("debug_log", True):
            # 想看"任务完成"就必须有 debug 日志：ok-ww 只在
            # logger.debug('end running onetime_task …') 里留这个痕迹，
            # INFO 级别下任务跑完日志直接静默，没有任何标记。
            # 用一个自己的入口写 debug=True，不去动它的 config.py。
            entry = entry or "_launcher_auto.py"
            try:
                with open(os.path.join(workdir, entry), "w", encoding="utf-8") as f:
                    f.write(
                        "# 由「一键日常启动器」生成，每次启动重写，勿手改\n"
                        "import logging\n"
                        "\n"
                        "\n"
                        "class _KeepTaskFlow(logging.Filter):\n"
                        "    \"\"\"只留\"任务开始/结束\"两行 debug，其余 debug 全丢\n"
                        "\n"
                        "    ok-ww 正常是 INFO 级别；为了拿到 end running onetime_task\n"
                        "    必须开 DEBUG，但不加过滤的话识别日志会涨到几十万行。\n"
                        "    \"\"\"\n"
                        "\n"
                        "    def filter(self, record):\n"
                        "        if record.levelno >= logging.INFO:\n"
                        "            return True\n"
                        "        return 'onetime_task' in record.getMessage()\n"
                        "\n"
                        "\n"
                        "if __name__ == '__main__':\n"
                        "    from config import config\n"
                        "    from ok import OK\n"
                        "\n"
                        "    # 先挂过滤器再构造，构造期间那一堆 Config:init 的 debug 也一起挡掉\n"
                        "    logging.getLogger('ok').addFilter(_KeepTaskFlow())\n"
                        "    config['debug'] = True\n"
                        "    OK(config).start()\n"
                    )
            except Exception as e:
                self.log("⚠ 写 %s 失败（%s），退回 main.py" % (entry, e))
                entry = ""
        script = entry or "main.py"
        # task 为空 = 用户选了「不自启」：不能传 -t ""，argparse 会当成空任务名报错，
        # 干脆不传，ok-ww 就只开界面等你自己点。
        args = [script] + (["-t", task] if task else [])
        if m.get("headless", False):
            # 必须用 --headless：ok 的 logger 里另有一个 argparse 也在读 -h，
            # 传 -h 会先被它当成 help，直接打印用法并退出
            args.append("--headless")
        if m.get("exit_after", False):
            args.append("-e")

        self.step("okww", "run", "启动中")
        try:
            self.baseline["okww"] = time.time()
            spawn(py, workdir, args)
        except Exception as e:
            self.step("okww", "err", "启动失败")
            self.log("✗ ok-ww 启动失败：%s" % e)
            return
        self.log("ok-ww 已启动：%s %s（工作目录 %s）"
                 % (os.path.basename(py), " ".join(args), workdir))

        # 等界面出来再确认一次，顺便把"任务已在跑"这件事落到日志里
        limit = int(m.get("wait_start", 60))
        t0 = time.time()
        seen = False
        while time.time() - t0 < limit and not self.stop_flag:
            if okww_windows():
                seen = True
                break
            el = int(time.time() - t0)
            if el and el % 10 < 3:
                self.step("okww", "run", "等界面出现 %ds" % el)
            time.sleep(1.5)
        if seen:
            self.step("okww", "ok", "已启动 · 自动开始每日任务")
            self.log("ok-ww 界面已出现，「%s」应已开始（约 %ds）"
                     % (task, int(time.time() - t0)))
        else:
            self.step("okww", "ok", "已拉起（界面未确认）")
            self.log("⚠ 等了 %d 秒没看到 ok-ww 窗口，进程可能还在初始化；"
                     "直接看它的 logs\\ok-script.log" % limit)

    # -- 后台完成监视 -------------------------------------------------------
    def start_monitor(self):
        """启动流程结束后接着盯日志，等任务跑完再做收尾动作

        要做的两件事：
          ① MAA + MaaFgo 都完成 -> 关 MuMu 模拟器省资源（进程一律不杀）
          ② ok-ww 完成 -> 关鸣潮游戏（ok-ww 自己留着，方便看日志）
        """
        if self.monitor_on:
            return False
        want_emu = bool(self.cfg.get("shutdown_emulator_when_done", True))
        want_game = bool(self.cfg.get("okww", {}).get("close_game_when_done", True))
        if not want_emu and not want_game:
            self.log("后台监视已关闭（config.json 里 shutdown_emulator_when_done / "
                     "okww.close_game_when_done 都是 false）")
            return False
        self.monitor_on = True
        threading.Thread(target=self.monitor_loop, daemon=True).start()
        return True

    def release_instance(self, key, idx, label):
        """某个程序跑完了，就把它用的那个实例关掉；其他实例、四个程序都不动"""
        if idx is None:
            return
        started = [int(i["index"]) for i in self.cfg.get("instances", [])]
        if idx not in started:
            self.log("  %s 对应实例 %s 不在本次启动列表里，跳过关闭" % (label, idx))
            return
        self.emit("status", "%s 完成，关闭实例 %d…" % (label, idx))
        if shutdown_instance(self.cfg, idx, self.log):
            self.step("vm%d" % idx, "idle", "已关闭")
            self.log("✓ 实例 %d 已关闭（%s 跑完了）· 其余程序和终端都保留"
                     % (idx, label))
        else:
            self.step("vm%d" % idx, "err", "关闭失败")

    def monitor_loop(self):
        cfg = self.cfg
        poll = max(5, int(cfg.get("monitor_poll", 20)))
        max_hours = float(cfg.get("monitor_max_hours", 10))
        want_emu = bool(cfg.get("shutdown_emulator_when_done", True))
        want_game = bool(cfg.get("okww", {}).get("close_game_when_done", True))

        # 只有"这次启动过"的程序才参与判定：跳过启动的（已在运行）没有基线，
        # 硬看日志会把上一轮的完成标记当成本轮结果
        need_maa = [k for k in ("maa", "maafgo")
                    if k in self.baseline and cfg.get(k, {}).get("enabled", True)]
        need_game = "okww" in self.baseline and cfg.get("okww", {}).get("enabled", True)

        # 每个程序负责关掉自己用的那个实例：谁先跑完谁先释放，不用等另一个
        inst_of = {}
        if "maa" in need_maa:
            inst_of["maa"] = int(cfg.get("maa", {}).get("instance_index", 0))
        if "maafgo" in need_maa:
            inst_of["maafgo"] = int(cfg.get("maafgo", {}).get("emulator_index", 1))
        started_insts = [int(i["index"]) for i in cfg.get("instances", [])]

        if need_maa:
            plan = "、".join(
                "%s→实例%d" % ("MAA" if k == "maa" else "MaaFgo", inst_of[k])
                for k in need_maa if inst_of.get(k) in started_insts)
            self.log("后台监视已开：%s 跑完就关各自的实例（进程全保留）" % plan)
        if need_game:
            self.log("后台监视已开：等 ok-ww 的每日任务完成就关鸣潮（ok-ww 保留）")

        emu_closed = game_closed = False
        if not need_maa:
            emu_closed = True
        if not need_game:
            game_closed = True

        t0 = time.time()
        while time.time() - t0 < max_hours * 3600:
            time.sleep(poll)

            # ① MAA
            if not emu_closed and not self.done.get("maa") and "maa" in need_maa:
                ts = scan_logs(maa_log_files(cfg), MAA_DONE_MARK, self.baseline["maa"])
                if ts is None:
                    ts = scan_logs(maa_core_log_files(cfg), MAACORE_DONE_MARK,
                                   self.baseline["maa"])
                if ts:
                    self.done["maa"] = True
                    self.log("✓ MAA 任务已完成（%s）" % time.strftime(
                        "%H:%M:%S", time.localtime(ts)))
                    self.step("maa", "ok", "任务已完成")
                    if want_emu:
                        self.release_instance("maa", inst_of.get("maa"), "MAA")

            # ② MaaFgo：MXU 的任务链会分段跑（实测 17:39:02 / 17:39:27 / 17:41:50
            #    三段，段间只隔二十来秒），所以判据是：
            #      最后一次 tasks-completed 之后，没有再出现「开始执行任务」，
            #      并且已经静默 quiet 秒 —— 才算真的收工
            if not emu_closed and not self.done.get("maafgo") and "maafgo" in need_maa:
                quiet = float(cfg.get("maafgo", {}).get("quiet", 60))
                hits = scan_logs_multi(maafgo_log_files(cfg),
                                       (MXU_START_MARK, MXU_DONE_MARK),
                                       self.baseline["maafgo"])
                st, ts = hits.get(MXU_START_MARK), hits.get(MXU_DONE_MARK)
                if ts and (st is None or ts >= st) and time.time() - ts >= quiet:
                    self.done["maafgo"] = True
                    self.log("✓ MaaFgo 任务已完成（%s，之后 %d 秒没再开新一段）"
                             % (time.strftime("%H:%M:%S", time.localtime(ts)),
                                int(quiet)))
                    self.step("maafgo", "ok", "任务已完成")
                    if want_emu:
                        self.release_instance("maafgo", inst_of.get("maafgo"), "MaaFgo")

            # 兜底：所有程序都完事了，还有实例在跑就一起关掉
            # （比如某个程序没勾选，它那个实例就没人负责）
            if not emu_closed and need_maa and all(self.done.get(k) for k in need_maa):
                if any(instance_running(cfg, i) for i in started_insts):
                    self.emit("status", "任务完成，正在关闭剩余模拟器…")
                    self.shutdown_emulators_for_monitor()
                for inst in cfg.get("instances", []):
                    self.step("vm%d" % int(inst["index"]), "idle", "已关闭")
                emu_closed = True
                self.emit("status", "就绪（模拟器已关闭）")

            # ③ ok-ww
            if not game_closed and not self.done.get("okww") and need_game:
                ts = scan_logs(okww_log_files(cfg), OKWW_DONE_MARK, self.baseline["okww"])
                if ts:
                    self.done["okww"] = True
                    self.log("✓ ok-ww 每日任务已完成（%s）" % time.strftime(
                        "%H:%M:%S", time.localtime(ts)))
                    self.step("okww", "ok", "任务已完成")

            if not game_closed and need_game and self.done.get("okww"):
                self.emit("status", "ok-ww 完成，正在关闭鸣潮…")
                close_game_window(cfg, self.log)
                game_closed = True
                self.step("okww", "ok", "已完成 · 游戏已关")
                self.emit("status", "就绪")

            if emu_closed and game_closed:
                self.log("—— 后台监视结束 ——")
                return

        self.log("后台监视已超时退出（%.0f 小时），没等到全部完成标记" % max_hours)

    def shutdown_emulators_for_monitor(self):
        """关实例但保留所有程序进程——MAA / MaaFgo 留着看日志"""
        ok = shutdown_emulators(self.cfg, self.log)
        if ok:
            self.log("注意：MAA / MaaFgo / MaaEnd / ok-ww 都没动，日志照旧可查")

    # -- 关闭全部 -----------------------------------------------------------
    def shutdown_all(self):
        try:
            self.stop_flag = False
            self.emit("busy", True)
            self.emit("status", "正在关闭…")
            mgr = mumu_manager(self.cfg.get("mumu_root", ""))
            if os.path.isfile(mgr):
                self.log("关闭所有 MuMu 实例…")
                rc, _ = run_hidden([mgr, "control", "-v", "all", "shutdown"], 120)
                if rc != 0:
                    self.log("MuMuManager 关闭失败，直接结束设备进程")
                    run_hidden(["taskkill", "/F", "/IM", "MuMuNxDevice.exe"], 30)
            if self.cfg.get("close_tools_with_emulator"):
                for key in ("maa", "maafgo", "maaend"):
                    exe = self.cfg.get(key, {}).get("path", "")
                    if exe and proc_running(os.path.basename(exe)):
                        run_hidden(["taskkill", "/IM", os.path.basename(exe), "/F"], 30)
                        self.log("已结束 %s" % os.path.basename(exe))
            for inst in self.cfg.get("instances", []):
                self.step("vm%d" % int(inst["index"]), "idle", "未启动")
            self.step("maa", "idle", "")
            self.step("maafgo", "idle", "")
            self.log("已关闭")
            self.emit("status", "已关闭")
        except Exception:
            self.log("✗ 关闭异常：\n" + traceback.format_exc())
        finally:
            self.emit("busy", False)


# ----------------------------------------------------------------------------
# GDI 小工具
# ----------------------------------------------------------------------------
def rgb(hexcolor):
    h = hexcolor.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b << 16) | (g << 8) | r


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", wt.HDC),
        ("fErase", wt.BOOL),
        ("rcPaint", wt.RECT),
        ("fRestore", wt.BOOL),
        ("fIncUpdate", wt.BOOL),
        ("rgbReserved", ctypes.c_byte * 32),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wt.WORD),
        ("biBitCount", wt.WORD),
        ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wt.DWORD),
        ("biClrImportant", wt.DWORD),
    ]


RAINBOW = {
    "bg": "#F1F3FB",
    "card": "#FFFFFF",
    "border": "#E1E5F0",
    "line": "#F0F2F6",
    "text": "#20263D",
    "text2": "#59647D",
    "muted": "#75819A",
    "accent": "#6264E8",
    "accent_d": "#4C4ECC",
    "accent_l": "#EDEEFF",
    "ok": "#17B26A",
    "err": "#F04438",
    "run": "#F79009",
    "idle": "#C6CCD6",
    "ghost_bg": "#FFFFFF",
    "ghost_bg_h": "#F2F4F8",
    "err_bg": "#FFF4F3",
    "err_bg_h": "#FFE6E4",
    "err_border": "#F6C9C4",
    "disabled": "#B7BEC9",
    "logbg": "#FAFBFF",
    "iconbg": "#F1F2FC",     # 行图标背后的圆角底板
    "panel": "#F7F8FA",      # 关于页里的信息块底色
    "panel_line": "#EDF0F5",  # 信息块的描边
}
C = {k: rgb(v) for k, v in RAINBOW.items()}

# ----------------------------------------------------------------------------
# Win32 声明
# ----------------------------------------------------------------------------
WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM
)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", ctypes.c_uint),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE),
        ("hIcon", wt.HICON),
        ("hCursor", wt.HANDLE),
        ("hbrBackground", wt.HBRUSH),
        ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
    ]


user32.DefWindowProcW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.CreateWindowExW.argtypes = [
    wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID,
]
user32.CreateWindowExW.restype = wt.HWND
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = wt.WORD
user32.GetDC.argtypes = [wt.HWND]
user32.GetDC.restype = wt.HDC
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.LoadCursorW.argtypes = [wt.HINSTANCE, wt.LPCWSTR]
user32.LoadCursorW.restype = wt.HANDLE
user32.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int,
                              ctypes.c_int, wt.UINT]
user32.LoadImageW.restype = wt.HANDLE
user32.DrawIconEx.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, wt.HANDLE,
                              ctypes.c_int, ctypes.c_int, wt.UINT, wt.HBRUSH, wt.UINT]
user32.DrawIconEx.restype = wt.BOOL
user32.DestroyIcon.argtypes = [wt.HANDLE]
user32.DestroyIcon.restype = wt.BOOL
user32.SetCursor.argtypes = [wt.HANDLE]
user32.SetCursor.restype = wt.HANDLE
user32.AdjustWindowRectEx.argtypes = [ctypes.POINTER(wt.RECT), wt.DWORD, wt.BOOL, wt.DWORD]
user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
user32.ShowWindow.restype = wt.BOOL
user32.UpdateWindow.argtypes = [wt.HWND]
user32.UpdateWindow.restype = wt.BOOL
user32.DestroyWindow.argtypes = [wt.HWND]
user32.DestroyWindow.restype = wt.BOOL
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.PostMessageW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
user32.PostMessageW.restype = wt.BOOL
user32.SendMessageW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.GetMessageW.restype = ctypes.c_int
user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.restype = ctypes.c_ssize_t
user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
user32.FindWindowW.restype = wt.HWND
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.SetForegroundWindow.restype = wt.BOOL
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.IsWindowVisible.restype = wt.BOOL
user32.IsWindow.argtypes = [wt.HWND]
user32.IsWindow.restype = wt.BOOL
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowTextLengthW.argtypes = [wt.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindow.argtypes = [wt.HWND, wt.UINT]
user32.GetWindow.restype = wt.HWND
try:
    user32.EnumWindows.argtypes = [
        ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM), wt.LPARAM]
    user32.EnumWindows.restype = wt.BOOL
except Exception:
    pass
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wt.UINT]
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.InvalidateRect.argtypes = [wt.HWND, wt.LPVOID, wt.BOOL]
user32.InvalidateRect.restype = wt.BOOL
user32.SetTimer.argtypes = [wt.HWND, wt.UINT_PTR, wt.UINT, wt.LPVOID]
user32.SetTimer.restype = wt.UINT_PTR
user32.KillTimer.argtypes = [wt.HWND, wt.UINT_PTR]
user32.KillTimer.restype = wt.BOOL
try:                                    # Win10+ 才有 GetDpiForSystem
    user32.GetDpiForSystem.argtypes = []
    user32.GetDpiForSystem.restype = wt.UINT
except AttributeError:
    pass
gdi32.GetDeviceCaps.argtypes = [wt.HDC, ctypes.c_int]
gdi32.GetDeviceCaps.restype = ctypes.c_int
user32.BeginPaint.argtypes = [wt.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.BeginPaint.restype = wt.HDC
user32.EndPaint.argtypes = [wt.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.EndPaint.restype = wt.BOOL
user32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.GetClientRect.restype = wt.BOOL
user32.FillRect.argtypes = [wt.HDC, ctypes.POINTER(wt.RECT), wt.HBRUSH]
user32.FillRect.restype = ctypes.c_int
user32.DrawTextW.argtypes = [wt.HDC, wt.LPCWSTR, ctypes.c_int,
                             ctypes.POINTER(wt.RECT), ctypes.c_uint]
user32.DrawTextW.restype = ctypes.c_int

gdi32.CreateSolidBrush.argtypes = [wt.DWORD]
gdi32.CreateSolidBrush.restype = wt.HBRUSH
gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wt.DWORD]
gdi32.CreatePen.restype = wt.HPEN
gdi32.GetStockObject.argtypes = [ctypes.c_int]
gdi32.GetStockObject.restype = wt.HGDIOBJ
gdi32.CreateFontW.argtypes = [ctypes.c_int] * 5 + [wt.DWORD] * 8 + [wt.LPCWSTR]
gdi32.CreateFontW.restype = wt.HFONT
gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
gdi32.DeleteObject.restype = wt.BOOL
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.SelectObject.restype = wt.HGDIOBJ

# 滚动列表要靠裁剪把超出卡片的那几行切掉
gdi32.SaveDC.argtypes = [wt.HDC]
gdi32.SaveDC.restype = ctypes.c_int
gdi32.RestoreDC.argtypes = [wt.HDC, ctypes.c_int]
gdi32.RestoreDC.restype = wt.BOOL
gdi32.IntersectClipRect.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int]
gdi32.IntersectClipRect.restype = ctypes.c_int
gdi32.SetTextColor.argtypes = [wt.HDC, wt.DWORD]
gdi32.SetTextColor.restype = wt.DWORD
gdi32.SetBkMode.argtypes = [wt.HDC, ctypes.c_int]
gdi32.SetBkMode.restype = ctypes.c_int


class XFORM(ctypes.Structure):
    """世界变换矩阵（GDI）。文字超采样靠它把图层放大 2 倍渲染再缩回去。"""
    _fields_ = [("eM11", ctypes.c_float), ("eM12", ctypes.c_float),
                ("eM21", ctypes.c_float), ("eM22", ctypes.c_float),
                ("eDx", ctypes.c_float), ("eDy", ctypes.c_float)]


GM_ADVANCED = 2
# 文字层超采样倍数：1 = 不超采样。GDI 的灰度抗锯齿只有 16 级，
# 26px 以上的中文标题能明显看出台阶；放大 2 倍渲染再用 BOX 缩回去能有 100+ 级。
TEXT_SS = 2
gdi32.SetGraphicsMode.argtypes = [wt.HDC, ctypes.c_int]
gdi32.SetGraphicsMode.restype = ctypes.c_int
gdi32.SetWorldTransform.argtypes = [wt.HDC, ctypes.POINTER(XFORM)]
gdi32.SetWorldTransform.restype = wt.BOOL
gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.DeleteDC.argtypes = [wt.HDC]
gdi32.DeleteDC.restype = wt.BOOL
gdi32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wt.HBITMAP
gdi32.BitBlt.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         wt.HDC, ctypes.c_int, ctypes.c_int, wt.DWORD]
gdi32.BitBlt.restype = wt.BOOL
gdi32.SetStretchBltMode.argtypes = [wt.HDC, ctypes.c_int]
gdi32.SetStretchBltMode.restype = ctypes.c_int
gdi32.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, wt.LPVOID,
                            ctypes.POINTER(BITMAPINFOHEADER), wt.UINT]
gdi32.GetDIBits.restype = ctypes.c_int
gdi32.RoundRect.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                            ctypes.c_int, ctypes.c_int, ctypes.c_int]
gdi32.RoundRect.restype = wt.BOOL
gdi32.Ellipse.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
gdi32.Ellipse.restype = wt.BOOL
gdi32.MoveToEx.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, wt.LPVOID]
gdi32.MoveToEx.restype = wt.BOOL
gdi32.LineTo.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
gdi32.LineTo.restype = wt.BOOL
gdi32.SaveDC.argtypes = [wt.HDC]
gdi32.SaveDC.restype = ctypes.c_int
gdi32.RestoreDC.argtypes = [wt.HDC, ctypes.c_int]
gdi32.RestoreDC.restype = wt.BOOL
gdi32.IntersectClipRect.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int]
gdi32.IntersectClipRect.restype = ctypes.c_int

# 局部刷新（hover）时把落笔范围限制在变化的那几块：多块矩形合成一个裁剪区
gdi32.CreateRectRgn.argtypes = [ctypes.c_int] * 4
gdi32.CreateRectRgn.restype = wt.HRGN
gdi32.CombineRgn.argtypes = [wt.HRGN, wt.HRGN, wt.HRGN, ctypes.c_int]
gdi32.CombineRgn.restype = ctypes.c_int
gdi32.SelectClipRgn.argtypes = [wt.HDC, wt.HRGN]
gdi32.SelectClipRgn.restype = ctypes.c_int

# ---------------------------------------------------------------------------
# GDI+：圆角矩形 / 圆 / 折线的抗锯齿
# ---------------------------------------------------------------------------
# GDI 的 RoundRect 和 Ellipse 不做抗锯齿：100% 缩放下还能忍，175% 下按钮、
# 勾选框、侧边栏高亮的圆角全是硬台阶（"控件有锯齿"）。GDI+ 用
# SmoothingModeAntiAlias 画同一条路径，边缘按覆盖率混合，才像现代 UI。
#
# 成本（1680×1365 的 DDB 实测）：
#   小控件 180×40 填充+描边        0.06 ms / 个，38 个 2.5 ms  → 小块一律 GDI+
#   整张卡片 1600×1200 纯填充      16 ms                      → 大块 GDI 铺底 + GDI+ 描边
#   大块带 GDI+ 裁剪区时填充       0.17 ms                    → 补丁帧里大块也走 GDI+
GP_AA_FILL_MAX = 120000        # 超过这么多像素的圆角块，填充改用 GDI（阈值见上）
GP_SMOOTH_AA = 4               # SmoothingModeAntiAlias
GP_PIXEL_HALF = 4              # PixelOffsetModeHalf
# GpUnit：UnitPixel 是 **2**，不是 1（1 是 UnitDisplay，画笔不接受 ——
# GdipCreatePen1 会返回 2=InvalidParameter，而且画不出来，边框整个消失。踩过。）
GP_UNIT_PIXEL = 2


class _GpStartupInput(ctypes.Structure):
    _fields_ = [("GdiplusVersion", ctypes.c_uint32),
                ("DebugEventCallback", ctypes.c_void_p),
                ("SuppressBackgroundThread", ctypes.c_int),
                ("SuppressExternalCodecs", ctypes.c_int)]


_gp_lib = None


def gp_lib():
    """懒加载 gdiplus.dll 并声明原型；不可用返回 None（调用方退回纯 GDI）。"""
    global _gp_lib
    if _gp_lib is not None:
        return _gp_lib or None
    try:
        lib = ctypes.WinDLL("gdiplus")
        token = ctypes.c_void_p()
        inp = _GpStartupInput(1, None, 0, 0)
        if lib.GdiplusStartup(ctypes.byref(token), ctypes.byref(inp), None) != 0:
            raise OSError("GdiplusStartup 失败")
    except Exception:
        log_line("GDI+ 不可用，圆角退回 GDI 绘制（会有锯齿）")
        _gp_lib = False
        return None
    P = ctypes.c_void_p
    proto = {
        "GdipCreateFromHDC": [P, ctypes.POINTER(P)],
        "GdipDeleteGraphics": [P],
        "GdipSetSmoothingMode": [P, ctypes.c_int],
        "GdipSetPixelOffsetMode": [P, ctypes.c_int],
        "GdipCreateRegion": [ctypes.POINTER(P)],
        "GdipCombineRegionRectI": [P, ctypes.POINTER(wt.RECT), ctypes.c_int],
        "GdipSetClipRegion": [P, P, ctypes.c_int],
        "GdipDeleteRegion": [P],
        "GdipCreatePath": [ctypes.c_int, ctypes.POINTER(P)],
        "GdipAddPathArc": [P] + [ctypes.c_float] * 6,
        "GdipClosePathFigure": [P],
        "GdipDeletePath": [P],
        "GdipCreateSolidFill": [ctypes.c_uint32, ctypes.POINTER(P)],
        "GdipDeleteBrush": [P],
        "GdipFillPath": [P, P, P],
        "GdipFillEllipse": [P, P] + [ctypes.c_float] * 4,
        "GdipCreatePen1": [ctypes.c_uint32, ctypes.c_float, ctypes.c_int, ctypes.POINTER(P)],
        "GdipDeletePen": [P],
        "GdipDrawPath": [P, P, P],
        "GdipDrawLinesI": [P, P, ctypes.POINTER(ctypes.c_int), ctypes.c_int],
        "GdipSetPenStartCap": [P, ctypes.c_int],
        "GdipSetPenEndCap": [P, ctypes.c_int],
        "GdipSetPenLineJoin": [P, ctypes.c_int],
    }
    for fname, args in proto.items():
        fn = getattr(lib, fname)
        fn.argtypes = args
        fn.restype = ctypes.c_int
    _gp_lib = lib
    return lib


def gp_argb(colorref, alpha=255):
    """COLORREF（0x00BBGGRR）→ GDI+ 的 ARGB（0xAARRGGBB）"""
    v = int(colorref)
    return (((alpha & 0xFF) << 24) | ((v & 0xFF) << 16)
            | (((v >> 8) & 0xFF) << 8) | ((v >> 16) & 0xFF))


def gp_round_path(x, y, w, h, r):
    """圆角矩形路径。四条 90° 圆弧拼起来，和 GDI RoundRect 的几何一致。"""
    lib = gp_lib()
    path = ctypes.c_void_p()
    lib.GdipCreatePath(0, ctypes.byref(path))          # FillModeAlternate
    d = float(r) * 2.0
    for sx, sy, start in ((x, y, 180.0),
                          (x + w - d, y, 270.0),
                          (x + w - d, y + h - d, 0.0),
                          (x, y + h - d, 90.0)):
        lib.GdipAddPathArc(path, float(sx), float(sy), d, d, start, 90.0)
    lib.GdipClosePathFigure(path)
    return path


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


# AlphaBlend 在 msimg32 里，不在 gdi32（记错过一次，报 "function not found"）
msimg32 = ctypes.WinDLL("msimg32", use_last_error=True)
msimg32.AlphaBlend.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                               wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                               BLENDFUNCTION]
msimg32.AlphaBlend.restype = wt.BOOL

kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
kernel32.GetModuleHandleW.restype = wt.HINSTANCE
user32.MessageBoxW.argtypes = [wt.HWND, wt.LPCWSTR, wt.LPCWSTR, wt.UINT]
user32.MessageBoxW.restype = ctypes.c_int
kernel32.CreateMutexW.argtypes = [wt.LPVOID, wt.BOOL, wt.LPCWSTR]
kernel32.CreateMutexW.restype = wt.HANDLE
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.CloseHandle.restype = wt.BOOL
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE          # 必须声明，否则句柄被截断
kernel32.GetProcessTimes.argtypes = [wt.HANDLE, ctypes.POINTER(wt.FILETIME),
                                     ctypes.POINTER(wt.FILETIME),
                                     ctypes.POINTER(wt.FILETIME),
                                     ctypes.POINTER(wt.FILETIME)]
kernel32.GetProcessTimes.restype = wt.BOOL

shell32.ShellExecuteW.argtypes = [wt.HWND, wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR,
                                  wt.LPCWSTR, ctypes.c_int]
shell32.ShellExecuteW.restype = wt.HINSTANCE
shell32.ExtractIconExW.argtypes = [wt.LPCWSTR, ctypes.c_int, ctypes.POINTER(wt.HICON),
                                   ctypes.POINTER(wt.HICON), wt.UINT]
shell32.ExtractIconExW.restype = wt.UINT


def load_cursor(cid):
    """MAKEINTRESOURCE"""
    return user32.LoadCursorW(None, ctypes.cast(cid, wt.LPCWSTR))


WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_PAINT = 0x000F
WM_ERASEBKGND = 0x0014
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_MOUSEWHEEL = 0x020A
WM_SETCURSOR = 0x0020
WM_TIMER = 0x0113
WM_KEYDOWN = 0x0100
WM_SETICON = 0x0080
ICON_SMALL = 0
ICON_BIG = 1

DT_LEFT, DT_CENTER, DT_RIGHT = 0x0000, 0x0001, 0x0002
DT_VCENTER, DT_SINGLELINE = 0x0004, 0x0020
DT_WORDBREAK, DT_END_ELLIPSIS, DT_NOPREFIX = 0x0010, 0x00008000, 0x00000800

STEP_KEYS = ["maaend", "vm0", "vm1", "maa", "maafgo", "okww"]


class App(VisualShell):
    def __init__(self):
        self.cfg = load_config()
        _TMARK["cfg"] = _boot_time.time()
        self.hwnd = None
        self._animation_scene = None
        self._blend_surface = None
        self._visual_generation = 0
        self._animation_generation = -1
        self._animation_clock = AnimationClock()
        self._compositor = Compositor()
        self._last_scene = None
        self._transition = None
        self._modal_transition = None
        self.dpi = 96.0
        self.motion_allowed, self.transparency_allowed = system_preferences()
        self.frame_effect = "solid"
        self._hover_from = None
        self._hover_at = 0.0
        self.hover = None
        # hover 局部刷新用：本帧只需重算的矩形 / 该矩形对应的整帧序号
        self._hover_patch = None
        self._hover_patch_serial = -1
        self._paint_serial = 0
        self._patch_clip = None
        # 屏幕上"还留着底色"的行：动画淡出是渐进的，鼠标已经移走的那一行
        # 可能还停在 0.8 的浓度上，必须继续重画，直到它彻底淡到 0。
        self._hover_tinted = set()
        self._hover_keys = set()
        # 排队 hover 补丁那一刻的画面指纹（提交前核对，见 _paint_sig）
        self._hover_sig = None
        # 本帧的动画时钟（paint 开始时冻结，见 hover_amount）
        self._frame_t = None
        # 当前帧的 GDI+ Graphics（懒建，paint 结束前必须释放）
        self._gp_gfx = None
        self._gp_dc = None
        # 这一帧画了哪些文字（用于和上一帧比对，只重算变化的块）
        self._text_ops = []
        self._prev_text_ops = None
        self.pressed = None
        self.busy = False
        self.steps = {k: ("idle", "") for k in STEP_KEYS}
        for _i in _cfg_indexes(self.cfg):        # 实例数量是动态的，补齐状态槽
            self.steps.setdefault("vm%d" % _i, ("idle", ""))
        self.ports = {}
        self.logs = []          # list of (text, color_key)
        self.status = "就绪"
        self.q = []             # worker -> ui 消息队列
        self.qlock = threading.Lock()
        self.runner = Runner(self.cfg, self.emit)
        self._fonts = {}
        self._fonts2 = {}          # HFONT -> 2 倍字号（超采样文字层用）
        self.rects = {}
        self.no_auto = False        # 调试/截图时关掉自动启动
        self._auto_pending = False
        self._auto_at = 0.0
        self.chk = {}
        for inst in self.cfg.get("instances", []):
            self.chk[int(inst["index"])] = bool(inst.get("enabled", True))
        # 自定义项的勾选（键是 custom_items[].id）
        self.chk_custom = {}
        for it in self.cfg.get("custom_items", []) or []:
            self.chk_custom[it.get("id")] = bool(it.get("enabled", True))
        self.maa_on = bool(self.cfg.get("maa", {}).get("enabled", True))
        self.maafgo_on = bool(self.cfg.get("maafgo", {}).get("enabled", True))
        self.okww_on = bool(self.cfg.get("okww", {}).get("enabled", True))
        self.maaend_on = bool(self.cfg.get("maaend", {}).get("enabled", False))
        self.page = "main"          # main | settings | custom | night | about
        self.sub_page = False       # 是否处于子页面（子页面只有「返回」可点）
        # 页面栈：记录从哪儿来，返回时按栈回退
        #   main → settings → custom/night
        self.page_stack = []
        # 关于页的排版缓存（layout 里算，paint / hit 共用）
        self._about = None
        # 「选 exe」卡片：{"items": [...], "sel": 选中下标, "title": 标题, "on_ok": 回调}
        self.exepick = None
        # 开机的「只跑手游日常吗」询问：{"until": 到点时间戳, "left": 剩余秒}
        self.prompt = None
        # 本次只跑这些 key（点「是」时设；只影响这一轮，不改勾选、不写 config.json）
        self.run_only = None
        # 自动更新状态机：
        #   idle / checking / uptodate / available / downloading / ready / error
        # 只影响界面提示，不阻塞任何启动流程。
        self.upd = {"state": "idle", "tag": "", "url": "", "page": "",
                    "size": 0, "asset": "", "date": "", "pct": 0,
                    "kind": "zip", "err": "", "path": ""}
        # 子页面内容超长时的滚动位置（逻辑像素，0 = 顶部）
        self.scroll = 0
        self._scroll_max = 0
        self._scroll_page = None
        self._upd_due = time.time() + 3.0      # 开机 3 秒后才开始查，别和启动抢
        self._upd_tried = False
        # 路径还没指过（或中途被清空）：直接进设置页，绝不自动开跑。
        # 默认配置里没有任何真实路径，自动跑只会满屏「找不到 xxx.exe」。
        self.first_run = not config_ready(self.cfg)
        # 换新版 exe 后第一跑：记下上一版，日志里提示一句"配置沿用了"。
        # 这个版本号**不写 config.json**（那是用户的东西），
        # 记在 launcher.state.json 里，用户改不到也不影响配置。
        self.prev_version = str(STATE.get("last_run_version") or "")
        if self.prev_version != APP_VERSION:
            STATE["last_run_version"] = APP_VERSION
            save_state()
        if self.first_run:
            self.page_stack.append("main")
            self.page = "settings"
            self.no_auto = True
            self.status = "还没配置：请在「① 选择各实例的路径」里逐行点「选择」"

    def refresh_effects(self):
        self.finish_transition()
        self.finish_modal_transition()
        self.motion_allowed, self.transparency_allowed = system_preferences()
        self.frame_effect = apply_native_frame(
            self.hwnd, self.cfg.get("ui_mica", True) and self.transparency_allowed and self._compositor.available,
            material=self.cfg.get("ui_material", "mica"))
        if not self.motion_enabled():
            user32.KillTimer(self.hwnd, 2)
            self._hover_at = 0.0
            self.finish_transition()
            self.finish_modal_transition()

    def motion_enabled(self):
        return self.motion_allowed and self.cfg.get("ui_motion", True)

    def text_diff_rects(self):
        """比较这一帧和上一帧的文字清单，返回变了的那些矩形。

        跑任务时状态栏的字每次刷新都会变，但整屏其余部分一模一样；
        知道只有那几行变了，就能只重算那几块。
        """
        cur = self._text_ops
        prev = self._prev_text_ops
        self._prev_text_ops = list(cur)
        if prev is None:
            return None
        if len(prev) != len(cur):
            return None                  # 行数都变了，整页重排，别抠了
        rects = []
        for old, new in zip(prev, cur):
            if old != new:
                rects.append(new[1])
                rects.append(old[1])
        return rects

    def _decide_patch(self, mem, w, h):
        """整帧画完之后再决定走不走补丁，返回 (patch_rects, text_rects)。

        patch_rects 为 [] 表示画面一个像素都没变 → 连 present 都不用做；
        返回 (None, None) 表示拿不准（换页/弹窗/变化太大）→ 老实用整帧。
        """
        if self.frame_effect not in ('mica', 'tabbed', 'acrylic'):
            return None, None
        if getattr(self, '_force_full_paint', False):     # 自检用：强制整帧
            return None, None
        if self._transition or self._modal_transition or self.prompt or self.exepick:
            return None, None
        # 注意：这里不检查 motion_enabled。关掉动画只是不做过渡，场景照样只变了
        # 一小块；不放行就会退回整帧重算（150ms），鼠标一扫就卡成幻灯片。
        prev = self._last_scene
        prepared = self._compositor.prepared
        if (not prev or (prev.width, prev.height) != (w, h)
                or not prepared or (prepared.width, prepared.height) != (w, h)):
            return None, None
        changed = self._compositor.scene_diff_rects(mem, prev, w, h)
        text_rects = self.text_diff_rects()
        if text_rects is None:
            return None, None
        rects = list(changed) + list(text_rects)
        if not rects:
            return [], []
        area = sum(max(0, r[2] - r[0]) * max(0, r[3] - r[1]) for r in rects)
        if area > w * h * 0.3:            # 变了一半屏还抠什么，整帧更快
            return None, None
        return rects, text_rects

    def _mark_hover_patch(self):
        """记下这一帧只需重算的矩形：hover 动画只改鼠标下那颗控件。

        材质模式整帧合成要 150ms 左右，而 hover 只动了控件底色这一小块，
        按矩形打补丁能到 ~30ms/帧。算不出矩形（命中在奇怪位置）就置 None，
        退回整帧重算 —— 宁可慢一点，也不能画错。

        两个坑（都是真机复现出来的，别改回去）：

        1. **必须累计，不能覆盖**：鼠标扫得快时，一个消息循环里会连着来好几个
           WM_MOUSEMOVE，每次覆盖掉的话，中间扫过的那几行就再没机会被重画。
        2. **必须带上"正在淡出"的行**：`hover_amount()` 给 `_hover_from` 的是
           `1-t`，鼠标刚落到新行的那一瞬间旧行是**满色**（t≈0 → 1-t≈1）。
           如果紧接着又移到第三行，第二行就成了"既不是 hover 也不是 from"的行，
           永远停在满色上 —— 用户看到的就是"扫过谁谁就上底色"。
           所以这里记一本 `_hover_tinted` 账：上一帧画过、浓度还没归零的行，
           下一帧继续重画，直到 `hover_amount()` 真的回到 0。
        """
        if (self.prompt or self.exepick
                or self.frame_effect not in ('mica', 'tabbed', 'acrylic')):
            self._hover_patch = None
            self._hover_keys = set()
            return
        keys = set(self._hover_tinted)
        for k in (self.hover, self._hover_from):
            if k:
                keys.add(k)
        rects = []
        for k in keys:
            rects.extend(self.hover_rects(k))
        if not rects:
            self._hover_patch = None
            self._hover_keys = set()
            return
        pad = self.S(8)          # 圆角/描边/阴影外扩一点，别留毛边
        fresh = [(r[0] - pad, r[1] - pad, r[2] + pad, r[3] + pad) for r in rects]
        # 上一帧已经提交过的话，旧矩形是陈的，别带过来
        if getattr(self, '_hover_patch_serial', -1) != self._paint_serial:
            self._hover_patch = None
        pending = merge_rects((self._hover_patch or []) + fresh)
        area = sum(max(0, r[2] - r[0]) * max(0, r[3] - r[1]) for r in pending)
        w = getattr(self, '_paint_w', 0) or 1
        h = getattr(self, '_paint_h', 0) or 1
        if not pending or area > w * h * 0.45:
            # 扫过太多行，补丁已经不比整帧省了；整帧重画一次，顺便把尾巴擦干净
            self._hover_patch = None
            self._hover_keys = set()
            return
        self._hover_patch = pending
        self._hover_keys = keys
        self._hover_patch_serial = self._paint_serial
        # 记下"排队这一刻画面里除 hover 之外的东西"，提交前再核对一遍
        self._hover_sig = self._paint_sig()

    def _paint_sig(self):
        """画面里除 hover 之外，所有会影响像素的状态。

        hover 补丁的前提是「只有鼠标下那颗控件变了」。但鼠标移动、滚轮、状态刷新
        常常落在同一个消息循环里：先排了 hover 补丁，紧接着 scroll 变了，这一帧
        就只重画了鼠标那一块，其余部分停在旧的滚动位置 —— 用户看到的就是
        「滑动设置页时画面错乱」（v2.17.6）。补丁排队时记一份指纹、提交前再算一遍，
        对不上就老实走整帧。`cfg` 用 repr 一起算，省得漏掉某个字段。
        """
        steps = tuple(sorted((self.steps or {}).items()))
        ep = self.exepick
        return (self.page, self.scroll, self._scroll_max,
                getattr(self, '_paint_w', 0), getattr(self, '_paint_h', 0),
                self.status, self.upd_hint(), bool(self.busy), self.pressed,
                len(self.logs), steps, bool(self.prompt),
                (len(ep["items"]), ep["sel"]) if ep else None,
                repr(self.cfg))

    def _settle_hover_tint(self):
        """一帧提交之后结账：哪些行的底色浓度还没归零，下一帧还得继续画。

        浓度用 `hover_amount()` 判断；返回 0 的行说明这一帧已经把它画干净了，
        从账上划掉。整帧重画时同理 —— 屏幕已经全对，账自然清零。
        """
        keys = set(getattr(self, '_hover_keys', ()))
        for k in (self.hover, self._hover_from):
            if k:
                keys.add(k)
        self._hover_tinted = {k for k in keys if self.hover_amount(k) > 0.004}

    def hover_amount(self, key):
        # 一帧之内所有行必须用**同一个时间点**：一帧要画 70~190ms，而 hover 动画
        # 只有 0.18s。如果每行都取实时时钟，同一帧里先画的行和后画的行会差好几级
        # 浓度；更糟的是 `_settle_hover_tint()` 在帧末结算时动画早已跑完，于是把
        # 明明还带着底色的行当成"已经归零"划掉，下一帧不再重画它 —— 屏幕上就是
        # 擦不掉的残留（v2.17.6）。所以 paint 开始时把时钟冻住，帧末再解冻。
        now = getattr(self, '_frame_t', None) or time.monotonic()
        if not self.motion_enabled() or not self._hover_at:
            return float(self.hover == key)
        t = min(1.0, (now - self._hover_at) / 0.18)
        t = 1.0 - (1.0 - t) ** 3
        if key == self.hover:
            return t
        return 1.0 - t if key == self._hover_from else 0.0

    def row_highlight(self, hdc, key, rect):
        a = self.hover_amount(key)
        if a > 0:
            self.fill_round(hdc, rect, 9, mix_color(C["card"], C["accent_l"], a))

    # ---------- 消息 ----------
    def ui_log(self, msg):
        """界面日志 + 文件日志（按钮直接触发的动作用这个）"""
        log_line(msg)
        self.emit("log", msg)

    def emit(self, kind, *args):
        with self.qlock:
            self.q.append((kind, args))

    def drain(self):
        with self.qlock:
            items = self.q[:]
            del self.q[:]
        if not items:
            return
        for kind, args in items:
            if kind == "upd":
                self._upd_state(*args)
                continue
            if kind == "log":
                text = args[0]
                color = "text2"
                if text.startswith("✗"):
                    color = "err"
                elif ("已就绪" in text) or ("已启动" in text) or ("完成" in text):
                    color = "ok"
                self.logs.append((text, color))
                if len(self.logs) > 400:
                    del self.logs[:100]
            elif kind == "step":
                key, state, detail = args
                self.steps[key] = (state, detail)
            elif kind == "busy":
                self.busy = bool(args[0])
            elif kind == "status":
                self.status = args[0]
            elif kind == "port":
                self.ports[int(args[0])] = int(args[1])
            elif kind == "sync":
                # 后台按 MuMu 实际情况重排过实例列表，重建一下勾选缓存
                self.reload_instances()
        user32.InvalidateRect(self.hwnd, None, False)

    def reload_instances(self):
        """实例列表被增删后，按 cfg 里最新的 enabled 重建勾选缓存"""
        self.chk = {int(inst["index"]): bool(inst.get("enabled", True))
                    for inst in self.cfg.get("instances", [])}
        for i in self.chk:
            self.steps.setdefault("vm%d" % i, ("idle", ""))

    # ---------- GDI 封装 ----------
    def S(self, v):
        return int(round(v * self.dpi / 96.0))

    def font(self, px, bold=False, face="Microsoft YaHei UI"):
        key = (px, bold, face)
        f = self._fonts.get(key)
        if f:
            return f
        h = -max(8, self.S(px))
        weight = 700 if bold else 400
        f = gdi32.CreateFontW(h, 0, 0, 0, weight, False, False, False,
                              134, 0, 0, 4, 0, face)
        if not f:
            f = gdi32.CreateFontW(h, 0, 0, 0, weight, False, False, False,
                                  134, 0, 0, 4, 0, "Microsoft YaHei")
        self._fonts[key] = f
        if TEXT_SS > 1:
            twin = gdi32.CreateFontW(h * TEXT_SS, 0, 0, 0, weight, False, False,
                                     False, 134, 0, 0, 4, 0, face)
            if not twin:
                twin = gdi32.CreateFontW(h * TEXT_SS, 0, 0, 0, weight, False, False,
                                         False, 134, 0, 0, 4, 0, "Microsoft YaHei")
            if twin:
                self._fonts2[f] = twin
        return f

    def text(self, hdc, s, rect, color, fnt,
             flags=DT_LEFT | DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX):
        layers = getattr(self, '_glass_text_layers', None)
        if layers and hdc == getattr(self, '_paint_dc', None):
            clip = wt.RECT()
            gdi32.GetClipBox.argtypes = [wt.HDC, ctypes.POINTER(wt.RECT)]
            gdi32.GetClipBox(hdc, ctypes.byref(clip))
            # 图层是 TEXT_SS 倍尺寸：字号、矩形、裁剪框统统乘 ss 直接画成大图，
            # 合成时再 Box 降采样 —— 等于给文字做超采样。
            # （不要用 SetWorldTransform 偷懒：DrawText 的排版/省略号/裁剪在变换下
            #   行为不一致，会整段文字消失，踩过。）
            ss = getattr(self, '_text_ss', 1)
            big = self._fonts2.get(fnt, fnt) if ss != 1 else fnt
            box = (int(rect[0]) * ss, int(rect[1]) * ss,
                   int(rect[2]) * ss, int(rect[3]) * ss)
            cl, ct = clip.left * ss, clip.top * ss
            cr, cb = clip.right * ss, clip.bottom * ss
            for layer, ink in zip(layers, (0xffffff, color)):
                saved = gdi32.SaveDC(layer.dc)
                gdi32.IntersectClipRect(layer.dc, cl, ct, cr, cb)
                self._apply_patch_clip(layer.dc, ss)
                gdi32.SelectObject(layer.dc, big)
                gdi32.SetTextColor(layer.dc, ink)
                gdi32.SetBkMode(layer.dc, 1)
                r = wt.RECT(*box)
                user32.DrawTextW(layer.dc, s, -1, ctypes.byref(r), flags)
                gdi32.RestoreDC(layer.dc, saved)
            # 记一笔：下一帧比较这行字有没有变，没变就不重算它那块
            self._text_ops.append((s, tuple(int(v) for v in rect), color, fnt))
            return
        gdi32.SelectObject(hdc, fnt)
        gdi32.SetTextColor(hdc, color)
        gdi32.SetBkMode(hdc, 1)
        r = wt.RECT(*rect)
        user32.DrawTextW(hdc, s, -1, ctypes.byref(r), flags)

    def text_layer_cover(self, rect=None):
        """把已经画进文字层的字擦掉。

        材质模式下文字单独存在两个覆盖层里，最后统一合成到场景上 —— 也就是说
        「后画的实色面板」盖不住「先画的字」。模态弹窗的遮罩、卡片就是这种面板，
        不擦就会变成：主界面的字浮在弹窗上面（v2.16.1 的毛病）。
        rect 传客户区矩形即整屏擦掉；不给 rect 就擦全部。
        """
        layers = getattr(self, '_glass_text_layers', None)
        if not layers:
            return
        if rect is None:
            r = wt.RECT(0, 0, self._paint_w, self._paint_h)
        else:
            r = wt.RECT(int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3]))
        gdi32.PatBlt.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, wt.DWORD]
        # 图层是 TEXT_SS 倍尺寸且带缩放变换；PatBlt 在变换下不可靠，
        # 先临时恢复单位矩阵、按物理坐标擦，再装回去。
        for layer in layers:
            ss = getattr(self, '_text_ss', 1)
            gdi32.PatBlt(layer.dc, r.left * ss, r.top * ss,
                         (r.right - r.left) * ss, (r.bottom - r.top) * ss,
                         0x00000042)          # BLACKNESS = 全 0，等于没画过
    def _apply_patch_clip(self, dc, ss=1):
        """局部刷新：把 DC 的裁剪区再和 patch 矩形求交（多块用区域合并）。

        没有 patch 时什么都不做；有的话就在 DC 上装一个「只允许这几块」的区域，
        后面所有落笔自动被裁掉。
        """
        rects = getattr(self, '_patch_clip', None)
        if not rects:
            return
        rgn = gdi32.CreateRectRgn(0, 0, 0, 0)
        if not rgn:
            return
        first = True
        for r in rects:
            sub = gdi32.CreateRectRgn(int(r[0]) * ss, int(r[1]) * ss,
                                      int(r[2]) * ss, int(r[3]) * ss)
            if not sub:
                continue
            if first:
                gdi32.CombineRgn(rgn, sub, 0, 5)      # RGN_COPY
                first = False
            else:
                gdi32.CombineRgn(rgn, rgn, sub, 2)    # RGN_OR
            gdi32.DeleteObject(sub)
        gdi32.SelectClipRgn(dc, rgn)
        gdi32.DeleteObject(rgn)

    def hover_rects(self, key):
        """把 hover 的 key 翻成屏幕矩形；翻不出来就返回 []（调用方会退回整帧重算）。"""
        if not key:
            return []
        R = self.rects
        for page, rect in self.nav_rects():
            if key == 'nav:' + page:
                return [rect]
        if key.startswith('chk:'):
            k = key[4:]
            r = (R.get('tiles') or {}).get(k)
            if r:
                return [r]
        r = R.get(key)
        if isinstance(r, (list, tuple)) and len(r) == 4:
            return [r]
        if key.startswith('chk:') or key.startswith('set:'):
            name = key.split(':', 1)[1]
            for item, ry, rowh in R.get('rows', []):
                if item.get('key') == name:
                    card = R.get('card')
                    l = card[0] if card else 0
                    rr = card[2] if card else self._paint_w
                    return [(l, ry - 2, rr, ry + rowh - 2)]
        return []

    # ---- GDI+ 句柄（每帧一支 DC 一个，画完就放） ----
    def _gp(self, hdc):
        """取（或新建）这支 DC 对应的 GDI+ Graphics，带抗锯齿和补丁裁剪。"""
        lib = gp_lib()
        if lib is None:
            return None
        if getattr(self, '_gp_gfx', None) and self._gp_dc == int(hdc):
            return self._gp_gfx
        self._gp_release()
        gfx = ctypes.c_void_p()
        if lib.GdipCreateFromHDC(ctypes.c_void_p(int(hdc)), ctypes.byref(gfx)) != 0 or not gfx:
            self._gp_dc = int(hdc)
            return None
        lib.GdipSetSmoothingMode(gfx, GP_SMOOTH_AA)
        lib.GdipSetPixelOffsetMode(gfx, GP_PIXEL_HALF)
        rects = getattr(self, '_patch_clip', None)
        if rects:
            # 补丁帧必须给 GDI+ 自己的裁剪区：GDI 的裁剪区对它几乎不起作用
            # （整张卡片填充 16ms → 13ms），GDI+ 的裁剪区才真的省（→ 0.2ms）。
            rgn = ctypes.c_void_p()
            if lib.GdipCreateRegion(ctypes.byref(rgn)) == 0:
                for r in rects:
                    box = wt.RECT(int(r[0]), int(r[1]),
                                  int(r[2] - r[0]), int(r[3] - r[1]))
                    lib.GdipCombineRegionRectI(rgn, ctypes.byref(box), 2)   # Union
                lib.GdipSetClipRegion(gfx, rgn, 0)                         # Replace
                lib.GdipDeleteRegion(rgn)
        self._gp_dc, self._gp_gfx = int(hdc), gfx
        return gfx

    def _gp_release(self):
        """释放 GDI+ 句柄。必须在 BitBlt/合成之前调用 —— GDI+ 有内部批处理，
        不删 Graphics 的话最后几笔可能还没落到 DIB 上。"""
        gfx = getattr(self, '_gp_gfx', None)
        if gfx:
            lib = gp_lib()
            if lib is not None:
                lib.GdipDeleteGraphics(gfx)
        self._gp_gfx = None
        self._gp_dc = None

    def _fill_round_gdi(self, hdc, rect, radius, fill, border, bwidth):
        """GDI 回退路径（GDI+ 不可用时；也是大块面板铺底用的）"""
        br = gdi32.CreateSolidBrush(fill)
        pen = (gdi32.CreatePen(0, max(1, self.S(bwidth)), border) if border
               else gdi32.GetStockObject(8))                 # 8 = NULL_PEN
        ob = gdi32.SelectObject(hdc, br)
        op = gdi32.SelectObject(hdc, pen)
        gdi32.RoundRect(hdc, int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3]),
                        self.S(radius * 2), self.S(radius * 2))
        gdi32.SelectObject(hdc, ob)
        gdi32.SelectObject(hdc, op)
        if br:
            gdi32.DeleteObject(br)
        if border and pen:
            gdi32.DeleteObject(pen)

    def fill_round(self, hdc, rect, radius, fill, border=None, bwidth=1):
        """圆角矩形：rect 已是物理像素，radius 是逻辑值。

        走 GDI+ 的 AntiAlias 路径。大块（整张卡片/日志卡）纯 GDI+ 填充要 16ms，
        所以先用 GDI 铺满，再用 GDI+ 描一圈 —— 描边本来就是抗锯齿的，
        顺带把 GDI 铺底留下的硬边盖掉；没有边框时用填充色描边，只为抗锯齿。
        """
        l, t, r, b = (int(round(float(v))) for v in rect[:4])
        w, h = r - l, b - t
        if w <= 0 or h <= 0:
            return
        gfx = self._gp(hdc)
        if gfx is None:
            return self._fill_round_gdi(hdc, rect, radius, fill, border, bwidth)
        lib = gp_lib()
        rad = max(0.0, min(float(self.S(radius)), w / 2.0, h / 2.0))
        bw = max(1.0, float(self.S(bwidth)))
        stroke = border
        path = gp_round_path(l, t, w, h, max(rad, 0.5))
        if rad < 0.5 or w * h <= GP_AA_FILL_MAX or getattr(self, '_patch_clip', None):
            # 小块（或补丁帧里被裁剪过的大块）直接用 GDI+ 填充：几十微秒
            br = ctypes.c_void_p()
            lib.GdipCreateSolidFill(gp_argb(fill), ctypes.byref(br))
            lib.GdipFillPath(gfx, br, path)
            lib.GdipDeleteBrush(br)
        else:
            self._fill_round_gdi(hdc, (l, t, r, b), radius, fill, None, 1)
            if stroke is None:
                stroke = fill          # 没有边框也要描，否则铺底的硬边留着
        if stroke is not None:
            pen = ctypes.c_void_p()
            lib.GdipCreatePen1(gp_argb(stroke), ctypes.c_float(bw), GP_UNIT_PIXEL,
                               ctypes.byref(pen))
            lib.GdipDrawPath(gfx, pen, path)
            lib.GdipDeletePen(pen)
        lib.GdipDeletePath(path)      # 每帧画 30~40 个圆角，不删就是每秒泄几百个路径对象

    def dot(self, hdc, cx, cy, r, color):
        rr = self.S(r)
        gfx = self._gp(hdc)
        if gfx is None:
            br = gdi32.CreateSolidBrush(color)
            ob = gdi32.SelectObject(hdc, br)
            op = gdi32.SelectObject(hdc, gdi32.GetStockObject(8))
            gdi32.Ellipse(hdc, int(cx - rr), int(cy - rr), int(cx + rr), int(cy + rr))
            gdi32.SelectObject(hdc, ob)
            gdi32.SelectObject(hdc, op)
            gdi32.DeleteObject(br)
            return
        lib = gp_lib()
        br = ctypes.c_void_p()
        lib.GdipCreateSolidFill(gp_argb(color), ctypes.byref(br))
        lib.GdipFillEllipse(gfx, br, ctypes.c_float(cx - rr), ctypes.c_float(cy - rr),
                            ctypes.c_float(rr * 2), ctypes.c_float(rr * 2))
        lib.GdipDeleteBrush(br)

    def hline(self, hdc, x1, x2, y, color):
        # 水平/垂直直线没有斜边，GDI 就够；保留原实现，省一次 GDI+ 调用
        pen = gdi32.CreatePen(0, 1, color)
        op = gdi32.SelectObject(hdc, pen)
        gdi32.MoveToEx(hdc, int(x1), int(y), None)
        gdi32.LineTo(hdc, int(x2), int(y))
        gdi32.SelectObject(hdc, op)
        gdi32.DeleteObject(pen)

    def check_mark(self, hdc, x, y, color):
        """对勾：两段折线。GDI 的 LineTo 是硬边，折线的斜边台阶很明显，
        交给 GDI+ 并给圆头圆角，白勾才干净。"""
        pts = [(x, y), (x + self.S(3), y + self.S(3)), (x + self.S(8), y - self.S(3))]
        gfx = self._gp(hdc)
        lib = gp_lib()
        if gfx is None or lib is None:
            pen = gdi32.CreatePen(0, max(1, self.S(1.6)), color)
            op = gdi32.SelectObject(hdc, pen)
            gdi32.MoveToEx(hdc, int(pts[0][0]), int(pts[0][1]), None)
            gdi32.LineTo(hdc, int(pts[1][0]), int(pts[1][1]))
            gdi32.LineTo(hdc, int(pts[2][0]), int(pts[2][1]))
            gdi32.SelectObject(hdc, op)
            gdi32.DeleteObject(pen)
            return
        pen = ctypes.c_void_p()
        lib.GdipCreatePen1(gp_argb(color), ctypes.c_float(max(1.0, self.S(1.6))),
                           2, ctypes.byref(pen))
        lib.GdipSetPenStartCap(pen, 2)      # LineCapRound
        lib.GdipSetPenEndCap(pen, 2)
        lib.GdipSetPenLineJoin(pen, 2)      # LineJoinRound
        arr = (ctypes.c_int * 6)(int(pts[0][0]), int(pts[0][1]),
                                 int(pts[1][0]), int(pts[1][1]),
                                 int(pts[2][0]), int(pts[2][1]))
        lib.GdipDrawLinesI(gfx, pen, arr, 3)
        lib.GdipDeletePen(pen)

    def fit_work_area(self):
        """窗口被任务栏/分辨率变化挤到工作区外时，把它拉回来。

        只在真的越界时才动 —— 用户自己拖过的位置要保住。
        """
        if not self.hwnd:
            return
        work = wt.RECT()
        user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work), 0)
        if work.right <= work.left or work.bottom <= work.top:
            return
        r = wt.RECT()
        user32.GetWindowRect(self.hwnd, ctypes.byref(r))
        ww, wh = r.right - r.left, r.bottom - r.top
        x, y = r.left, r.top
        if x + ww > work.right:
            x = work.right - ww
        if y + wh > work.bottom:
            y = work.bottom - wh
        if x < work.left:
            x = work.left
        if y < work.top:
            y = work.top
        # 窗口比工作区还大的话，上面几条会互相打架（改分辨率变小的情况）
        if ww > work.right - work.left or wh > work.bottom - work.top:
            log_line("窗口比工作区大（%dx%d vs %dx%d），保持不动"
                     % (ww, wh, work.right - work.left, work.bottom - work.top))
            return
        if (x, y) != (r.left, r.top):
            user32.SetWindowPos(self.hwnd, None, x, y, 0, 0, 0x0001 | 0x0004)
            log_line("窗口越界，已挪回工作区：(%d,%d) -> (%d,%d)"
                     % (r.left, r.top, x, y))

    # ---------- 布局 ----------
    def layout(self, w, h):
        """w,h 是客户区物理像素；内部先排逻辑坐标，最后统一乘 DPI 系数"""
        kk = self.dpi / 96.0
        pad = 28
        left = 212
        W = int(round(w / kk))
        H = int(round(h / kk))
        card_t = 216 if self.page == "main" else 96
        # 子页面（设置 / 自定义 / 夜间）行数多，用矮一点的行高，日志区才不会被挤没。
        # 三个子页面统一行高，各分组内部密度才一致（之前 ①组 38、②③组 32，看着参差）。
        row_h = {"settings": 42, "custom": 42, "night": 42, "tasks": 42}.get(self.page, 58)
        self.row_h_logical = row_h
        self.sub_page = self.page in ("settings", "custom", "night", "about", "tasks")
        items = self.current_rows()
        b_h = 46

        # 换页时把滚动位置归零，别让新页面一进来就停在中间
        if getattr(self, "_scroll_page", None) != self.page:
            self._scroll_page = self.page
            self.scroll = 0

        # 先按"内容全长"排一遍，再决定卡片能显示多少、要不要滚动。
        rows = []
        y = 0
        for it in items:
            if it.get("key", "").startswith("sec:"):
                y += 7              # 分组标题前面留一点空隙，视觉上分组清楚
                rh = int(it.get("h") or 24)
            else:
                rh = int(it.get("h") or row_h)
            rows.append([it, y, rh])
            y += rh
        if self.page == "main":
            rows = [[it, (i//2)*104, 98] for i,(it,_,_) in enumerate(rows)]
            y = ((len(rows)+1)//2)*104
        content_h = y + 6                  # 底部内边距
        view_top = card_t + 6

        # 卡片最高到哪儿：底下要留出按钮行 + 至少 3 行日志
        card_cap = H - 36 - b_h - 20 - 82
        card_b = min(view_top + content_h, max(view_top + 80, card_cap))
        if self.page == "about":
            # 关于页是自绘的整块，占满到按钮行之前，不留日志区
            card_b = H - 40 - 46 - 14
            content_h = self.about_geom((left, card_t, W-pad, card_b))[0]["bottom"] - view_top

        # 内容比可视区高就滚动（子页面才滚；主界面行少，用不到）
        self._scroll_max = max(0, content_h - (card_b - view_top))
        self.scroll = max(0, min(int(getattr(self, "scroll", 0) or 0),
                                 self._scroll_max))
        off = view_top - self.scroll
        for r in rows:
            r[1] += off
        rows = [tuple(r) for r in rows]

        by = card_b + 10
        # 按钮从左到右排：宽 200 / 118 / 118 / 104 / 110，间距 12 或 10
        x = left
        log_top = by + b_h + 10
        log_bot = max(log_top, H - 36)      # 子页面行多，日志区可能被压成 0 高
        rects = {
            "title": (left, 19, W - pad, 52),
            "sub": (left, 57, W - pad, 78),
            "card": (left, card_t, W - pad, card_b),
            "logcard": (left, log_top, W - pad, log_bot),
            "statusbar": (left, H - 34, W - pad, H - 12),
        }
        # 有可用更新时，状态栏右侧那块是可点的（点了跳设置页）
        if self.upd_hint():
            _l, _t, _r, _b = rects["statusbar"]
            _w = min(self.S(300), (_r - _l) // 2)
            rects["upd_hint"] = (_r - _w, _t, _r, _b)
        for i, (key, bw) in enumerate(
                (("start", 200), ("cancel", 118), ("shutdown", 118),
                 ("edit", 104), ("night", 110))):
            rects[key] = (x, by, x + bw, by + b_h)
            x += bw + (12 if i == 0 else 10)

        if self.page == "main":
            rects["hero"] = (left, 94, W-pad, 178)
            button_widths = (("start", 242), ("night", 142), ("cancel", 120), ("shutdown", 150))
            x = left
            for name, width in button_widths:
                width = int((W-pad-left-36)*width/654)
                rects[name] = (x, by, x+width, by+b_h)
                x += width+12
            # Kept as a valid return anchor for layout tooling; navigation is in the sidebar.
            rects["edit"] = (left, by, left+140, by+b_h)
        else:
            rects["edit"] = (left, by, left+140, by+b_h)
        # 标题右侧的「全选」（只占标题行右边，不加高窗口）
        chip_t, chip_b = (185, 209) if self.page == "main" else (18, 44)
        all_w = 96
        xr = W - pad
        rects["all"] = (xr - all_w, chip_t, xr, chip_b)

        # 关于页：自绘整块，顺手把可点的链接矩形登记进来（逻辑坐标，后面统一乘 kk）
        if self.page == "about":
            self._about = self.about_geom((left, card_t-self.scroll, W - pad, card_b))
            for i, (url, lr) in enumerate(self._about[2]):
                rects["about_link:%d" % i] = tuple(lr)

        # 「夜间启动」询问卡片：模态盖住整个客户区，居中一块卡片 + 两个按钮
        if self.prompt:
            cw, chh = 620, 246
            cx = (W-cw)//2
            cy = max(card_t+10,(H-chh)//2)
            rects["prompt"]=(cx,cy,cx+cw,cy+chh)
            bx=cx+33
            by=cy+chh-70
            for key,bw in (("prompt_all",190),("prompt_night",226),("prompt_cancel",112)):
                rects[key]=(bx,by,bx+bw,by+42)
                bx+=bw+12

        # 「选 exe」卡片：同样盖在主界面之上
        if self.exepick:
            cw, chh = 460, 400
            cx = (W - cw) // 2
            cy = max(card_t + 6, (H - chh) // 2)
            rects["expick"] = (cx, cy, cx + cw, cy + chh)
            bw, bh, gap = 96, 34, 12
            bx = cx + cw - 26 - bw * 2 - gap
            by = cy + chh - 50
            rects["expick_ok"] = (bx, by, bx + bw, by + bh)
            rects["expick_cancel"] = (bx + bw + gap, by, bx + bw + gap + bw, by + bh)
            # 候选列表每一行的矩形（点击/双击用）
            top = cy + 72
            bot = cy + chh - 66
            lh = 26
            n = len(self.exepick.get("items", []))
            maxn = max(1, int((bot - top - 8) // lh))
            first = max(0, min(self.exepick.get("sel", 0) - maxn // 2, n - maxn))
            if n <= maxn:
                first = 0
            erows = []
            for k in range(min(maxn, n)):
                iy = top + 4 + k * lh
                erows.append((first + k, iy, iy + lh - 2))
            rects["expick_rows"] = erows
        R = self.rects
        for key, r in rects.items():
            if key == "expick_rows":
                continue                       # 列表，单独处理
            R[key] = tuple(int(round(v * kk)) for v in r)
        if "expick_rows" in rects:
            R["expick_rows"] = [(idx, int(round(a * kk)), int(round(b * kk)))
                                for idx, a, b in rects["expick_rows"]]
        R["rows"] = [(item, int(round(y * kk)), int(round(h * kk)))
                     for item, y, h in rows]
        R["row_h"] = int(round(row_h * kk))
        R["disabled_rows"]={it["key"] for it,_,_ in rows if not it["key"].startswith("sec:")
                            and self.page != "main" and not self.setting_button(it)[2]}
        R["tiles"] = {}
        if self.page == "main":
            cl,ct,cr,cb=R["card"]
            tilew=(cr-cl-self.S(12))//2
            for i,(it,yy,hh) in enumerate(R["rows"]):
                xx=cl+(i%2)*(tilew+self.S(12))
                R["tiles"][it["key"]]=(xx,yy,xx+tilew,yy+hh)


        if self.page == "tasks":
            self.layout_task_page(W, H)

    def current_rows(self):
        if self.page == "about":
            return []                   # 关于页是自绘整块，不用行列表
        if self.page == "custom":
            return self.custom_rows()
        if self.page == "night":
            return self.night_rows()
        if self.page == "tasks":
            return self.task_rows()
        if self.page == "settings":
            return self.settings_rows()
        return self.instance_rows()

    # ---------- 关于页 ----------
    @staticmethod
    def _short_url(u):
        """长网址压短一点，点得着就行；点一下会用浏览器打开完整地址"""
        u = (u or "").strip()
        for pre in ("https://", "http://"):
            if u.startswith(pre):
                u = u[len(pre):]
        return u.rstrip("/")

    def about_blocks(self):
        """关于页要展示的几块内容：[(块标题, [(标签, 值, 链接), ...]), ...]

        作者名 / 主页 / 仓库**只认代码里的 ABOUT_INFO**，不再读 config.json ——
        这些是作者信息，放进配置文件等于谁都能改，改完界面上显示的就是假的了。
        """
        def g(key):
            return str(ABOUT_INFO.get(key) or "").strip()

        author = g("author") or "未填写"
        author_page = g("author_page")
        project = g("project")
        issues = g("issues")
        group = g("group")

        lines = [("作者", author, None)]
        if group:
            lines.append(("交流群", group, None))
        if author_page:
            lines.append(("作者主页", self._short_url(author_page), author_page))
        if project:
            lines.append(("项目与下载", self._short_url(project), project))
        if issues:
            lines.append(("问题反馈", self._short_url(issues), issues))

        return [
            ("作者与项目", lines),
            ("使用声明", [
                ("免费使用", "完全免费，无广告、无内购、不收费，也不收赞助", None),
                ("非商业用途", "仅供个人自用；请勿转卖、代练代肝、随盘附赠等任何盈利场景", None),
                ("只跑本机", "只操作本机的模拟器和脚本，不联网、不上传任何信息", None),
                ("按原样给", "不提供任何担保，用出问题（账号/数据）需自行承担", None),
                ("转载", "随便转载，但请保留作者署名和项目地址，别删掉当自己的", None),
            ]),
            ("第三方组件", [
                ("", "MAA / MaaEnd / MaaFgo / ok-ww / MuMu 版权归各自作者，本程序只做串联调用", None),
            ]),
        ]

    def about_geom(self, card):
        """Flow layout shared by drawing, scrolling, and link hit-testing."""
        x1,y1,x2,y2=card
        pad=24
        g={"avatar":(x1+pad,y1+22,x1+pad+52,y1+74)}
        g["name"]=(x1+pad+70,y1+20,x2-pad,y1+49)
        g["ver"]=(x1+pad+70,y1+50,x2-pad,y1+74)
        g["tag"]=(x1+pad,y1+88,x2-pad,y1+112)
        bx1,bx2=x1+pad,x2-pad
        y=y1+130
        blocks,links=[],[]
        for title,lines in self.about_blocks():
            height=40+len(lines)*26+14
            rect=(bx1,y,bx2,y+height)
            rows=[]
            ly=y+40
            for label,value,url in lines:
                lr=(bx1+20,ly,bx2-18,ly+26)
                rows.append((label,value,url,lr))
                if url:
                    links.append((url,lr))
                ly+=26
            blocks.append((title,rect,rows))
            y+=height+14
        g["cfg"]=(bx1,y+4,bx2,y+30)
        g["hint"]=(bx1,y+34,bx2,y+56)
        g["bottom"]=y+74
        links.append(("file:"+CONFIG_PATH,g["cfg"]))
        return g,blocks,links

    def draw_about(self, hdc, card):
        """关于页：头像 + 名字 + 版本 + 一句话 + 几块说明（自绘，跟行列表无关）"""
        S = self.S
        if not getattr(self, "_about", None):
            return
        g, blocks, links = self._about

        # 头像：白底圆角块 + 程序图标
        ax1, ay1, ax2, ay2 = g["avatar"]
        self.fill_round(hdc, (S(ax1) - S(2), S(ay1) + S(2), S(ax2) + S(2), S(ay2) + S(4)),
                        16, rgb("#DCE2EC"))
        self.fill_round(hdc, (S(ax1), S(ay1), S(ax2), S(ay2)), 14,
                        C["card"], C["border"], 1.2)
        draw_icon(hdc, "launcher", S(ax1 + 6), S(ay1 + 6), S(40))

        self.text(hdc, APP_TITLE, tuple(S(v) for v in g["name"]),
                  C["text"], self.font(19, True),
                  DT_LEFT | DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS | DT_NOPREFIX)
        _variant = ("文件夹版 · 秒开 · 更新走安装程序" if ONEDIR
                    else "单文件版 · 双击即用 · 换 exe 即升级")
        self.text(hdc, "%s · %s" % (APP_VERSION, _variant),
                  tuple(S(v) for v in g["ver"]), C["muted"], self.font(10.5),
                  DT_LEFT | DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS | DT_NOPREFIX)
        self.text(hdc, "按顺序拉起 MaaEnd → MuMu 实例 → MAA → MaaFgo → ok-ww，全程不弹 UAC",
                  tuple(S(v) for v in g["tag"]), C["text2"], self.font(11),
                  DT_LEFT | DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS | DT_NOPREFIX)

        for title, rect, rows in blocks:
            self.fill_round(hdc, tuple(S(v) for v in rect), 10,
                            C["panel"], C["panel_line"])
            # 标题左边一根小竖条，代替图标
            th = 12
            ty = (rect[1] + 14, rect[1] + 14 + th)
            self.fill_round(hdc, (S(rect[0] + 20), S(ty[0]),
                                  S(rect[0] + 23), S(ty[1])), 1.5, C["accent"])
            self.text(hdc, title,
                      (S(rect[0] + 32), S(rect[1] + 8), S(rect[2] - 16), S(rect[1] + 32)),
                      C["text"], self.font(11.5, True),
                      DT_LEFT | DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX)

            for label, value, url, lr in rows:
                lx = lr[0]
                if label:
                    self.dot(hdc, S(lx - 6), S((lr[1] + lr[3]) / 2.0), 1.6, C["muted"])
                    self.text(hdc, label, (S(lx), S(lr[1]), S(lx + 70), S(lr[3])),
                              C["muted"], self.font(10.5),
                              DT_LEFT | DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX)
                    vx1 = lx + 72
                else:
                    vx1 = lx
                hot = url and any(
                    self.hover == "about_link:%d" % i
                    for i, (u, r) in enumerate(links) if u == url and r == lr)
                col = (C["accent_d"] if hot else C["accent"]) if url else C["text2"]
                self.text(hdc, value, (S(vx1), S(lr[1]), S(lr[2]), S(lr[3])),
                          col, self.font(10.5, bool(url)),
                          DT_LEFT | DT_SINGLELINE | DT_VCENTER
                          | DT_END_ELLIPSIS | DT_NOPREFIX)

        # 底部的配置文件路径行
        cr = g.get("cfg")
        if cr:
            hot = any(self.hover == "about_link:%d" % i
                      for i, (u, r) in enumerate(links)
                      if u.startswith("file:") and r == cr)
            self.text(hdc, "配置文件", (S(cr[0]), S(cr[1]), S(cr[0] + 66), S(cr[3])),
                      C["muted"], self.font(10.5),
                      DT_LEFT | DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX)
            hint = "（就在 exe 旁边，覆盖 exe 升级不会丢）"
            self.text(hdc, CONFIG_PATH, (S(cr[0] + 68), S(cr[1]), S(cr[2]), S(cr[3])),
                      C["accent_d"] if hot else C["accent"], self.font(10.5),
                      DT_LEFT | DT_SINGLELINE | DT_VCENTER
                      | DT_END_ELLIPSIS | DT_NOPREFIX)
            self.text(hdc, hint, tuple(S(v) for v in g["hint"]),
                      C["muted"], self.font(9.5),
                      DT_LEFT | DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS | DT_NOPREFIX)

    # ---------- 安排自动任务 ----------
    MXU_CFG = {"maaend": "mxu-MaaEnd.json", "maafgo": "mxu-MaaFgo.json"}
    TASK_DEFAULTS = {
        "maaend.instance": "全套日常",
        "maaend.autostart": True,
        "maa.auto_run": True,
        "maafgo.instance": "默认设置",
        "maafgo.autostart": True,
        "okww.task": "DailyTask",
    }
    # ok-ww 的任务名 → 界面上的中文（空串 = 不给 -t，只打开界面不自动开始）
    OKWW_TASKS = (("DailyTask", "每日任务"), ("", "不自启（只打开）"))

    def _mxu_options(self, key):
        """MaaEnd / MaaFgo 有几套「任务配置」

        这俩是 MXU 壳，任务都勾在它自己的 config\\mxu-*.json 里，
        一套就是一个"实例"（名字由用户起）。我们只读名字，不改内容。
        """
        m = self.cfg.get(key, {}) or {}
        p = (m.get("path") or "").strip()
        fn = self.MXU_CFG.get(key)
        if not p or not fn:
            return []
        j = os.path.join(os.path.dirname(p), "config", fn)
        if not os.path.isfile(j):
            return []
        return _mxu_names(j) or []

    def task_summary(self):
        """设置页入口那行的一行摘要"""
        c = self.cfg
        parts = []
        m = c.get("maaend", {}) or {}
        if m.get("enabled", False):
            parts.append("MaaEnd %s" % ((m.get("instance") or "").strip() or "未设"))
        a = c.get("maa", {}) or {}
        if a.get("enabled", True):
            parts.append("MAA " + ("自动" if a.get("auto_run", True) else "不自动"))
        f = c.get("maafgo", {}) or {}
        if f.get("enabled", True):
            parts.append("MaaFgo %s" % ((f.get("instance") or "").strip() or "未设"))
        w = c.get("okww", {}) or {}
        if w.get("enabled", True):
            t = (w.get("task") or "").strip()
            parts.append("ok-ww " + (dict(self.OKWW_TASKS).get(t, t) if t else "不自启"))
        return "、".join(parts) or "（没有启用的项目）"

    def task_rows(self):
        """二级页：每个项目启动后自动跑什么"""
        c = self.cfg
        out = [{
            "key": "t_hint",
            "icon": "ui_info",
            "title": "改这里 = 改它们启动后自动做什么",
            "sub": "只影响「启动后要不要自动开始」；具体勾了哪些子任务，在各脚本自己的界面里",
            "chip": "说明",
        }]

        m = c.get("maaend", {}) or {}
        opts = self._mxu_options("maaend")
        cur = (m.get("instance") or "").strip()
        out.append({
            "key": "t_mx:maaend",
            "icon": "maaend",
            "title": "MaaEnd · 任务配置",
            "sub": ("现在是「%s」" % cur if cur else "还没设")
                   + ("· 点右侧换一套（共 %d 套）" % len(opts) if opts
                      else "· 读不到列表：先手动打开一次 MaaEnd"),
            "chip": cur or "未设",
        })
        out.append({
            "key": "t_flag:maaend.autostart",
            "icon": "maaend",
            "title": "MaaEnd · 启动后自动开始",
            "sub": ("开：带 --autostart，一打开就直接跑任务"
                    if m.get("autostart", True)
                    else "关：只把 MaaEnd 打开，任务要你自己点开始"),
            "chip": "开" if m.get("autostart", True) else "关",
        })

        a = c.get("maa", {}) or {}
        out.append({
            "key": "t_flag:maa.auto_run",
            "icon": "maa",
            "title": "MAA · 启动后自动运行",
            "sub": ("开：替你打开 MAA 的「启动后直接运行任务」"
                    if a.get("auto_run", True)
                    else "关：会把这选项改回关闭，任务要你在 MAA 里点"),
            "chip": "开" if a.get("auto_run", True) else "关",
        })

        f = c.get("maafgo", {}) or {}
        opts = self._mxu_options("maafgo")
        cur = (f.get("instance") or "").strip()
        out.append({
            "key": "t_mx:maafgo",
            "icon": "maafgo",
            "title": "MaaFgo · 任务配置",
            "sub": ("现在是「%s」" % cur if cur else "还没设")
                   + ("· 点右侧换一套（共 %d 套）" % len(opts) if opts
                      else "· 读不到列表：先手动打开一次 MaaFgo"),
            "chip": cur or "未设",
        })
        out.append({
            "key": "t_flag:maafgo.autostart",
            "icon": "maafgo",
            "title": "MaaFgo · 启动后自动开始",
            "sub": ("开：带 --autostart，起来就开跑"
                    if f.get("autostart", True)
                    else "关：只打开 MaaFgo，任务要你自己点开始"),
            "chip": "开" if f.get("autostart", True) else "关",
        })

        w = c.get("okww", {}) or {}
        t = (w.get("task") or "").strip()
        out.append({
            "key": "t_okww",
            "icon": "okww",
            "title": "ok-ww · 用哪个任务",
            "sub": ("每日任务：一条龙（开游戏 → 登录 → 月卡 → 刷声骸 → 领奖 → 邮件）"
                    if t == "DailyTask" else "不自启：只把 ok-ww 打开，任务你自己点"),
            "chip": dict(self.OKWW_TASKS).get(t, t) if t else "不自启",
        })

        # 启动编排（原来在设置页的独立二级页，用户要求合并到这一页）
        out.extend(self.pipeline_section_rows())

        out.append({
            "key": "t_reset",
            "icon": "ui_update",
            "title": "恢复脚本默认",
            "sub": "MaaEnd「全套日常」+ 自动开始 · MAA 自动运行 · ok-ww 每日任务",
            "chip": "恢复",
        })
        return out

    def cycle_task_config(self, key):
        """MaaEnd / MaaFgo 换一套「任务配置」"""
        label = "MaaEnd" if key == "maaend" else "MaaFgo"
        opts = self._mxu_options(key)
        m = self.cfg.setdefault(key, {})
        cur = (m.get("instance") or "").strip()
        if not opts:
            self.ui_log("读不到 %s 的任务配置：先手动打开一次 %s（会生成 config\\%s），"
                        "或者在 config.json 里直接改 %s.instance"
                        % (label, label, self.MXU_CFG.get(key, ""), key))
            self.status = "读不到 %s 的任务配置列表" % label
            return
        nxt = opts[(opts.index(cur) + 1) % len(opts)] if cur in opts else opts[0]
        m["instance"] = nxt
        save_config(self.cfg)
        self.ui_log("%s 的任务配置 →「%s」（下一轮启动生效）" % (label, nxt))
        self.status = "%s 的任务配置：%s" % (label, nxt)

    def toggle_task_flag(self, dotted):
        """切换 maaend.autostart / maa.auto_run / maafgo.autostart 这类开关"""
        try:
            section, name = dotted.split(".", 1)
        except ValueError:
            return
        m = self.cfg.setdefault(section, {})
        val = not bool(m.get(name, True))
        m[name] = val
        save_config(self.cfg)
        label = {"maaend": "MaaEnd", "maa": "MAA", "maafgo": "MaaFgo"}.get(section, section)
        what = {"autostart": "启动后自动开始", "auto_run": "启动后自动运行"}.get(name, name)
        self.ui_log("%s 的「%s」→ %s" % (label, what, "开" if val else "关"))
        self.status = "%s · %s：%s" % (label, what, "开" if val else "关")

    def cycle_okww_task(self):
        """ok-ww 用哪个任务：每日任务 / 不自启"""
        w = self.cfg.setdefault("okww", {})
        cur = (w.get("task") or "").strip()
        keys = [k for k, _ in self.OKWW_TASKS]
        nxt = keys[(keys.index(cur) + 1) % len(keys)] if cur in keys else keys[0]
        w["task"] = nxt
        save_config(self.cfg)
        label = dict(self.OKWW_TASKS).get(nxt, nxt) if nxt else "不自启（只打开）"
        self.ui_log("ok-ww 的任务 → %s" % label)
        self.status = "ok-ww：%s" % label

    def reset_tasks(self):
        """把这页的 6 个字段恢复默认，别的不动"""
        for dotted, val in self.TASK_DEFAULTS.items():
            section, name = dotted.split(".", 1)
            self.cfg.setdefault(section, {})[name] = val
        save_config(self.cfg)
        self.ui_log("已恢复默认：MaaEnd「全套日常」+ 自动开始 · MAA 自动运行 · "
                    "MaaFgo「默认设置」+ 自动开始 · ok-ww 每日任务")
        self.status = "安排自动任务已恢复默认"

    # ---------- 启动编排页 ----------
    PIPELINE_MAX_ROUNDS = 4

    def pipeline_items(self):
        """参与编排的项目：主界面里能看到的那些（不含分组标题）"""
        return [it for it in self.instance_rows()
                if not str(it.get("key", "")).startswith("sec:")
                and not str(it.get("key", "")).startswith("custom_add")]

    def default_pipeline(self):
        """第一次开启编排时给个贴合现状的默认：终末地 / 模拟器那一批 / 鸣潮"""
        assign = {}
        for it in self.pipeline_items():
            k = it["key"]
            if k == "maaend":
                assign[k] = 1
            elif k == "okww":
                assign[k] = 3
            else:
                assign[k] = 2
        return assign

    def pipeline_section_rows(self):
        """启动编排那一段（合并进「安排自动任务」页，不再是独立二级页）

        每项一行，点右侧按钮循环切换「第几轮」；下面是按轮汇总。
        """
        cfg = self.cfg
        pl = cfg.get("pipeline") or {}
        assign = pl.get("assign") or {}
        out = [{
            "key": "sec:pipe",
            "h": 22,
            "title": "启动编排 · 一轮一轮跑",
            "sub": "轮号小的先跑；一轮的任务真跑完了才开下一轮",
        }, {
            "key": "pl_enabled",
            "icon": "ui_tasks",
            "h": 42,
            "title": "分轮执行",
            "sub": "开启后按下面的轮次一轮一轮跑；关闭则所有勾选项一趟跑完（原行为）",
            "chip": "已开启" if pl.get("enabled") else "已关闭",
        }, {
            "key": "sec:assign",
            "h": 22,
            "title": "每项属于第几轮",
            "sub": "点右侧按钮切换：不参与 → 第1轮 → 第2轮 … → 第%d轮 → 不参与"
                   % self.PIPELINE_MAX_ROUNDS,
        }]
        for it in self.pipeline_items():
            k = it["key"]
            try:
                r = int(assign.get(k, 0) or 0)
            except Exception:
                r = 0
            out.append({
                "key": "pl:" + k,
                "icon": it.get("icon"),
                "h": 42,
                "title": it.get("title") or k,
                "sub": ("第 %d 轮" % r) if r > 0 else "不参与编排（这一趟不会启动）",
                "chip": ("第 %d 轮" % r) if r > 0 else "未编排",
            })
        # 轮次摘要
        for r in range(1, self.PIPELINE_MAX_ROUNDS + 1):
            names = [self.runner.item_label(k) for k, v in assign.items()
                     if str(v) == str(r)]
            if names:
                out.append({
                    "key": "pl_sum:%d" % r,
                    "icon": "ui_tasks",
                    "h": 30,
                    "title": "第 %d 轮：%s" % (r, " → ".join(names)),
                    "sub": "",
                })
        out.append({
            "key": "pl_hint", "icon": "ui_info", "h": 30,
            "title": "同一轮里按依赖顺序启动（实例先起，再 MAA / MaaFgo）；轮与轮之间严格串行。",
            "sub": "",
        })
        return out

    def settings_rows(self):
        """设置页：路径、连接与版本、软件更新、界面偏好；模块入口统一在侧栏

        每块前面插一行分组标题（key 以 "sec:" 开头，绘制时特殊处理），
        这样用户一眼能看出"这块是干什么的"，不用对着 11 行平铺猜。
        """
        cfg = self.cfg
        out = [{
            "key": "sec:path",
            "h": 22,
            "title": "① 选择各实例的路径",
            "sub": "选各个模拟器 / 脚本所在的文件夹（点右侧「选择」）",
        }]
        out.append({
            "key": "mumu",
            "icon": "mumu",
            "h": 42,
            "title": "MuMu 模拟器目录",
            "sub": cfg.get("mumu_root") or "未设置（点右侧「选择」）",
        })
        for key, name, game in (("maaend", "MaaEnd", "终末地"),
                                ("maa", "MAA", "明日方舟"),
                                ("maafgo", "MaaFgo", "FGO"),
                                ("okww", "ok-ww", "鸣潮")):
            p = (cfg.get(key, {}) or {}).get("path") or ""
            out.append({
                "key": key,
                "icon": key,
                "h": 42,
                "title": "%s · %s" % (name, game),
                "sub": p or "未设置（点右侧「选择」）",
            })

        out.append({
            "key": "sec:inst",
            "h": 22,
            "title": "② 模拟器实例与游戏版本",
            "sub": "决定脚本连哪台模拟器、用哪个服（点右侧按钮切换）",
        })
        names = {int(i["index"]): (i.get("name") or "模拟器")
                 for i in cfg.get("instances", []) or []}
        mi = int(cfg.get("maa", {}).get("instance_index", 0))
        fi = int(cfg.get("maafgo", {}).get("emulator_index", 1))
        out.append({
            "key": "maa_instance",
            "icon": "maa",
            "title": "MAA 连哪台实例",
            "sub": ("实例%d · %s" % (mi, names.get(mi, "不存在"))) if names
                   else "还没有实例（先选 MuMu 目录）",
            "chip": "实例%d" % mi,
        })
        out.append({
            "key": "fgo_instance",
            "icon": "fgo",
            "title": "MaaFgo 连哪台实例",
            "sub": ("实例%d · %s" % (fi, names.get(fi, "不存在"))) if names
                   else "还没有实例（先选 MuMu 目录）",
            "chip": "实例%d" % fi,
        })
        pkg = (cfg.get("maafgo", {}) or {}).get("game_package") or ""
        label = next((n for n, p in FGO_PACKAGES if p == pkg), "自定义")
        out.append({
            "key": "fgo_ver",
            "icon": "fgo",
            "title": "FGO 版本（包名）",
            "sub": "%s · %s" % (label, pkg or "未设置"),
            "chip": label,
        })

        out.append({"key": "sec:update", "h": 22, "title": "③ 软件更新", "sub": ""})
        u_sub, u_chip = self.upd_text()
        out.append({
            "key": "update",
            "icon": "ui_update",
            "h": 42,
            "title": "检查更新",
            "sub": u_sub,
            "chip": u_chip,
        })

        out.extend([
            {"key": "sec:appearance", "h": 22, "title": "④ 界面与动效", "sub": ""},
            {"key": "ui_material", "icon": "ui_sparkle", "title": "窗口背景材质",
             "sub": "Mica / Tabbed（Mica Alt）/ 亚克力 / 实色 · 不支持时自动回退",
             "chip": self.material_name()},
            {"key": "ui_motion", "icon": "ui_sliders", "title": "轻量动画",
             "sub": "页面淡入与滑移 · 跟随 Windows 的动画偏好",
             "chip": "开启" if cfg.get("ui_motion", True) else "关闭"},
        ])
        return out

    def instance_rows(self):
        out = []
        hid = self.hidden()
        # MaaEnd 排第一：它就是最优先跑的那个
        m = self.cfg.get("maaend", {})
        inst_name = (m.get("instance") or "").strip()
        if "maaend" not in hid:
            out.append({
                "key": "maaend",
                "icon": "maaend",
                "title": "MaaEnd · 终末地",
                "sub": ("%s · 自动开始任务，跑完关游戏" % inst_name) if inst_name
                       else "自动开始任务，跑完关游戏",
            })
        for inst in self.cfg.get("instances", []):
            idx = int(inst["index"])
            if ("vm%d" % idx) in hid:
                continue
            port = self.ports.get(idx) or read_adb_port(self.cfg.get("mumu_root", ""), idx)
            out.append({
                "key": "vm%d" % idx,
                "index": idx,
                "icon": self._vm_icon(idx, inst.get("name")),
                "title": "MuMu 实例 %d · %s" % (idx, inst.get("name") or "模拟器"),
                "sub": "ADB 127.0.0.1:%d" % port,
            })
        if "maa" not in hid:
            out.append({
                "key": "maa",
                "icon": "maa",
                "title": "MAA",
                "sub": "明日方舟 · 启动后自动开始任务"
                       if self.cfg.get("maa", {}).get("auto_run", True)
                       else "明日方舟 · 只启动界面",
            })
        if "maafgo" not in hid:
            out.append({
                "key": "maafgo",
                "icon": "maafgo",
                "title": "MaaFgo · FGO",
                "sub": self._maafgo_sub(),
            })
        if "okww" not in hid:
            out.append({
                "key": "okww",
                "icon": "okww",
                "title": "ok-ww · 鸣潮",
                "sub": self._okww_sub(),
            })
        # 用户自己加的（没适配：只打开，不自动跑）
        for it in self.cfg.get("custom_items", []) or []:
            cid = it.get("id")
            if ("custom:%s" % cid) in hid:
                continue
            out.append({
                "key": "custom:%s" % cid,
                "icon": "ui_apps",
                "title": it.get("name") or "自定义",
                "sub": self._custom_sub(it),
                "custom": True,
            })
        return out

    @staticmethod
    def _custom_sub(it):
        """自定义行的一句话说明：强调"只打开，不自动跑" """
        sc = os.path.basename(it.get("script") or "") or "未设脚本"
        gm = os.path.basename(it.get("game") or "")
        tail = gm if gm else "只开脚本"
        return "未适配 · 只打开不自动跑 · %s + %s" % (sc, tail)

    def hidden(self):
        return set(self.cfg.get("hidden_items", []) or [])

    def custom_rows(self):
        """自定义页：加新实例 / 逐个删除·恢复 / 恢复默认"""
        out = [{
            "key": "c_add",
            "icon": "ui_apps",
            "title": "+ 增加自定义实例",
            "sub": "选一个脚本 exe，再选一个游戏启动 exe（最多 %d 个）" % MAX_CUSTOM,
            "chip": "添加",
        }]
        hid = self.hidden()
        for label, key, ico in (("MaaEnd · 终末地", "maaend", "maaend"),
                                ("MAA · 明日方舟", "maa", "maa"),
                                ("MaaFgo · FGO", "maafgo", "maafgo"),
                                ("ok-ww · 鸣潮", "okww", "okww")):
            out.append(self._manage_row(label, key, key in hid, icon=ico))
        for inst in self.cfg.get("instances", []):
            idx = int(inst["index"])
            key = "vm%d" % idx
            out.append(self._manage_row(
                "MuMu 实例 %d · %s" % (idx, inst.get("name") or "模拟器"),
                key, key in hid, icon="mumu"))
        for it in self.cfg.get("custom_items", []) or []:
            cid = it.get("id")
            key = "custom:%s" % cid
            out.append(self._manage_row(it.get("name") or "自定义", key,
                                        key in hid, custom=it))
        out.append({
            "key": "c_restore",
            "icon": "ui_update",
            "title": "恢复默认主界面",
            "sub": "清掉自定义项、把删掉的行都放回来（4 个脚本 + 所有实例）",
            "chip": "恢复",
        })
        return out

    @staticmethod
    def _manage_row(label, key, hidden, custom=None, icon=None):
        if hidden:
            sub = "已经在主界面隐藏 —— 点「恢复」放回来"
            chip = "恢复"
        elif custom:
            sc = os.path.basename(custom.get("script") or "") or "未设脚本"
            gm = os.path.basename(custom.get("game") or "") or "只开脚本"
            sub = "%s + %s" % (sc, gm)
            chip = "删除"
        else:
            sub = "主界面上正显示这一项 —— 点「删除」隐藏它"
            chip = "删除"
        return {"key": "c_del:" + key, "icon": icon or "ui_apps", "title": label,
                "sub": sub, "chip": chip}

    # ---------- 《今晚的手游日常》 ----------
    NIGHT_SCRIPTS = (("maa", "MAA · 明日方舟"), ("maafgo", "MaaFgo · FGO"),
                     ("maaend", "MaaEnd · 终末地"), ("okww", "ok-ww · 鸣潮"))

    def night_items(self):
        """用户勾定的《今晚的手游日常》项目键（不含自动带上的实例）"""
        items = self.cfg.get("night_items")
        if items is None:
            items = ["maa", "maafgo"]
        return list(items)

    def night_keep(self):
        """《今晚的手游日常》实际会启动哪些键（这一个函数说了算）

        规则：
          - 设置里勾了谁就带谁（含用户自己加的项目 `custom:<id>`）；
          - 勾了 MAA / MaaFgo 就自动带上它绑定的那台模拟器实例 ——
            不带的话脚本起来也连不上，等于白开；
          - 实例已经被删掉的就丢掉。

        ⚠ 历史上这里曾有**两个同名定义**，后一个（返回实例号列表）把
        前一个覆盖了，于是「勾了鸣潮也只跑 MAA+MaaFgo」。改这块前先确认
        全文件只有这一个 `def night_keep`。
        """
        keys = []
        for k in self.night_items():
            if not isinstance(k, str):
                continue
            if k.startswith("vm"):
                continue                  # 实例统一在下面按绑定关系补，避免重复
            if k not in keys:
                keys.append(k)
        vms = set()
        if "maa" in keys:
            vms.add(int(self.cfg.get("maa", {}).get("instance_index", 0)))
        if "maafgo" in keys:
            vms.add(int(self.cfg.get("maafgo", {}).get("emulator_index", 1)))
        idxs = self._inst_indexes()
        for v in sorted(vms):
            if v in idxs:
                k = "vm%d" % v
                if k not in keys:
                    keys.append(k)
        return keys

    def night_desc(self):
        """《今晚的手游日常》包含哪些 —— 弹窗里那一行短描述"""
        names = []
        for k in self.night_items():
            if k.startswith("vm"):
                continue
            if k.startswith("custom:"):
                names.append(self._night_label(k))
            else:
                names.append(self._night_short(k))
        return "、".join(names) or "（还没设置，去设置里选）"

    @staticmethod
    def _night_short(key):
        return {"maa": "明日方舟（MAA）", "maafgo": "FGO（MaaFgo）",
                "maaend": "终末地（MaaEnd）", "okww": "鸣潮（ok-ww）"}.get(key, key)

    def _night_label(self, key):
        for k, label in self.NIGHT_SCRIPTS:
            if k == key:
                return label
        if key.startswith("vm"):
            return "MuMu 实例 %s" % key[2:]
        if key.startswith("custom:"):
            for it in self.cfg.get("custom_items", []) or []:
                if it.get("id") == key[7:]:
                    return it.get("name") or "自定义"
        return key

    def night_rows(self):
        """《今晚的手游日常》设置页：勾哪些项目算"""
        items = set(self.night_items())
        out = [{
            "key": "n_hint",
            "icon": "ui_moon",
            "title": "一天要清两次日常的手游",
            "sub": "勾上的算《今晚的手游日常》—— 开机弹窗点「只启动今晚的手游日常」，或主界面按「夜间启动」，都只跑它们",
            "chip": "说明",
        }]
        for k, label in self.NIGHT_SCRIPTS:
            on = k in items
            out.append({
                "key": "n_toggle:" + k,
                "icon": k,
                "title": label,
                "sub": ("属于《今晚的手游日常》" if on else "不属于"),
                "chip": "算" if on else "不算",
            })
        for it in self.cfg.get("custom_items", []) or []:
            cid = it.get("id")
            k = "custom:%s" % cid
            on = k in items
            out.append({
                "key": "n_toggle:" + k,
                "icon": "ui_apps",
                "title": it.get("name") or "自定义",
                "sub": "自定义项目（未适配，只帮你打开，不自动跑任务）",
                "chip": "算" if on else "不算",
            })
        out.append({
            "key": "n_restore",
            "icon": "ui_update",
            "title": "恢复默认",
            "sub": "回到「明日方舟（MAA）+ FGO（MaaFgo）」",
            "chip": "恢复",
        })
        return out

    @staticmethod
    def _vm_icon(idx, name):
        """实例行用游戏官方图标：先认名字，认不出再按实例号兜底"""
        n = (name or "").lower()
        if "舟" in n or "ark" in n:
            return "arknights"
        if "fgo" in n or "冠位" in n:
            return "fgo"
        if idx == 0:
            return "arknights"
        if idx == 1:
            return "fgo"
        return "mumu"

    def _okww_sub(self):
        m = self.cfg.get("okww", {})
        task = (m.get("task") or "DailyTask").strip()
        name = "每日任务" if task.lower() == "dailytask" else task
        tail = "无界面" if m.get("headless", False) else "自动开始"
        if m.get("exit_after", False):
            tail += "，跑完关游戏"
        return "%s · %s" % (name, tail)

    def _maafgo_sub(self):
        m = self.cfg.get("maafgo", {})
        name = (m.get("instance") or "").strip()
        idx = m.get("emulator_index", 1)
        pkg = (m.get("game_package") or "").strip()
        head = ("实例%d" % idx) if pkg else "FGO"
        tail = "等游戏起来再开始任务" if m.get("autostart", True) else "只启动界面"
        return ("%s · %s · %s" % (head, name, tail)) if name else ("%s · %s" % (head, tail))

    # ---------- 绘制 ----------
    def paint(self, target):
        frame_started = time.monotonic()
        rc = wt.RECT()
        user32.GetClientRect(self.hwnd, ctypes.byref(rc))
        w, h = rc.right, rc.bottom
        cached = self._animation_scene
        if ((self._transition or self._modal_transition) and cached
                and self._animation_generation == self._visual_generation
                and (cached.width,cached.height) == (w,h)):
            self.present_scene(target,cached.dc,w,h)
            if DEBUG_TIMING:
                log_line("frame(anim): present %.0f ms, %dx%d"
                         % ((time.monotonic() - frame_started) * 1000, w, h))
            return
        # hover 局部刷新：只有鼠标悬停状态在变，场景其余部分和上一帧逐像素相同。
        # 这时只重算变化的矩形，整帧合成（~175ms）省掉，动画才跟得上手。
        patch = None
        hp = getattr(self, '_hover_patch', None)
        if (hp and getattr(self, '_hover_patch_serial', -1) == self._paint_serial
                and not self._transition and not self._modal_transition
                and not self.prompt and not self.exepick
                and self.frame_effect in ('mica', 'tabbed', 'acrylic')
                and self._hover_sig == self._paint_sig()):
            # 最后那个指纹比较是关键：排补丁之后又滚了页/改了状态的话，
            # 只重画鼠标那一块会把整屏其余部分留在旧内容上（见 _paint_sig）
            patch = hp
        self._hover_patch = None
        self._hover_sig = None
        self._patch_serial_seen = self._paint_serial
        # 冻结动画时钟：这一帧里所有 hover 浓度都以帧首为基准（见 hover_amount）
        self._frame_t = frame_started

        render_started = time.monotonic()
        mem = gdi32.CreateCompatibleDC(target)
        bmp = gdi32.CreateCompatibleBitmap(target, w, h)
        old_bmp = gdi32.SelectObject(mem, bmp)

        self._paint_dc = mem
        self._paint_w, self._paint_h = w, h
        self._text_ops = []
        self._patch_clip = list(patch) if patch else None
        # 走补丁时场景只有那几块会被读走，干脆把画笔也裁到那几块，
        # GDI 少画一大片（整帧 25ms → 5ms）。前提是整帧缓存确实对得上，
        # 否则 patch 会退回整帧合成，读到被裁过的场景就花了。
        prepared = self._compositor.prepared
        if self._patch_clip and prepared and (prepared.width, prepared.height) == (w, h):
            self._apply_patch_clip(mem)
        else:
            self._patch_clip = None

        bg = gdi32.CreateSolidBrush(C["bg"])
        full = wt.RECT(0, 0, w, h)
        user32.FillRect(mem, ctypes.byref(full), bg)
        gdi32.DeleteObject(bg)

        material = self.frame_effect in ('mica', 'tabbed', 'acrylic')
        ss = TEXT_SS if material else 1
        layers = getattr(self, '_glass_text_layers', None)
        if layers and (layers[0].width, layers[0].height) != (w * ss, h * ss):
            for layer in layers:
                layer.close()
            layers = None
        self._glass_text_layers = layers
        self._text_ss = ss if layers else 1
        if material:
            from ui_render import DibSurface
            if layers is None:
                # 图层的绘制坐标仍是逻辑像素：按 TEXT_SS 倍渲染，
                # 合成时再 BOX 缩回去 —— 等于给文字做超采样，把 GDI 那 16 级灰度
                # 抗锯齿变成 100 多级（锯齿主要就来自这 16 级）。
                try:
                    self._glass_text_layers = (
                        DibSurface(mem, w * TEXT_SS, h * TEXT_SS),
                        DibSurface(mem, w * TEXT_SS, h * TEXT_SS))
                except OSError:
                    # 2 倍图层比窗口大 4 倍内存，极端情况下（显存/内存吃紧）退回 1 倍，
                    # 宁可少点抗锯齿也不能画不出来
                    self._glass_text_layers = (DibSurface(mem, w, h), DibSurface(mem, w, h))
                    self._text_ss = 1
                else:
                    self._text_ss = TEXT_SS
                layers = self._glass_text_layers
            # 2 倍图层 135MB，每帧整层 clear 要 16ms；局部刷新只擦变化的那几块，
            # 文字绘制也只在那些块里进行（见 text()），否则同一行字会被叠两遍、变粗。
            if patch:
                for rect in patch:
                    self.text_layer_cover(rect)
            else:
                self.text_layer_cover()
        else:
            for layer in layers or ():
                layer.close()
            self._glass_text_layers = None
            self._text_ss = 1
        self.layout(w, h)
        R = self.rects

        self.draw_shell(mem, w, h)
        if self.page == "main":
            self.draw_hero(mem)
            self.text(mem, "任务清单", (self.S(212),self.S(185),self.S(460),self.S(209)),
                      C["text2"], self.font(11, True))
            # 顺序说明：和卡片上的序号角标呼应，省得用户自己数
            _n = len(R.get("rows") or [])
            if _n > 1:
                _hint = "按序号依次执行  1 → %d" % _n
                try:
                    _rounds = self.runner.planned_rounds()
                except Exception:
                    _rounds = None
                if _rounds:
                    _idx = {it["key"]: i + 1 for i, (it, _, _) in
                            enumerate(R.get("rows") or [])}
                    _segs = []
                    for _r in _rounds:
                        _ns = sorted(_idx[k] for k in _r if k in _idx)
                        if _ns:
                            _segs.append(str(_ns[0]) if len(_ns) == 1
                                         else "%d-%d" % (_ns[0], _ns[-1]))
                    if _segs:
                        _hint = "分 %d 轮执行 · %s（每轮跑完再开下一轮）" % (
                            len(_rounds), " / ".join(_segs))
                self.text(mem, _hint,
                          (self.S(288), self.S(186), self.S(720), self.S(209)),
                          C["muted"], self.font(9.5),
                          DT_LEFT | DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS
                          | DT_NOPREFIX)
        if self.page not in ("main", "tasks"):
            cr = R["card"]
            self.fill_round(mem, (cr[0], cr[1] + self.S(3), cr[2], cr[3] + self.S(3)),
                            14, rgb("#E6E9F4"))
            self.fill_round(mem, cr, 14, C["card"], C["border"])
            self.fill_round(mem, (cr[0] + self.S(20), cr[1], cr[0] + self.S(64), cr[1] + self.S(3)),
                            1.5, C["accent"])
        if self.page == "tasks":
            self.draw_task_page(mem)
        elif self.page == "about":
            clip=gdi32.SaveDC(mem)
            card=R["card"]
            gdi32.IntersectClipRect(mem,card[0],card[1]+self.S(6),card[2],card[3]-self.S(4))
            self.draw_about(mem, card)
            gdi32.RestoreDC(mem,clip)
            if self._scroll_max:
                self.draw_scrollbar(mem,card,card[1]+self.S(6),card[3]-self.S(6),self.scroll,self._scroll_max)
        else:
            rows = R["rows"]
            # 内容能滚动时，超出卡片的部分必须裁掉，否则会画到按钮/日志区上
            scrolling = self._scroll_max > 0
            _dc = 0
            if scrolling:
                _dc = gdi32.SaveDC(mem)
                card = R["card"]
                gdi32.IntersectClipRect(mem, card[0], card[1], card[2], card[3])
            for i, (item, y, rh) in enumerate(rows):
                if self.page == "main":
                    self.draw_task_tile(mem, item, R["tiles"][item["key"]], i + 1)
                else:
                    self.draw_row(mem, item, y, R["card"][0], R["card"][2], rh)
                if self.page != "main" and i < len(rows) - 1:
                    self.hline(mem, R["card"][0] + self.S(22), R["card"][2] - self.S(22),
                               y + rh - self.S(3), C["line"])
            if scrolling:
                gdi32.RestoreDC(mem, _dc)
                self.draw_scrollbar(mem, R["card"], R["card"][1] + self.S(6),
                                    R["card"][3] - self.S(6), self.scroll,
                                    self._scroll_max)

        if self.page == "main":
            self.draw_shortcuts(mem)
        self.draw_buttons(mem)
        if self.page != "about":          # 关于页占满整块，没有日志区
            self.draw_log(mem, R["logcard"])
        _sb = R["statusbar"]
        _hint = self.upd_hint()
        if _hint:
            # 右边那句话是可点的：左边状态文字让出一半，免得两行叠在一起
            self.text(mem, self.status,
                      (_sb[0], _sb[1], _sb[0] + (_sb[2] - _sb[0]) // 2, _sb[3]),
                      C["muted"], self.font(11),
                      DT_LEFT | DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS
                      | DT_NOPREFIX)
            self.text(mem, _hint, _sb, C["accent"], self.font(11, True),
                      DT_RIGHT | DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX)
        else:
            self.text(mem, self.status, _sb, C["muted"], self.font(11))

        if self.prompt:                     # 模态询问要盖在一切之上
            self.draw_prompt(mem, w, h)
        if self.exepick:                   # 「选 exe」卡片也在最上层
            self.draw_exe_picker(mem, w, h)

        # GDI+ 有内部批处理：不在这里收尾，最后画的圆角可能还没落到位图上，
        # 后面 BitBlt 出去的画面就会缺一块
        self._gp_release()

        render_elapsed = time.monotonic() - render_started
        if self._transition:
            old, started, direction = self._transition
            self._transition = (old, started + render_elapsed, direction)
        if self._modal_transition:
            old, started, opening, dialog = self._modal_transition
            self._modal_transition = (old, started + render_elapsed, opening, dialog)
        if patch:
            self.present_scene(target, mem, w, h, patch=patch)
        else:
            rects, text_rects = self._decide_patch(mem, w, h)
            if rects == []:
                # 一个像素都没变：不重算，但仍然要提交一次（窗口被遮挡后重画要靠它）
                self.present_scene(target, mem, w, h, patch=[])
            elif rects:
                self.present_scene(target, mem, w, h, patch=rects, text_rects=text_rects)
            else:
                self.present_scene(target, mem, w, h)
        self._patch_clip = None
        self._settle_hover_tint()
        self._frame_t = None
        self._paint_serial += 1
        if DEBUG_TIMING:
            log_line("frame: gdi %.0f ms, present %.0f ms, %dx%d%s"
                     % (render_elapsed * 1000,
                        (time.monotonic() - render_started - render_elapsed) * 1000,
                        w, h, " patch=%d" % len(patch) if patch else ""))
        gdi32.SelectObject(mem, old_bmp)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)

    # ---------- 「选 exe」卡片 ----------
    def open_exe_picker(self, title, items, on_ok):
        """弹出「从候选 exe 里挑一个」的卡片

        系统自带的"打开文件"框在这台机器上用不了（GetOpenFileNameW 报错 87，
        IFileDialog 链路太长且没法可靠验证），所以自绘一张卡片。
        候选来自用户刚选的文件夹 —— 列的是该目录下的 exe。
        """
        self.exepick = {
            "title": title,
            "items": list(items),
            "sel": 0,
            "on_ok": on_ok,
        }
        user32.InvalidateRect(self.hwnd, None, False)

    def close_exe_picker(self, ok):
        """关掉卡片；ok=True 时把选中的路径交给 on_ok"""
        st = self.exepick
        self.exepick = None
        if st and ok:
            try:
                st["on_ok"](st["items"][st["sel"]])
            except Exception:
                log_line("选择 exe 时出错：\n" + traceback.format_exc())
        user32.InvalidateRect(self.hwnd, None, False)

    def draw_exe_picker(self, hdc, w, h):
        """画「选 exe」卡片：标题 + 候选列表 + 确定/取消"""
        S = self.S
        st = self.exepick
        if not st:
            return
        R = self.rects
        card = R.get("expick")
        if not card:
            return

        mask = gdi32.CreateSolidBrush(rgb("#E7ECF3"))
        user32.FillRect(hdc, ctypes.byref(wt.RECT(0, 0, w, h)), mask)
        gdi32.DeleteObject(mask)
        self.text_layer_cover()          # 同上：遮罩也要擦掉文字层里的旧字

        self.fill_round(hdc, (card[0] + S(1), card[1] + S(4),
                              card[2] + S(1), card[3] + S(4)),
                        16, rgb("#DCE2EC"))
        self.fill_round(hdc, card, 16, C["card"], C["border"], 1.2)

        x1 = card[0] + S(26)
        x2 = card[2] - S(26)
        y1 = card[1]

        self.text(hdc, st["title"], (x1, y1 + S(16), x2, y1 + S(42)),
                  C["text"], self.font(14.5, True))
        self.text(hdc, "点一行选中它，再点「确定」；也可以双击那一行直接选。",
                  (x1, y1 + S(44), x2, y1 + S(64)), C["muted"], self.font(10.5))

        # 候选列表
        top = y1 + S(72)
        bot = card[3] - S(66)
        self.fill_round(hdc, (x1, top, x2, bot), 8, C["iconbg"])
        items = st["items"]
        lh = S(26)
        maxn = max(1, int((bot - top - S(8)) // lh))
        sel = st["sel"]
        first = max(0, min(sel - maxn // 2, len(items) - maxn))
        if len(items) <= maxn:
            first = 0
        for k in range(min(maxn, len(items))):
            idx = first + k
            path = items[idx]
            iy = top + S(4) + k * lh
            if idx == sel:
                self.fill_round(hdc, (x1 + S(4), iy, x2 - S(4), iy + lh - S(2)),
                                5, C["accent_l"])
            label = os.path.basename(path)
            self.text(hdc, label, (x1 + S(12), iy, x2 - S(12), iy + lh - S(2)),
                      C["text"] if idx == sel else C["text2"], self.font(11))
        if len(items) > maxn:
            self.text(hdc, "… 共 %d 个，用滚轮上下翻" % len(items),
                      (x1 + S(12), bot - S(20), x2 - S(12), bot - S(4)),
                      C["muted"], self.font(9.5))

        # 确定 / 取消
        bw, bh, gap = S(96), S(34), S(12)
        bx = x2 - bw * 2 - gap
        by = card[3] - S(50)
        for key, label, primary in (("expick_ok", "确定", True),
                                    ("expick_cancel", "取消", False)):
            r = R.get(key)
            if not r:
                continue
            hot = self.hover == key
            if primary:
                bg = C["accent_d"] if hot else C["accent"]
                col = rgb("#FFFFFF")
            else:
                bg = C["ghost_bg_h"] if hot else C["ghost_bg"]
                col = C["text2"]
            self.fill_round(hdc, r, 9, bg, C["accent"] if primary else C["border"], 1.1)
            self.text(hdc, label, r, col, self.font(12, True),
                      DT_CENTER | DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX)

    # 设置页每一行的「文字块」高度（逻辑像素）= 标题带 + 副标题带。
    # 固定成一块再在行内垂直居中：这样行高不一样时文字间距也一致，
    # 也不会因为行高一小两行字就叠在一起。
    SET_TEXT_BLOCK = 30
    SET_TITLE_H = 17

    def draw_setting_row(self, hdc, item, y, cx1, cx2, rh=None):
        """设置页的一行：左边图标+标题+当前值，右边一个按钮（「选择」或可切换的 chip）

        坐标一律按逻辑像素排版，最后统一乘 DPI 系数。
        （之前这里拿物理行高又套了一次 S()，图标和按钮整体被推到副标题那一行，
          跟标题对不齐 —— 就是那个「图标和文字错位」的 bug。）
        """
        S = self.S
        kk = max(0.01, self.dpi / 96.0)
        key = item["key"]
        is_cfg = key == "config"
        btn_w = 180
        # 进来的全是物理像素，先换算成逻辑像素统一排版
        y = y / kk
        cx1 = cx1 / kk
        cx2 = cx2 / kk
        if rh is None:
            rh = getattr(self, "row_h_logical", 58)
        else:
            rh = rh / kk

        # ---- 分组标题行：整行就是标题，没有图标也没有按钮 ----
        if key.startswith("sec:"):
            self.fill_round(hdc, (S(cx1 + 16), S(y + 1), S(cx2 - 16), S(y + rh - 3)),
                            7, C["accent_l"])
            self.text(hdc, item["title"],
                      (S(cx1 + 28), S(y + 2), S(cx2 - 28), S(y + rh - 4)),
                      C["accent"], self.font(12, True),
                      DT_LEFT | DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX)
            return

        self.row_highlight(hdc, "set:" + key,
                           (S(cx1 + 8), S(y), S(cx2 - 8), S(y + rh - 3)))

        # 文字块：标题带 + 副标题带，整体在行内垂直居中
        blk = min(self.SET_TEXT_BLOCK, rh)
        top = y + (rh - blk) / 2.0
        th = self.SET_TITLE_H if blk >= self.SET_TITLE_H else blk

        # 左侧图标：跟「标题」这一行的中线对齐（不是跟整块居中），
        # 才会跟标题看起来在同一行上。行高不够放不下就自动缩小。
        isz = min(28, max(18, rh - 10))
        ix = cx1 + 20
        iy = y + (rh - isz) / 2.0
        self.fill_round(hdc, (S(ix), S(iy), S(ix + isz), S(iy + isz)), 8, C["iconbg"])
        if not draw_icon(hdc, item.get("icon"), S(ix), S(iy), S(isz)):
            ch = (item.get("title") or "?")[:1]
            self.text(hdc, ch, (S(ix), S(iy), S(ix + isz), S(iy + isz)), C["muted"],
                      self.font(11.5, True),
                      DT_CENTER | DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX)

        tx1 = ix + isz + 14
        tx2 = cx2 - btn_w - 26

        self.text(hdc, item["title"], (S(tx1), S(top), S(tx2), S(top + th)),
                  C["text"], self.font(12, True))
        self.text(hdc, item["sub"], (S(tx1), S(top + th), S(tx2), S(top + blk)),
                  C["muted"], self.font(9.5),
                  DT_LEFT | DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS | DT_NOPREFIX)

        bx2 = cx2 - 22
        bx1 = bx2 - btn_w
        bh = 34
        by1 = y + (rh-bh)/2.0
        by2 = by1+bh
        hot=self.hover == "set:"+key
        current,action,enabled=self.setting_button(item)
        if not enabled and not action:
            self.text(hdc,current,(S(bx1),S(by1),S(bx2),S(by2)),C["muted"],self.font(9.5),
                      DT_CENTER|DT_SINGLELINE|DT_VCENTER|DT_NOPREFIX)
            return
        danger=item.get("chip")=="删除"
        bg=C["err_bg_h"] if danger and hot else C["err_bg"] if danger else C["accent_l"] if hot else C["ghost_bg"]
        self.fill_round(hdc,(S(bx1),S(by1),S(bx2),S(by2)),8,bg,C["border"])
        self.text(hdc,current,(S(bx1+5),S(by1+2),S(bx2-5),S(by1+16)),C["text2"],self.font(9),
                  DT_CENTER|DT_SINGLELINE|DT_VCENTER|DT_END_ELLIPSIS|DT_NOPREFIX)
        self.text(hdc,action,(S(bx1+5),S(by1+16),S(bx2-5),S(by2-1)),
                  C["muted"] if not enabled else C["err"] if danger else C["accent"],self.font(9.5,True),
                  DT_CENTER|DT_SINGLELINE|DT_VCENTER|DT_END_ELLIPSIS|DT_NOPREFIX)

    def draw_row(self, hdc, item, y, cx1, cx2, rh=None):
        if self.sub_page:
            self.draw_setting_row(hdc, item, y, cx1, cx2, rh)
            return
        key = item["key"]
        state, detail = self.steps.get(key, ("idle", ""))
        if key.startswith("vm"):
            checked = self.chk.get(int(item["index"]), True)
        elif key.startswith("custom:"):
            checked = self.chk_custom.get(key[7:], True)
        elif key == "maa":
            checked = self.maa_on
        elif key == "maaend":
            checked = self.maaend_on
        elif key == "okww":
            checked = self.okww_on
        else:
            checked = self.maafgo_on

        S = self.S
        self.row_highlight(hdc, "chk:" + key,
                           (cx1 + S(8), y, cx2 - S(8), y + S(55)))
        # 左侧图标（28 逻辑像素），行高 58，垂直居中
        isz = S(28)
        ix = cx1 + S(20)
        iy = y + (S(58) - isz) // 2
        self.fill_round(hdc, (ix, iy, ix + isz, iy + isz), 9, C["iconbg"])
        if not draw_icon(hdc, item.get("icon"), ix, iy, isz):
            ch = (item.get("title") or "?")[:1]
            self.text(hdc, ch, (ix, iy, ix + isz, iy + isz), C["muted"],
                      self.font(12, True),
                      DT_CENTER | DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX)

        bx, by, bs = ix + isz + S(13), y + S(20), S(19)
        if checked:
            self.fill_round(hdc, (bx, by, bx + bs, by + bs), 5, C["accent"])
            self.check_mark(hdc, bx + S(5), by + S(10), rgb("#FFFFFF"))
        else:
            self.fill_round(hdc, (bx, by, bx + bs, by + bs), 5, C["card"], C["border"], 1.2)

        tx = bx + bs + S(13)
        self.text(hdc, item["title"], (tx, y + S(8), cx2 - S(180), y + S(32)),
                  C["text"] if checked else C["muted"], self.font(13, True))
        self.text(hdc, item["sub"], (tx, y + S(30), cx2 - S(180), y + S(52)),
                  C["muted"], self.font(11))

        label = {"idle": "待启动", "run": "进行中", "ok": "完成", "err": "失败"}[state]
        if detail:
            label = detail
        color = {"idle": C["muted"], "run": C["run"], "ok": C["ok"], "err": C["err"]}[state]
        dotc = {"idle": C["idle"], "run": C["run"], "ok": C["ok"], "err": C["err"]}[state]
        self.text(hdc, label, (cx2 - S(220), y + S(18), cx2 - S(40), y + S(42)), color,
                  self.font(11.5, state != "idle"),
                  DT_RIGHT | DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX)
        radius = 4.5
        if state == "run" and self.motion_enabled():
            import math
            radius += 1.2 * (0.5 + 0.5 * math.sin(time.monotonic() * 4))
        self.dot(hdc, cx2 - S(26), y + S(30), radius, dotc)

    def draw_shortcuts(self, hdc):
        """标题右侧的一键开关：全选"""
        R = self.rects
        S = self.S
        for key, label, on in (("all", "全选", self.all_checked()),):
            r = R.get(key)
            if not r:
                continue
            hot = self.hover == key
            bg = C["accent_l"] if on else (C["ghost_bg_h"] if hot else C["ghost_bg"])
            self.fill_round(hdc, r, 13, bg, C["accent"] if on else C["border"], 1.2)

            bs = S(11)
            bx = r[0] + S(10)
            by = (r[1] + r[3]) // 2 - bs // 2
            if on:
                self.fill_round(hdc, (bx, by, bx + bs, by + bs), 3, C["accent"])
                self.check_mark(hdc, bx + S(1.5), by + S(6), rgb("#FFFFFF"))
            else:
                self.fill_round(hdc, (bx, by, bx + bs, by + bs), 3,
                                C["card"], C["border"], 1.1)

            self.text(hdc, label, (bx + bs + S(6), r[1], r[2] - S(8), r[3]),
                      C["accent"] if on else C["text2"], self.font(11.5, on),
                      DT_LEFT | DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX)

    def draw_prompt(self, hdc, w, h):
        """开机询问卡片：要不要只跑「一天要清两次体力」的手游日常

        GDI 没有真正的半透明，铺一层比背景略深的实色当遮罩，
        视觉上就是"模态弹窗盖住了主界面"。
        """
        S = self.S
        R = self.rects
        card = R.get("prompt")
        if not card:
            return

        mask = gdi32.CreateSolidBrush(rgb("#E7ECF3"))
        user32.FillRect(hdc, ctypes.byref(wt.RECT(0, 0, w, h)), mask)
        gdi32.DeleteObject(mask)
        self.text_layer_cover()          # 材质模式：遮罩要连文字层一起擦，否则露出后面的字

        self.fill_round(hdc, (card[0] + S(1), card[1] + S(4),
                              card[2] + S(1), card[3] + S(4)),
                        16, rgb("#DCE2EC"))
        self.fill_round(hdc, card, 16, C["card"], C["border"], 1.2)

        x1 = card[0] + S(26)
        x2 = card[2] - S(26)
        y1 = card[1]

        # 右上角：剩余秒数
        left = int(self.prompt.get("left", 0))
        tw = S(48)
        tr = (card[2] - S(22) - tw, y1 + S(18), card[2] - S(22), y1 + S(42))
        self.fill_round(hdc, tr, S(12), C["accent_l"])
        self.text(hdc, "%d 秒" % left, tr, C["accent"], self.font(11, True),
                  DT_CENTER | DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX)

        self.text(hdc, "按上次的勾选全部一键启动吗？",
                  (x1, y1 + S(18), card[2] - S(78), y1 + S(44)),
                  C["text"], self.font(15.5, True))

        self.text(hdc, "夜间清单：%s" % self.night_desc(),
                  (x1, y1 + S(50), x2, y1 + S(70)), C["text2"], self.font(11.5))
        self.text(hdc, "每日需清两次的手游，可在左侧「夜间清单」修改。",
                  (x1, y1 + S(70), x2, y1 + S(90)), C["text2"], self.font(11.5))
        self.text(hdc, "不操作就等 %d 秒，按上次的勾选全部启动" % PROMPT_SECONDS,
                  (x1, y1 + S(92), x2, y1 + S(112)), C["muted"], self.font(10.5))

        for key, label, primary in (("prompt_all", "是，立即全部启动", True),
                                    ("prompt_night", "只启动今晚的手游日常", False),
                                    ("prompt_cancel", "取消启动", False)):
            r = R.get(key)
            if not r:
                continue
            hot = self.hover == key
            if primary:
                bg = C["accent_d"] if hot else C["accent"]
                self.fill_round(hdc, r, S(10), bg, C["accent"], 1.0)
                col = rgb("#FFFFFF")
            else:
                bg = C["ghost_bg_h"] if hot else C["ghost_bg"]
                self.fill_round(hdc, r, S(10), bg, C["border"], 1.1)
                col = C["text2"]
            self.text(hdc, label, r, col, self.font(12.5, True),
                      DT_CENTER | DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX)

    def draw_buttons(self, hdc):
        if self.page == "main":
            self.draw_main_actions(hdc)
        else:
            r = self.rects["edit"]
            self.fill_round(hdc, r, 10, C["card"], C["border"])
            self.text(hdc, "← 返回设置" if self.page_stack and self.page_stack[-1] == "settings" else "← 返回控制台", r,
                      C["accent"], self.font(12, True),
                      DT_CENTER | DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX)
        return

    def draw_scrollbar(self, hdc, card, top, bot, offset, max_offset):
        """卡片右侧那条细滚动条：只有内容比可视区高时才出现"""
        if max_offset <= 0 or bot - top < self.S(40):
            return
        S = self.S
        x1 = card[2] - S(7)
        x2 = x1 + S(4)
        self.fill_round(hdc, (x1, top, x2, bot), 2, C["line"])
        visible = bot - top
        total = visible + max_offset
        hh = max(S(28), int(visible * visible / max(1, total)))
        y = top + int((visible - hh) * (offset / float(max_offset)))
        self.fill_round(hdc, (x1, y, x2, y + hh), 2, C["muted"])

    def draw_log(self, hdc, rect):
        self.fill_round(hdc, rect, 10, C["logbg"], C["border"])
        l, t, r, b = rect
        S = self.S
        pad = S(14)
        line_h = S(18)
        self.text(hdc, "运行记录", (l+pad,t+S(10),r-pad,t+S(30)), C["text2"], self.font(10.5,True))
        gdi32.SaveDC(hdc)
        gdi32.IntersectClipRect(hdc, l + pad - S(2), t + S(36), r - pad + S(4), b - S(8))
        fnt = self.font(10.5)
        avail = max(1, int((b - t - S(46)) // line_h))
        lines = self.logs[-avail:]
        yy = t + S(36)
        for text, ckey in lines:
            self.text(hdc, text, (l + pad, yy, r - pad, yy + line_h),
                      C.get(ckey, C["text2"]), fnt)
            yy += line_h
        gdi32.RestoreDC(hdc, -1)

    # ---------- 命中 ----------
    def hit(self, x, y):
        R = self.rects
        if self._modal_transition:
            return "modal_transition"
        if not self.prompt and not self.exepick:
            for page, rect in self.nav_rects():
                if rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]:
                    return "nav:" + page
        if self.prompt:
            # 询问卡是模态的：只认卡片上的两个按钮，别的一律吞掉
            for key in ("prompt_all", "prompt_night", "prompt_cancel"):
                r = R.get(key)
                if r and r[0] <= x <= r[2] and r[1] <= y <= r[3]:
                    return key
            return "prompt_mask"
        if self.exepick:
            # 「选 exe」卡片也是模态的
            for key in ("expick_ok", "expick_cancel"):
                r = R.get(key)
                if r and r[0] <= x <= r[2] and r[1] <= y <= r[3]:
                    return key
            for idx, a, b in R.get("expick_rows", []):
                if a <= y <= b:
                    return "expick_row:%d" % idx
            return "expick_mask"
        # 状态栏右侧的「有新版本」提示：整块可点
        r = R.get("upd_hint")
        if r and r[0] <= x <= r[2] and r[1] <= y <= r[3]:
            return "upd_goto"
        # 设置页 / 自定义页 / 关于页里只有「返回」可用，其余按钮是灰的，不参与命中
        keys = (("edit",) if self.page in ("settings", "custom", "night", "about", "tasks")
                else ("start", "cancel", "shutdown", "edit", "night",
                      "all"))
        for key in keys:
            r = R.get(key)
            if r and r[0] <= x <= r[2] and r[1] <= y <= r[3]:
                return key
        # 关于页的链接行：整行都能点，比只点文字好点
        if self.page == "about":
            for k, r in R.items():
                if k.startswith("about_link:") and R["card"][1]+self.S(6) <= y <= R["card"][3]-self.S(4) and r[0] <= x <= r[2] and r[1] <= y <= r[3]:
                    return k
        if self.page == "main":
            card = R.get("card")
            if card and card[1] <= y <= card[3]:
                for key, rect in R.get("tiles", {}).items():
                    if rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]:
                        return "chk:"+key
            return None
        if self.page == "tasks":
            return self.task_page_hit(x,y)
        # 行列表只算卡片可视区里那部分（滚动后上半截可能被挡住了）
        card = R.get("card")
        if card and not (card[0] <= x <= card[2] and card[1] <= y <= card[3]):
            return None
        rh = R.get("row_h", self.S(56))
        prefix = "chk:" if self.page == "main" else "set:"
        for item, ry, rowh in R.get("rows", []):
            if item["key"].startswith("sec:") or item["key"] in R.get("disabled_rows",set()):
                continue                       # 分组标题行不可点
            if ry - 2 <= y <= ry + rowh - 2:
                return prefix + item["key"]
        return None

    def _persist_selection(self):
        """把界面上的勾选写进 config.json —— 这就是"记住上次选择"的实现"""
        for i, on in self.chk.items():
            for inst in self.cfg.get("instances", []):
                if int(inst["index"]) == i:
                    inst["enabled"] = bool(on)
        self.cfg["maaend"]["enabled"] = self.maaend_on
        self.cfg["maa"]["enabled"] = self.maa_on
        self.cfg["maafgo"]["enabled"] = self.maafgo_on
        self.cfg["okww"]["enabled"] = self.okww_on
        for it in self.cfg.get("custom_items", []) or []:
            cid = it.get("id")
            if cid in self.chk_custom:
                it["enabled"] = bool(self.chk_custom[cid])
        self.cfg["last_selection_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        save_config(self.cfg)

    def selection_summary(self):
        """当前勾选了哪几项，一句话说清（用在日志和状态栏）"""
        hid = self.hidden()
        picked = []
        total = 0
        if "maaend" not in hid:
            total += 1
            if self.maaend_on:
                picked.append("MaaEnd")
        for inst in self.cfg.get("instances", []):
            i = int(inst["index"])
            if ("vm%d" % i) in hid:
                continue
            total += 1
            if self.chk.get(i, True):
                picked.append("实例%d" % i)
        for key, on, label in (("maa", self.maa_on, "MAA"),
                               ("maafgo", self.maafgo_on, "MaaFgo"),
                               ("okww", self.okww_on, "ok-ww")):
            if key in hid:
                continue
            total += 1
            if on:
                picked.append(label)
        for it in self.cfg.get("custom_items", []) or []:
            cid = it.get("id")
            if ("custom:%s" % cid) in hid:
                continue
            total += 1
            if self.chk_custom.get(cid, True):
                picked.append(it.get("name") or "自定义")
        if total and len(picked) == total:
            return "全部 %d 项" % total
        if not picked:
            return "一项都没勾"
        return "%d/%d 项：%s" % (len(picked), total, "、".join(picked))

    # ---------- 快捷开关：全选 / 开机询问（夜间启动） ----------
    def _inst_indexes(self):
        return [int(i["index"]) for i in self.cfg.get("instances", [])]

    def all_checked(self):
        idxs = self._inst_indexes()
        return (all(self.chk.get(i) for i in idxs)
                and self.maaend_on and self.maa_on
                and self.maafgo_on and self.okww_on)

    def night_start(self):
        """只跑《今晚的手游日常》—— 开机弹窗的「否」和主界面「夜间启动」共用

        只影响这一轮：`run_only` 交给 Runner 当白名单用，**不动勾选、
        不写 config.json**，下次打开还是原来的选择。
        """
        keys = self.night_keep()
        if not keys:
            self.status = "《今晚的手游日常》里一个项目都没选"
            self.ui_log("「夜间启动」没跑：请在左侧「夜间清单」中"
                        "先勾上要跑的项目。")
            return
        self.run_only = set(keys)
        self.do("start")            # 内部会把 run_only 交给 Runner 再清空
        self.status = "只启动《今晚的手游日常》"
        self.ui_log("《今晚的手游日常》：只启动 %s；其余项本次跳过（勾选未改动）"
                    % "、".join(self._night_label(k) for k in keys))

    def answer_prompt(self, night, all_selected=False):
        """回答开机的「按上次的勾选全部一键启动吗」

        night=True  → 回答"否"：不按上次勾选全跑，只启动《今晚的手游日常》，
                      不改勾选、不写 config.json，下次打开照旧
        night=False → 「取消启动」：这次什么都不启动
        """
        self.prompt = None
        user32.InvalidateRect(self.hwnd, None, False)
        if all_selected:
            self.ui_log("立即按上次的勾选全部一键启动。")
            self.do("start")
            return
        if not night:
            self.status = "已取消：这次不启动任何东西"
            self.ui_log("已取消启动：什么都没开。下次打开还会再问一次。")
            return
        # 和「夜间启动」按钮同一条路
        self.night_start()

    def _tick_prompt(self):
        """开机询问的倒计时：到点就当作"不回答"，按上次的勾选全部启动"""
        if not self.prompt:
            return
        left = int(self.prompt["until"] - time.time() + 0.999)
        if left <= 0:
            self.prompt = None
            self.ui_log("等了 %d 秒没有回答，按上次的勾选全部启动。"
                        % PROMPT_SECONDS)
            self.status = "按上次的勾选全部启动"
            self.do("start")
            return
        if left != self.prompt.get("left"):
            self.prompt["left"] = left
            user32.InvalidateRect(self.hwnd, None, False)

    def _apply_checks(self, vm_on, maaend, maa, maafgo, okww):
        """一次性把 5 组开关写进内存和 config.json"""
        for i in self._inst_indexes():
            self.chk[i] = vm_on
            for inst in self.cfg.get("instances", []):
                if int(inst["index"]) == i:
                    inst["enabled"] = vm_on
        self.maaend_on = maaend
        self.cfg["maaend"]["enabled"] = maaend
        self.maa_on = maa
        self.cfg["maa"]["enabled"] = maa
        self.maafgo_on = maafgo
        self.cfg["maafgo"]["enabled"] = maafgo
        self.okww_on = okww
        self.cfg["okww"]["enabled"] = okww
        self._persist_selection()

    def toggle_all(self):
        on = not self.all_checked()
        self._apply_checks(on, on, on, on, on)
        n = len(self._inst_indexes()) + 4
        if on:
            self.ui_log("已全选：%d 项全部勾上" % n)
            self.status = "已全选（%d 项）" % n
        else:
            self.ui_log("已全部取消：%d 项都没勾，点「一键启动」将什么都不做" % n)
            self.status = "已全部取消"

    def toggle(self, key):
        if not key.startswith("chk:"):
            return
        k = key[4:]
        if k.startswith("vm"):
            idx = int(k[2:])
            self.chk[idx] = not self.chk.get(idx, True)
            for inst in self.cfg.get("instances", []):
                if int(inst["index"]) == idx:
                    inst["enabled"] = self.chk[idx]
        elif k == "maaend":
            self.maaend_on = not self.maaend_on
            self.cfg["maaend"]["enabled"] = self.maaend_on
        elif k == "maa":
            self.maa_on = not self.maa_on
            self.cfg["maa"]["enabled"] = self.maa_on
        elif k == "maafgo":
            self.maafgo_on = not self.maafgo_on
            self.cfg["maafgo"]["enabled"] = self.maafgo_on
        elif k == "okww":
            self.okww_on = not self.okww_on
            self.cfg["okww"]["enabled"] = self.okww_on
        elif k.startswith("custom:"):
            cid = k[7:]
            self.chk_custom[cid] = not self.chk_custom.get(cid, True)
            for it in self.cfg.get("custom_items", []) or []:
                if it.get("id") == cid:
                    it["enabled"] = self.chk_custom[cid]
        self._persist_selection()

    def cycle_setting(self, kind):
        """设置页那三个"点一下就换"的选项：实例号 / FGO 版本"""
        idxs = self._inst_indexes() or [0]
        if kind in ("maa_instance", "fgo_instance"):
            sec = "maa" if kind == "maa_instance" else "maafgo"
            field = "instance_index" if kind == "maa_instance" else "emulator_index"
            cur = int(self.cfg.get(sec, {}).get(field, idxs[0]))
            nxt = idxs[(idxs.index(cur) + 1) % len(idxs)] if cur in idxs else idxs[0]
            self.cfg.setdefault(sec, {})[field] = nxt
            label = "MAA" if kind == "maa_instance" else "MaaFgo"
            msg = "%s 改为连接实例 %d" % (label, nxt)
            if len(idxs) == 1:
                msg += "（MuMu 里只有这一个实例；要分开两台就在 MuMu 里新建实例）"
        elif kind == "fgo_ver":
            cur = (self.cfg.get("maafgo", {}) or {}).get("game_package", "")
            pkgs = [p for _n, p in FGO_PACKAGES]
            nxt = pkgs[(pkgs.index(cur) + 1) % len(pkgs)] if cur in pkgs else pkgs[0]
            self.cfg.setdefault("maafgo", {})["game_package"] = nxt
            name = next((n for n, p in FGO_PACKAGES if p == nxt), nxt)
            msg = "FGO 版本改为 %s（%s）" % (name, nxt)
            msg += " —— 别的服在 config.json 改 maafgo.game_package"
        else:
            return
        save_config(self.cfg)
        self.ui_log(msg)
        self.status = msg

    # ---------- 自定义实例 / 主界面增删 / 夜间项目 ----------
    def add_custom(self):
        """加一个自定义实例：先选脚本所在的文件夹 → 挑 exe，再选游戏文件夹 → 挑 exe"""
        items = self.cfg.setdefault("custom_items", [])
        if len(items) >= MAX_CUSTOM:
            msg = ("自定义实例最多 %d 个（再多主界面就挤不下了），先删一个再加"
                   % MAX_CUSTOM)
            self.ui_log(msg)
            self.status = msg
            user32.InvalidateRect(self.hwnd, None, False)
            return
        self._cus_state = {"script": "", "game": ""}
        self.pick_exe_step("第 1 步：选脚本 exe", "script")

    def pick_exe_step(self, title, which):
        """选文件夹 → 列出里面的 exe → 弹卡片让用户挑

        系统的"打开文件"框在这台机器上用不了（GetOpenFileNameW 报错误 87，
        IFileDialog 的 Show 虽能弹出但整条链路没法可靠验证），
        只有 SHBrowseForFolder（选文件夹）实测 100% 可靠。
        所以拆成两步：选文件夹 → 在自绘卡片里挑 exe。
        """
        folder = pick_folder(self.hwnd, title + "（选它所在的文件夹）")
        if not folder:
            self.ui_log("已取消（%s）" % title)
            self.status = "已取消"
            user32.InvalidateRect(self.hwnd, None, False)
            return
        exes = list_exes_in(folder)
        if not exes:
            msg = "「%s」里没有找到 .exe 文件，换个文件夹试试" % folder
            self.ui_log("✗ " + msg)
            self.status = msg
            user32.InvalidateRect(self.hwnd, None, False)
            return
        if len(exes) == 1:
            self.ui_log("「%s」里只有一个 exe，直接选它：%s"
                        % (os.path.basename(folder), os.path.basename(exes[0])))
            self.on_exe_picked(which, exes[0])
            return
        self.ui_log("「%s」里有 %d 个 exe，请挑一个"
                    % (os.path.basename(folder), len(exes)))
        self.open_exe_picker(title, exes,
                             lambda p: self.on_exe_picked(which, p))

    def on_exe_picked(self, which, path):
        st = getattr(self, "_cus_state", None)
        if st is None:
            return
        st[which] = path
        self.ui_log("已选%s：%s"
                    % ("脚本" if which == "script" else "游戏", path))
        if which == "script":
            self.pick_exe_step("第 2 步：选游戏的启动 exe", "game")
        else:
            self.finish_custom(st.get("script", ""), st.get("game", ""))

    def finish_custom(self, script, game):
        if not script:
            self.ui_log("✗ 没选到脚本 exe，放弃添加")
            self.status = "已放弃"
            user32.InvalidateRect(self.hwnd, None, False)
            return
        items = self.cfg.setdefault("custom_items", [])
        name = os.path.splitext(os.path.basename(script))[0]
        cid = "c%d" % int(time.time() * 1000)
        items.append({"id": cid, "name": name, "script": script,
                      "game": game, "enabled": True})
        self.chk_custom[cid] = True
        save_config(self.cfg)
        self.ui_log("已添加自定义实例「%s」：脚本 %s%s"
                    % (name, os.path.basename(script),
                       ("、游戏 " + os.path.basename(game)) if game
                       else "（没选游戏，只开脚本）"))
        self.ui_log("⚠ 这是「未适配」项：启动器只负责把游戏和脚本打开，"
                    "不会帮你点任务、也不检测任务完成 —— "
                    "任务要在脚本自己的界面里点开始。")
        self.status = "已添加：%s" % name
        user32.InvalidateRect(self.hwnd, None, False)

    def _key_label(self, key):
        for k, label in (("maaend", "MaaEnd · 终末地"),
                         ("maa", "MAA · 明日方舟"),
                         ("maafgo", "MaaFgo · FGO"),
                         ("okww", "ok-ww · 鸣潮")):
            if k == key:
                return label
        if key.startswith("vm"):
            return "MuMu 实例 %s" % key[2:]
        if key.startswith("custom:"):
            for it in self.cfg.get("custom_items", []) or []:
                if it.get("id") == key[7:]:
                    return it.get("name") or "自定义"
        return key

    def toggle_hidden(self, key):
        """主界面行的删除 / 恢复（删掉 = 从主界面隐藏，不真删配置）"""
        hid = self.cfg.setdefault("hidden_items", [])
        if key in hid:
            hid.remove(key)
            msg = "已放回主界面：%s" % self._key_label(key)
        else:
            hid.append(key)
            msg = ("已从主界面隐藏：%s（想放回来再到「主界面项目」这一页点「恢复」）"
                   % self._key_label(key))
        save_config(self.cfg)
        self.ui_log(msg)
        self.status = msg
        user32.InvalidateRect(self.hwnd, None, False)

    def restore_default(self):
        """恢复默认主界面：自定义项清空、删掉的行全部放回来"""
        self.cfg["custom_items"] = []
        self.cfg["hidden_items"] = []
        self.chk_custom = {}
        save_config(self.cfg)
        msg = "已恢复默认主界面：自定义项清空、删掉的行全部放回"
        self.ui_log(msg)
        self.status = msg
        user32.InvalidateRect(self.hwnd, None, False)

    def toggle_night(self, key):
        """《今晚的手游日常》勾选/取消"""
        items = self.cfg.setdefault("night_items", ["maa", "maafgo"])
        if key in items:
            items.remove(key)
            msg = "《今晚的手游日常》不再包含 %s" % self._night_label(key)
        else:
            items.append(key)
            msg = "《今晚的手游日常》现在包含 %s" % self._night_label(key)
        save_config(self.cfg)
        self.ui_log(msg)
        self.status = msg
        user32.InvalidateRect(self.hwnd, None, False)

    def restore_night(self):
        self.cfg["night_items"] = ["maa", "maafgo"]
        save_config(self.cfg)
        msg = "《今晚的手游日常》已恢复默认：明日方舟（MAA）+ FGO（MaaFgo）"
        self.ui_log(msg)
        self.status = msg
        user32.InvalidateRect(self.hwnd, None, False)

    # ---------- 自动更新 ----------
    def _tick_update(self):
        """开机 3 秒后悄悄查一次更新；查过就不再自动查（用户还能手动点）"""
        if self._upd_tried or time.time() < self._upd_due:
            return
        self._upd_tried = True
        if not self.cfg.get("check_update_on_launch", True):
            return
        # 自检截图 / 开发调试一律不联网，免得截图里出现"检查中"或者卡住
        if self.no_auto or getattr(self, "no_mutex", False):
            return
        self.upd_check(auto=True)

    def upd_hint(self):
        """状态栏右边那句可点的提示；没有可更新的就返回空串"""
        u = self.upd
        st = u.get("state")
        if st == "available" and u.get("tag"):
            return "发现新版 %s · 点这里更新" % u["tag"]
        if st == "downloading":
            return "正在下载新版 %s（%.0f%%）· 点这里查看" % (u.get("tag"), u.get("pct") or 0)
        if st == "ready":
            return "新版 %s 已下载 · 点这里安装" % u.get("tag")
        return ""

    def upd_text(self):
        """设置页「检查更新」那一行显示什么：(副标题, 右侧按钮文字)"""
        u = self.upd
        st = u.get("state")
        if st == "checking":
            return "正在查询 GitHub…（几秒就好）", "查询中"
        if st == "downloading":
            mb = (u.get("size") or 0) / 1048576.0
            return ("正在下载 %s：%.0f%%%s（别关窗口）"
                    % (u.get("tag"), u.get("pct") or 0,
                       "（共 %.1f MB）" % mb if mb else "")), "下载中"
        if st == "ready":
            return ("新版 %s 已下载好，点右侧安装：程序会关闭、替换后自动重开"
                    % u.get("tag")), "安装"
        if st == "available":
            mb = (u.get("size") or 0) / 1048576.0
            extra = "（约 %.1f MB）" % mb if mb else ""
            when = " · %s 发布" % u["date"] if u.get("date") else ""
            return ("发现新版 %s%s，点右侧下载%s" % (u.get("tag"), when, extra)), "下载"
        if st == "uptodate":
            return "已经是最新（%s）· 点右侧再查一次" % APP_VERSION, "再查"
        if st == "error":
            return "检查失败：%s · 点右侧重试" % (u.get("err") or "未知错误"), "重试"
        return "当前 %s · 点右侧去 GitHub 看看有没有新版" % APP_VERSION, "检查"

    def _upd_state(self, st, info=None):
        """worker 线程回传的状态落到界面（只在 UI 线程跑，由 drain 调用）"""
        info = info or {}
        u = self.upd
        if st in ("available", "uptodate"):
            u.update({"state": st, "tag": info.get("tag") or "",
                      "url": info.get("url") or "", "page": info.get("page") or "",
                      "size": info.get("size") or 0,
                      "asset": info.get("asset") or "",
                      "kind": info.get("kind") or "zip",
                      "date": info.get("published") or "", "pct": 0})
            if st == "available":
                u["page"] = u["page"] or UPDATE_PAGE
                self.ui_log("发现新版 %s（当前 %s）。设置 →「检查更新」可以直接下载安装，"
                            "或者点状态栏右边那句。"
                            % (u["tag"], APP_VERSION))
            else:
                self.ui_log("已经是最新版（%s）。" % APP_VERSION)
        elif st == "downloading":
            u["state"] = "downloading"
            u["pct"] = info.get("pct") or 0
        elif st == "ready":
            u.update({"state": "ready", "pct": 100, "path": info.get("path") or "",
                      "kind": info.get("kind") or u.get("kind") or "zip"})
            self.ui_log("新版 %s 已下载完成。点设置页「安装」，或点状态栏右边那句。"
                        % (u.get("tag") or ""))
        elif st == "error":
            u["state"] = "error"
            u["err"] = info.get("err") or "未知错误"
            self.ui_log("检查更新失败：%s" % u["err"])
        user32.InvalidateRect(self.hwnd, None, False)

    def upd_check(self, auto=False):
        """查 GitHub 最新 Release（后台线程，不弹窗、不阻塞界面）"""
        if self.upd.get("state") in ("checking", "downloading"):
            return
        self.upd["state"] = "checking"
        self.upd["err"] = ""
        user32.InvalidateRect(self.hwnd, None, False)
        if not auto:
            self.ui_log("正在查询 GitHub 上的最新版本…")

        def work():
            try:
                rel = find_latest_release()
                if not rel.get("tag"):
                    raise RuntimeError("没拿到版本号")
                if is_newer(rel["tag"]):
                    self.emit("upd", "available", rel)
                else:
                    self.emit("upd", "uptodate", rel)
            except HttpError as e:
                msg = ("GitHub 限流了，过一会儿再试" if e.code in (403, 429)
                       else "GitHub 返回 %s" % e.code)
                self.emit("upd", "error", {"err": msg})
            except Exception as e:
                self.emit("upd", "error", {"err": _short_net_err(e)})

        threading.Thread(target=work, daemon=True).start()

    def upd_download(self):
        """下载新版：文件夹版下安装程序，单文件版下 zip（后台线程，带进度）"""
        if self.upd.get("state") in ("checking", "downloading"):
            return
        url = self.upd.get("url") or ""
        tag = self.upd.get("tag") or ""
        if not url:
            self.ui_log("这个版本没带可下载的附件，已打开 GitHub 页面让你手动下")
            open_url(self.upd.get("page") or UPDATE_PAGE)
            return
        self.upd["state"] = "downloading"
        self.upd["pct"] = 0
        user32.InvalidateRect(self.hwnd, None, False)
        asset = self.upd.get("asset") or ""
        is_setup = (self.upd.get("kind") == "setup")
        self.ui_log("开始下载 %s（%s）…" % (tag, asset or "发布包"))

        def work():
            try:
                out_dir = UPDATE_TMP if is_setup else UPDATE_DIR
                os.makedirs(out_dir, exist_ok=True)
                if is_setup:
                    path = os.path.join(out_dir, asset or ("setup-%s.exe" % tag))
                else:
                    path = os.path.join(
                        out_dir, asset or ("daily-launcher-%s-windows-x64.zip" % tag))
                last = [-5.0]

                def prog(got, total):
                    if total:
                        pct = got * 100.0 / total
                    else:
                        pct = min(95.0, got * 100.0 / max(1, self.upd.get("size") or 1))
                    if pct - last[0] >= 2:
                        last[0] = pct
                        self.emit("upd", "downloading", {"pct": pct})

                download_file(url, path, prog)
                if is_setup:
                    if os.path.getsize(path) < 1024 * 1024:
                        raise RuntimeError("安装程序只有 %d 字节，像是没下全"
                                           % os.path.getsize(path))
                    exe = path
                else:
                    exe = extract_new_exe(path, UPDATE_DIR)
                self.emit("upd", "ready", {"path": exe, "kind": "setup" if is_setup else "zip"})
            except Exception as e:
                self.emit("upd", "error", {"err": "下载失败：%s" % _short_net_err(e)})

        threading.Thread(target=work, daemon=True).start()

    def upd_apply(self):
        """装更新：文件夹版交给安装程序（静默、原地、保留配置），单文件版还是换 exe"""
        if self.busy:
            self.ui_log("正在跑任务，等这一轮结束再装更新（或者先点「取消启动」）")
            return
        path = self.upd.get("path") or ""
        if not path or not os.path.isfile(path):
            self.ui_log("更新包不见了，请重新下载一次")
            self.upd["state"] = "available"
            user32.InvalidateRect(self.hwnd, None, False)
            return
        if not FROZEN:
            self.ui_log("源码模式不支持自动更新，请手动重新打包")
            return
        tag = self.upd.get("tag") or ""
        self.status = "正在安装更新，马上重开…"
        user32.InvalidateRect(self.hwnd, None, False)
        if self.upd.get("kind") == "setup":
            self.ui_log("正在安装 %s：安装程序会等本窗口退出后铺新文件，"
                        "config.json 原样保留，装完自动重开…" % tag)
            try:
                run_setup_silent(path, wait_pid=os.getpid(), restart=True)
            except Exception as e:
                self.ui_log("启动安装程序失败：%s" % e)
                return
            time.sleep(0.3)
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
            return
        target = os.path.abspath(sys.executable)
        self.ui_log("正在安装 %s：窗口会关闭，替换完成后自动重开…" % tag)
        try:
            subprocess.Popen([path, "--apply-update", target, str(os.getpid())],
                             close_fds=True)
        except Exception as e:
            self.ui_log("启动更新程序失败：%s" % e)
            return
        time.sleep(0.3)
        user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    def upd_click(self):
        """设置页点「检查更新」那一行：按当前状态决定做什么"""
        st = self.upd.get("state")
        if st == "available":
            self.upd_download()
        elif st == "ready":
            self.upd_apply()
        elif st in ("checking", "downloading"):
            return                              # 正在忙，忽略连点
        else:
            self.upd_check()

    def pick_row(self, kind):
        """设置页点了一行：路径类弹文件夹选择框，选项类就地循环切换"""
        # 分轮编排那几行是"进二级页 / 切轮号"，不是选路径。
        # 设置页的点击统一走 pick_row（命中 key 是 set:<kind>），所以必须在这里
        # 先把它们摘出去交给 do()，否则会掉到最后的兜底分支去弹"浏览文件夹"
        # —— v2.18.0 实测：点「启动顺序与轮次」直接弹出选择目录对话框。
        if kind == "pl_enabled" or kind.startswith("pl:"):
            self.do(kind)
            return
        if self.busy:
            return
        if kind == "ui_material":
            choices=["mica","tabbed","acrylic","solid"]
            current=self.cfg.get("ui_material","mica") if self.cfg.get("ui_mica",True) else "solid"
            nxt=choices[(choices.index(current)+1)%len(choices)] if current in choices else "mica"
            self.cfg.update(ui_material=nxt,ui_mica=nxt!="solid")
            save_config(self.cfg)
            self.refresh_effects()
            user32.InvalidateRect(self.hwnd,None,False)
            return
        if kind in ("ui_mica", "ui_motion"):
            self.cfg[kind] = not self.cfg.get(kind, True)
            save_config(self.cfg)
            self.refresh_effects()
            user32.InvalidateRect(self.hwnd, None, False)
            return
        if kind in ("maa_instance", "fgo_instance", "fgo_ver"):
            self.cycle_setting(kind)
            user32.InvalidateRect(self.hwnd, None, False)
            return
        if kind == "custom_page":
            self.page_stack.append("settings")
            self.page = "custom"
            self.status = "二级 · 主界面项目：加自定义实例、删掉不用的行、恢复默认"
            user32.InvalidateRect(self.hwnd, None, False)
            return
        if kind == "night_page":
            self.page_stack.append("settings")
            self.page = "night"
            self.status = "二级 · 《今晚的手游日常》：勾哪些项目算"
            user32.InvalidateRect(self.hwnd, None, False)
            return
        if kind == "task_page":
            self.page_stack.append("settings")
            self.page = "tasks"
            self.status = "二级 · 安排自动任务：启动后自动跑什么"
            user32.InvalidateRect(self.hwnd, None, False)
            return
        if kind.startswith("t_mx:"):
            self.cycle_task_config(kind[5:])
            user32.InvalidateRect(self.hwnd, None, False)
            return
        if kind.startswith("t_flag:"):
            self.toggle_task_flag(kind[7:])
            user32.InvalidateRect(self.hwnd, None, False)
            return
        if kind == "t_okww":
            self.cycle_okww_task()
            user32.InvalidateRect(self.hwnd, None, False)
            return
        if kind == "t_reset":
            self.reset_tasks()
            user32.InvalidateRect(self.hwnd, None, False)
            return
        if kind == "t_hint":
            self.ui_log("这一页改的是「启动后要不要自动开始」，"
                        "以及 MaaEnd / MaaFgo 用哪一套任务配置。"
                        "具体勾哪些子任务，请在各脚本自己的界面里改。")
            return
        if kind == "about_page":
            self.page_stack.append("settings")
            self.page = "about"
            self.status = "二级 · 关于本软件：免费使用、非商业用途"
            user32.InvalidateRect(self.hwnd, None, False)
            return
        if kind == "c_add":
            self.add_custom()
            return
        if kind.startswith("c_del:"):
            self.toggle_hidden(kind[6:])
            return
        if kind == "c_restore":
            self.restore_default()
            return
        if kind.startswith("n_toggle:"):
            self.toggle_night(kind[9:])
            return
        if kind == "n_restore":
            self.restore_night()
            return
        if kind == "update":
            self.upd_click()
            return
        if kind == "config":
            try:
                subprocess.Popen(["notepad.exe", CONFIG_PATH], creationflags=CREATE_NO_WINDOW)
            except Exception as e:
                self.ui_log("打开配置失败：%s" % e)
            return
        titles = {
            "mumu": "选择 MuMu 模拟器安装目录（里面应有 nx_main 文件夹）",
            "maaend": "选择 MaaEnd 所在目录（会自动找 MaaEnd.exe）",
            "maa": "选择 MAA 所在目录（会自动找 MAA.exe）",
            "maafgo": "选择 MaaFgo 所在目录（会自动找 MaaFgo.exe）",
            "okww": "选择 ok-ww.exe 所在目录",
        }
        folder = pick_folder(self.hwnd, titles.get(kind, "选择目录"))
        if not folder:
            self.status = "已取消"
            user32.InvalidateRect(self.hwnd, None, False)
            return
        msg = apply_path_choice(kind, self.cfg, folder)
        save_config(self.cfg)
        self.ui_log(msg)
        self.status = msg
        if kind == "mumu":
            self.ports = {}          # 端口缓存作废，下次重绘重新读
        user32.InvalidateRect(self.hwnd, None, False)

    def do(self, key):
        if key.startswith("task_view:"):
            view = key.split(":",1)[1]
            if view in ("scripts", "rounds") and not self.busy:
                self.task_view = view
                self.scroll = 0
                self._hover_patch = None
                self.finish_transition()
                self.hover = self.pressed = None
                user32.InvalidateRect(self.hwnd, None, False)
            return
        if key.startswith("pl_sum:"):
            return
        if key == "pl_enabled":
            if self.busy:
                return
            pl = self.cfg.setdefault("pipeline", {})
            pl["enabled"] = not bool(pl.get("enabled"))
            if pl["enabled"] and not pl.get("assign"):
                pl["assign"] = self.default_pipeline()
                pl["order"] = [it["key"] for it in self.pipeline_items()]
                self.ui_log("启动编排已开启，先按「终末地 / 模拟器 / 鸣潮」分成 3 轮，"
                            "下面的轮次可以逐项改")
            else:
                self.ui_log("分轮执行 → %s" % ("开" if pl["enabled"] else "关"))
            save_config(self.cfg)
            user32.InvalidateRect(self.hwnd, None, False)
            return
        if key.startswith("pl:"):
            if not self.busy:
                self.choose_pipeline_round(key[3:])
            return
        if key.startswith("nav:"):
            target = key[4:]
            if target in {row[0] for row in self.NAV} and target != self.page and not self.busy:
                self.page_stack = [] if target == "main" else ["main"]
                self.page = target
                self.status = "就绪" if target == "main" else "设置改动会自动保存"
            return
        if key in ("prompt_all", "prompt_night", "prompt_cancel"):
            self.answer_prompt(key == "prompt_night", key == "prompt_all")
            return
        if key == "prompt_mask":       # 点在询问卡外面：什么也不做
            return
        if key == "expick_ok":
            self.close_exe_picker(True)
            return
        if key == "expick_cancel":
            self.close_exe_picker(False)
            return
        if key == "expick_mask":       # 点在卡片外面：什么也不做
            return
        if key.startswith("expick_row:"):
            idx = int(key.split(":")[1])
            if self.exepick:
                self.exepick["sel"] = idx
                user32.InvalidateRect(self.hwnd, None, False)
            return
        if key.startswith("about_link:"):
            # 关于页的链接：http(s) 交给默认浏览器；file: 是配置文件，用记事本打开
            try:
                url = self._about[2][int(key.split(":")[1])][0]
            except Exception:
                url = ""
            if url.startswith("file:"):
                target = url[5:]
                try:
                    subprocess.Popen(["notepad.exe", target], creationflags=CREATE_NO_WINDOW)
                    self.status = "已用记事本打开 config.json"
                except Exception as e:
                    self.ui_log("打开配置失败：%s" % e)
                user32.InvalidateRect(self.hwnd, None, False)
                return
            err = open_url(url)
            if err:
                self.ui_log("打开链接失败：%s（%s）" % (err, url))
            else:
                self.status = "已在浏览器打开：%s" % self._short_url(url)
                self.ui_log("打开链接：%s" % url)
                user32.InvalidateRect(self.hwnd, None, False)
            return
        if key == "upd_goto":
            # 状态栏那句提示：跳到设置页，更新入口位于 ③ 软件更新
            if self.page != "settings":
                self.page_stack.append(self.page)
                self.page = "settings"
                self.status = ("新版 %s 等着装：点「检查更新」那一行右边的按钮"
                               % (self.upd.get("tag") or ""))
                self.ui_log("已跳到设置页：③ 软件更新 →「检查更新」")
            else:
                self.status = self.upd_hint() or self.status
            user32.InvalidateRect(self.hwnd, None, False)
            return
        if key == "start":
            if not self.busy:
                self._persist_selection()      # 点启动前再存一次，确保下次能记住
                self.logs = []
                self.status = "启动中…"
                # 点过「是」就只跑手游那套；其余情况 None = 按勾选跑
                self.runner.only = self.run_only
                self.run_only = None
                threading.Thread(target=self.runner.run, daemon=True).start()
        elif key == "cancel":
            if self.busy:
                self.runner.cancel()
                self.status = "正在取消…"
                user32.InvalidateRect(self.hwnd, None, False)
        elif key == "shutdown":
            if not self.busy:
                threading.Thread(target=self.runner.shutdown_all, daemon=True).start()
        elif key == "night":
            if self.busy:
                return
            self.night_start()
        elif key == "all":
            if self.busy:
                return
            self.toggle_all()
            user32.InvalidateRect(self.hwnd, None, False)
        elif key == "edit":
            if self.busy:
                return
            if self.page == "main":
                # 主界面 → 一级设置页
                self.page_stack.append("main")
                self.page = "settings"
                self.status = "设置：点右侧「选择」换目录，改完立刻生效"
                self.emit("log", "设置页：先在「① 选择各实例的路径」里指路径，"
                                 "再在「② 模拟器实例与游戏版本」里切换。")
            elif self.page == "settings":
                # 一级设置页 → 回主界面
                if self.page_stack and self.page_stack[-1] == "main":
                    self.page_stack.pop()
                self.page = "main"
                self.status = "就绪"
            else:
                # 二级页 → 回一级设置页（不是主界面）
                self.page = self.page_stack.pop() if self.page_stack else "settings"
                self.status = "设置：点右侧「选择」换目录，改完立刻生效"
            user32.InvalidateRect(self.hwnd, None, False)

    # ---------- 窗口过程 ----------
    def wndproc(self, hwnd, msg, wp, lp):
        try:
            if msg == WM_PAINT:
                ps = PAINTSTRUCT()
                hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
                self.paint(hdc)
                user32.EndPaint(hwnd, ctypes.byref(ps))
                return 0
            if msg == WM_ERASEBKGND:
                return 1
            if msg == WM_MOUSEMOVE:
                x = ctypes.c_short(lp & 0xFFFF).value
                y = ctypes.c_short((lp >> 16) & 0xFFFF).value
                h = self.hit(x, y)
                if h != self.hover:
                    self._hover_from = self.hover
                    self._hover_at = time.monotonic()
                    self.hover = h
                    self._mark_hover_patch()
                    if self.motion_enabled():
                        user32.SetTimer(hwnd, 2, 16, None)
                    user32.InvalidateRect(hwnd, None, False)
                return 0
            if msg == WM_LBUTTONDOWN:
                x = ctypes.c_short(lp & 0xFFFF).value
                y = ctypes.c_short((lp >> 16) & 0xFFFF).value
                self.pressed = self.hit(x, y)
                if self._transition and not (self.pressed or "").startswith("nav:"):
                    self.pressed = None
                return 0
            if msg == WM_LBUTTONUP:
                x = ctypes.c_short(lp & 0xFFFF).value
                y = ctypes.c_short((lp >> 16) & 0xFFFF).value
                h = self.hit(x, y)
                if h and h == self.pressed:
                    if h.startswith("chk:"):
                        if not self.busy:
                            self.toggle(h)
                            user32.InvalidateRect(hwnd, None, False)
                    elif h.startswith("set:"):
                        self.pick_row(h[4:])
                        user32.InvalidateRect(hwnd, None, False)
                    else:
                        self.do(h)
                self.pressed = None
                return 0
            if msg == WM_LBUTTONDBLCLK:
                # 双击「选 exe」列表里的某一行 = 直接选中并确认
                x = ctypes.c_short(lp & 0xFFFF).value
                y = ctypes.c_short((lp >> 16) & 0xFFFF).value
                h = self.hit(x, y)
                if h and h.startswith("expick_row:"):
                    self.do(h)
                    self.close_exe_picker(True)
                return 0
            if msg == WM_MOUSEWHEEL:
                # ⚠ 滚轮增量在 **wParam 的高 16 位**；lParam 是鼠标的屏幕坐标
                #   （低 16 位 x、高 16 位 y）。以前误用了 lp，算出来的"增量"
                #   其实是鼠标 y 坐标，永远是正的 —— 于是只能"往上滚"，
                #   停在顶部就再也滚不动，看起来就是滚轮失灵。
                delta = ctypes.c_short((wp >> 16) & 0xFFFF).value
                if not delta:
                    return 0
                # 一格 = 120，触控板/高精度滚轮可能是 30、60 之类的小值
                notches = delta / 120.0
                if not notches:
                    notches = 1.0 if delta > 0 else -1.0
                # 「选 exe」列表用滚轮翻页
                if self.exepick:
                    st = self.exepick
                    n = len(st["items"])
                    if n > 1:
                        mv = 1 if notches > 0 else -1
                        st["sel"] = max(0, min(n - 1, st["sel"] - mv))
                        user32.InvalidateRect(hwnd, None, False)
                    return 0
                # 设置/自定义/夜间/任务页：内容超长时滚轮上下滚
                if self._scroll_max > 0:
                    self.scroll = max(0, min(self._scroll_max,
                                             self.scroll - int(notches * self.S(48))))
                    user32.InvalidateRect(hwnd, None, False)
                return 0
            if msg == WM_SETCURSOR:
                if self.hover:
                    user32.SetCursor(load_cursor(32649))
                    return 1
            if msg in (0x031A, 0x001A, 0x031E):  # theme / system preferences changed
                self.refresh_effects()
                if msg == 0x001A:                # WM_SETTINGCHANGE：任务栏挪位置也走这里
                    self.fit_work_area()
                user32.InvalidateRect(hwnd, None, False)
            if msg == WM_TIMER:
                if wp == 4:
                    if user32.IsIconic(hwnd):
                        self.finish_modal_transition()
                    user32.InvalidateRect(hwnd, None, False)
                    return 0
                if wp == 3:
                    user32.InvalidateRect(hwnd, None, False)
                    return 0
                if wp == 2:
                    self._mark_hover_patch()
                    user32.InvalidateRect(hwnd, None, False)
                    if time.monotonic() - self._hover_at >= 0.18:
                        user32.KillTimer(hwnd, 2)
                    return 0
                if self.busy and self.motion_enabled() and user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
                    user32.InvalidateRect(hwnd, None, False)
                self.drain()
                self._tick_prompt()
                self._tick_update()
                if self._auto_pending and not self.busy and time.time() >= self._auto_at:
                    self._auto_pending = False
                    self.do("start")
                return 0
            if msg == WM_KEYDOWN:
                if (wp == 0x0D and not self.busy and self.page == "main"
                        and not self._transition and not self._modal_transition
                        and not self.prompt and not self.exepick):
                    self.do("start")
                    return 0
            if msg == WM_DESTROY:
                for layer in getattr(self, "_glass_text_layers", ()) or ():
                    layer.close()
                self._glass_text_layers = None
                self.finish_modal_transition()
                self.finish_transition()
                if self._last_scene:
                    self._last_scene.close()
                    self._last_scene = None
                for surface in (self._animation_scene,self._blend_surface):
                    if surface:
                        surface.close()
                self._animation_clock.stop()
                self._compositor.close()
                user32.KillTimer(hwnd, 1)
                user32.KillTimer(hwnd, 2)
                user32.PostQuitMessage(0)
                return 0
        except Exception:
            log_line("wndproc 异常：\n" + traceback.format_exc())
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    # ---------- 图标 ----------
    def apply_icon(self, hwnd):
        """优先用自带的角色图标；打包后直接用 exe 里嵌的那张"""
        cands = []
        if getattr(sys, "frozen", False):
            cands.append(("exe", sys.executable))
        for p in (os.path.join(APP_DIR, "build", "mumu.ico"),
                  os.path.join(APP_DIR, "mumu.ico"),
                  os.path.join(APP_DIR, "源码", "build", "mumu.ico")):
            if os.path.isfile(p):
                cands.append(("ico", p))
                break
        mumu = os.path.join(self.cfg.get("mumu_root", ""), "nx_main", "MuMuNxMain.exe")
        if os.path.isfile(mumu):
            cands.append(("exe", mumu))
        big_px = user32.GetSystemMetrics(11)    # SM_CXICON
        small_px = user32.GetSystemMetrics(49)  # SM_CXSMICON
        for kind, path in cands:
            hb = hs = None
            if kind == "ico":
                hb = user32.LoadImageW(None, path, 1, big_px, big_px, 0x0010)
                hs = user32.LoadImageW(None, path, 1, small_px, small_px, 0x0010)
            else:
                lb, ls = wt.HICON(), wt.HICON()
                if shell32.ExtractIconExW(path, 0, ctypes.byref(lb), ctypes.byref(ls), 1) > 0:
                    hb = lb.value if lb else None
                    hs = ls.value if ls else None
            if hb:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hb)
            if hs:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hs)
            if hb:
                return hb
        return None

    # ---------- 创建 ----------
    def create(self):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                user32.SetProcessDPIAware()
            except Exception:
                pass
        # 取真实 DPI：打包后由 manifest 声明 per-monitor v2，这里只需按 DPI 放大绘制
        dpi = 0
        try:
            dpi = int(user32.GetDpiForSystem())
        except Exception:
            dpi = 0
        if not dpi:
            hdc = user32.GetDC(None)
            dpi = gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
            user32.ReleaseDC(None, hdc)
        self.dpi = float(dpi or 96)

        hInst = kernel32.GetModuleHandleW(None)
        cls = "DailyLauncherWndClass"

        wc = WNDCLASSW()
        self._proc = WNDPROC(self.wndproc)
        wc.style = 0x0002 | 0x0020  # CS_HREDRAW | CS_VREDRAW
        wc.lpfnWndProc = self._proc
        wc.hInstance = hInst
        wc.hbrBackground = gdi32.CreateSolidBrush(C["bg"])
        wc.hCursor = load_cursor(32512)
        wc.lpszClassName = cls
        user32.RegisterClassW(ctypes.byref(wc))

        # --shot 自检不参与单实例保护：否则程序开着时就没法截图验证界面
        if getattr(self, "no_mutex", False):
            ctypes.set_last_error(0)          # 别让上次的 183 残留误判
        else:
            kernel32.CreateMutexW(None, False, "DailyLauncherMutex_v1")
        if ctypes.get_last_error() == 183:
            old = user32.FindWindowW(cls, None)
            if old:
                # 已有实例正常开着：把它提到前面
                user32.ShowWindow(old, 9)
                user32.SetForegroundWindow(old)
                return None

            # 互斥量还在、窗口却找不到 —— 上一次异常退出留下的僵尸进程。
            # 以前这里直接 return None，用户看到的就是"双击没反应"，很难排查。
            exe_name = os.path.basename(sys.executable)
            if getattr(sys, "frozen", False):
                ans = user32.MessageBoxW(
                    None,
                    "检测到上一次的启动器进程还留在后台（没有窗口）。\n\n"
                    "点「是」结束它并重新打开。",
                    APP_NAME, 0x00000004 | 0x00000030)  # YESNO | 警告图标
                if ans != 6:            # IDYES
                    return None
                killed = 0
                for pid, ppid, name in list_processes():
                    if name.lower() == exe_name.lower() and pid != os.getpid():
                        rc, _ = run_hidden(["taskkill", "/F", "/PID", str(pid)], 20)
                        if rc == 0:
                            killed += 1
                if killed:
                    time.sleep(0.6)
                else:
                    user32.MessageBoxW(
                        None,
                        "清除失败（可能那个进程权限更高）。\n\n"
                        "请打开任务管理器，结束所有「一键日常启动器.exe」后再试。",
                        APP_NAME, 0x00000000 | 0x00000030)
                    return None
            else:
                return None

        style = 0x00CF0000 & ~0x00010000 & ~0x00040000  # 去掉最大化/可调边框
        # 设置页现在有 14 行（3 个分组标题 + 11 行内容），比主界面高不少，
        # 窗口要留够高度，否则子页面的日志区会被压扁。
        cw, ch = self.S(960), self.S(780)
        # Fit the work area at high DPI; overflowing task tiles remain scrollable.
        work = wt.RECT()
        user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work), 0)
        if work.right > work.left and work.bottom > work.top:
            cw = min(cw, work.right-work.left-self.S(24))
            ch = min(ch, work.bottom-work.top-self.S(56))
        rect = wt.RECT(0, 0, cw, ch)
        user32.AdjustWindowRectEx(ctypes.byref(rect), style, False, 0)
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        # 必须在**工作区**里居中，不能用整块屏幕：把任务栏挪到顶部之后
        # (GetSystemMetrics 仍报整屏高度)，窗口标题栏就会被任务栏压住，拽都拽不出来。
        if not (work.right > work.left and work.bottom > work.top):
            work = wt.RECT(0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
        x = work.left + max(0, (work.right - work.left - w) // 2)
        y = work.top + max(0, (work.bottom - work.top - h) // 3)
        hwnd = user32.CreateWindowExW(0, cls, APP_NAME, style, x, y, w, h,
                                      None, None, hInst, None)
        if not hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        self.hwnd = hwnd
        self.refresh_effects()

        try:
            self.apply_icon(hwnd)
        except Exception:
            pass

        user32.ShowWindow(hwnd, 5)
        user32.UpdateWindow(hwnd)
        user32.SetTimer(hwnd, 1, 120, None)
        _TMARK["win"] = _boot_time.time()
        if "--timing" in sys.argv:
            # 启动耗时拆解：全部是 epoch 毫秒，外部脚本拿父进程的 spawn 时间就能算
            log_line("TIMING py=%d imp=%d cfg=%d app=%d win=%d"
                     % (_BOOT_T * 1000, _T_IMP * 1000,
                        _TMARK.get("cfg", 0) * 1000,
                        _TMARK.get("app", 0) * 1000,
                        _TMARK.get("win", 0) * 1000))

        # 后台摸一遍 MuMu 里到底有几个实例（不卡界面，读完自己刷新）
        threading.Thread(target=self._discover_instances, daemon=True).start()

        auto = bool(self.cfg.get("auto_start_on_launch", True)) and not self.no_auto
        if self.prev_version and self.prev_version != APP_VERSION:
            # 覆盖 exe 升级上来：路径/勾选全在 config.json 里，原样沿用
            self.emit("log", "已从 %s 升级到 %s：路径、勾选、自定义项都沿用，"
                             "不用重新设置。" % (self.prev_version, APP_VERSION))
        if self.first_run:
            self.emit("log", "还没配置好：已经在设置页了。逐行点右侧「选择」，把 5 个路径指对。")
            self.emit("log", "下面三行是「MAA/MaaFgo 连哪台实例」和「FGO 版本」，点一下就能换。")
            self.emit("log", "都指好之后回主界面点「一键启动」—— 启动前会自动自检，"
                             "哪项没准备好会直接说明原因。")
        elif auto:
            self.emit("log", "「打开即启动」已开启：先问一句要不要只跑手游日常，"
                             "%d 秒不回答就按上次的勾选全部启动。" % PROMPT_SECONDS)
        else:
            self.emit("log", "准备就绪：点「一键启动」，或先点掉不想启动的项。")
        if not self.first_run:
            self.emit("log", "已记住上次的勾选（%s）—— 想改就点对应那一行，改完自动存"
                      % self.selection_summary())
        self.emit("log", "权限：%s" % ("管理员（MuMu 可正常启动）" if is_admin()
                                      else "普通权限（MuMu 会弹 UAC，可能启动失败）"))
        self.emit("log", "路径不对就点「设置」换目录（选文件夹，自动找 exe）。")
        user32.InvalidateRect(hwnd, None, False)
        if auto:
            # 先进「要只跑手游日常吗」询问卡；5 秒不回答就走默认一键启动。
            # 嫌烦可以 config.json 里 night_prompt 设 false，恢复成直接开跑。
            if self.cfg.get("night_prompt", True):
                self.prompt = {"until": time.time() + PROMPT_SECONDS,
                               "left": PROMPT_SECONDS}
            else:
                self._auto_pending = True
                self._auto_at = time.time() + 1.0
        return hwnd

    def _discover_instances(self):
        """后台读一次 MuMu 实际实例数：新用户常常只建了 1 个，
        配置里却躺着 0 和 1，界面得先让人看见这件事。"""
        try:
            if sync_instances(self.cfg, self.ui_log):
                save_config(self.cfg)
                self.emit("sync")
        except Exception:
            log_line("实例发现失败：\n" + traceback.format_exc())

    def run(self):
        hwnd = self.create()
        if not hwnd:
            return 0
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        return 0


# ----------------------------------------------------------------------------
# 调试：整屏截图（--shot 输出路径）
# ----------------------------------------------------------------------------
def screenshot(path, rect=None):
    if path.lower().endswith((".py", ".json", ".exe", ".bat")):
        log_line("拒绝写入 %s（防止覆盖程序文件）" % path)
        return
    hdc_screen = user32.GetDC(None)
    cw = user32.GetSystemMetrics(0)
    ch = user32.GetSystemMetrics(1)
    mem = gdi32.CreateCompatibleDC(hdc_screen)
    bmp = gdi32.CreateCompatibleBitmap(hdc_screen, cw, ch)
    gdi32.SelectObject(mem, bmp)
    gdi32.BitBlt(mem, 0, 0, cw, ch, hdc_screen, 0, 0, 0x00CC0020)
    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.biWidth = cw
    bi.biHeight = -ch
    bi.biPlanes = 1
    bi.biBitCount = 32
    buf = ctypes.create_string_buffer(cw * ch * 4)
    gdi32.GetDIBits(mem, bmp, 0, ch, buf, ctypes.byref(bi), 0)
    import zlib, struct
    data = buf.raw
    row = cw * 4
    x0, y0, ow, oh = 0, 0, cw, ch
    if rect:
        x0, y0, ow, oh = rect
        x0 = max(0, x0)
        y0 = max(0, y0)
        ow = min(ow, cw - x0)
        oh = min(oh, ch - y0)
    raw = bytearray()
    for yy in range(y0, y0 + oh):
        line = data[yy * row + x0 * 4: yy * row + (x0 + ow) * 4]
        raw.append(0)
        for xx in range(0, len(line), 4):
            raw += bytes((line[xx + 2], line[xx + 1], line[xx]))

    def chunk(tag, d):
        return (struct.pack(">I", len(d)) + tag + d
                + struct.pack(">I", zlib.crc32(tag + d) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", ow, oh, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
           + chunk(b"IEND", b""))
    open(path, "wb").write(png)


def main():
    _TMARK["main"] = _boot_time.time()
    args = sys.argv[1:]

    # 更新器模式：新版 exe 被旧进程拉起来替自己换文件。跑完就退，绝不进界面。
    # 必须在最前面处理 —— 否则它会走下面的提权/计划任务逻辑，又开一个窗口。
    if "--apply-update" in args:
        return apply_update_cli(args)

    # 卸载：先清快捷方式/卸载项/计划任务，再交给 cmd 等本进程退出后删目录
    if "--uninstall" in args:
        return uninstall_cli(args)

    # 自检：冻结版里 zipfile 还能不能用（打包时排掉了 bz2/lzma，别把 deflate 也带走了）
    if "--selftest" in args:
        import tempfile
        ok = True
        try:
            import zipfile
            d = tempfile.mkdtemp(prefix="dl_selftest_")
            zp = os.path.join(d, "t.zip")
            with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("a.txt", b"hello launcher" * 100)
            with zipfile.ZipFile(zp) as z:
                got = z.read("a.txt")
            ok = got.startswith(b"hello launcher")
            shutil.rmtree(d, ignore_errors=True)
            msg = "selftest: zipfile deflate %s" % ("OK" if ok else "FAIL(内容不对)")
        except Exception as e:
            msg = "selftest: zipfile FAIL %s: %s" % (type(e).__name__, e)
            ok = False
        for fn in (print, log_line):
            try:
                fn(msg)
            except Exception:
                pass
        return 0 if ok else 1

    # 排障：把 Pillow 在这台机器/这个打包产物里的真实状态写出来（--diag-icon）
    if "--diag-icon" in args:
        _write_icon_diag()
        return 0

    # 命令行查更新（排障 / 自检用）：结果同时写日志，窗口版 exe 也能查
    if "--check-update" in args:
        try:
            rel = find_latest_release()
        except Exception as e:
            msg = "检查更新失败：%s" % _short_net_err(e)
            print(msg)
            log_line(msg)
            return 1
        msg = ("当前 %s，GitHub 最新 %s%s"
               % (APP_VERSION, rel.get("tag") or "?",
                  "" if is_newer(rel.get("tag")) else "（已是最新）"))
        print(msg)
        log_line(msg)
        if rel.get("asset"):
            msg2 = "发布包 %s（%.1f MB）：%s" % (
                rel["asset"], (rel.get("size") or 0) / 1048576.0, rel.get("url"))
            print(msg2)
            log_line(msg2)
        return 0

    shot = None
    if "--shot" in args:
        i = args.index("--shot")
        shot = args[i + 1] if len(args) > i + 1 else os.path.join(APP_DIR, "shot.png")

    # 每次启动都记一行"身份信息"，方便定位 UAC 到底是谁弹的：
    # 进程链里出现 svchost.exe  => 走的是计划任务（已是管理员，不该再弹 UAC）
    # 进程链里出现 explorer.exe => 双击启动（普通权限，必要时才自提权）
    # （onefile 的 exe 会先跑一个引导进程再拉起本体，所以要多追几层）
    try:
        _snap = {pid: (ppid, name) for pid, ppid, name in list_processes()}
        _pid, _chain = os.getpid(), []
        for _ in range(4):
            _n = _snap.get(_pid)
            if not _n:
                break
            _chain.append("%s(%d)" % (_n[1], _pid))
            _pid = _n[0]
    except Exception:
        _chain = []
    log_line("start: pid=%d admin=%s chain=%s args=%s"
             % (os.getpid(), "yes" if is_admin() else "no",
                " -> ".join(_chain) or "?", " ".join(sys.argv[1:]) or "(none)"))
    # 命令行快捷方式：只处理「MuMu模拟器」主窗口，不开界面
    # （必须和 MuMu 同权限才改得动窗口，所以没提权就先提自己一次）
    if "--hide-main" in args or "--show-main" in args:
        want = "--show-main" in args
        if not is_admin() and "--no-elevate" not in args and elevate_self():
            return 0
        set_main_window(want, log_line)
        return 0

    # 默认不再自提权：MuMuNxMain 直接 spawn 就能跑（VMM 服务由 SCM 管理），
    # 每次双击弹 UAC 属于多余。确实需要管理员的场景（清 SYSTEM 僵尸进程、
    # 关模拟器）失败了会在日志里提示，不影响启动。
    # 想要恢复"开机就提权"：config.json 里把 require_admin 设为 true。
    if not shot and "--no-elevate" not in args and not is_admin():
        try:
            _c0 = load_config() or {}
        except Exception:
            _c0 = {}
        want_admin = bool(_c0.get("require_admin", True)) or "--elevate" in args
        # 只有真要管理员才多起一个进程 —— 否则每次双击都白白多花半秒
        if want_admin:
            # 首选：计划任务。它让本程序以最高权限启动且不弹 UAC，
            # 子进程（MuMuNxDevice）随之继承权限，也就不会各自弹 UAC。
            if "--no-task" not in args and trigger_task():
                return 0
            # 次选：免 UAC 没走成，就自己 runas 提权一次。
            # 这样子进程（MuMuNxDevice）会继承权限，不会再各自弹 UAC。
            # 想彻底不弹任何 UAC，先让上面的计划任务生效即可。
            log_line("计划任务免 UAC 未生效，改为自提权（会弹一次 UAC）")
            if elevate_self():
                return 0
            log_line("未获得管理员权限（UAC 被取消），继续以普通权限运行")
        else:
            log_line("未提权运行：MuMu 设备进程可能会自己弹 UAC")

    # 已经是管理员：顺手把计划任务对齐到当前 exe（换目录/改名后免 UAC 会失效）。
    # ⚠ 一定要放后台线程：这一步要起 PowerShell，冷启动时要 2~5 秒，
    #   放在建窗口之前会把"双击到出窗口"的时间拖长 5 秒（v2.14.0 实测 10 秒）。
    if not shot and is_admin() and "--no-task" not in args:
        threading.Thread(target=ensure_task, daemon=True).start()

    # 上次更新留下的 _update 目录 / *.exe.old，开机顺手清掉（删不掉就下次再说）
    threading.Thread(target=cleanup_update_leftovers, daemon=True).start()

    app = App()
    _TMARK["app"] = _boot_time.time()
    if shot or "--no-auto" in args:
        app.no_auto = True
    if shot:
        app.no_mutex = True                # 自检截图不抢单实例锁
    if shot and "--fake-update" in args:
        # 自检用：假装查到了新版，好在截图里看状态栏提示和设置页那一行
        app.upd.update({"state": "available", "tag": "v2.12.0", "pct": 0,
                        "size": 8846816, "date": "2026-11-02",
                        "url": "https://example.com/x.zip", "asset": "x.zip"})
    if shot and "--prompt" in args:
        # 自检用：--shot 会关掉自动启动，这里手动把询问卡摆出来截图
        app.prompt = {"until": time.time() + PROMPT_SECONDS, "left": PROMPT_SECONDS}
    if shot and "--exepick" in args:
        # 自检用：把「选 exe」卡片摆出来截图
        app.exepick = {
            "title": "第 1 步：选脚本 exe",
            "items": [r"D://game//StarRail.exe", r"D://game//ZZZ.exe",
                      r"D://game//GenshinImpact.exe", r"D://game//HSR Launcher.exe",
                      r"D://game//unins000.exe"],
            "sel": 1,
            "on_ok": lambda p: None,
        }
    if "--page" in args:
        # 以前只在 --shot / --test-wheel 下生效；调 hover 这类交互 bug 时
        # 需要让真窗口直接停在某一页，所以这里放开，普通启动也认
        _i = args.index("--page")
        if len(args) > _i + 1:
            _pg = args[_i + 1].lower()
            if _pg.startswith("set"):
                app.page = "settings"          # 自检时截设置页
            elif _pg.startswith("cus"):
                app.page = "custom"            # 自检时截「主界面项目」页
            elif _pg.startswith("nig"):
                app.page = "night"             # 自检时截《今晚的手游日常》页
            elif _pg.startswith("tas"):
                app.page = "tasks"             # 自检时截「安排自动任务」页
                app.page_stack.append("settings")
            elif _pg.startswith("abo"):
                app.page = "about"             # 自检时截「关于」页
                app.page_stack.append("settings")
            elif _pg.startswith("pip"):
                app.page = "tasks"             # 启动编排已并入「安排自动任务」，截这一页
                app.page_stack.append("main")
    if shot and "--scroll" in args:
        # 自检用：把子页面滚到指定位置再截图（看裁剪和滚动条对不对）
        # 必须在 --page 之后设置，否则 layout 换页会把它归零
        try:
            app.scroll = max(0, int(args[args.index("--scroll") + 1]))
        except Exception:
            app.scroll = 0
        app._scroll_page = app.page
    # --test-wheel：往真实窗口发滚轮消息，验证 wndproc 真的收到、方向也对
    # （滚轮增量在 wParam 高 16 位，搞错了就是"只能往上滚"，肉眼看像失灵）
    if "--test-wheel" in args:
        def tw():
            time.sleep(1.2)
            try:
                rc = wt.RECT()
                user32.GetClientRect(app.hwnd, ctypes.byref(rc))
                app.layout(rc.right, rc.bottom)
                app.scroll = 0
                app._scroll_page = app.page

                def spin(delta):
                    user32.SendMessageW(app.hwnd, WM_MOUSEWHEEL,
                                        (delta & 0xFFFF) << 16, 0)
                    return app.scroll

                mx = app._scroll_max
                d1 = spin(-120)          # 向下滚一格
                u1 = spin(120)           # 向上滚一格
                # 内容装得下（max=0）就没什么可滚的，算 SKIP 不算失败
                if mx <= 0:
                    verdict = "SKIP(内容装得下，无需滚动)"
                else:
                    verdict = "OK" if (d1 > 0 and u1 < d1) else "FAIL"
                log_line("wheel test: page=%s max=%d down=%d up=%d => %s"
                         % (app.page, mx, d1, u1, verdict))
                print("wheel test: page=%s max=%d down=%d up=%d => %s"
                      % (app.page, mx, d1, u1, verdict))
            except Exception:
                log_line("wheel test fail: " + traceback.format_exc())
            user32.PostMessageW(app.hwnd, WM_CLOSE, 0, 0)
        threading.Thread(target=tw, daemon=True).start()

    if shot:
        def later():
            time.sleep(1.4)
            try:
                hwnd = app.hwnd
                user32.SetWindowPos(hwnd, wt.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
                user32.SetForegroundWindow(hwnd)
                time.sleep(0.6)
                r = wt.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(r))
                cr = wt.RECT()
                user32.GetClientRect(hwnd, ctypes.byref(cr))
                _R = app.rects
                _c = _R.get("card"); _rows = _R.get("rows") or []
                log_line("layout: page=%s scroll=%s max=%s card=%s rows=%d"
                         % (app.page, app.scroll, app._scroll_max,
                            [round(v) for v in _c] if _c else None, len(_rows)))
                if _rows:
                    u = _rows[0]; d = _rows[-1]
                    log_line("rows: first y=%.0f h=%d (card_t=%.0f) | last y=%.0f h=%d bottom=%.0f (card_b=%.0f)"
                             % (u[1], u[2], _c[1] if _c else -1,
                                d[1], d[2], d[1] + d[2], _c[3] if _c else -1))
                log_line("dpi=%s screen=%sx%s win=(%s,%s,%s,%s) client=%sx%s" % (
                    app.dpi, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1),
                    r.left, r.top, r.right - r.left, r.bottom - r.top,
                    cr.right, cr.bottom))
                screenshot(shot, (r.left, r.top, r.right - r.left, r.bottom - r.top))
                log_line("screenshot -> %s" % shot)
            except Exception:
                log_line("shot fail: " + traceback.format_exc())
            user32.PostMessageW(app.hwnd, WM_CLOSE, 0, 0)
        threading.Thread(target=later, daemon=True).start()

    # --test-ui：自检「增加自定义实例」这条链路
    # 走的是真实代码路径（pick_row → add_custom → pick_folder → 挑 exe 卡片）。
    if "--test-ui" in args:
        def tui():
            for _ in range(80):
                if app.hwnd:
                    break
                time.sleep(0.1)
            time.sleep(0.8)
            try:
                log_line("TEST-UI: 进设置页")
                app.page = "settings"
                app.page_stack.append("main")
                log_line("TEST-UI: 进「主界面项目」页")
                app.pick_row("custom_page")
                log_line("TEST-UI: 点「添加」")
                app.pick_row("c_add")
                log_line("TEST-UI: 已返回（说明文件夹框被关掉了）")
            except Exception:
                log_line("TEST-UI error://n" + traceback.format_exc())
            try:
                user32.PostMessageW(app.hwnd, WM_CLOSE, 0, 0)
            except Exception:
                pass
        threading.Thread(target=tui, daemon=True).start()

    return app.run()


if __name__ == "__main__":
    sys.exit(main())
