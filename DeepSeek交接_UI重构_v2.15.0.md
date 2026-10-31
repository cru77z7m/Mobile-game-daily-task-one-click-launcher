# DeepSeek 交接：v2.15.0 全窗 Mica、页面动画与主界面重构

> 最新增量修正见根目录 `DeepSeek交接_UI修正_v2.15.1.md`，包含设置去重、概览标语、启动弹窗动画与关于页重叠修复。

日期：2026-10-31（Asia/Hong_Kong）。基线：上一次 v2.14.2 美化。执行：Codex。

本文件是当前交接文档，替代 v2.14.2 文档中“仅标题栏 Mica”“没有页面动画”的实现说明。用户本轮明确要求：模块切换必须有动画，Mica 覆盖整个窗口，主界面需要重新设计。

## 完成结果

- 主界面改为固定左侧导航、顶部概览、双列任务卡片、底部操作区和独立日志区。
- 六个模块均可从侧栏访问：控制台、设置、自动任务、夜间清单、项目管理、关于。
- 页面进入、返回、侧栏跳转均使用 280ms 淡入 + 22 逻辑像素轻滑移，三次 ease-out；返回采用反方向。
- 支持快速反向切换：从当前已显示的合成场景开始下一次过渡，不跳回最初页面。
- 全窗 Mica：通过公开 DWM API 将材质扩展至整个客户区，并以真实带预乘 alpha 的半透明 UI 内容覆盖其上。不是窗口整体透明度、不是把桌面截图当背景、也不是只改标题栏。
- Windows 10/不支持的系统走原生不透明 GDI 路径；用户关闭 Mica、系统关闭透明效果、高对比度、新效果调用失败时也有回退。
- 已保留上一轮 GPT Image 图标及对应原图、提示词；本轮复用这些资源，没有再次调用生成服务。

## 文件与职责

| 文件 | 作用 |
| --- | --- |
| `源码/daily_launcher.py` | 版本改为 v2.15.0；App 继承 VisualShell；新布局、两列命中判断、侧栏路由、计时器接入、绘制入口、工作区尺寸适配 |
| `源码/ui_design.py` | 新增：页面属性拦截、过渡生命周期、固定导航、概览、任务卡片、操作按钮、场景呈现与透明度分区 |
| `源码/ui_render.py` | 新增：Surface 场景缓存、AlphaBlend、UxTheme BufferedPaint 的 ARGB 合成与安全释放 |
| `源码/ui_effects.py` | 升级：Mica 从标题栏扩展至整个客户区；失败时撤销扩展；继续保留版本门控和系统偏好 |
| `源码/build/verify_ui_refresh.py` | 更新为新布局与渲染资源检查；避免截图时误接收物理点击 |
| `源码/build/verify_navigation.py` | 新增：真实窗口导航消息、动画、命中、资源、ARGB 和回退集成检查；导出动画示例 |
| `design/previews/main-0.png` | 新主界面实际窗口截图 |
| `design/previews/settings-999.png` | 设置页底部实际截图，包含全窗 Mica / 动画开关 |
| `design/previews/page-transition.gif` | 页面切换效果演示，由应用实际渲染缓存导出中间帧后编码，不是界面概念图 |
| `design/previews/navigation/` | 进入动画的渲染帧，以及 Mica 开/关、Win10 分支窗口截图 |
| `design/navigation-results.txt` | 集成测试输出 |
| 根目录 EXE / `_internal` | 部署后的新版文件夹版运行程序与资源 |
| `ui_refresh_backup/v2.14.2/` | 本轮修改前的 EXE、完整 `_internal`、主源码、ui_effects 备份 |

运行依赖仍为 Python 标准库和系统 DLL。没有新增 Qt、WebView、numpy 或自编译原生库。Pillow 仅用于构建/验证脚本中的图标转换和 GIF/PNG 导出。

## 页面动画如何工作

1. `VisualShell.page` 是属性，统一拦截运行中的页面变化。因此原有设置行跳转、返回按钮、更新提示跳转也自然进入动画路径，不需要在每个调用点重复写动画。
2. 初始加载、创建窗口前的页面指定不播放动画。
3. 已显示场景保存在 `_last_scene`，由兼容内存 DC + 位图组成，不从桌面抓屏。
4. 导航时克隆当前场景为 outgoing snapshot；下一页立即按真实数据完成布局与绘制。
5. timer 3 每 16ms 请求重绘，按 monotonic 时钟计算 280ms 的归一化进度，以 `1-(1-t)^3` 插值。
6. 左侧导航固定，只有右侧内容淡入并轻滑移；按页面深度决定方向。
7. 动画期间不接受移动内容区的点击，避免视觉位置与实际命中位置不一致；侧栏仍允许再次导航。
8. 过渡结束、动画关闭、窗口销毁时释放 outgoing surface，停止 timer 3。普通悬停仍使用 timer 2，原后台刷新仍使用 timer 1。
9. Windows 关闭客户区动画、用户关闭“轻量动画”或高对比度开启时不播放过渡。

不要用会阻塞 UI 消息循环的 `sleep` 做动画，也不要捕捉桌面作为运行时旧页面；本实现没有这些做法。演示脚本为了逐帧展示，会控制过渡时间点，但生产程序按真实时钟自动推进。

## 全窗口 Mica 的关键实现

`apply_native_frame()` 先检查 Windows build。低于 22621 直接返回 unsupported，不加载新 DWM 功能。支持的系统使用：

- `DWMWA_SYSTEMBACKDROP_TYPE = 38`，取值 MAINWINDOW = 2。
- `DwmExtendFrameIntoClientArea`，四边 margin 均为 -1，扩展到整个客户区。
- 关闭效果时 backdrop = NONE，并把四边 margin 恢复为 0。
- 扩展失败时尝试撤销属性和 margin，返回 unavailable。
- 保留可选圆角，显式使用浅色 DWM 外观以匹配当前浅色界面。

**仅扩展 margin 不够。** 旧 GDI 绘制会把文本/形状区域的 alpha 清为 0，直接放到玻璃客户区会出现“图标还在，文字和按钮消失”。本轮已在实际截图检查中修正这一问题，最终路径如下：

1. 正常 GDI 将完整场景画入离屏位图，保持文本、图标和布局的原有清晰度。
2. 通过 `BeginBufferedPaint(BPBF_TOPDOWNDIB)` 建立源 DIB，把场景复制进去，并用 `BufferedPaintSetAlpha(..., 255)` 将源数据规范为不透明 ARGB。
3. 再创建清零的目标 BufferedPaint 缓冲，使用 `AlphaBlend(AC_SRC_ALPHA)` 按不同表面的不透明度合成。
4. 底层背景 alpha 为 38/255；侧栏、标题区、卡片和按钮按各自权重叠加，保证材质透出同时保留文字可读性。模态询问/选 EXE 也使用半透明遮罩及更实的对话卡片。
5. `AlphaBlend` 同时计算 RGB 预乘与目标 alpha；不能只把最终目标 alpha 改小而不预乘 RGB，否则会出现发白/错误叠色。
6. `EndBufferedPaint` 把 ARGB 内容提交给扩展后的 DWM 客户区。
7. 如果 BufferedPaint / AlphaBlend 不可用或提交失败，撤销材质并恢复普通 BitBlt，避免留下不可读的玻璃界面。

Windows 10 保持完整实色界面，同时仍可使用页面切换动画。Mica 和动画是两个独立偏好，配置键仍是 `ui_mica`、`ui_motion`，无需配置迁移或提高 CONFIG_VERSION。

材质本身由 Windows 管理。Mica 是壁纸取色的底材，不等同于 Acrylic；它不会像实时毛玻璃那样清晰映出后方每一个窗口。失焦、节能、系统透明设置等也可能改变系统显示的材质效果。

公开 API 参考：

- https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwm_systembackdrop_type
- https://learn.microsoft.com/en-us/windows/win32/dwm/customframe
- https://learn.microsoft.com/en-us/windows/win32/api/uxtheme/ns-uxtheme-bp_paintparams
- https://learn.microsoft.com/en-us/windows/win32/api/uxtheme/nf-uxtheme-bufferedpaintsetalpha
- https://learn.microsoft.com/en-us/windows/win32/gdi/alpha-blending

## 主界面布局与交互细节

- 默认客户区 960 × 780 逻辑像素；窗口建立时限制在工作区范围内，避免高 DPI 时挡住任务栏。
- 固定侧栏占左侧约 192 逻辑像素，内容从 x=212 开始。
- 任务以两列卡片展示，保留原执行顺序（阅读顺序：从左到右、从上到下），不改变 Runner 实际启动顺序。
- 每卡片包含原应用图标、任务名、简要说明、勾选状态、执行状态。
- 新增 `rects['tiles']`，两列同一 y 的项目按完整 x/y 矩形命中；不再复用只按 y 判断的单列表命中方式。
- 右侧列表滚动时保留裁剪与滚动条；任务较多或工作区较矮时主界面也可滚动。
- 主操作区为“启动所选任务 / 夜间启动 / 取消启动 / 关闭模拟器”，宽度按内容区计算。设置等入口已进入固定侧栏。
- 子页面只显示返回按钮，不再堆放一排灰色无效主操作按钮。
- 日志改用界面字体，增加“运行记录”标题；为设置页至少保留 82 逻辑像素的日志区，避免标题占满后日志被切成半行。
- 限制 Enter 仅在控制台且无过渡时启动，避免在设置页按 Enter 误启动任务。
- 修正子页面行命中只判断 y 的问题，侧栏空白位置不会误触设置行。
- 原程序路径、勾选、游戏自动化、UAC 策略、更新源、作者及第三方归属均保留。

## 验证结果与边界

本机：Windows build 26300，DPI 168（175%）。

- 模块编译、图标加载及 100% / 125% / 150% / 200% 六页布局计算通过。
- 六个页面完成实际窗口截图复核；设置底部包含两个外观开关并能滚到。
- 真实 HWND 的滚轮消息、外观开关往返、两列任务命中、侧栏空白命中通过。
- 通过真实 `WM_LBUTTONDOWN` / `WM_LBUTTONUP` 验证进入、返回、快速反向切换；系统/用户关闭动画时立即切换。
- 连续 36 次页面切换后 GDI 对象计数 **99 → 99**。
- 主界面连续 120 次重绘 GDI 对象计数 **98 → 98**；设置等子页也分别检查，无持续增长。
- 在真实原生 BufferedPaint 缓冲上探测 BGRA：背景 `(37,36,36,38)`、面板 `(221,216,215,224)`。alpha 均低于 255，RGB 各分量不超过 alpha，验证透明及预乘成立。
- 验证全窗 Mica 开启、关闭、模拟 Win10 分支、合成器不可用后的不透明回退。
- Win10 build 19045 的版本门控测试断言不解析新 DWM DLL；还模拟 DLL 缺失和 HRESULT 失败。
- 已重新构建文件夹版、便携 ZIP、安装 EXE、单文件 EXE；打包版本需随源码一起更新，不能只替换 .py。
- 最终构建位于 `dist/1031_014614/`。文件夹版和单文件版均以隔离空配置实际启动并成功输出截图，日志无绘制异常；便携 ZIP 中含 9 个新图标且不含用户 config.json。根目录已更新，EXE 的 SHA-256 与最终 onedir 构建一致。

**验证边界**：本机不是 Windows 10，没有 Win10 实机/VM 测试。Win10 结论来自分支、API 隔离和实际不透明绘制路径检查，仍建议发布前在 Win10 22H2 实机/VM 启动复核。没有运行实际游戏日常或安装/卸载流程；本轮主要验证界面、导航、渲染与打包程序启动。

测试脚本禁止真实用户配置写入，关闭实例发现、在线更新和自动启动。动画 GIF 从程序场景缓存生成，避免抓入用户正在使用的其它应用；材质对比使用原生窗口截图。

复核命令（本机已安装依赖的 Python 位于 `C:\Users\Cru77z7M\.workbuddy\binaries\python\versions\3.13.12\python.exe`）：

```powershell
python 源码/build/verify_ui_refresh.py main
python 源码/build/verify_ui_refresh.py settings 999
python 源码/build/verify_navigation.py
python build_launcher.py --only all --keep-work
```

## 部署与回退

根目录继续使用文件夹版 EXE + `_internal`。本轮在 `release/` 生成 v2.15.0 的 setup、portable、windows 单文件三种发布产物，另有 `一键日常启动器-单文件版.exe`。未对外发布 GitHub Release。

回退到上一轮时：退出启动器，将 `ui_refresh_backup/v2.14.2/` 中 EXE 与 `_internal` 成套恢复。源码也可从同目录恢复 `daily_launcher.py` 和 `ui_effects.py`；新加的 ui_design/ui_render 不被旧主模块导入，不影响旧版，但可另行归档。不要覆盖 config.json，不要把单文件 EXE 与文件夹版 `_internal` 混用。

后续调整动画只需维护 ui_design 的过渡时间/位移和生命周期；调整透明度必须维护 ui_render 的预乘流程。不要为了改透明度删掉规范化源 alpha 的步骤，也不要给所有像素直接写一个较小 alpha 后提交。
