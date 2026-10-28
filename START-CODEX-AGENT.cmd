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
codex "Read AGENTS.md, docs/audits/KineLab_PT_Production_Readiness_Report.md and docs/implementation/MASTER_PLAN.md, TASK_BOARD.md, TASK_CATALOG.md, VERIFICATION_LOG.md and DECISION_REGISTER.md. Compare HEAD with audited revision ffde4be7, reproduce baseline and complete M0. Prioritize truth, durability, containment and evidence. Do NOT modify the existing live app or patient data, push to main, deploy, or start application code fixes before the scoped plan is approved. Report the verified state, precise test outcomes and implementation proposal."
endlocal
