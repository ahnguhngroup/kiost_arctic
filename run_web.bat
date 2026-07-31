@echo off
REM ============================================================
REM run_web.bat
REM Arctic data viewer - start local HTTP server and open browser
REM
REM index.html fetches catalog.json / COG files, so opening it
REM with file:// does not work. range_server.py serves HTTP Range
REM requests, so a large COG loads only the bytes it needs.
REM
REM Usage: run_web.bat [port]
REM   port : listen port (default 8000)
REM
REM Python lookup order:
REM   1. ARCTIC_PYTHON env var (full path to python.exe) - override
REM   2. conda root from CONDA_EXE / "where conda" / common paths,
REM      then the CONDA_ENV env below
REM   3. "python" on PATH, then "py -3"
REM   4. python.org / OSGeo4W default install paths
REM
REM ASCII-only file. A .bat saved as UTF-8 with Korean text is
REM mis-parsed by cmd under CP949 and comment lines get executed
REM as commands. Korean console output comes from Python instead.
REM ============================================================
setlocal EnableExtensions
cd /d "%~dp0"

set "CONDA_ENV=ahnguhn"

set "PORT=%~1"
if "%PORT%"=="" set "PORT=8000"

if not exist "range_server.py" (
    echo [error] range_server.py not found in "%CD%"
    pause
    exit /b 1
)

set "PY="
set "CROOT="

REM ---- 0) explicit override ------------------------------------
if defined ARCTIC_PYTHON if exist "%ARCTIC_PYTHON%" set "PY="%ARCTIC_PYTHON%""

REM ---- 1) locate the conda/miniconda/miniforge root -------------
if defined CONDA_EXE for %%I in ("%CONDA_EXE%") do for %%J in ("%%~dpI..") do set "CROOT=%%~fJ"

if not defined CROOT (
    for /f "delims=" %%I in ('where conda 2^>nul') do (
        if not defined CROOT for %%J in ("%%~dpI..") do set "CROOT=%%~fJ"
    )
)

if not defined CROOT (
    for %%R in (
        "%USERPROFILE%" "%LOCALAPPDATA%" "C:\ProgramData" "C:" "D:"
        "%ProgramFiles%" "%ProgramData%"
    ) do (
        for %%N in (
            anaconda3 Anaconda3 anaconda Anaconda
            miniconda3 Miniconda3 miniconda Miniconda
            miniforge3 Miniforge3 mambaforge micromamba
        ) do (
            if not defined CROOT if exist "%%~R\%%N\python.exe" set "CROOT=%%~R\%%N"
        )
    )
)

REM ---- 2) python from the named conda env ----------------------
if not defined PY if defined CROOT (
    if exist "%CROOT%\envs\%CONDA_ENV%\python.exe" set "PY="%CROOT%\envs\%CONDA_ENV%\python.exe""
)
if not defined PY if exist "%USERPROFILE%\.conda\envs\%CONDA_ENV%\python.exe" set "PY="%USERPROFILE%\.conda\envs\%CONDA_ENV%\python.exe""
if not defined PY if defined CROOT (
    if exist "%CROOT%\python.exe" set "PY="%CROOT%\python.exe""
)

REM ---- 3) python already on PATH -------------------------------
REM Plain "python" may be the Microsoft Store alias stub, which
REM only prints "Python was not found" - so verify it executes.
if not defined PY (
    python -c "import sys" >nul 2>nul
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    py -3 -c "import sys" >nul 2>nul
    if not errorlevel 1 set "PY=py -3"
)

REM ---- 4) other common install paths ---------------------------
if not defined PY (
    for %%D in (
        "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
        "C:\OSGeo4W\bin\python3.exe"
        "C:\Python313\python.exe" "C:\Python312\python.exe"
        "C:\Python311\python.exe" "C:\Python310\python.exe"
    ) do (
        if not defined PY if exist %%D set "PY=%%D"
    )
)

if not defined PY (
    echo.
    echo [error] Python 3 was not found.
    echo.
    echo   conda root detected : "%CROOT%"
    echo   conda env looked for: "%CONDA_ENV%"
    echo.
    echo   Fix by pointing this script straight at your python.exe:
    echo     set ARCTIC_PYTHON=C:\path\to\envs\%CONDA_ENV%\python.exe
    echo     run_web.bat
    echo   To find that path, open Anaconda Prompt and run:
    echo     conda activate %CONDA_ENV%  ^&^&  where python
    echo.
    echo   The Microsoft Store alias is not a real install. Turn it off:
    echo     Settings ^> Apps ^> Advanced app settings
    echo     ^> App execution aliases ^> python.exe / python3.exe OFF
    echo.
    pause
    exit /b 1
)

REM ---- 5) open the browser ~2s after the server starts ---------
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://localhost:%PORT%/index.html'" >nul 2>nul

echo.
echo  Arctic data viewer : http://localhost:%PORT%
echo  Python             : %PY%
echo  Press Ctrl+C to stop the server.
echo.

%PY% range_server.py %PORT%

endlocal
