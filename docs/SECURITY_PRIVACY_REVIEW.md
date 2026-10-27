# Security and privacy review

**Status: `NOT_STARTED`.** No control in this document has been implemented or
tested in the current repository state (no application source present). Each row
is a requirement plus the negative test that must exist before G1 can pass.

---

## 1. Data classification

| Class | Examples | Handling |
|---|---|---|
| Sensitive personal / biometric | Session MP4s, pose keypoints, marker trajectories | Local only; never pushed; never uploaded; never in logs |
| Machine-local metadata | Session index DB, configs, instance token | Local only; git-ignored |
| Public/source | Application code, tests, docs, lockfiles | Feature branch, reviewed |
| Prohibited in Git | Media, models, checkpoints, backups, tokens, absolute paths | Blocked at staging |

A person's motion recording is identifying data even without a face. Treat every
capture as sensitive unless the owner declares otherwise in writing.

## 2. Threat and control matrix

| # | Threat | Required control | Negative test | Status |
|---|---|---|---|---|
| 1 | Unauthenticated local API write | Bearer token required on every state-changing route | Anonymous POST → 401 | NOT_STARTED |
| 2 | Cross-origin request from a web page | Strict `Origin` allowlist; reject on mismatch | Cross-origin POST → 403 | NOT_STARTED |
| 3 | DNS rebinding / hostile Host header | Validate `Host` against `127.0.0.1:<port>` | `Host: evil.example` → 403 | NOT_STARTED |
| 4 | Path traversal via artifact route | Allowlisted route→file map; resolve and confirm containment | `../../secrets.json` → 400/404 | NOT_STARTED |
| 5 | Symlink escape from session folder | Reject symlinked artifacts for read/write | Symlink to outside → refused | NOT_STARTED |
| 6 | Token leakage in URL, logs, errors | Token never in query string; redact in logs and error bodies | grep logs for token → absent | NOT_STARTED |
| 7 | Upload corrupts an existing original | Stage → verify → atomic publish, no-overwrite | Kill upload mid-write → original hash unchanged | NOT_STARTED |
| 8 | Killing another process | Store the owning PID *and* start time; never clear a stale lock automatically | Forged lock → refuses to kill | NOT_STARTED |
| 9 | Absolute local paths disclosed in API/UI | Relative session-relative paths only | Scan responses for `C:\Users` → none | NOT_STARTED |
| 10 | Secret committed to Git | Pre-commit staged-file scan; `.env*` ignored | Planted dummy token → commit blocked | NOT_STARTED |
| 11 | Media committed to Git | `.gitignore` + explicit staging manifest review | Planted `.mp4` → not staged | NOT_STARTED |
| 12 | Backup leaks off-machine | Backups local, opt-in, no cloud path, no auto-upload | Inspect backup module for network calls → none | NOT_STARTED |
| 13 | Unbounded request body / log amplification | Body size caps; structured, rate-limited logs | Oversized JSON/MP4 body → 413 | NOT_STARTED |

## 3. Localhost is not a security boundary

Binding to `127.0.0.1` prevents remote network access; it does not prevent a
malicious page in the user's browser from issuing requests, nor another local
process from reading files. Therefore: token **and** `Origin` **and** `Host`
checks on every write, fail-closed defaults, and no state-changing GET routes.

## 4. Logging and diagnostics rules

- Logs record event, session id, stage, duration, exit code, and error class.
- Logs never record media content, keypoints, absolute paths, or the bearer token.
- Error bundles for offline support exclude footage and credentials; the bundle
  builder must prove this by scanning before packaging.
- A diagnostic bundle is never uploaded automatically.

## 5. Git staging rules (before any commit)

1. Produce a staged-file manifest (path, size, SHA-256, classification).
2. Run the redacted secret scan; a hit blocks the commit — fix, do not bypass.
3. Confirm no media, model, database, backup, launcher binary, or `.env` is staged.
4. Confirm no absolute user paths in committed config or docs.
5. Confirm third-party licenses exist for every redistributed binary or model.
6. Push to a feature branch; never force; never rewrite `main`.

## 6. Regulatory boundary

Research-only status must stay explicit in UI, exports, and docs. If future work
proposes clinical decision support, intended-use analysis and qualified
regulatory advice are required before those features ship. Local-only operation
is **not** a HIPAA compliance claim.
