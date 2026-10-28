# KineLab PT — Start Here (Codex and Antigravity)

This is the **isolated engineering workspace**. Your existing Windows app is separate and has not been replaced.

## Where the project is

`C:\Users\soren\Documents\Projects\KineLab-PT-Production-Agent-Workspace`

## Codex

Open the existing desktop `START-CODEX-AGENT` shortcut, or open this folder in Codex. Start by reading `AGENTS.md`, `docs/audits/KineLab_PT_Production_Readiness_Report.md`, and `docs/implementation/MASTER_PLAN.md` before changing code.

## Antigravity

On a computer with Antigravity installed, choose **File → Open Folder** and select the repository checkout of this project. If it is another computer, clone the private GitHub repository and check out the dedicated production-readiness feature branch first. Antigravity was not detected as a CLI on AgentZero at setup, so no working launcher is claimed.

## Working together

Each coding agent should use a separate child branch/worktree. Codex handles backend integrity and tests; Antigravity handles frontend and tracking UX; integration changes require review. `docs/implementation/TASK_BOARD.md` and `TASK_CATALOG.md` are the shared source of task status and acceptance criteria.

## Paste this one-line instruction to either agent

> Open `AGENTS.md`, read `docs/audits/KineLab_PT_Production_Readiness_Report.md` and all `docs/implementation/*.md`. Compare current HEAD with the audited revision. First complete milestone M0: plan and reproducible baseline. Keep synthetic demo separated from real measurements, preserve patient data and original app, and do not modify application code or deploy until the implementation plan has been accepted.

**Current release status:** NO-GO for clinical measurement. No human camera/EMG validation was performed.