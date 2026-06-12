@echo off
REM POE2 Sentinel - Quick Build Script
REM Double-click this file to build the executable and installer.

echo ================================================================================
echo                        POE2 Sentinel - Build Script
echo ================================================================================
echo.

py --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH!
    echo Please install Python 3.12+ from https://www.python.org/
    echo.
    pause
    exit /b 1
)

echo Python found! Starting build...
echo.
py "%~dp0build_exe.py"

echo.
echo ================================================================================
echo Build process complete! Check the output above for any errors.
echo If successful, the installer is in: dist\POE2Sentinel_Setup_v*.exe
echo ================================================================================
echo.
pause
