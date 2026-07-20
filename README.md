# PalModManager（帕鲁 Mod 管理器）

Palworld 的 Mod 管理器，支持 UE4SS Lua Mod 与 PAK Mod 的启用/禁用、状态同步，以及程序自身的**自动更新**。

- 技术栈：Python 3 + PyQt5 + PyInstaller（`--onefile --windowed`）
- 入口：`main.py`
- 打包：`build.bat <版本号>`（自动生成 `version.json`、构建、提交并打 Git tag、打开发布页）

## 目录结构

```
pal-mod-manager/
├── main.py              # 程序入口
├── build.bat            # 打包/发布脚本
├── PalModManager.spec   # PyInstaller 配置
├── version.json         # 版本信息（被程序读取以检查更新）
├── src/
│   ├── ui/              # 界面（main_window / settings_page / styles）
│   ├── core/            # 业务逻辑（manager 等）
│   └── utils/
│       └── updater.py   # 自更新核心逻辑
└── dist/                # 打包产物 PalModManager.exe
```

## 自更新机制

更新流程的关键是**彻底避开“从 .bat / VBS 脚本里启动新 EXE”**这一在 Windows 上不稳定的环节，改为由程序自身用 `subprocess` 拉起另一个进程完成替换。

### 版本检查

- `updater.CURRENT_VERSION`：当前程序版本号（由 `build.bat` 在打包时写入）。
- 程序启动后读取 `version.json`（`UPDATE_URL`，即仓库 `main` 分支上的文件）。
- 通过 `_version_le()` 归一化比较（去掉 `v` 前缀、忽略非数字部分）。若远端版本号更高，则提示更新。

### 双进程替换流程（核心）

1. **下载**：`download_update()` 以 512KB 缓冲区下载新 EXE 到临时文件，失败自动尝试 `mirror_url` 镜像。
2. **暂存**：`apply_update()` 把下载好的新 EXE 复制为同目录下的 `PalModManager_new.exe`（与最终文件名不同，避免被运行中的文件锁住），然后用 **`subprocess.Popen`（脱离父进程 + 清掉 `_MEIPASS` 环境变量）** 直接拉起它，并传入 `--apply-update` 参数。随后当前程序立即 `os._exit(0)` 退出、释放文件锁。
3. **替换**：新进程（`PalModManager_new.exe`）启动时，`main.py` 最开头调用 `finish_pending_update()` 检测到 `--apply-update`，执行：
   - 等待约 3 秒，确保旧程序已退出并释放文件句柄；
   - 把旧 `PalModManager.exe` 改名备份为 `PalModManager.exe.bak`（Windows 允许对运行中的 EXE 改名）；
   - 把 `PalModManager_new.exe` 复制为最终的 `PalModManager.exe`（带重试）；
   - 再用 `subprocess` 拉起最终的 `PalModManager.exe`；
   - 当前 `_new.exe` 进程 `os._exit(0)` 退出。
4. **最终启动**：最终 `PalModManager.exe` 正常运行；`cleanup_update_leftovers()` 在启动时清理残留的 `PalModManager_new.exe` 与 `PalModManager.exe.bak`。

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
