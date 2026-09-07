@echo off
setlocal enabledelayedexpansion

:: Build PalModManager WinUI 3 frontend + backend
:: Requirements: .NET 8 SDK, Python 3.x with requirements.txt installed

set ROOT=%~dp0..
cd /d "%ROOT%"

:: Read current version from updater.py as default
for /f "tokens=2 delims== " %%v in ('findstr /b "CURRENT_VERSION" src\utils\updater.py') do set DEFAULT_VER=%%~v
set /p APP_VERSION="Enter version [%DEFAULT_VER%]: "
if "%APP_VERSION%"=="" set APP_VERSION=%DEFAULT_VER%

:: Update version in source files
set PAL_VER=%APP_VERSION%
powershell -NoProfile -Command "$v=$env:PAL_VER; $q=[char]34; $e=New-Object Text.UTF8Encoding $false; $p=(Resolve-Path 'src\utils\updater.py').Path; $c=[IO.File]::ReadAllText($p); $c=$c -replace 'CURRENT_VERSION\s*=\s*.*', ('CURRENT_VERSION = '+$q+$v+$q); [IO.File]::WriteAllText($p,$c,$e)"
powershell -NoProfile -Command "$v=$env:PAL_VER; $q=[char]34; $e=New-Object Text.UTF8Encoding $false; $p=(Resolve-Path 'scripts\installer.iss').Path; $c=[IO.File]::ReadAllText($p); $c=$c -replace '(?m)^#define MyAppVersion\s+.*', ('#define MyAppVersion '+$q+$v+$q); [IO.File]::WriteAllText($p,$c,$e)"
echo Version set to %APP_VERSION%

cmd /c "tasklist /FI ""IMAGENAME eq PalModManager.WinUI.exe"" 2>nul | find /I ""PalModManager.WinUI.exe""" >nul 2>&1
if not errorlevel 1 (
    echo [0/3] Closing running instance...
    taskkill /F /IM PalModManager.WinUI.exe >nul 2>&1
    timeout /t 2 /nobreak >nul
)

echo [1/3] Installing Python dependencies...
python -m pip install -r requirements.txt

echo [2/3] Publishing WinUI 3 app (self-contained)...
dotnet publish "PalModManager.WinUI\PalModManager.WinUI\PalModManager.WinUI.csproj" -c Release -r win-x64 --self-contained true -p:WindowsAppSDKSelfContained=true -p:EnableMsixTooling=true -o "build\winui\app"
if errorlevel 1 goto :fail

echo [3/3] Copying backend files...
if exist "build\winui\app\src" rd /s /q "build\winui\app\src"
if exist "build\winui\app\resources" rd /s /q "build\winui\app\resources"
xcopy /E /I /Y "src" "build\winui\app\src" >nul
if errorlevel 1 goto :fail
xcopy /E /I /Y "resources" "build\winui\app\resources" >nul
if errorlevel 1 goto :fail

echo Done. Output: %ROOT%\build\winui\app

set "ISCC="
where iscc >nul 2>&1 && set "ISCC=iscc"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"

if not defined ISCC goto :skip_installer
echo [4/4] Generating installer...
"%ISCC%" "scripts\installer.iss"
if errorlevel 1 goto :fail
echo Installer output: %ROOT%\build\installer
goto :end

:skip_installer
echo [Skip] Inno Setup not found, skipping installer generation.
echo        Install from https://jrsoftware.org/isdl.php then re-run this script.

:end
endlocal
exit /b 0

:fail
echo Build failed.
pause
endlocal
exit /b 1
