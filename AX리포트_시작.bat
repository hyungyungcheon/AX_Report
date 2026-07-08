@echo off
cd /d "%~dp0"
title AX Intelligence Report Server
echo.
echo  Starting AX Report server... (browser will open automatically)
echo  To stop: close this window or press Ctrl+C
echo.
python ax_report.py --serve
pause
