@echo off
title somni installer
setlocal EnableDelayedExpansion

set "PYEXE="

REM 1) Prefer the `py` launcher — it's almost always installed with Python on Windows.
py -3 --version >nul 2>nul
if !errorlevel! equ 0 (
  set "PYEXE=py -3"
  goto :run
)

REM 2) Try `python`, but only if it's a real Python (not the Microsoft Store stub).
python --version 2>&1 | findstr /r /c:"^Python [0-9]" >nul
if !errorlevel! equ 0 (
  set "PYEXE=python"
  goto :run
)

REM 3) Search common install locations directly (bypasses any PATH games).
for %%P in (
  "%LocalAppData%\Programs\Python\Python313\python.exe"
  "%LocalAppData%\Programs\Python\Python312\python.exe"
  "%LocalAppData%\Programs\Python\Python311\python.exe"
  "%LocalAppData%\Programs\Python\Python310\python.exe"
  "C:\Python313\python.exe"
  "C:\Python312\python.exe"
  "C:\Python311\python.exe"
  "C:\Python310\python.exe"
  "C:\Program Files\Python313\python.exe"
  "C:\Program Files\Python312\python.exe"
  "C:\Program Files\Python311\python.exe"
  "C:\Program Files\Python310\python.exe"
) do (
  if exist %%P (
    set "PYEXE=%%P"
    goto :run
  )
)

echo.
echo  -------------------------------------------------------------
echo   No working Python 3 was found on this system.
echo.
echo   somni's installer needs any Python 3.x to run.
echo.
echo   If you DO have Python installed, the Windows Microsoft
echo   Store "App execution alias" may be shadowing it. Fix it via:
echo     Settings ^> Apps ^> Advanced app settings
echo            ^> App execution aliases
echo     ...and turn OFF the two entries for "python.exe" and
echo     "python3.exe".
echo.
echo   Or install Python from: https://www.python.org/downloads/
echo   (Tick "Add Python to PATH" during install.)
echo  -------------------------------------------------------------
echo.
pause
endlocal
exit /b 1

:run
echo  Using Python: !PYEXE!
echo.
!PYEXE! "%~dp0installer.py"
set "RC=!ERRORLEVEL!"
echo.
if "!RC!"=="0" (
  echo  Installer exited normally.
) else (
  echo  Installer exited with code !RC!.
  echo  If you see an error above, copy it for support.
)
echo.
pause
endlocal
exit /b !RC!
