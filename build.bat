@echo off
set VERSION=%1
if "%VERSION%"=="" set /p VERSION="Enter version: "
echo ======== Release v%VERSION% ========

:: 1. Update version.json
venv\Scripts\python.exe -c "import json,io;v='%VERSION%';json.dump({'version':v,'download_url':'https://github.com/muqing12320/PalModManager/releases/download/v'+v+'/Mod.exe','notes':'v'+v},io.open('version.json','w',encoding='utf-8'),ensure_ascii=False)"
echo [OK] version.json

:: 2. Update updater.py
powershell -Command "(gc src/utils/updater.py -Raw -Encoding UTF8) -replace 'CURRENT_VERSION = \""[\d.]+\""', 'CURRENT_VERSION = \""%VERSION%\""' | sc src/utils/updater.py -Encoding UTF8 -NoNew"
echo [OK] updater.py

:: 3. Build
echo Building...
venv\Scripts\python.exe -m PyInstaller PalModManager.spec --noconfirm
if %ERRORLEVEL% NEQ 0 (echo BUILD FAILED & exit /b 1)
echo [OK] Built

:: 4. Git
git add .
git commit -m "v%VERSION%"
git tag "v%VERSION%"
git push
git push origin "v%VERSION%"
echo [OK] Pushed

:: 5. Open release page
start https://github.com/muqing12320/PalModManager/releases/new?tag=v%VERSION%^&title=v%VERSION%
echo Open the page and upload dist\Mod.exe
