@echo off
setlocal enabledelayedexpansion

:: Build PalModManager WinUI 3 frontend + backend
:: Requirements: .NET 8 SDK, Python 3.x with requirements.txt installed

set ROOT=%~dp0..
cd /d "%ROOT%"

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
xcopy /E /I /Y "src" "build\winui\app\src" >nul
if errorlevel 1 goto :fail
xcopy /E /I /Y "resources" "build\winui\app\resources" >nul
if errorlevel 1 goto :fail

echo Done. Output: %ROOT%\build\winui\app

set ISCC=
where iscc >nul 2>&1 && set ISCC=iscc
if "%ISCC%"=="" if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if "%ISCC%"=="" if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if "%ISCC%"=="" if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"

if defined ISCC (
    echo [4/4] Generating installer...
    %ISCC% "scripts\installer.iss"
    if errorlevel 1 goto :fail
    echo Installer output: %ROOT%\build\installer
) else (
    echo [Skip] Inno Setup not found, skipping installer generation.
    echo        Install from https://jrsoftware.org/isdl.php then re-run this script.
)

endlocal
exit /b 0

:fail
echo Build failed.
endlocal
exit /b 1
