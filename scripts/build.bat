@echo off
setlocal
cd /d %~dp0..

echo [1/3] Generating app icon...
py scripts\make_icon.py
if errorlevel 1 goto :err

echo.
echo [2/3] Building EXE with PyInstaller...
set ROOT=%~dp0..
py -m PyInstaller --noconfirm --clean --windowed --name EasyExtract ^
  --icon "%ROOT%\app\resources\icon.ico" ^
  --add-binary "%ROOT%\app\bin\7z.exe;bin" ^
  --add-binary "%ROOT%\app\bin\7z.dll;bin" ^
  --add-binary "%ROOT%\app\bin\License.txt;bin" ^
  --add-data "%ROOT%\app\resources\icon.ico;." ^
  --distpath build\dist --workpath build\work --specpath build ^
  run.py
if errorlevel 1 goto :err

echo.
echo [3/3] Building installer with Inno Setup...
set ISCC=
for %%P in ("ISCC.exe" "%ProgramFiles%\Inno Setup 7\ISCC.exe" "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles(x86)%\Inno Setup 5\ISCC.exe") do (
  if not defined ISCC if exist %%P set "ISCC=%%~P"
)
if not defined ISCC (
  echo ISCC.exe not found. Please install Inno Setup 5+ first.
  goto :err
)
"%ISCC%" installer\setup.iss
if errorlevel 1 goto :err

echo.
echo ===== BUILD OK =====
dir /b dist\installer
goto :eof

:err
echo BUILD FAILED
exit /b 1
