@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (start "" ".venv\Scripts\pythonw.exe" "%~dp0launch_gui.pyw" --preview) else (start "" pythonw.exe "%~dp0launch_gui.pyw" --preview)
exit /b
