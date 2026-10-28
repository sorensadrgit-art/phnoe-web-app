# G0 audit - 20261027-215915

Verdict: **G0_PASSED_WITH_WARNINGS** | STOP=0 FAIL=1 | host `AGENTZERO`

| Phase | Check | Status | Detail |
|---|---|---|---|
| preflight | project-root | PASS | C:\Users\soren\Documents\Projects\KineLab-PT-DualCam |
| preflight | run-dir | PASS | C:\Users\soren\Documents\Projects\KineLab-G0-Snapshots\g0-20261027-215915 |
| preflight | disk-free | PASS | 595.85 GB free |
| git | repository | FAIL | not a git work tree; snapshot still valid, branch creation disabled |
| secrets | tracked-files | PASS | no credential patterns in tracked text files |
| media | media-files | PASS | 39 media file(s) hashed |
| media | read-only | PASS | no media byte was modified by this script |
| versions | python | PASS | 3.13.16 (main, Oct 14 2026, 01:05:56) [MSC v.1944 64 bit (AMD64)] |
| snapshot | worktree-copy | PASS | code snapshot at C:\Users\soren\Documents\Projects\KineLab-G0-Snapshots\g0-20261027-215915\worktree |
| snapshot | hash-verify | PASS | 5593 file(s) compared, 0 mismatch(es) |
| baseline | tests | SKIP | tests skipped by switch |
| branch | create | SKIP | review the report first, then re-run with -CreateBranch |

