@echo off
rem Sets up once, inside this folder, then starts the demo. Delete the folder to remove everything.
cd /d "%~dp0"
set "UV_CACHE_DIR=%CD%\.setup\cache"
set "UV_PYTHON_INSTALL_DIR=%CD%\.setup\python"
set "TOOL=uv\windows\uv.exe"
set "PY=.setup\venv\Scripts\python.exe"
if exist .setup\ready goto run
echo First run: setting up inside this folder. This needs internet and takes a minute or two.
"%TOOL%" venv --no-config --python 3.12 --python-preference only-managed .setup\venv
if errorlevel 1 goto failed
"%TOOL%" pip install --no-config --python "%PY%" -r requirements.txt
if errorlevel 1 goto failed
"%TOOL%" pip install --no-config --python "%PY%" -r requirements-voice.txt
if errorlevel 1 echo No voice on this machine: you can still type to Val.
"%TOOL%" pip install --no-config --python "%PY%" -r requirements-export.txt
if errorlevel 1 echo No IFC or DXF download on this machine. Everything else works.
type nul > .setup\ready
:run
"%PY%" run_demo.py %*
pause
exit /b
:failed
echo Setup failed. Check the internet connection and run this again.
pause
exit /b 1
