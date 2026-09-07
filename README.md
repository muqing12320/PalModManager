# PalModManager（帕鲁 Mod 管理器）

> 当前版本：**v1.2.12**

Palworld 的 Mod 管理器，支持 UE4SS Lua Mod 与 PAK Mod 的启用/禁用、状态同步，以及程序自身的**自动更新**。

- 技术栈：C# WinUI 3 前端（`PalModManager.WinUI/`）+ Python Flask 后端（`src/backend/`），前端通过本地 HTTP 调用后端
- 入口：`PalModManager.WinUI/PalModManager.WinUI/MainWindow.xaml.cs`（负责拉起 `src.backend.api_server` 作为后端进程）
- 打包：`scripts\build_winui.bat`（提示输入版本号 → dotnet publish → 复制后端 → 调 Inno Setup 出安装包）
- 安装包产物：`build\installer\PalModManager-Setup.exe`
- 当前版本号：`src/utils/updater.py` 的 `CURRENT_VERSION`（构建脚本会自动写入）

## 目录结构

```
pal-mod-manager/
├── PalModManager.WinUI/     # C# WinUI 3 前端
├── scripts/
│   ├── build_winui.bat      # 构建前端 + 生成安装包
│   ├── installer.iss        # Inno Setup 安装脚本
│   ├── install_inno.ps1     # 安装 Inno Setup
│   └── download_cn_lang.ps1 # 下载简体中文语言文件（Inno Setup 不自带）
├── main.py                  # 旧版 PyQt5 界面入口（仅开发用，不参与发布）
├── version.json             # 版本信息（被程序读取以检查更新）
├── resources/               # 应用图标、框架压缩包（UE4SS / PalSchema）
├── src/
│   ├── backend/             # Flask API 层（供 WinUI 前端调用）
│   ├── ui/                  # 旧版 PyQt5 界面（仅开发用，不参与发布）
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

发版只发布 Inno Setup 安装包，自更新不再做原地文件替换：下载 `PalModManager-Setup.exe` → 静默运行 → 由安装包负责替换文件并重启应用。这样避开了在 Windows 上手工换文件所遇到的文件锁、权限与残留问题。

### 版本检查

- `updater.CURRENT_VERSION`：当前程序版本号（位于 `src/utils/updater.py` 顶部，由 `scripts\build_winui.bat` 自动写入）。
- 程序启动后读取 `version.json`（`UPDATE_URL`，即仓库 `main` 分支上的文件）。
- 通过 `_version_le()` 归一化比较（去掉 `v` 前缀、忽略非数字部分）。若远端版本号更高，则提示更新。

### 下载安装包

`download_update()` 优先追速度、逐级降级：

1. **urllib 多线程分片**：把文件切成每段约 4MB 的 Range 区间并行下载。在按连接限速的代理网络下多连接可叠加带宽（实测 4~8 倍提速）。优先走 `ghproxy.net` 镜像，失败回退直连。
2. **urllib 单连接**：自动重试，保证进度持续推进。
3. **requests 单连接**：极端情况兜底。

每一段都带断点续传与重试，下载完成后校验文件总大小。全程通过 SSE（`/api/update/download-stream`）向前端回报进度。

### 安装包静默升级流程（核心）

发版只发布 Inno Setup 安装包，自更新不再做原地文件替换：

1. **检查**：`check_for_update()` 读取仓库 `main` 分支上的 `version.json`，比较 `version` 与 `CURRENT_VERSION`。
2. **下载**：前端调 `/api/update/download-stream`；后端重新读一次 `version.json` 取出 `download_url`（指向 `PalModManager-Setup.exe`）后下载。
3. **安装**：`MainWindow.xaml.cs` 下载完成后直接以 `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS` 拉起安装包，随后 `Application.Current.Exit()` 退出释放文件锁。
4. **重启**：`installer.iss` 的 `[Run]` 段不带 `skipifsilent`，因此静默安装结束时会自动启动新版本。

> 配置与 Mod 数据放在 `%APPDATA%\帕鲁Mod管理器\`，安装过程只替换安装目录，不会动用户数据。
>
> 校验：安装包下载后检查 `MZ` 头且体积大于 1MB，避免把 HTML 错误页当成 exe 执行。

### 相关函数（`src/utils/updater.py`）

| 函数 | 作用 |
| --- | --- |
| `check_for_update(url)` | 读取 `version.json`，返回 `(info, error)` |
| `download_update(url, progress, cancel_check, method_cb)` | 下载新版本安装包（分片 + 镜像回退 + 断点续传） |
| `apply_update(downloaded_path)` | 静默拉起安装包（旧版 PyQt5 界面路径用；WinUI 流程由 C# 侧完成） |
| `cleanup_update_leftovers()` | 正常启动时清理残留临时文件 |

## 本地测试更新

1. 用较低版本号构建并安装一个旧版本：
   ```powershell
   scripts\build_winui.bat        # 输入一个较低的版本号，如 1.2.12
   build\installer\PalModManager-Setup.exe
   ```
2. 用新版本号重新构建，把新的 `build\installer\PalModManager-Setup.exe` 上传到对应的 GitHub Release，并把仓库里的 `version.json` 的 `version` 与 `download_url` 更新到该版本后推送。
3. 运行旧版本 → 检查更新 → 下载安装包 → 应自动静默安装并重新以新版本打开。

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
- **自更新的安装动作在 C# 侧**：升级由 `MainWindow.xaml.cs` 直接静默拉起安装包完成。后端刻意不暴露 `/api/update/apply`：`updater.apply_update()` 用 `sys.executable` 推导安装目录，在「C# 前端 + Python 后端」结构下那是 `python.exe` 的目录，据此安装会写错位置。该函数只保留给旧版 PyQt5 界面路径。
