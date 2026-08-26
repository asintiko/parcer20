@echo off
setlocal
set TARGET=%ProgramData%\TBSparcer\security
if not exist "%TARGET%" mkdir "%TARGET%"
copy /Y "%~dp0client-access.json" "%TARGET%\client-access.json"
echo.
echo Config copied to: %TARGET%\client-access.json
echo Launch TBSparcer from Start Menu.
pause
