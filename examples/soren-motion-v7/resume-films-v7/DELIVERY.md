# SOREN — Motion exhibits v7

The four refined concepts now use Remotion and Three.js. About is an anatomical sculpture; Experience is an animated machined assembly; Education separates tissue layers; Projects presents the existing KineLab interface beside its exported demo movement and two camera objects. Skills and Contact keep their independent playful and painterly styles.

Each of the six folders remains a separate editable HyperFrames project with its own film and poster. `section-motion/src/PremiumStudies.tsx` contains the four registered Remotion compositions; `Root.tsx` exposes AboutPremium, ExperiencePremium, EducationPremium and ProjectsPremium separately. The older six compositions remain available.

Run `node render-premium.mjs --render` from `section-motion` to render the four refined films. `--only=education` selects one. The legacy `render.mjs` still renders only the six original studies. Run `python work/build-section-media.py v7` in the original workspace to rebuild the self-contained résumé after changing exports; the builder refuses an altered v4 baseline.

The résumé is available at `http://127.0.0.1:3044/SOREN-Living-Resume-Premium-Films-v7.html`. HyperFrames Studio is `http://localhost:3045/#project/resume-films-v7`; Remotion Studio is `http://localhost:3041/EducationPremium`. These previews require their local servers to remain running. The self-contained HTML can be opened independently. The gallery page plays the six films separately.

Product Design guidance actually read: index, user-context, get-context, ideate, image-to-code, critical overrides, communication protocol and design-qa. Applied the existing-target refinement path: the approved v6 frames and current user brief ground the visual direction. Reused actual source assets and checked the combined before/after frames. No Product Design account, persistent preferences or new application scaffold was created. Its user-context preflight reported no saved context.

Read and applied Remotion's create, markup, render and best-practices guidance, the Three.js material guidance, and the existing HyperFrames/CLI instructions. HyperFrames catalog search was performed during v6; its unused downloaded sample was not used as a v7 asset. The desktop-app inventory contained no open HyperFrames window, so Studio provides the editable preview. The in-app browser successfully opened the final résumé and was marked as a deliverable.

See `design-qa.md`, `ASSET-CREDITS.md`, `../premium-films-v7-verification.json`, and `dependency-audit.json` for scope and evidence. Earlier artifacts and the newer original React source tree remain intact.

The render project overrides Zod to 4.6.6 to resolve the installed 4.5.4 security advisory. Remotion prints its exact-version warning for this override. Fresh still rendering, TypeScript, lint and Studio compilation were verified; the exported films and résumé do not contain this authoring dependency.
