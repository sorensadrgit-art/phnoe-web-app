# KineLab PT v1.0 — T4 synchronized review software checkpoint

Host: AgentZero Windows, October 27, 2026. This is a software verification checkpoint, not a physical camera or clinical-accuracy certificate.

## Implemented

- Added viewer/src/syncPlayback.js: strict pure validation of native run manifest identity and SHA-256 provenance; validates REAL v2 motion only, both camera normalized MP4 SHA-256 values, session/config/source identities, six native stage passes, independent cue pairs, reference/offset and measured native sync quality. Maps a common synchronized timeline to each recorded camera frame using the normalized source timestamps; leaves out-of-range frames unavailable.
- Added viewer/src/VerifiedReview.jsx: local file selectors for run.json, normalization.json, sync.json, and the two normalized MP4s. Web Crypto locally hashes the exact selected files before mounting them in side-by-side video panes. Demo/legacy motion cannot claim a valid real-video pairing. Native sync evidence and browser video seek-preview limitations are clearly labeled. Source clips never leave the browser.
- Added viewer/src/AngleChart.jsx: three paired OpenSim joint-angle graph modes (knees, hips, ankles) with interactive timeline scrubbing and descriptive range-of-motion readouts over available measurements only. Marker-only and missing coordinates never receive invented values.
- Integrated components into the existing MotionApp.jsx and local CSS. Removed the external Google Fonts import in favor of system fonts for offline-safe rendering. Existing launcher and Three.js skeleton remain intact.
- Updated RUNBOOK.md for the exact five-file local evidence workflow and its limitations.
- Added viewer/src/syncPlayback.test.js with local SHA verification, native manifest mismatch rejection, camera timestamp/frame-offset alignment, demo refusal, and missing-angle behavior.

## Verification

- The earlier T3 full Python suite passed **114 tests**. T4 did not change the Python processing modules.
- T4 full JavaScript suite passed **15 tests**, zero failures.
- Vite production build passed, including all new React components; the existing large JS chunk advisory remains.
- Chrome headless DOM runtime check on KineLab's current loopback address **http://127.0.0.1:4174/** found Motion Analysis Lab, Angle over time, and Synchronized dual-camera review. No React application-error text was captured.
- Port 4173 was occupied by a separate SOREN site; the existing KineLab launcher selected 4174 rather than hijack another application's port.
- Evidence: C:\Users\soren\Projects\kinelab-team\evidence\v1-execution\t4-js.log and t4-browser-dom.html.
- Camera originals were previously verified unchanged by T3 checks, and no real camera process or recording was started by this T4 work.

## Pending acceptance

- **Real positive T4 end-to-end video review is not verified** because there is no genuine calibrated, accepted REAL two-camera session with passed native run.json, sync.json and a session-bound v2 motion export. Mixed online example videos are rejected.
- HTML media element frame seeking while playing cannot be claimed accurate within one native frame; source-timestamp mapping is verified by JS unit tests, but decoded frame presentation is a browser preview and not an independent hardware synchronization measurement.
- T5 movement-analysis algorithms and T6 unified local desktop shell remain next, followed by T7 reporting/history, T8 clean offline installer, T9 physical pilot and T10 fixed build sign-off.
