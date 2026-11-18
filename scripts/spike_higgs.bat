@echo off
rem Throwaway: runs scripts\spike_higgs.py (see its docstring) with the app's own uv and Python.
cd /d "%~dp0.."
set "UV_PYTHON_INSTALL_DIR=%CD%\.local\python"
".local\uv\uv.exe" run --python 3.11 scripts\spike_higgs.py %*
echo.
echo Done. The report is in .local\spike-higgs\out\report.json
pause
