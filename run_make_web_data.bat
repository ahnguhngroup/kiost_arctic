@echo off
REM ============================================================
REM run_make_web_data.bat
REM Build web viewer data from the utils pipeline output.
REM
REM   E:\workspace2026\arctic\test_data\Data_Out\<model>\yyyy\mm\dd  (model GeoTIFF)
REM       -> web\Data_Out\<model>\yyyy\mm\dd\*_EPSG3413_cog.tif  (Byte COG,
REM          same dated-folder rule as Data_Out)
REM       -> web\data\catalog.json / descriptions.json
REM       -> web\data\route_nsr.geojson
REM
REM Date folder selection (--date):
REM   folder (default) : each product's FINAL (newest) yyyy\mm\dd folder is
REM                      used as-is - assumes one date folder per product;
REM                      if several exist the newest is taken with a warning.
REM   today | yesterday | YYYYMMDD | latest : pin one reference date and read
REM                      only that date folder (older behaviour).
REM Before converting, web\Data_Out is emptied so only the selected data
REM remains (smallest footprint). --keep-others keeps satellite folders,
REM --no-purge keeps everything (old accumulating behaviour).
REM
REM Usage: run_make_web_data.bat [extra args passed to the python script]
REM   run_make_web_data.bat                       final date folder per product
REM   run_make_web_data.bat --dry-run             list only, no conversion/purge
REM   run_make_web_data.bat --date 20260801       specific reference date
REM   run_make_web_data.bat --date latest         newest reference date in Data_Out
REM   run_make_web_data.bat --models topaz5_1d riops_2d
REM   run_make_web_data.bat --vars siconc sithick
REM   run_make_web_data.bat --lat-min 60 --keep-others
REM   run_make_web_data.bat --no-sat               models only
REM   run_make_web_data.bat --sat amsr2_l2_SIC asip_l3   selected satellite products
REM   run_make_web_data.bat --sat-extra viirs_29   also VIIRS/ICESat-2 (off by default)
REM Satellite products (SAT_PRODUCTS in the script) are copied as-is: every
REM file of the reference date (all swath passes) becomes a catalog item.
REM
REM Needs gdal(osgeo) + numpy + pillow -> use the utils conda env.
REM ASCII-only file (cmd mis-parses UTF-8 Korean under CP949).
REM ============================================================
setlocal EnableExtensions
cd /d "%~dp0"

set "CONDA_ENV=ahnguhn"
set "PY="
set "CROOT="

if defined ARCTIC_PYTHON if exist "%ARCTIC_PYTHON%" set "PY="%ARCTIC_PYTHON%""

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
if not defined PY if defined CROOT (
    if exist "%CROOT%\envs\%CONDA_ENV%\python.exe" set "PY="%CROOT%\envs\%CONDA_ENV%\python.exe""
)
if not defined PY if exist "%USERPROFILE%\.conda\envs\%CONDA_ENV%\python.exe" set "PY="%USERPROFILE%\.conda\envs\%CONDA_ENV%\python.exe""
if not defined PY if defined CROOT (
    if exist "%CROOT%\python.exe" set "PY="%CROOT%\python.exe""
)
if not defined PY (
    python -c "from osgeo import gdal" >nul 2>nul
    if not errorlevel 1 set "PY=python"
)

if not defined PY (
    echo.
    echo [error] No GDAL-capable Python found.
    echo   conda root : "%CROOT%"   env : "%CONDA_ENV%"
    echo   In Anaconda Prompt, run this to find the path:
    echo     conda activate %CONDA_ENV%  ^&^&  where python
    echo   then:  set ARCTIC_PYTHON=^<that path^>  and run again.
    echo.
    pause
    exit /b 1
)

echo.
echo  Python : %PY%
echo.
%PY% tools\make_web_data.py %*
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" echo [error] exit code %RC%
pause
endlocal
exit /b %RC%
