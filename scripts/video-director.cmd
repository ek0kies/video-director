@echo off
setlocal

set "SCRIPT_DIR=%~dp0"

if not "%VIDEO_DIRECTOR_PYTHON%"=="" (
  set "VIDEO_DIRECTOR_SELECTED_PYTHON=%VIDEO_DIRECTOR_PYTHON%"
  call :check
  if not errorlevel 1 goto run
  echo error: VIDEO_DIRECTOR_PYTHON is set but is not Python 3.11+: %VIDEO_DIRECTOR_PYTHON% 1>&2
  echo Unset VIDEO_DIRECTOR_PYTHON or point it to a compatible interpreter. 1>&2
  exit /b 1
)

for %%P in ("py -3.11" "py -3" "python" "python3") do (
  set "VIDEO_DIRECTOR_SELECTED_PYTHON=%%~P"
  call :check
  if not errorlevel 1 goto run
)

echo error: Python 3.11 or newer is required for Video Director. 1>&2
echo Install Python 3.11+ or set VIDEO_DIRECTOR_PYTHON to a compatible python.exe. 1>&2
exit /b 1

:check
%VIDEO_DIRECTOR_SELECTED_PYTHON% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
exit /b %ERRORLEVEL%

:run
%VIDEO_DIRECTOR_SELECTED_PYTHON% "%SCRIPT_DIR%video_director.py" %*
exit /b %ERRORLEVEL%
