# PROGRESS.md — 长任务进度、交付与断点恢复记录

> **当前状态：v2.16.2 已构建、已部署、已验证（本地）**｜最后更新：2026-10-31 16:10（GMT+8）
> **本文件是可恢复的任务记录，不是任务已完成的证明。** 恢复时请按第 9 节核对真实文件与运行结果。

## 0. 维护约定（执行前必读）

- 本文件位于项目根目录 `D:\tools\一键日常启动器\`，是**唯一的进度索引**。每完成一个可独立验收的步骤、或做出影响后续的决策，就更新第 2/3/4/5/6 节。
- 优先级：**保护成果 → 核对真实文件 → 执行 → 验证 → 记录**。只有跑过命令、看过截图，才写「已验证」。
- 术语沿用模板：
  `未开始` / `进行中` / `已保存（本地）` / `已验证`（有命令或截图证据）/ `已持久化`（推到远端或另存并回读过）/ `阻塞`。
- 每轮改动都单独写一份 `DeepSeek交接_*.md`（放在根目录），本文件只写**结论、状态和断点**，不重复实现细节。
- 不要改 `config.json`：它是用户配置（路径、勾选）。构建/验证脚本一律用隔离配置。

### 0.1 版本节奏

| 环节 | 做法 |
|---|---|
| 改代码 | 只动 `源码\*.py`；UI 相关分 `daily_launcher.py`（GDI 绘制/窗口）+ `ui_design.py`（布局/过渡）+ `ui_render.py`（ARGB 合成） |
| 自检 | `python 源码/build/verify_glass.py`、`python 源码/build/verify_navigation.py`（都会开真窗口，跑完自动关） |
| 构建 | `python build_launcher.py --keep-work` → `release\daily-launcher-<ver>-{setup-x64.exe,portable-x64.zip,windows-x64.zip}` |
| 部署 | `release\daily-launcher-<ver>-setup-x64.exe /S "/D=D:\tools\一键日常启动器"`（原地升级，保留 config.json） |
| 记录 | 新增/更新 `DeepSeek交接_*.md` + 本文件 + `README.md` 更新记录 + 工作记忆 `...\.workbuddy\memory\YYYY-MM-DD.md` |

---

## 1. 项目档案

| 字段 | 当前值 |
|---|---|
| 项目名称 | 一键日常启动器（Windows 桌面工具，单文件 + 附带 UI 模块，纯 ctypes/GDI 自绘） |
| 当前版本 | **v2.16.2**（`源码/daily_launcher.py` 的 `APP_VERSION`） |
| 工作区根目录 | `D:\tools\一键日常启动器\`（**同时是安装目录**：根 exe + `_internal` 就是运行中的程序） |
| 运行形态 | 文件夹版（onedir）：`一键日常启动器.exe` + `_internal\`，安装程序装在原地 |
| Python | `C:\Users\Cru77z7M\.workbuddy\binaries\python\versions\3.13.12\python.exe`（构建/验证用；程序本身不依赖 Python） |
| 真机环境 | Windows 11 build 26300，DPI 168（175%），**任务栏在屏幕顶部**，屏幕 2560×1440 |
| 远端仓库 | `github.com/cru77z7m/Mobile-game-daily-task-one-click-launcher`（源码/文档同步；v2.14.1 之后未再推 Release） |
| 备份 | `ui_refresh_backup/v2.14.1|v2.14.2|v2.15.0|v2.15.1|v2.16.0|v2.16.1/`（每份 = 旧 EXE + 完整 `_internal`） |

### 1.1 本轮（v2.16.2）目标与边界

- 目标：① 材质模式下开机询问弹窗上叠着主界面文字；② Win11 任务栏置顶时窗口标题栏被压住；③ 界面文字观感。
- 边界：不改任务执行逻辑、不改 `config.json` 结构、不动更新/安装链路、不重新生成介绍视频。
- 输入资料：`DeepSeek交接_UI美化_v2.14.2.md`、`_UI重构_v2.15.0.md`、`_UI修正_v2.15.1.md`、`_UI与视频_v2.16.0.md`、`_材质与动画修复_v2.16.1.md`（读这几份即可掌握现有 UI 架构）。

---

## 2. 当前状态摘要

**状态：** `已验证（本地）`
**最近可靠成果：** v2.16.2 已构建 → 已部署到根目录（`install.json` = v2.16.2 / setup）→ 五屏截图人工核对通过
**当前正在处理：** 无（本轮收尾）
**最近一次成功操作：** `daily-launcher-v2.16.2-setup-x64.exe /S "/D=D:\tools\一键日常启动器"`，部署前后 `config.json` 哈希一致
**最近一次失败/中断：** 无（过程中踩过：`flatten()` 首版 alpha 写成 0 → 窗口全白，已修）
**距离可交付还差什么：** 用户验收；是否发布 GitHub Release 待用户决定；Win10 实机未测

**下一条可直接执行的操作：**

> 若用户反馈“弹窗不好看/想要半透明”：改 `ui_render.Compositor.prepare()` 的 alpha 策略（见第 7 节 P2），
> 不要直接恢复 v2.15 的「按矩形区域指定 alpha」——那会让卡片圆角外出现矩形底块（v2.16.1 已修）。

---

## 3. 任务清单

| ID | 任务 | 状态 | 涉及文件 | 验收依据 |
|---|---|---|---|---|
| T01 | 弹窗文字穿透：文字层 z 序 | 已验证 | `daily_launcher.py`（`text_layer_cover`、`draw_prompt`、`draw_exe_picker`）、`ui_design.py`、`ui_render.py`（`flatten`） | `verify_glass.py` → `PASS: modal covers page text in every material`；实机截图 |
| T02 | 模态弹窗改不透明呈现 | 已验证 | `ui_design.py`（`present_scene`、`prompt` 属性） | 同上；`verify_navigation.py` 弹窗断言 |
| T03 | 窗口按工作区摆放 + 越界自动让开 | 已验证 | `daily_launcher.py`（`create`、`fit_work_area`、`WM_SETTINGCHANGE`） | `PASS: window inside work area (0,84)-(2560,1440)` |
| T04 | 验证脚本补回归 | 已验证 | `源码/build/verify_glass.py`、`verify_navigation.py` | 两脚本全绿（见第 6 节） |
| T05 | 文档：交接 + README + 本文件 | 已验证 | `DeepSeek交接_弹窗与工作区_v2.16.2.md`、`README.md`、`PROGRESS.md` | 文件存在且内容与代码一致 |
| T06 | 构建与部署 v2.16.2 | 已验证 | `release/*`、根目录 exe+`_internal` | `install.json`、截图版本号 v2.16.2 |
| T07 | 发布 GitHub Release | 未开始 | —— | 等用户决定（v2.15/2.16 都没发） |
| T08 | Win10 实机验证 | 未开始 | —— | 需实机/VM |

---

## 4. 检查点与关键操作日志

| 检查点 | 时间 | 已完成操作 | 验证情况 | 下一步 |
|---|---|---|---|---|
| CP-001 | 10-31 15:45 | 复现问题：mica 下 `--shot --prompt`，`mem` 干净但成品有页面文字 → 定位到文字层 z 序 | 截图 + `prepare()` 前 dump 对比 | 加擦除逻辑 |
| CP-002 | 10-31 15:52 | 加 `text_layer_cover()` + 模态不透明提交 + `flatten()` | 首版全白（alpha=0），改为 alpha=255 后正常 | 跑验证脚本 |
| CP-003 | 10-31 16:00 | `verify_glass.py` 新增弹窗回归、`verify_navigation.py` 改断言 + 工作区断言 | 6 + 9 条全 PASS，GDI 116→116 | 构建 |
| CP-004 | 10-31 16:03 | 备份 v2.16.1 → 构建 v2.16.2 → 部署 → 五屏截图 | 版本号 v2.16.2，config 哈希未变 | 写文档 |
| CP-005 | 10-31 16:10 | 交接文档 + README 更新记录 + 本文件 | 见第 5、6 节 | 等用户验收 |

### 4.2 故障与处理记录

| 时间 | 问题 | 影响 | 处理 |
|---|---|---|---|
| 10-31 15:52 | `flatten()` 输出 alpha=0 | 窗口整屏白（`BitBlt` 后 DWM 认为全透明） | 改为输出 `RGBA` + `alpha=255` |
| 10-31 15:56 | `Image.alpha_composite` 报 `image has wrong mode` | 弹窗画不出来（异常被 wndproc 吞掉，画面停在旧帧） | `flatten()` 里先把 RGB 转 `RGBA` 再合成 |
| 10-31 15:50 | 测试时探针配置没清空 ok-ww 路径，弹窗超时后真拉起了 ok-ww | 启动了一个无关脚本（已确认进程随后退出，未进游戏） | 以后测自动启动一律把 `okww/maa/maaend/maafgo/mumu_root` 全清空；`--shot` 本身会关自动启动，优先用它 |

---

## 5. 文件清单与持久化

| 文件 | 路径 | 版本/说明 | 状态 |
|---|---|---|---|
| 主程序 | `源码\daily_launcher.py` | v2.16.2，7185 行 | 已验证 |
| 界面布局/过渡 | `源码\ui_design.py` | 358 行 | 已验证 |
| ARGB 合成 | `源码\ui_render.py` | 284 行（本轮 +`overlay_text`/`flatten`） | 已验证 |
| 原生材质 | `源码\ui_effects.py` | 103 行 | 未改 |
| 安装程序 | `源码\installer.py` | 1017 行 | 未改 |
| 构建脚本 | `build_launcher.py` | 读 `APP_VERSION` 自动定版本 | 未改 |
| 验证脚本 | `源码\build\verify_glass.py`（158 行）、`verify_navigation.py`（306 行） | 本轮各加回归 | 已验证 |
| 交接文档 | `DeepSeek交接_弹窗与工作区_v2.16.2.md` | 本轮 | 已保存 |
| 发布产物 | `release\daily-launcher-v2.16.2-*.{exe,zip}` | setup 16.75 MB / portable 11.54 MB / onefile 11.51 MB | 已保存 |
| 运行副本 | 根目录 `一键日常启动器.exe` + `_internal\`（73 文件，21 MB） | v2.16.2 | 已部署 |
| 回退副本 | `ui_refresh_backup\v2.16.1\`（EXE + `_internal`，75 文件） | v2.16.1 | 已保存（本地） |
| 远端 | GitHub main | 停在 v2.14.1 的源码（v2.15+ 未推） | **未持久化**（见 P1） |

---

## 6. 验收与测试记录

| 检查项 | 方法 | 结果 | 时间 |
|---|---|---|---|
| 材质表面 alpha / 动画帧 | `verify_glass.py` | PASS ×5（mica/tabbed/acrylic/solid + 动画开关 8 轮） | 10-31 16:00 |
| 弹窗盖住页面文字 | `verify_glass.py` 新增断言（读真实客户区 DC，页面标题区域深色像素必须为 0） | PASS（四材质） | 10-31 16:00 |
| 窗口在工作区内 | `verify_navigation.py` 新增断言（SPI_GETWORKAREA） | PASS `(0,84)-(2560,1440)` | 10-31 16:00 |
| 导航/命中/动画/DPI | `verify_navigation.py` | PASS ×9；36 次切页 GDI 104→104 | 10-31 16:00 |
| 弹窗开关 GDI 泄漏 | `verify_navigation.py` 16 轮（材质模式） | GDI 116→116 | 10-31 16:00 |
| 实机五屏 | 根目录 exe `--shot` 抓真实屏幕 | 主界面/设置/安排自动任务/选 exe/询问卡，标题栏完整、无穿透、版本 v2.16.2 | 10-31 16:04 |
| 部署不动配置 | 部署前后 `config.json` SHA-256 | 一致 | 10-31 16:03 |

### 6.1 已知缺陷 / 未验证

- 材质模式下弹窗**不透明**（看不到 Mica）—— 有意的取舍，见第 7 节 P2。
- Win10 实机未测（代码走实色分支，本轮改动对它等价）。
- 未跑真实游戏日常；未验证安装/卸载全流程（沿用 v2.14.1 的结论）。
- 「界面文字有点问题」用户原话较宽泛；本轮按「弹窗叠字 + 标题栏被压住」处理，五屏人工核对未见其它异常。若用户还有具体位置，需要按其截图再定位。

---

## 7. 未解决问题与优先级

| 优先级 | 问题 | 影响 | 建议处理 |
|---|---|---|---|
| P1 | GitHub 远端停在 v2.14.1 | 代码只在本地，换机/协作会丢 | 推 main（源码+README+交接文档），是否发 Release 由用户定 |
| P2 | 材质弹窗不透明 | 弹窗那 5 秒失去 Mica 观感 | 若要半透明：改 `prepare()` 的 alpha 策略（按亮度分层，而不是按矩形区域），别回退到 v2.15 的区域 alpha |
| P3 | 高 DPI 下窗口高度受工作区限制，主界面需滚动 | 168 DPI + 顶部任务栏时内容偏高 | 已可滚动，非阻塞 |
| P4 | `design/` 与 `源码/build/` 下截图文件很多（约 100 张） | 目录噪音 | 归档到 `design/archive/` 或删除，注意别删验证脚本引用的路径 |

---

## 8. 中断前检查点

- [x] 源码已写入 `源码\`，可直接 `python build_launcher.py` 重出包
- [x] 已验证的构建产物在 `release\`（v2.16.2 三件套）
- [x] 根目录运行副本已更新（`install.json` = v2.16.2）
- [x] 回退副本在 `ui_refresh_backup\v2.16.1\`
- [x] 交接文档 + README + 本文件已更新
- [ ] 远端未同步（P1）

---

## 9. 断点恢复：下一次应该执行什么

**恢复起点：** CP-005（v2.16.2 已验证、已部署）
**先读：** 本文件 → `DeepSeek交接_弹窗与工作区_v2.16.2.md` → `DeepSeek交接_材质与动画修复_v2.16.1.md`（了解合成管线）
**先核验：**

```powershell
cd D:\tools\一键日常启动器
& C:\Users\Cru77z7M\.workbuddy\binaries\python\versions\3.13.12\python.exe 源码\build\verify_glass.py
& C:\Users\Cru77z7M\.workbuddy\binaries\python\versions\3.13.12\python.exe 源码\build\verify_navigation.py
& .\一键日常启动器.exe --shot D:\tools\_shot\check.png --prompt --no-elevate --no-task
```

**已完成、不要重复：** 弹窗文字穿透、模态不透明呈现、工作区摆放、两个验证脚本的回归、v2.16.2 构建与部署。
**下一任务候选：** ① 推 GitHub main（P1）；② 若用户要半透明弹窗，按 P2 改合成；③ 收尾清理 `design/` 截图（P4）。

---

## 10. 交付检查与结项状态

- [x] 用户报的三个问题都有对应改动（弹窗叠字、界面文字、顶部任务栏遮挡）
- [x] 改动范围有记录（交接文档「改动」四节）
- [x] 关键验证已执行，未做的已标注（Win10、真实日常、安装/卸载）
- [x] 用户可访问交付物：`release\daily-launcher-v2.16.2-setup-x64.exe`，根目录直接双击即是 v2.16.2
- [ ] 远端同步（P1）
- **最终状态：** `待用户验收`（本地已验证）
