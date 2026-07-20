# 一键发布脚本 - 帕鲁Mod管理器
# 用法: .\release.ps1 [版本号]

param([string]$Version = "")

$ErrorActionPreference = "Stop"
if (-not $Version) { $Version = Read-Host "请输入版本号 (如 1.0.1)" }
if (-not $Version) { Write-Host "版本号不能为空" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "======== 帕鲁Mod管理器 v$Version 发布 ========" -ForegroundColor Cyan

# 1. 更新 version.json
$vj = '{"version":"' + $Version + '","download_url":"https://github.com/muqing12320/PalModManager/releases/download/v' + $Version + '/Mod.exe","notes":"v' + $Version + ' 版本更新"}'
[System.IO.File]::WriteAllText("$PSScriptRoot\version.json", $vj, (New-Object System.Text.UTF8Encoding $false))
Write-Host "[OK] version.json" -ForegroundColor Green

# 2. 更新 updater.py
$up = "$PSScriptRoot\src\utils\updater.py"
(Get-Content $up -Encoding UTF8 -Raw) -replace 'CURRENT_VERSION = "[\d.]+"', ('CURRENT_VERSION = "' + $Version + '"') | Set-Content $up -Encoding UTF8 -NoNewline
Write-Host "[OK] updater.py" -ForegroundColor Green

# 3. 打包
Write-Host "正在打包..." -ForegroundColor Yellow
& "$PSScriptRoot\venv\Scripts\python.exe" -m PyInstaller PalModManager.spec --noconfirm
if ($LASTEXITCODE -ne 0) { Write-Host "[FAIL] 打包失败" -ForegroundColor Red; exit 1 }
$mb = [math]::Round((Get-Item "$PSScriptRoot\dist\帕鲁Mod管理器.exe").Length / 1MB, 1)
Write-Host "[OK] 打包完成 (${mb}MB)" -ForegroundColor Green

# 4. 提交 Git
Write-Host "提交 Git..." -ForegroundColor Yellow
git add .
git commit -m "v$Version"
git tag "v$Version"
git push
git push origin "v$Version"
Write-Host "[OK] 已推送" -ForegroundColor Green

# 5. 打开 Release 页面
Write-Host ""
Write-Host "打开 GitHub Release 页面，拖入 dist\Mod.exe 即可" -ForegroundColor Cyan
Start-Process "https://github.com/muqing12320/PalModManager/releases/new?tag=v$Version&title=v$Version"
