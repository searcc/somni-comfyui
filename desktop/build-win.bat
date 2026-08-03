@echo off
title somni desktop — build windows
setlocal EnableDelayedExpansion

echo ============================================================
echo   somni desktop — building windows installer
echo ============================================================
echo.

cd /d "%~dp0"

echo Building somni-app (Windows NSIS installer)...
pushd somni-app
if not exist node_modules ( call npm install || goto :error )

REM Build Windows executable natively
call npx electron-builder --win || goto :error
popd

echo.
echo ============================================================
echo   Done!
echo.
echo   Windows Installer: %~dp0dist\somni-app\somni-setup-*.exe
echo ============================================================
echo.
pause
exit /b 0

:error
echo.
echo Windows build failed. Check the output above.
pause
exit /b 1