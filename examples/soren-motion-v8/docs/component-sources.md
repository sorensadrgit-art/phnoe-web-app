# Component and asset sources

Research and implementation: 28 October 2026. The selected components were adapted to the existing stack rather than installing multiple UI kits. Motion is the only new runtime library. No hosted component generator was used.

## Component record

| Source | Use in v8 | Reuse / integration |
|---|---|---|
| [Motion Primitives TransitionPanel](https://raw.githubusercontent.com/ibelick/motion-primitives/main/components/core/transition-panel.tsx) | Controlled chapter presence/exit pattern in `ExplorerControls.tsx` | MIT notice retained. A smaller local adaptation uses the existing component structure; semantic tabs and reduced motion are supplied locally. |
| [Kokonut ScrollIndex](https://kokonutui.com/docs/navigation/scroll-index) | Scoped role-navigation reference | MIT notice retained. The role rail is a local implementation fitted to the panel, not a full library installation. |
| [Cult Expandable](https://www.cult-ui.com/docs/components/expandable) | Inline project evidence expansion reference | MIT notice retained. Uses local controlled state and Motion; no nested dialog or measurement dependency. |
| [Cult CopyButton](https://www.cult-ui.com/docs/components/copy-button) | Clipboard success/failure interaction reference | MIT notice retained. Uses the browser clipboard API and a persistent selectable fallback link. |
| [Fancy Drag Elements](https://www.fancycomponents.dev/docs/components/blocks/drag-elements) | Bounded tactile arrangement reference | MIT notice retained. Uses Motion's installed drag support, no momentum; selection remains available by keyboard/click/tap. |
| [Magic UI AnimatedBeam](https://magicui.design/docs/components/animated-beam) | Skill-to-project connection reference | MIT notice retained. The local connection is a simple finite CSS signal, avoiding an SVG measurement/observer implementation for a straight line. |
| [Motion reduced motion](https://motion.dev/docs/react-use-reduced-motion) | MotionConfig plus reactive preference handling | Installed package license retained by package distribution. |

Exact retrieved license hashes and URLs are in `source-license-receipt.json`; notices are in `licenses/`.

React Bits, paid Shadcnblocks, and 21st.dev candidates with unverified individual source reuse terms were not copied. MotionSites and discovery galleries supplied inspiration only. Aceternity, Hover, and shadcn references did not require additional runtime packages for this implementation.

## Existing media and geometry

- Six films and six posters are copied unchanged from the reviewed v7 output. Their editable Remotion and HyperFrames projects remain in the sibling `soren-motion-v7` example; they are not website runtime dependencies.
- `anatomy-low.glb` is the existing adapted BodyParts3D study asset. Attribution: BodyParts3D © DBCLS, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). It is simplified study geometry, not a complete atlas or clinical model. Bone, muscle, and tendon mesh groups were inspected before adding isolation controls.
- `demo.motion.json` and `kinelab-workspace.png` are existing KineLab demonstration assets already used in v7 film authoring. The live movement viewer uses the exported coordinates directly; physical accuracy remains unverified.
- `baseline.json` records the preserved v7 HTML hash and the unchanged reference-motion module hash.

## Guidance and tool execution

Read local Research Methodology, 21st exploration, Product Design routing/context/QA, agent-browser, Three.js glTF-loading, SOREN deployment preflight, learning-loop, and Anti-Slop guidance as applicable. Used the read-only SOREN route once and searched Lightswind once; no suitable Lightswind candidate was returned. The source project was inspected through local files because Open Design's native context tools were not exposed in this client. Hindsight retrieval was attempted but its local service was unavailable. No remote memory was retained.

Verification uses the installed agent-browser CLI. No new browser installation, global MCP change, provider configuration, or production deployment is part of v8.

Guidance files read during research and implementation include:

- `C:/Users/soren/.codex/plugins/cache/openai-curated-remote/research-plugin/1.1.0/skills/research-methodology/SKILL.md`
- `C:/Users/soren/.codex/plugins/cache/openai-curated-remote/product-design/0.1.56/skills/index/SKILL.md`, `get-context/SKILL.md`, `image-to-code/SKILL.md`, and `design-qa/SKILL.md` under that same skills directory.
- `C:/Users/soren/.agents/skills/agent-browser/SKILL.md` plus the installed CLI's `skills get core` instructions.
- `C:/Users/soren/.agents/skills/soren-learning-loop/SKILL.md`, `soren-universal-deployment/SKILL.md`, and `router/SKILL.md` under that same skills directory.
- `C:/Users/soren/.codex/plugins/cache/anti-slop/antislop/3.2.24/skills/antislop/SKILL.md` and `antislop-ui/SKILL.md` under that same skills directory.
- `C:/Users/soren/.codex/plugins/cache/caveman/caveman/4.0.1/skills/caveman/SKILL.md` and `C:/Users/soren/.codex/plugins/cache/chisle/chisle/3.8.1/skills/chisle/SKILL.md`.
