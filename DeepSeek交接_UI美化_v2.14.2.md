# 给 DeepSeek 的交接：界面美化 v2.14.2

> 历史记录：当前实现已升级为 v2.15.0。请优先阅读根目录 `DeepSeek交接_UI重构_v2.15.0.md`；本文件中仅标题栏 Mica / 无页面动画的说明不再代表当前版本。

日期：2026-10-31（Asia/Hong_Kong）  
执行：Codex；图像生成：内置 GPT Image 工具。  
项目：`D:\tools\一键日常启动器`，基线版本 v2.14.1，当前版本 v2.14.2。

## 1. 用户要求与完成范围

用户要求用 GPT Image 美化启动器、补齐设置功能图标、改善主界面、增加动画及 Windows Mica，并保证 Windows 10 有兼容回退；根目录保留交接 Markdown。

已修改源码、生成真实图片资源、构建安装版/便携版/单文件版，并把新的文件夹版 EXE 和 `_internal` 更新到项目根目录。直接打开根目录的 `一键日常启动器.exe` 即为新界面。

保留标准库 + ctypes + GDI 的运行结构，未引入 Qt、WebView、Pillow 等运行依赖。Pillow 只用于构建阶段把生成的图集转换为 ICO。没有修改任务执行算法、游戏包名、启动顺序、作者署名及项目地址。

**实现边界：Mica 用于原生窗口标题栏/非客户区，客户区仍是实色 GDI 卡片。不是整窗透明或全客户区 Mica。** 这样避免原有不带 alpha 的 GDI 双缓冲与玻璃客户区混用导致黑底或文字异常。若后续要整窗 Mica，需要单独设计支持 alpha 的绘制/合成路径，不能仅调用 `DwmExtendFrameIntoClientArea(-1)` 后继续整窗不透明 BitBlt。

## 2. 改动文件

| 路径 | 改动 |
| --- | --- |
| `源码/daily_launcher.py` | v2.14.2；配色、卡片层次、行距、图标映射；外观设置；悬停渐变与运行状态动画；接入系统偏好和 DWM |
| `源码/ui_effects.py` | 新增：系统动画/透明偏好、高对比度检测，版本门控、DWM 安全调用、颜色插值 |
| `源码/assets/icons/ui_*.ico` | 新增 9 个 GPT Image 图标，多尺寸 RGBA ICO |
| `源码/build/extract_ui_icons.py` | 图集拆分及 ICO 转换脚本，需要构建环境 Pillow |
| `源码/build/verify_ui_refresh.py` | 兼容性模拟、图标加载、DPI 布局、真实窗口截图、滚轮/开关测试、GDI 重绘检查 |
| `design/fluent-icon-atlas.png` | GPT Image 原始透明图集，1254 × 1254，保留 alpha |
| `design/imagegen-prompt.txt` | 完整英文生成提示词、工具和转换说明 |
| `design/previews/` | 主界面、设置页顶部/底部、自定义/夜间/任务/关于页、打包程序截图 |
| `design/verification.log` | 源码截图检查日志；与正常 launcher.log 分离 |
| `release/daily-launcher-v2.14.2-*` | 新版三种发布产物 |
| 根目录 EXE / `_internal` | 更新为新文件夹版，资源随包分发 |
| `ui_refresh_backup/` | 修改前的 EXE、完整 `_internal` 和主源码备份 |

原有 `build_launcher.py` 已会收集整个 assets 目录并分析本地模块，无需为新图标和 ui_effects 增加特殊打包参数。

## 3. 图片资源及功能映射

GPT Image 生成了一张 3 × 3 的透明 Fluent 风格软质立体图集，采用蓝/紫/青配色。没有用代码绘制的占位图冒充生成图。完整最终 prompt 在 `design/imagegen-prompt.txt`。

| ICO 名称 | 用途 |
| --- | --- |
| `ui_dashboard` | 主界面项目管理 |
| `ui_moon` | 今晚的手游日常、夜间说明 |
| `ui_tasks` | 自动任务设置入口 |
| `ui_update` | 更新、恢复默认 |
| `ui_info` | 关于本软件 |
| `ui_sliders` | 动画设置 |
| `ui_apps` | 添加/显示/管理自定义项目，替代原先 icon=None 的文字占位 |
| `ui_sparkle` | Mica 标题栏设置 |
| `ui_play` | 配套预留播放图标，目前未接入按钮 |

原有 MuMu、MAA、MaaEnd、MaaFgo、游戏图标及 launcher 头像保留；通用配置文件图标 cfg 也保留。新 ICO 含 16/24/32/48/64/96/128 像素层，继续复用 `load_icon` 缓存与 `DrawIconEx` 路径，缺文件仍走原有字符回退。

图集没有作为运行时资源打包，只有 ICO 进入 assets，避免将整张原始图片拖入单文件程序增加启动开销。重新转换：

```powershell
python 源码/build/extract_ui_icons.py
```

## 4. 界面变化

- 统一为浅蓝紫背景、靛紫强调色、白卡片和较清晰的次要文字色；按钮、选中框、分组条及状态提示沿用同一配色表。
- 主内容卡片加轻阴影与顶部短强调线；主启动按钮增加圆角、180ms 悬停颜色渐变。
- 主列表、设置列表加入圆角悬停底色，保留原命中矩形与点击逻辑。
- 设置/自定义/夜间/任务页默认行高从 34 提升至 42 逻辑像素；设置页显式 h=34 的行同步提升。图标改为行内垂直居中，最大 28 逻辑像素。
- 设置保留滚动和裁剪，增加“④ 界面与动效”，原“关于”变为“⑤ 关于”。内容增加后需要向下滚动才能看到外观及关于。
- 新增“ Mica 标题栏”“轻量动画”两项，点击切换并沿用原 save_config 原子写入流程。

## 5. Mica 与 Windows 10 回退

`ui_effects.apply_native_frame(hwnd, enabled=True, build=None)`：

1. 惰性读取 `sys.getwindowsversion().build`。
2. **build < 22621 直接返回 unsupported，不加载 dwmapi、不调用任何新 DWM 属性。** 因此 Windows 10（例如 19045）和 Windows 11 21H2 都走普通系统标题栏。
3. 对支持的系统惰性加载 `dwmapi.dll` 并明确声明 `DwmSetWindowAttribute` 的 HWND/指针签名，避免 64 位句柄截断。
4. 可选设置圆角属性 33；使用公开的属性 38 `DWMWA_SYSTEMBACKDROP_TYPE`，2 = MAINWINDOW，1 = NONE。
5. 主效果检查 HRESULT。DLL/入口缺失、调用失败只返回 unavailable，不中断程序。圆角是可选属性，其失败不会影响主功能。
6. 不使用未公开的 1029 属性、不使用 Windows 10 的非公开 AccentPolicy。

系统偏好由 `system_preferences()` 获取：SPI_GETCLIENTAREAANIMATION、SPI_GETHIGHCONTRAST，以及 HKCU Personalize/EnableTransparency。高对比度开启时关闭新增动画和透明效果；读取失败时采用保守回退。窗口接收 WM_SETTINGCHANGE / WM_THEMECHANGED 后重新应用偏好。

配置新增两个可选布尔值，默认均为 true：

```json
{"ui_mica": true, "ui_motion": true}
```

旧配置没有字段时使用默认值，不需要提高 CONFIG_VERSION。外观开关不会修改原有游戏路径、任务或勾选。Mica 开关表示用户偏好，不代表当前系统一定显示了材质；API 回退状态保存在 App.frame_effect（mica/solid/unsupported/unavailable）。系统也可能自行降低材质表现。

微软公开依据：

- https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwm_systembackdrop_type
- https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute

## 6. 动画、计时器与资源

- 悬停动画使用 monotonic 时钟、180ms ease-out 颜色插值。
- 原 timer 1（120ms）继续负责消息队列、自动启动、更新检查。
- 新 timer 2（16ms）只在悬停过渡期间启用，过渡结束立即 KillTimer；不永久维持高频计时器。
- 执行中项目的小状态点增加轻微呼吸；复用原 timer 1，仅 busy、窗口可见且未最小化、系统/用户允许动画时请求重绘。
- WM_DESTROY 清理两个 timer；关闭动画时立即停止 timer 2。
- 显式声明 KillTimer 的 HWND / UINT_PTR 签名。
- 修复 paint 中位图仍选入内存 DC 就 DeleteObject 的既有问题：保存旧位图，BitBlt 后先选回旧位图再删除，防止动画重绘放大 GDI 泄漏。
- 本次高对比度处理只控制新增效果，未把原有全部自绘配色改造成高对比度主题。

## 7. 已完成验证

本机环境：Windows build 26300，实际窗口 DPI 168（175%），系统动画与透明度均开启。

- Python 主源码与新模块编译通过。
- Win10 build 19045 模拟：断言完全不调用 WinDLL / 新 DWM 属性。
- 模拟缺失 DLL、DWM HRESULT 失败、Mica 开启/关闭及颜色插值端点，通过。
- 设置页/自定义页/夜间页中的非分组图标均通过真实 LoadImageW 加载断言。
- 100%、125%、150%、200% 的六页布局计算通过；实际 175% 截图复核主界面、设置顶部/底部、自定义/夜间/任务/关于页。
- 对真实 HWND 发送正负 WM_MOUSEWHEEL，验证下滚/上滚及滚动范围；外观动画开关切换往返通过。
- 对真实窗口连续重绘 120 次，GDI 对象数 **84 → 84**。
- PyInstaller 文件夹版、安装程序、单文件版均构建成功。
- 文件夹版和单文件版 EXE 均在独立测试目录以 `--no-auto --no-elevate --no-task --shot` 启动并成功输出窗口截图；便携 ZIP 校验含 9 个新图标且无用户 config.json。
- 根目录 EXE 的 SHA-256 与本次构建文件夹版一致。

测试脚本隔离配置读写、禁用实例发现/在线更新，不会启动游戏或修改真实用户设置。打包烟测使用构建/独立测试目录的空配置，不操作真实任务。预览为实际窗口截图，不是界面概念图。

**尚未完成的验证**：没有 Windows 10 虚拟机/实机，本次 Win10 是分支模拟与 API 隔离测试，不能称作 Windows 10 实机测试通过。也未执行实际游戏日常任务回归、未运行安装程序安装/卸载流程；安装程序完成构建。后续发布前建议在 Win10 22H2 实机/VM 启动一次，验证路径设置、滚动和普通标题栏，再在支持的 Win11 上核对材质表现。

复核示例（请使用装有 Pillow/PyInstaller 的真实 Python，避免 WindowsApps 的 python 占位器）：

```powershell
python 源码/build/verify_ui_refresh.py main
python 源码/build/verify_ui_refresh.py settings
python 源码/build/verify_ui_refresh.py settings 999
python 源码/build/verify_ui_refresh.py custom
python 源码/build/verify_ui_refresh.py night
python 源码/build/verify_ui_refresh.py tasks
python 源码/build/verify_ui_refresh.py about
python build_launcher.py --only all --keep-work
```

本机已安装依赖的 Python：`C:\Users\Cru77z7M\.workbuddy\binaries\python\versions\3.13.12\python.exe`。

## 8. 构建、部署与回退

本次构建目录：`dist/1031_011814/`；保留中间文件于 `build_tmp/1031_011814/`。

发布文件：

- `release/daily-launcher-v2.14.2-setup-x64.exe`
- `release/daily-launcher-v2.14.2-portable-x64.zip`
- `release/daily-launcher-v2.14.2-windows-x64.zip`
- `release/一键日常启动器-单文件版.exe`

根目录是文件夹版，必须配套 `_internal`。不要拿单文件 EXE 覆盖文件夹版 EXE；本次部署复制的是对应 onedir 的 EXE 和 `_internal`。根目录现有 config.json、其备份、install.json 和免 UAC 脚本均保留。构建产物未对外上传、未创建 GitHub Release。

需要回退时，先退出启动器，再把 `ui_refresh_backup/一键日常启动器.exe` 与备份 `_internal` 恢复到根目录；源码基线在 `ui_refresh_backup/daily_launcher.v2.14.1.py`。如需完全恢复旧运行目录，先把新版 `_internal` 移到独立备份位置，再恢复旧 `_internal`，避免混用。用户新增的两个外观字段可保留，旧版读取未知字段不会影响原功能。

## 9. 给后续维护者的注意点

1. 更换图标只修改 ui_ 前缀资源，不要覆盖官方应用图标；换图后重新构建所有发布形态。
2. 图片原件、提示词及转换脚本都已留档，运行时不需要联网生成图像或 API key。
3. 所有未来新增 Win11 效果必须维持惰性加载、版本门控和失败回退，不要在模块导入时硬解析新系统入口。
4. 当前设置页更长，维护时继续检查最底部可见性、裁剪和滚轮，尤其不要把逻辑像素行高重复乘 DPI。
5. 新增 16ms 动画前检查 GDI 对象稳定性，不要去掉位图恢复与 timer 清理。
6. 当前沿用原程序鼠标悬停命中机制；没有额外引入整页滑动、窗口透明度渐入或影响输入坐标的动画。
