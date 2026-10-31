# DeepSeek 交接：v2.16.2 弹窗文字穿透与顶部任务栏

日期：2026-10-31（Asia/Hong_Kong）。基线：v2.16.1。执行：DeepSeek（WorkBuddy）。

本轮没有动任务执行逻辑、配置结构、更新链路；只改绘制合成与窗口摆放。

## 用户报告

1. **不同背景材质下，开机询问弹窗的文字和主界面文字叠在一起**（截图里「按上次的勾选全部一键启动吗？」压着「MaaEnd · 终末地」「等待启动」「ADB 127.0.0.1:16384」）。
2. 界面上的文字也「有点问题」。
3. Windows 11 把任务栏放在**屏幕顶部**时，程序的顶部标题栏被任务栏盖住。

## 根因

1. **文字层的 z 序丢了。** 材质模式下 `text()` 不往场景位图（`mem`）里画，而是画进两个覆盖层
   （coverage + ink），最后在 `ui_render.Compositor.prepare()` 统一合成到场景上。
   于是「后画的实色面板」盖不住「先画进层的字」：`draw_prompt()` / `draw_exe_picker()`
   先把整窗铺一层遮罩、再画卡片，但遮罩只擦了 RGB，文字层里主界面的字一个没少，
   合成后又浮到最上层 —— 看起来就是弹窗上叠着页面文字。
2. 顺带暴露的第二层问题：遮罩是浅色实色，luminance→alpha 的 LUT 会把它算成 168（mica）/
   154（tabbed）/ 140（亚克力），于是弹窗又透出桌面，卡片和遮罩几乎一样实，层次也没了。
3. 窗口位置用 `GetSystemMetrics(0/1)`（整屏）算，y = (1440-h)/3。任务栏在顶部时
   工作区从 y=84 开始，窗口 y=39 → 标题栏整个压在任务栏底下，连拖都没法拖。

## 改动

### `源码/daily_launcher.py`

- 新增 `text_layer_cover(rect=None)`：用 `PatBlt(BLACKNESS)` 把两个文字层的指定区域清 0，
  语义是「这块被实色面板盖住了，之前画的字不算数」。
- `draw_prompt()` / `draw_exe_picker()`：铺完遮罩立刻 `text_layer_cover()`（整窗）。
- `paint()` 记录 `_paint_w/_paint_h`，供上面按整窗擦除。
- 窗口位置改用 `SPI_GETWORKAREA` 的工作区：`x = work.left + (work.width-w)/2`、
  `y = work.top + (work.height-h)/3`；工作区取不到时退回整屏。
- 新增 `fit_work_area()`：`WM_SETTINGCHANGE` 时只在窗口**越界**的情况下挪回工作区
  （用户自己拖过的位置不动）。窗口比工作区还大时只记日志、不动。

### `源码/ui_design.py`

- `present_scene()`：`material_on = 材质模式 and not (prompt or exepick)`。
  模态弹窗（询问卡 / 选 exe）期间按**不透明**提交，页面本体才走 Mica。
  材质提交失败的回退也改成 `present(..., mica=False)` —— 否则回退画面里的文字层没合回去，
  会变成一整屏没有字的空白。
- `prompt` 属性：材质模式下不再创建 220ms 弹窗淡入（不透明呈现下淡入没有意义，还会闪）。

### `源码/ui_render.py`

- 抽出 `overlay_text()`（原来的文字层合成逻辑）与 `flatten()`（场景 + 文字 → 不透明画面）。
- `present()`：`mica=False` 且存在文字层时先 `flatten()` 再 `BitBlt`；没有任何文字层时保持原样。
- `flatten()` 输出必须 **alpha=255**：DWM 会照 alpha 合成，写成 0 的话 BitBlt 出去等于全透明
  （踩过：第一版是白屏）。

### 其他

- `APP_VERSION` → `v2.16.2`；`README.md` 标题与更新记录补到 v2.16.2（顺手修了 v2.13.0 那行
  被写成字面量 `\n` 的坏表格行）。

## 验证

`源码/build/verify_glass.py`（新增一条回归）：

- 原 5 条全过：四材质表面 alpha + 三帧动画、动画开关 8 轮往返。
- 新增 `PASS: modal covers page text in every material`：四种材质各跑一遍，
  弹窗出现后读**真实客户区 DC**，断言页面标题区域的深色像素从 >50 变成 **0**，
  且弹窗卡片区域深色像素 >50（说明弹窗自己的字画出来了）。

`源码/build/verify_navigation.py`（改了断言 + 加一条）：

- 新增 `PASS: window inside work area (0,84)-(2560,1440)` —— 本机任务栏在顶部，
  这条直接卡住用户报的那个 bug。
- 弹窗相关断言改成新契约：材质模式下 `_modal_transition is None`（立即呈现），
  实色模式仍有 220ms 过渡并逐帧导出 GIF。
- 16 轮弹窗开关改在**材质模式**下跑，专门盯 `flatten()` 这条新路径的 GDI 泄漏：**116 → 116**。
- 其余（两列命中、真实点击导航、36 次切页 104→104、材质枚举、五档 DPI 关于页）全部通过。

实机截图（本机 Win11 build 26300、DPI 168、任务栏置顶）：
`design/previews/` 下的 `modal-instant.png` 等由验证脚本输出；本轮人工核对过
主界面 / 设置 / 安排自动任务 / 选 exe 卡片 / 询问卡五屏，标题栏完整可见、弹窗无穿透。

## 已知边界

- **材质模式下弹窗是不透明的**，弹窗那几秒看不到 Mica。原因：现有合成是「按最终颜色亮度
  反推 alpha」，浅色遮罩和浅色卡片都会被算成同一个透明度，做不出「半透明遮罩 + 更实的卡片」；
  要恢复那层效果得改回按区域指定 alpha（v2.16.1 已因此删掉，会因为圆角外一起着色出现矩形块）。
  现阶段优先保证可读。
- 未在 Windows 10 实机验证（Win10 走实色分支，本轮改动对它等价）。
- 未跑真实游戏日常，未重新生成介绍视频（沿用 v2.16.0）。

## 构建与部署

- 构建：`python build_launcher.py --keep-work` → `release/daily-launcher-v2.16.2-{setup-x64.exe,portable-x64.zip,windows-x64.zip}`
  （16.75 MB / 11.54 MB / 11.51 MB）。
- 部署：`release\daily-launcher-v2.16.2-setup-x64.exe /S "/D=D:\tools\一键日常启动器"`，
  `config.json` 哈希部署前后一致（已核对）。`install.json` 记录 `v2.16.2 / setup`。
- 回退：`ui_refresh_backup/v2.16.1/`（旧 EXE + 完整 `_internal`）。**必须成套替换**，
  不能把旧 exe 和新 `_internal` 混用；不要覆盖 `config.json`。
  源码级回退按本文「改动」四节逐条反向改（本轮没有单独存 v2.16.1 源码副本）。
- 未发布 GitHub Release（沿用 v2.15/v2.16 的做法，只在本地构建部署）。
