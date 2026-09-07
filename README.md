# PalModManager（帕鲁 Mod 管理器）

> 当前版本：**v1.2.0**

Palworld 的 Mod 管理器，支持 UE4SS Lua Mod 与 PAK Mod 的启用/禁用、状态同步，以及程序自身的**自动更新**。

- 技术栈：Python 3 + PyQt5 + PyInstaller（`--onefile --windowed`）
- 入口：`main.py`
- 打包：`build.bat <版本号>`（自动生成 `version.json`、构建、提交并打 Git tag、打开发布页）
- 当前版本号：`src/utils/updater.py` 的 `CURRENT_VERSION`（v1.2.0）

## 目录结构

```
pal-mod-manager/
├── main.py              # 程序入口
├── build.bat            # 打包/发布脚本
├── PalModManager.spec   # PyInstaller 配置
├── version.json         # 版本信息（被程序读取以检查更新）
├── resources/           # 应用图标、框架压缩包（UE4SS / PalSchema）
├── src/
│   ├── ui/              # 界面
│   │   ├── main_window.py   # 主窗口（菜单 / 列表 / 详情 / 更新下载）
│   │   ├── mod_list.py      # Mod 列表控件
│   │   ├── mod_detail.py    # Mod 详情面板
│   │   ├── settings_page.py # 设置页（路径、模式、框架）
│   │   ├── profile_dialog.py# 配置方案（客户端/服务器）管理
│   │   └── styles.py        # 样式
│   ├── core/            # 业务逻辑
│   │   ├── manager.py       # ModManager：刷新 / 导入 / 导出 / 合集扫描
│   │   ├── scanner.py       # Mod 扫描与智能识别（含 scan_collection）
│   │   └── models.py        # ModInfo 等数据模型
│   ├── services/        # 框架服务
│   │   ├── framework_setup.py   # UE4SS / PalSchema 安装
│   │   ├── ue4ss_service.py
│   │   └── palschema_service.py
│   └── utils/
│       ├── updater.py   # 自更新核心逻辑
│       ├── config.py    # 配置读写
│       ├── network.py   # 网络请求
│       └── helpers.py   # 工具函数
└── dist/                # 打包产物 PalModManager.exe
```

## 功能特性

- **双模式管理**：客户端（PAK Mod，置于 `~mods`）与服务器（UE4SS Lua / Logic Mod，置于 `Mods`）一键切换，状态独立保存。
- **启用 / 禁用 / 排序**：支持按文件后缀 `_disabled`、逻辑 Mod 启用开关、优先级排序。
- **智能识别说明**：自动读取 Mod 配套的 `使用说明.txt` / `说明.txt` / `README.md`（含 mod 根目录与 `Pal/` 上一级），客户端 `.pak` 也能显示说明。
- **Mod 合集扫描**：可扫描整理好的 Mod 合集目录（见下），列出其中所有 Mod 并一键导入。
- **框架安装**：内置 UE4SS、PalSchema 的一键安装 / 校验。
- **程序自更新**：见下一节。

## Mod 合集扫描

菜单「文件 → 扫描 Mod 合集目录...」可对任意整理好的 Mod 合集目录进行智能识别，自动列出其中所有 Mod（结果在主列表中以「合集」标签区分），并支持一键全部导入到当前游戏/服务器目录。

识别以下常见结构：

1. **含 `Pal/` 的 Mod 子文件夹**（推荐布局）：

   ```
   合集目录/
   └── 分类文件夹/
       └── Mod名称/
           ├── Pal/Content/Paks/...      # 实际 Mod 内容
           └── 使用说明.txt               # Mod 说明（位于 Pal/ 上一级）
   ```

2. **平铺的 `.pak` / `.lua` 文件**（可带同名 `.txt` 说明）：

   ```
   合集目录/
   └── 分类文件夹/
       ├── CoolMod.pak
       └── CoolMod.txt                    # 同名说明
   ```

> 说明：名称以 `ali213` 开头的目录（游侠/第三方汉化整合包，内部为 `*/files/` 布局）无法可靠解析，扫描时会自动跳过。

## 自更新机制

更新流程的关键是**彻底避开“从 .bat / VBS 脚本里启动新 EXE”**这一在 Windows 上不稳定的环节，改为由程序自身用 `subprocess` 拉起另一个进程完成替换。

### 版本检查

- `updater.CURRENT_VERSION`：当前程序版本号（v1.2.0，位于 `src/utils/updater.py` 顶部）。
- 程序启动后读取 `version.json`（`UPDATE_URL`，即仓库 `main` 分支上的文件）。
- 通过 `_version_le()` 归一化比较（去掉 `v` 前缀、忽略非数字部分）。若远端版本号更高，则提示更新。

### 双进程替换流程（核心）

1. **下载**：`download_update()` 采用 **稳定下载方式**——基于 `requests` 的单连接下载，内置自动重试（指数退避、覆盖 5xx/CDN 限流）、断点续传（连接中断从已下载位置继续）与 GitHub 302 重定向跟随，下载完成校验文件大小。
2. **暂存**：`apply_update()` 把下载好的新 EXE 复制为系统 temp（`<TEMP>/PalModManagerUpdate/`）下的 `PalModManager_new.exe`，然后用 **`subprocess.Popen`（脱离父进程 + 清掉 `_MEIPASS` 环境变量）** 直接拉起它，并传入 `--apply-update` 与当前 EXE 路径参数。随后当前程序立即 `os._exit(0)` 退出、释放文件锁。**用户原目录此刻不写入任何中间文件。**
3. **替换**：新进程（`PalModManager_new.exe`，位于 temp）启动时，`main.py` 最开头调用 `finish_pending_update()` 检测到 `--apply-update`，执行：
   - 等待约 3 秒，确保旧程序已退出并释放文件句柄；
   - 把旧 `PalModManager.exe` 改名备份到 temp 同目录（如 `PalModManager.exe.bak`，**不污染用户原目录**）；
   - 把 temp 下的 `PalModManager_new.exe` 复制为最终的 `PalModManager.exe`（带重试）；
   - 再用 `subprocess` 拉起最终的 `PalModManager.exe`；
   - 当前 `_new.exe` 进程 `os._exit(0)` 退出。
4. **最终启动**：最终 `PalModManager.exe` 正常运行；`cleanup_update_leftovers()` 在启动时清理系统 temp 中残留的 `PalModManager_new.exe` 与 `*.bak`。

> 设计要点：所有“启动另一个 EXE”的动作都在 Python 进程内通过 `subprocess` 完成（与管理器启动游戏是同一套可靠机制），不依赖 `cmd start` / `wscript` / `powershell Start-Process` 等脚本方式。

### 相关函数（`src/utils/updater.py`）

| 函数 | 作用 |
| --- | --- |
| `check_for_update(url)` | 读取 `version.json`，返回 `(info, error)` |
| `download_update(url, progress, mirror)` | 下载新版本（含镜像回退） |
| `apply_update(downloaded_path)` | 暂存新 EXE 并拉起更新进程 |
| `finish_pending_update()` | 以 `--apply-update` 启动时完成文件替换 |
| `cleanup_update_leftovers()` | 正常启动时清理残留临时文件 |

## 本地测试更新

1. 构建测试运行版（版本号低于待发布版），放入测试目录：
   ```powershell
   # 临时把 CURRENT_VERSION 改低，然后：
   .\venv\Scripts\python.exe -m PyInstaller PalModManager.spec --noconfirm
   Copy-Item dist\PalModManager.exe -Destination "<测试目录>\PalModManager.exe" -Force
   ```
2. `build.bat <新版本号>` 出正式版，把 `dist\PalModManager.exe` 上传到对应 GitHub Release。
3. 运行测试目录的程序 → 检查更新 → 应自动关闭并重新以新版本打开。

### 测试 Mod 合集扫描

1. 运行程序 → 文件 → 扫描 Mod 合集目录 → 选择整理好的合集目录（如 `幻兽帕鲁Mod合集`）。
2. 主列表应出现所有 Mod（带「合集」标签），且说明正确显示（如 mod 同级/上一级的 `使用说明.txt`）。
3. 点击「是」可将合集 Mod 一键导入到当前游戏/服务器目录。

---

## WinUI 3 重构（实验性）

正在新增基于 C# + WinUI 3 的新界面，保留 Python 后端作为本地 API，以获得更原生的 Windows 观感。

### 新工程结构

```
PalModManager.WinUI/                 # C# WinUI 3 前端
├── PalModManager.WinUI.sln
├── PalModManager.WinUI/
│   ├── App.xaml(.cs)                # 启动后端、应用主题、静默检查更新
│   ├── MainWindow.xaml(.cs)         # 顶栏 + NavigationView + 更新流程
│   ├── Views/                       # ModsPage（含 ModsViewModel）/ SettingsPage / ProfileDialog
│   ├── Controls/BusyDialog.cs       # 长任务进度弹窗（支持百分比进度）
│   ├── Services/                    # BackendClient（HTTP）/ BackendProcessService（子进程生命周期）
│   └── Themes/ThemeResources.xaml   # 明暗配色与卡片、标题样式
└── PalModManager.Core/              # C# 共享模型（ModInfo / AppConfigDto）
src/backend/                         # Python HTTP API 包装层
├── api_server.py                    # 入口：随机端口 + 父进程退出看门狗
├── api_routes.py                    # /api/* 端点，复用 src/core 的既有逻辑
└── app_state.py                     # 配置与 ModManager 实例缓存
```

### 已实现功能（WinUI 版）

- Mod 列表：加载、刷新、搜索、按类型/状态筛选、顶部统计（总数/启用/禁用/冲突）。
- 单个启用/禁用、全部启用/全部禁用、卸载（带二次确认，返回备份失败提示）。
- 导入 Mod、导出 Mod 合集（返回数量与错误明细）、修复文件结构、启动游戏/服务器。
- 顶栏客户端 ⇄ 服务器模式切换，列表、方案、框架、启动等操作随之切换目标目录。
- Mod 方案（Profile）：列表 / 新建 / 删除 / 加载。
- 设置：游戏与服务器路径（浏览 + 自动检测）、框架状态展示与一键安装、客户端↔服务器同步、深浅主题（写入配置并即时应用）。
- 更新：检查新版本 → 确认 → SSE 流式下载（显示百分比）→ 打开下载位置。
- 长任务统一使用进度弹窗，错误统一通过 InfoBar 展示后端返回的中文原因。

### 构建 WinUI 3 版本

要求：
- .NET 8 SDK（Windows App SDK 通过 NuGet 包引入，编译不需要 Visual Studio 工作负载）
- 运行需要 Windows App Runtime 1.6；`scripts\build_winui.bat` 的自包含发布产物不依赖它
- Python 3.x（已安装 `requirements.txt` 依赖，含 flask）

运行：

```bat
scripts\build_winui.bat
```

输出目录：`build\winui\app`

### 后端 API

启动后端（开发调试）：

```bat
python -m src.backend.api_server --port 5000
```

前端默认连接 `http://127.0.0.1:5000`。

### 已知限制

- **已验证（2026-09-08，.NET SDK 8.0.424）**：Debug 与 Release 自包含发布均 0 错误 0 警告；实际启动确认后端随进程拉起、Mod 列表与统计行加载、静默检查更新返回「已是最新版本」、顶栏切换到服务器模式后列表/标题/启动按钮随之改变，关闭窗口后后端看门狗正常退出。
- 在 Visual Studio 2022 中打开 `.sln` 需要额外安装「.NET 桌面开发」组件（本机 VS 只装了 MSBuild，没有 .NET SDK，命令行用 `dotnet build` 即可）。
- **客户端/服务器模式切换**：顶栏「客户端 / 服务器」药丸按钮切换当前管理的安装目录（未配置对应路径时拒绝切换并提示去设置）。模式存在 `BackendClient.Mode`，所有端点的 `mode` 参数默认取该值，因此 Mod 列表、启用/禁用、导入导出、修复、启动、框架安装、Mod 方案都会跟着切换；方案本身按安装目录哈希分别存储，两种模式互不可见。
- **合集扫描未实现**：`ModManager` / `ModScanner` 没有扫描任意合集目录的能力（PyQt 版同一条路径会抛 `AttributeError`），因此 `/api/collection/scan` 明确返回 501，前端提示改用「导入」。
- **未移植「启动服务器后台」按钮**：PyQt 版该按钮硬编码启动个人机器上的 `E:\Pal work\pst_v0.12.2_windows_x86_64\start.bat`，且当前项目内并不存在这个路径，不适合作为通用功能进入新前端。
- **不提供原地自更新**：`updater.apply_update()` 替换的是 `sys.executable`，在「C# 前端 + Python 后端」结构下那是 `python.exe`，暴露该端点会覆盖用户的 Python 安装；且 releases 中的产物是 PyQt 单文件 exe，与该前端并非同一程序。故后端仅开放检查与下载，`/api/update/apply` 已移除。若要真正的自动更新，需要先让 WinUI 版发布独立产物（单文件 exe 或 MSIX），并在 C# 侧实现替换逻辑。
