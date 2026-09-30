@echo off
REM Wipe GitHub Data_Out, copy the current web folder, then git commit + push.
REM   sync_github.bat                  -> commit "web sync <date>" + push
REM   sync_github.bat "my message"     -> commit with custom message + push
REM   sync_github.bat -NoPush          -> commit only
REM   sync_github.bat -NoCommit        -> copy + stage only (no git commit/push)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0sync_github.ps1" %*
if errorlevel 1 exit /b 1
