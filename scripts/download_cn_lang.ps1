$url = "https://raw.githubusercontent.com/jrsoftware/issrc/main/Files/Languages/ChineseSimplified.isl"
$dest = "$env:LOCALAPPDATA\Programs\Inno Setup 6\Languages\ChineseSimplified.isl"
Write-Host "Downloading..."
Invoke-WebRequest -Uri $url -OutFile $dest
if (Test-Path $dest) { Write-Host "OK: $dest" } else { Write-Host "FAILED" }
