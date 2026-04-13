@echo off
REM ============================================================
REM  build_windows.bat
REM  One-click build for Furnace Charge Calculator .exe
REM  Run from the charge_app folder on a Windows machine
REM ============================================================

echo.
echo ============================================================
echo  Furnace Charge Calculator -- Windows Build
echo ============================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.10+ from python.org
    pause & exit /b 1
)

echo [1/4] Installing dependencies...
pip install flask pywebview pyinstaller --quiet
if errorlevel 1 ( echo ERROR: pip install failed. & pause & exit /b 1 )

echo [2/4] Cleaning previous build...
if exist dist\FurnaceCalc rmdir /s /q dist\FurnaceCalc
if exist build rmdir /s /q build

echo [3/4] Building .exe (this takes 1-3 minutes)...
pyinstaller desktop_app.spec --noconfirm
if errorlevel 1 ( echo ERROR: PyInstaller build failed. & pause & exit /b 1 )

echo [4/4] Done!
echo.
echo ============================================================
echo  OUTPUT:  dist\FurnaceCalc\FurnaceCalc.exe
echo.
echo  Copy the entire "dist\FurnaceCalc\" folder anywhere.
echo  No Python install needed on the target PC.
echo.
echo  DATABASE:
echo    dist\FurnaceCalc\data\metal_specs.csv    <- grade library
echo    dist\FurnaceCalc\data\addition_specs.csv <- scraps + alloys
echo    dist\FurnaceCalc\data\heat_log.csv       <- saved heats
echo.
echo  All CSV files can be opened and edited in Excel or Notepad.
echo  Changes take effect immediately on app restart (or Reload).
echo ============================================================
echo.
pause
