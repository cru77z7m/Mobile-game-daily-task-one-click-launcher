# PROGRESS.md — 长任务进度、交付与断点恢复记录

> **当前状态：v2.16.2 已构建、已部署、已验证（本地）**｜最后更新：2026-10-31 16:10（GMT+8）
> **本文件是可恢复的任务记录，不是任务已完成的证明。** 恢复时请按第 9 节核对真实文件与运行结果。

## 0. 维护约定（执行前必读）

- 本文件位于项目根目录 `D:\tools\一键日常启动器\`，是**唯一的进度索引**。每完成一个可独立验收的步骤、或做出影响后续的决策，就更新第 2/3/4/5/6 节。
- 优先级：**保护成果 → 核对真实文件 → 执行 → 验证 → 记录**。只有跑过命令、看过截图，才写「已验证」。
- 术语沿用模板：
  `未开始` / `进行中` / `已保存（本地）` / `已验证`（有命令或截图证据）/ `已持久化`（推到远端或另存并回读过）/ `阻塞`。
- 每轮改动的**实现细节直接写进本文件第 11 节「实现细节存档」**（v2.16.2 起不再单独写 `DeepSeek交接_*.md`，早先那几份只作历史参考）。本文件要能单独讲清「改了什么、为什么、怎么验证、怎么回退」。
- 不要改 `config.json`：它是用户配置（路径、勾选）。构建/验证脚本一律用隔离配置。

### 0.1 版本节奏

| 环节 | 做法 |
|---|---|
| 改代码 | 只动 `源码\*.py`；UI 相关分 `daily_launcher.py`（GDI 绘制/窗口）+ `ui_design.py`（布局/过渡）+ `ui_render.py`（ARGB 合成） |
| 自检 | `python 源码/build/verify_glass.py`、`python 源码/build/verify_navigation.py`（都会开真窗口，跑完自动关） |
| 构建 | `python build_launcher.py --keep-work` → `release\daily-launcher-<ver>-{setup-x64.exe,portable-x64.zip,windows-x64.zip}` |
| 部署 | `release\daily-launcher-<ver>-setup-x64.exe /S "/D=D:\tools\一键日常启动器"`（原地升级，保留 config.json） |
| 记录 | 本文件（第 2/3/4/5/6 节写状态与断点，第 11 节写实现细节）+ `README.md` 更新记录 + 工作记忆 `...\.workbuddy\memory\YYYY-MM-DD.md` |

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
| 远端仓库 | `github.com/cru77z7m/Mobile-game-daily-task-one-click-launcher`（源码/文档已推 main；**Release v2.16.2 已发**，三个附件齐全，`latest` 指向它） |
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
| T05 | 文档：README + 本文件（含第 11 节实现细节） | 已验证 | `README.md`、`PROGRESS.md` | 文件存在且内容与代码一致 |
| T06 | 构建与部署 v2.16.2 | 已验证 | `release/*`、根目录 exe+`_internal` | `install.json`、截图版本号 v2.16.2 |
| T07 | 发布 GitHub Release | 已持久化 | `release/release-notes-v2.16.2.md` | <https://github.com/cru77z7m/Mobile-game-daily-task-one-click-launcher/releases/tag/v2.16.2>，三附件齐全、`latest` 指向它 |
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
| CP-006 | 10-31 16:20 | 清理 `dist/`、`build_tmp/`（848 MB）；源码 + 文档推 GitHub main `a40c6d4` | `git push` 成功、`dist/build_tmp` 已不存在 | 等用户验收或指定下一项 |
| CP-007 | 10-31 16:30 | 删 `design/` 下 6 个 smoke 打包副本（59 MB）；`DeepSeek交接_弹窗与工作区_v2.16.2.md` 并入本文件第 11 节后删除；维护约定改成「实现细节只写本文件」 | 目录 388 → 329 MB；`grep` 无残留引用 | 发 v2.16.2 Release |
| CP-008 | 10-31 16:35 | 发 Release v2.16.2（setup 16.75 MB / portable 11.54 MB / windows 11.51 MB），`latest` 已切换 | `gh api` 核对 tag/附件/latest；`find_latest_release` 实测：onedir → setup，onefile → windows-x64.zip | 等用户验收 |

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
| 实现细节 | 本文件第 11 节（原 `DeepSeek交接_弹窗与工作区_v2.16.2.md` 已并入并删除） | v2.16.2 的根因/改动/验证/回退 | 已并入 |
| 发布产物 | `release\daily-launcher-v2.16.2-*.{exe,zip}` | setup 16.75 MB / portable 11.54 MB / onefile 11.51 MB | 已保存 |
| 运行副本 | 根目录 `一键日常启动器.exe` + `_internal\`（73 文件，21 MB） | v2.16.2 | 已部署 |
| 回退副本 | `ui_refresh_backup\v2.16.1\`（EXE + `_internal`，75 文件） | v2.16.1 | 已保存（本地） |
| 远端 | GitHub main `a40c6d4` | 源码 + UI 模块 + 验证脚本 + README/PROGRESS/交接文档 | 已持久化 |

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
| P1 | ~~GitHub 远端停在 v2.14.1~~ | 已解决：源码/文档已推 main `a40c6d4` | 是否发 Release 仍由用户定 |
| P2 | 材质弹窗不透明 | 弹窗那 5 秒失去 Mica 观感 | 若要半透明：改 `prepare()` 的 alpha 策略（按亮度分层，而不是按矩形区域），别回退到 v2.15 的区域 alpha |
| P3 | 高 DPI 下窗口高度受工作区限制，主界面需滚动 | 168 DPI + 顶部任务栏时内容偏高 | 已可滚动，非阻塞 |
| P4 | `design/` 下的截图与验证输出较多（约 13 MB） | 目录噪音 | smoke 打包副本（6 个目录、59 MB）已删；剩下的 `previews/` 是验证脚本产物，别删 `previews/v2.16.2/` |

---

## 8. 中断前检查点

- [x] 源码已写入 `源码\`，可直接 `python build_launcher.py` 重出包
- [x] 已验证的构建产物在 `release\`（v2.16.2 三件套）
- [x] 根目录运行副本已更新（`install.json` = v2.16.2）
- [x] 回退副本在 `ui_refresh_backup\v2.16.1\`
- [x] 交接文档 + README + 本文件已更新
- [x] 远端已同步（main `a40c6d4`，P1 关闭）

---

## 9. 断点恢复：下一次应该执行什么

**恢复起点：** CP-005（v2.16.2 已验证、已部署）
**先读：** 本文件（第 2、9 节看断点，第 11 节看 v2.16.2 的实现细节）→ `DeepSeek交接_材质与动画修复_v2.16.1.md`（v2.16.2 之前的合成管线背景）
**先核验：**

```powershell
cd D:\tools\一键日常启动器
& C:\Users\Cru77z7M\.workbuddy\binaries\python\versions\3.13.12\python.exe 源码\build\verify_glass.py
& C:\Users\Cru77z7M\.workbuddy\binaries\python\versions\3.13.12\python.exe 源码\build\verify_navigation.py
& .\一键日常启动器.exe --shot D:\tools\_shot\check.png --prompt --no-elevate --no-task
```

**已完成、不要重复：** 弹窗文字穿透、模态不透明呈现、工作区摆放、两个验证脚本的回归、v2.16.2 构建与部署、远端同步、Release v2.16.2。
**下一任务候选：** ① 若要半透明弹窗，按 P2 改合成；② Win10 实机验证；③ 用户新报的问题（按截图定位）。

---

## 10. 交付检查与结项状态

- [x] 用户报的三个问题都有对应改动（弹窗叠字、界面文字、顶部任务栏遮挡）
- [x] 改动范围有记录（交接文档「改动」四节）
- [x] 关键验证已执行，未做的已标注（Win10、真实日常、安装/卸载）
- [x] 用户可访问交付物：`release\daily-launcher-v2.16.2-setup-x64.exe`，根目录直接双击即是 v2.16.2
- [x] 远端同步（P1 已关闭，main `a40c6d4`）
- [x] Release v2.16.2 已发（三附件、latest 已切换）
- **最终状态：** `已交付`（本地已验证 + 已发布）

---

## 11. 实现细节存档：v2.16.2（原 `DeepSeek交接_弹窗与工作区_v2.16.2.md`，已并入此处）

> 基线 v2.16.1。本轮没有动任务执行逻辑、配置结构、更新链路，只改绘制合成与窗口摆放。

### 11.1 用户报告

1. **不同背景材质下，开机询问弹窗的文字和主界面文字叠在一起**（截图里「按上次的勾选全部一键启动吗？」压着「MaaEnd · 终末地」「等待启动」「ADB 127.0.0.1:16384」）。
2. 界面上的文字也「有点问题」。
3. Windows 11 把任务栏放在**屏幕顶部**时，程序的顶部标题栏被任务栏盖住。

### 11.2 根因

1. **文字层的 z 序丢了。** 材质模式下 `text()` 不往场景位图（`mem`）里画，而是画进两个覆盖层
   （coverage + ink），最后在 `ui_render.Compositor.prepare()` 统一合成到场景上。
   于是「后画的实色面板」盖不住「先画进层的字」：`draw_prompt()` / `draw_exe_picker()`
   先把整窗铺一层遮罩、再画卡片，但遮罩只擦了 RGB，文字层里主界面的字一个没少，
   合成后又浮到最上层 —— 看起来就是弹窗上叠着页面文字。
2. 顺带暴露的第二层问题：遮罩是浅色实色，luminance→alpha 的 LUT 会把它算成 168（mica）/
   154（tabbed）/ 140（亚克力），于是弹窗又透出桌面，卡片和遮罩几乎一样实，层次也没了。
3. 窗口位置用 `GetSystemMetrics(0/1)`（整屏）算，`y = (1440-h)/3`。任务栏在顶部时
   工作区从 y=84 开始，窗口 y=39 → 标题栏整个压在任务栏底下，连拖都没法拖。

### 11.3 改动

**`源码/daily_launcher.py`**

- 新增 `text_layer_cover(rect=None)`：用 `PatBlt(BLACKNESS)` 把两个文字层的指定区域清 0，
  语义是「这块被实色面板盖住了，之前画的字不算数」。
- `draw_prompt()` / `draw_exe_picker()`：铺完遮罩立刻 `text_layer_cover()`（整窗）。
- `paint()` 记录 `_paint_w/_paint_h`，供上面按整窗擦除。
- 窗口位置改用 `SPI_GETWORKAREA` 的工作区：`x = work.left + (work.width-w)/2`、
  `y = work.top + (work.height-h)/3`；工作区取不到时退回整屏。
- 新增 `fit_work_area()`：`WM_SETTINGCHANGE` 时只在窗口**越界**的情况下挪回工作区
  （用户自己拖过的位置不动）。窗口比工作区还大时只记日志、不动。

**`源码/ui_design.py`**

- `present_scene()`：`material_on = 材质模式 and not (prompt or exepick)`。
  模态弹窗（询问卡 / 选 exe）期间按**不透明**提交，页面本体才走 Mica。
  材质提交失败的回退也改成 `present(..., mica=False)` —— 否则回退画面里的文字层没合回去，
  会变成一整屏没有字的空白。
- `prompt` 属性：材质模式下不再创建 220ms 弹窗淡入（不透明呈现下淡入没有意义，还会闪）。

**`源码/ui_render.py`**

- 抽出 `overlay_text()`（原来的文字层合成逻辑）与 `flatten()`（场景 + 文字 → 不透明画面）。
- `present()`：`mica=False` 且存在文字层时先 `flatten()` 再 `BitBlt`；没有任何文字层时保持原样。
- `flatten()` 输出必须 **alpha=255**：DWM 会照 alpha 合成，写成 0 的话 BitBlt 出去等于全透明
  （踩过：第一版是白屏）。

### 11.4 验证

`源码/build/verify_glass.py`（新增一条回归）：

- 原 5 条全过：四材质表面 alpha + 三帧动画、动画开关 8 轮往返。
- 新增 `PASS: modal covers page text in every material`：四种材质各跑一遍，
  弹窗出现后读**真实客户区 DC**，断言页面标题区域的深色像素从 >50 变成 **0**，
  且弹窗卡片区域深色像素 >50（说明弹窗自己的字画出来了）。

`源码/build/verify_navigation.py`：

- 新增 `PASS: window inside work area (0,84)-(2560,1440)` —— 本机任务栏在顶部，
  这条直接卡住用户报的那个 bug。
- 弹窗相关断言改成新契约：材质模式下 `_modal_transition is None`（立即呈现），
  实色模式仍有 220ms 过渡并逐帧导出 GIF。
- 16 轮弹窗开关改在**材质模式**下跑，专门盯 `flatten()` 这条新路径的 GDI 泄漏：**116 → 116**。
- 其余（两列命中、真实点击导航、36 次切页 104→104、材质枚举、五档 DPI 关于页）全部通过。

实机截图（本机 Win11 build 26300、DPI 168、任务栏置顶）：
`design/previews/v2.16.2/`（`prompt-mica.png`、`main-mica.png` 等 + 四材质 previews）。
本轮人工核对过主界面 / 设置 / 安排自动任务 / 选 exe 卡片 / 询问卡五屏，
标题栏完整可见、弹窗无穿透。

### 11.5 已知边界

- **材质模式下弹窗是不透明的**，弹窗那几秒看不到 Mica。原因：现有合成是「按最终颜色亮度
  反推 alpha」，浅色遮罩和浅色卡片都会被算成同一个透明度，做不出「半透明遮罩 + 更实的卡片」；
  要恢复那层效果得改回按区域指定 alpha（v2.16.1 已因此删掉，会因为圆角外一起着色出现矩形块）。
  现阶段优先保证可读。见第 7 节 P2。
- 未在 Windows 10 实机验证（Win10 走实色分支，本轮改动对它等价）。
- 未跑真实游戏日常，未重新生成介绍视频（沿用 v2.16.0）。

### 11.6 构建、部署与回退

- 构建：`python build_launcher.py --keep-work` →
  `release/daily-launcher-v2.16.2-{setup-x64.exe,portable-x64.zip,windows-x64.zip}`
  （16.75 MB / 11.54 MB / 11.51 MB）。
- 部署：`release\daily-launcher-v2.16.2-setup-x64.exe /S "/D=D:/tools/一键日常启动器"`，
  `config.json` 哈希部署前后一致（已核对）。`install.json` 记录 `v2.16.2 / setup`。
- 回退：`ui_refresh_backup/v2.16.1/`（旧 EXE + 完整 `_internal`）。**必须成套替换**，
  不能把旧 exe 和新 `_internal` 混用；不要覆盖 `config.json`。
  源码级回退按 11.3 四节逐条反向改（v2.16.1 没有单独存源码副本）。
