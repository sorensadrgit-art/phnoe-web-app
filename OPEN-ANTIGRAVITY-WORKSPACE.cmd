@echo off
setlocal
cd /d "%~dp0"
echo KineLab PT isolated engineering workspace:
echo %CD%
echo.
echo Open this folder from Antigravity: File ^> Open Folder.
echo Read ANTIGRAVITY-START.md and AGENTS.md first.
start "" explorer.exe "%CD%"
endlocal
