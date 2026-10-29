# 一键日常启动器

一款 Windows 日常任务启动工具，用来按顺序启动和协调 MaaEnd、MAA、MaaFgo、ok-ww 及 MuMu 模拟器。程序提供设置、自检、运行日志和取消启动等功能。各游戏与第三方工具仍需自行安装和配置。

**作者主页：** [Bilibili 个人主页](https://space.bilibili.com/5707907?spm_id_from=333.1365.0.0)。作者借助 **DeepSeek V4.1 Flash1017** 完成开发。

> **禁止商用：** 本项目仅授权个人、非商业用途。未经作者事先书面许可，不得销售、出租、收费提供、用于经营活动或以其他方式商业使用。完整条款见 [许可与免责声明](LICENSE.md)。

## 快速开始

1. 在 [Releases 发布页面](https://github.com/cru77z7m/Mobile-game-daily-task-one-click-launcher/releases) 下载 Windows x64 压缩包，解压到固定目录并运行 `一键日常启动器.exe`。首次使用可能需要管理员授权。
2. 自行安装 MuMu 12 和需要使用的 MaaEnd、MAA、MaaFgo、ok-ww；分别完成初始化并手动验证其任务可以运行。
3. 在启动器设置中选择本机路径和模拟器实例，保存后返回主界面开始运行。
4. 运行前请阅读[详细使用指南](docs/使用指南.md)和[安全与故障排查](wiki/安全与故障排查.md)。

首次运行会在程序旁生成 `config.json` 和 `launcher.log`；它们可能包含本机路径，请勿随意公开。可选的免 UAC 脚本会注册以最高权限运行的计划任务并创建快捷方式，请先阅读脚本和指南，自行决定是否使用。

## 从源码构建

源码位于 `源码/daily_launcher.py`，使用 Python 标准库和 Windows API；构建需要 Python 及 PyInstaller。仓库根目录运行 `python -m pip install pyinstaller`，然后运行 `python build_launcher.py`。构建脚本会清理项目下的 `dist` 和 `build_tmp`，并把生成的 exe 复制到项目根目录；请勿在这些目录存放需要保留的文件。

## 项目边界与风险

本项目是独立的第三方工具，与游戏厂商、模拟器和所调用的项目无官方关联。第三方程序及素材各自受其权利人条款约束；本项目的授权不覆盖它们。本工具会启动和控制第三方程序，并可能修改其配置文件，使用前请备份。自动化可能违反游戏或第三方服务条款，产生账号限制或其他损失，请自行评估并遵守适用规则。详见 [许可与免责声明](LICENSE.md)。

文档入口：[使用指南](docs/使用指南.md) · [Wiki 页面草稿](wiki/Home.md) · [许可与免责声明](LICENSE.md)。
