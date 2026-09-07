$url = "https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe"
$out = "$env:TEMP\innosetup.exe"
Write-Host "Downloading Inno Setup..."
Invoke-WebRequest -Uri $url -OutFile $out
Write-Host "Installing silently..."
Start-Process -FilePath $out -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART' -Wait
Write-Host "Done. Checking ISCC..."
if (Test-Path "C:\Program Files (x86)\Inno Setup 6\ISCC.exe") {
    Write-Host "Found at C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
} elseif (Test-Path "C:\Program Files\Inno Setup 6\ISCC.exe") {
    Write-Host "Found at C:\Program Files\Inno Setup 6\ISCC.exe"
} else {
    Write-Host "ISCC.exe not found in default locations"
}
