# KineLab PT — Decision Register

Status at setup: OPEN. These decisions must be resolved by the project owner and clinical validation lead before their dependent release paths can be accepted.

| ID | Decision needed | Default guardrail until answered | Blocks | Status |
|---|---|---|---|---|
| D01 | First supported clinical endpoint(s), e.g., knee flexion in a specified squat protocol; target population and exercise ROM | No clinical performance claim; research/demo only | B11, B12, B17, R16 | OPEN |
| D02 | Real-time tracking hardware and supported Windows/browser/camera combinations | Do not claim measured camera inference until proven end-to-end | B01, B17, B18, B20 | OPEN |
| D03 | Does v1 include measured muscle activity? Which muscles, EMG hardware/channels, normalization and synchronization? | No muscle activity measurement claim; avatar is visualization only | B21 | OPEN |
| D04 | Local-only single-operator or authenticated multi-user/cloud deployment, with consent, encryption, retention and data handling | Keep research service loopback-only; no real patient data in Vercel | B19, R05, R01 | OPEN |
| D05 | Acceptable recovery point/time objectives; backup destination, scheduling, encryption and restore approval | No promise of verified disaster recovery before drills | B08, B09, R18 | OPEN |
| D06 | Approved reference hardware, independent test population, numerical error/rejection limits and clinical sign-off | No claims of clinical accuracy until independently validated | B17, R16 | OPEN |
| D07 | What native research stages are in first release: dual-camera calibration/triangulation, OpenSim IK, gait/squat outputs? | Unsupported native claims disabled or clearly research-only | B13, B14, B15, R06 | OPEN |
| D08 | Who is responsible for source retention, de-identification, review/approval, rollback and incident response? | Protect source data; no destructive migration or outside-host copy | B06–B10, B19 | OPEN |

Record each approval below with date, owner, alternatives, risk, decision and link to supporting evidence. Never infer approval from a passing build.

## Decision history

- 2026-10-28: Setup records the above questions as OPEN. No project-owner release decisions inferred.
