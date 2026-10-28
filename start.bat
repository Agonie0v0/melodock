@echo off
cd /d "%~dp0"
if not exist launcher.py goto incomplete
if exist runtime\python.exe goto bundled
if exist .venv\Scripts\python.exe goto source
where python >nul 2>&1 || goto needpython
python -m venv .venv || goto failed
.venv\Scripts\python.exe install_dependencies.py || goto failed
:source
.venv\Scripts\python.exe -c "import requests_toolbelt; import importlib.metadata as m; assert m.version('musicdl') == '2.14.0+melokeep.1'" >nul 2>&1
if errorlevel 1 .venv\Scripts\python.exe install_dependencies.py || goto failed
if not exist frontend\dist\index.html (
  where npm >nul 2>&1 || goto neednode
  pushd frontend
  call npm ci || (popd & goto failed)
  call npm run build || (popd & goto failed)
  popd
)
.venv\Scripts\python.exe launcher.py
goto finished
:bundled
runtime\python.exe launcher.py
goto finished
:incomplete
echo Extract the ENTIRE ZIP to a folder before running start.bat.
goto failed
:needpython
echo Install Python 3.11+ or use the full-engine Windows package.
goto failed
:neednode
echo Node.js is required to build the frontend from source.
goto failed
:failed
set "melokeep_exit=1"
goto report
:finished
set "melokeep_exit=%errorlevel%"
:report
if not "%melokeep_exit%"=="0" (
  echo.
  echo Startup failed. See the error above and logs\startup.log.
  pause
)
exit /b %melokeep_exit%
