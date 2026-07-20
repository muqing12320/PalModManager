@echo off
setlocal enabledelayedexpansion

set VERSION=%1

:ASK
if defined VERSION goto :CHECK
set /p VERSION="Enter version: "

:CHECK
git ls-remote --tags origin "v!VERSION!" 2>nul | findstr /C:"v!VERSION!" >nul
if %ERRORLEVEL% NEQ 0 goto :BUILD

echo [WARN] Tag v!VERSION! already exists on GitHub!
set VERSION=
goto :ASK

:BUILD
echo ======== Release v!VERSION! ========

:: 1. version.json
venv\Scripts\python.exe -c "import json,io;v='!VERSION!';json.dump({'version':v,'download_url':'https://github.com/muqing12320/PalModManager/releases/download/v'+v+'/PalModManager.exe','mirror_url':'https://zyx123.xyz/PalModManager.exe','notes':'v'+v},io.open('version.json','w',encoding='utf-8'),ensure_ascii=False)"
echo [OK] version.json

:: 2. updater.py
powershell -Command "(gc src/utils/updater.py -Raw -Encoding UTF8) -replace 'CURRENT_VERSION = \""[\d.]+\""', 'CURRENT_VERSION = \""!VERSION!\""' | sc src/utils/updater.py -Encoding UTF8 -NoNew"
echo [OK] updater.py

:: 3. Build
echo Building...
venv\Scripts\python.exe -m PyInstaller PalModManager.spec --noconfirm
if %ERRORLEVEL% NEQ 0 (echo BUILD FAILED & exit /b 1)

:: Normalize EXE name to PalModManager.exe (for consistent download URL)
if exist "dist\PalModManager.exe" del /f "dist\PalModManager.exe" 2>nul
for %%f in (dist\*.exe) do (
    move /y "%%f" "dist\PalModManager.exe" >nul 2>&1
)
echo [OK] Built (dist\PalModManager.exe)

:: 4. Git
git add .
git commit -m "v!VERSION!"
git tag "v!VERSION!"
git push
git push origin "v!VERSION!"
echo [OK] Pushed

:: 5. Open release page
start https://github.com/muqing12320/PalModManager/releases/new?tag=v!VERSION!^&title=v!VERSION!
echo Open page and upload dist\PalModManager.exe
