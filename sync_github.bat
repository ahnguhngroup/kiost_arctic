@echo off
REM Wipe GitHub Data_Out, then copy the current web folder.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0sync_github.ps1"
if errorlevel 1 exit /b 1
