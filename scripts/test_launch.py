import os
exe = r"C:\Users\XOS\Desktop\更新mod\版本\PalModManager.exe"
lines = [
    'Set ws = CreateObject("WScript.Shell")',
    'Set fs = CreateObject("Scripting.FileSystemObject")',
    f'exe = "{exe}"',
    'WScript.Sleep 2000',
    'c = "cmd.exe /c start " & Chr(34) & Chr(34) & " " & Chr(34) & exe & Chr(34)',
    'ws.Run c, 0, False',
    'WScript.Sleep 1000',
    'WScript.Quit',
]
with open(r"C:\Users\XOS\Desktop\更新mod\版本\test_launch.vbs", 'w', newline='') as f:
    f.write('\r\n'.join(lines))
print("Written")
