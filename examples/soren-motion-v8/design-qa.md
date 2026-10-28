# v8 design and interaction QA

Verified locally on 28 October 2026 against the production build served over HTTP. Browser scope: local headless Chromium through the installed agent-browser CLI.

## Result

- Production build and TypeScript check pass. Ten Node tests pass, including the five retained reference-motion checks.
- All 92 browser assertions pass. The report is `qa/browser-results.json`; the repeatable script is `tests/browser-qa.py`.
- Production dependency audit reports zero known vulnerabilities for the installed lockfile. Development dependencies were outside that audit scope.

## Visual review

Inspected all six sections at 1440 × 900 and 390 × 844, the live anatomy and motion viewers, and the outer gallery. Compared About at 849 × 584 with the supplied screenshot. The redesign separates the film from readable chapter text; it does not attempt to reproduce the old overlay.

The six palettes, typography, and interaction models follow `DESIGN.md`. Film frames retain their baked titles with `object-fit: contain`. The demo disclaimer occupies its own row below the KineLab film. At small widths the content stacks and scrolls inside the panel; close and section navigation stay visible. Project tabs scroll horizontally within their own row and support arrow, Home, and End keys.

Automated layout checks cover all six sections at 390 × 844, 768 × 1024, 1440 × 900, and 1920 × 1080. No page or panel horizontal overflow was found. The About panel also passed a 200% zoom overflow check.

Screenshots remain local under `qa/screenshots/` and are excluded from Git.

## Interaction and lifecycle

The browser regression verifies modal focus wrapping, inert background, Escape and opener restoration, chapter keyboard navigation, four experience roles, all anatomy layer states, separation/zoom/reset, the existing 97-frame export, playback/scrubbing, project switching and viewer removal, inline evidence, skill dragging/reset and matching project links, supplied contact URLs, and clipboard recovery/success.

WebGL context loss and clipboard permission outcomes were simulated. Reduced motion selects a poster in every section and reports no uncaught browser errors. Direct `#projects` navigation resets to KineLab; a skill link still opens its matching project.

Additional manual browser probes verified that the About film pauses on a simulated hidden-document event, pauses when scrolled fully outside the panel, resumes on return, and falls back to its poster after a simulated media error. The offscreen check expanded the existing anatomy credit and used normal panel scrolling.

The reference-motion module is byte-identical to the v7 baseline. The original v7 example and its films remain preserved. The ribbon's film decoders pause while a section is open.

## Remaining boundaries

No production deployment, physical phone/GPU performance test, screen-reader certification, complete contrast audit, or clinical validation was performed. The existing anatomy is simplified study geometry and the KineLab coordinates are demonstration data. The lazy Three.js chunk remains about 524 kB before gzip; actual device rendering cost is unmeasured.
