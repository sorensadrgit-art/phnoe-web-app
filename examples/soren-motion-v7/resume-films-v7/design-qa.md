# Design QA — Motion exhibits

final result: passed

Scope: refine the four user-approved concepts, rather than clone their pixels. Preserve the six separate styles, résumé facts, ribbon motion and accessible fallback. Skills and Contact retain their v6 designs.

The combined comparison is `../premium-films-v7-design-comparison.jpg`. It places the approved v6 source frames above the v7 rendered frames at the same eight-second composition time (2 seconds), each at its original 1200 × 704 aspect ratio. The comparison was opened and visually reviewed. The finished résumé was also opened in the in-app browser.

## Findings and repairs

- P1: asynchronous models and the interface texture were absent from initial captured frames. The Three.js canvas now advances after resource loading before releasing Remotion's render hold. Updated stills show the complete geometry and actual KineLab screen.
- P2: initial ivory materials lost detail against the paper background. About now uses a darker verdigris material; the education study uses contrasting bone, muscle and tendon materials.
- P2: the first Projects headline overlapped the spatial display. A compact KineLab PT heading gives the real interface and motion export their own area.
- P2: an isolated regional cut made the education study harder to read. The full existing study mesh now separates into tissue layers, preserving the intended anatomy concept.

Post-fix comparison: identities and education status remain legible; the four subjects are visible; no headline crosses the main 3D object or the display; credits remain below the artwork. The curved ribbon shows the complete films. No remaining P0/P1/P2 issue was identified in this comparison scope.

## Verification

- 29 browser/media checks passed: all six dialog videos, live texture frames, bounded decoders, reduced motion, mobile playback/layout, scroll reset, resize recovery, no runtime errors and all six eight-second 30 fps files.
- Media lifecycle self-check passed: shared decoders, frame deduplication, offscreen/detail/reduced-motion/hidden-tab pause and cleanup.
- Remotion ESLint and TypeScript passed.
- HyperFrames root check: zero lint, runtime, layout, motion and contrast errors. Its intentional silent-film warning remains. This video-based check does not audit text baked into MP4 frames as DOM text.
- Render project dependency audit: zero vulnerabilities after a Zod 4.6.6 security override. Remotion expects Zod 4.5.4 and prints a version-pin warning; typechecking, Studio compilation and fresh four-composition still rendering were checked with the patched version. The warning remains in the editable toolchain, not in the exported HTML or videos.

Physical-device GPU performance, exhaustive accessibility acceptance and clinical/anatomical accuracy were not tested. No deployment or GitHub push was performed for v7.
