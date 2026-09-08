@echo off
REM Stop YT-Personal-Saver background server
schtasks /end /tn "YT-Personal-Saver" >nul 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*server.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host \"Stopped PID $($_.ProcessId)\" }"
echo Done. Server stopped.
pause
