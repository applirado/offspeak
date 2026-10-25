@echo off
rem Double-click to install OffSpeak; options are passed on to setup.ps1 (e.g. setup.cmd -NoAutostart).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
if errorlevel 1 (echo. & echo Setup failed, see the messages above.)
pause
