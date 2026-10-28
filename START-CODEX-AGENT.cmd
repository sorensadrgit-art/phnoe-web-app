@echo off
setlocal
cd /d "%~dp0"
where codex.cmd >nul 2>&1
if errorlevel 1 (
  echo Codex CLI is not installed or is not on PATH.
  echo Open this folder in your preferred coding agent and read AGENTS.md.
  pause
  exit /b 1
)
echo KineLab PT / Isolated Production Agent Workspace
echo Working directory: %CD%
echo The existing Windows app and Vercel deployment must remain unchanged.
codex "Open AGENTS.md and docs/PRODUCTION_READINESS_HANDOFF.md. Inspect this isolated Git branch and verify baseline tests. Perform SOREN P0 investigation and produce an evidence-based Plan Forge with acceptance gates for actual camera inference, offline packaging, scientific validity, and secure cloud architecture. Do not touch patient data, modify the original app, push to main, or deploy. Start by reporting current verified state, test outcomes and a scoped plan."
endlocal
