@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -m pip install -r requirements.txt
if errorlevel 1 (echo Python not available; try python instead of py.& pause & exit /b 1)
py build.py
if errorlevel 1 (pause & exit /b 1)
echo.
echo Done! Open site\index.html to preview.
pause
