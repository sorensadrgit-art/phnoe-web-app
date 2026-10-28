@echo off
setlocal
cd /d "%~dp0"
where claude.exe >nul 2>&1
if errorlevel 1 (
  echo Claude Code is not installed or is not on PATH.
  echo Open this folder in your preferred coding agent and read AGENTS.md.
  pause
  exit /b 1
)
echo KineLab PT / Isolated Production Agent Workspace
echo Working directory: %CD%
echo The existing Windows app and Vercel deployment must remain unchanged.
claude "Read AGENTS.md and docs/PRODUCTION_READINESS_HANDOFF.md. Inspect current source and P0/P1 technical risks. Verify baseline tests, identify synthetic-vs-camera inference gap, and propose an evidence-backed phased production readiness plan before code changes. Do not touch patient data, original app, Git main, or live Vercel site."
endlocal
