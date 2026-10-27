# Security and sensitive research data

This project handles computer-vision video data that can identify people and reveal personal movement or health-related information.

**Do not commit any recordings or patient data.** GitHub repository privacy is not a substitute for user consent, secure clinical data handling, or local retention policies. Keep source video and session output files on authorized local storage.

Exclude all secret tokens, API keys, server credentials, localhost bearer tokens, machine-specific runtime state, model downloads, and third-party footage whose redistribution rights are unverified.

Before each push, review the exact `git diff --cached --name-status` and `git ls-files` output, and perform a secrets/content scan. If a secret or participant video is accidentally staged, unstage it **before** committing; if committed, revoke affected credentials and rewrite history only with a deliberate remediation plan.

KineLab PT is a research prototype. 2D pose scores, test-only footage, and software regression tests do not establish calibrated 3D biomechanics, diagnostic accuracy, clinical validation, or medical-device approval.
