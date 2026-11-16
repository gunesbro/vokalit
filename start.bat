@echo off
setlocal
cd /d "%~dp0"

if not exist "app\requirements.txt" (
    echo Project files not found. Extract the zip to a folder first, then run start.bat from there.
    goto :fail
)

rem uv is used to set up Python. Use the copy inside this folder, a system-wide one, or download it.
set "UV_VERSION=0.11.32"
set "UV=%CD%\.local\uv\uv.exe"
if exist "%UV%" goto :have_uv
where uv >nul 2>&1
if not errorlevel 1 (
    set "UV=uv"
    goto :have_uv
)
echo Vokalit needs uv (a Python package manager) to set itself up.
echo It will be downloaded from GitHub (astral-sh/uv %UV_VERSION%, about 20 MB) into .local\uv\
echo Nothing outside this folder is changed.
set "ANSWER="
set /p "ANSWER=Download uv now? [y/N] "
if /i not "%ANSWER%"=="y" goto :fail
mkdir ".local\uv" 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Invoke-WebRequest -Uri 'https://github.com/astral-sh/uv/releases/download/%UV_VERSION%/uv-x86_64-pc-windows-msvc.zip' -OutFile '.local\uv\uv.zip'; Expand-Archive -Path '.local\uv\uv.zip' -DestinationPath '.local\uv' -Force; Remove-Item '.local\uv\uv.zip'" || goto :fail
if not exist "%UV%" (
    echo uv download failed.
    goto :fail
)
:have_uv

rem Keep everything inside the project folder.
set "UV_CACHE_DIR=%CD%\.local\uv-cache"
set "UV_PYTHON_INSTALL_DIR=%CD%\.local\python"
set "GRADIO_ANALYTICS_ENABLED=False"
set "HF_HUB_DISABLE_TELEMETRY=1"
set "GRADIO_TEMP_DIR=%CD%\.local\tmp"

set "VENV=.local\app\venv"
if not exist "%VENV%" (
    "%UV%" venv --python 3.11 "%VENV%" || goto :fail
)
"%UV%" pip install --python "%VENV%\Scripts\python.exe" -r app\requirements.txt || goto :fail
"%VENV%\Scripts\python.exe" app\main.py || goto :fail
exit /b 0

:fail
echo.
echo Vokalit could not start. See the message above.
pause
exit /b 1
