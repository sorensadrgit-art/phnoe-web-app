# SOREN — Section Explorers v8

An editable React résumé with six distinct interactive section experiences. The v7 films and measured ribbon controller are retained. The KineLab application at the repository root is separate.

## Run

Requires Node.js 22+ and npm. Verified locally with Node.js 24.19.0.

```powershell
npm ci --ignore-scripts
npm run dev -- --port 3048 --strictPort
```

Open http://127.0.0.1:3048/. Use `#about`, `#experience`, `#education`, `#projects`, `#skills`, or `#contact` for a direct section link.

```powershell
npm run build
npm test
npm run preview -- --port 3049 --strictPort
```

`dist/` is the portable built site. Serve it over HTTP; opening its HTML with `file://` does not support module loading reliably. Its paths are relative, so it can be hosted below a directory. No server API, credentials, or external media CDN is required.

## Experiences

- **About:** four readable chapters linked to the existing identity film.
- **Experience:** four indexed roles with a scoped scroll rail and synchronized chapter plaque.
- **Education:** opt-in Three.js anatomy with mesh isolation, separation, keyboard zoom/rotation, and reset.
- **Projects:** four separate treatments, expandable evidence, the existing 97-frame KineLab export, an illustrative agent workflow, a Spline palette study, and the résumé's six-film library.
- **Skills:** selectable and optionally draggable tools linked to the matching project. The full toolkit remains readable.
- **Contact:** supplied GitHub/Spline destinations and clipboard feedback with a visible fallback URL.

All films have pause controls. Reduced motion selects static posters. Hidden media pauses. The anatomy and movement renderers load on demand and dispose on exit; loss of their WebGL context returns to the film. The outer gallery retains its semantic HTML fallback.

## Source map

| File | Owns |
|---|---|
| `src/resume/resumeData.ts` | Existing résumé text and approved links |
| `src/resume/ResumeExperience.tsx` | Gallery, one modal/focus trap, history, section navigation, GSAP flight |
| `src/resume/reference-motion.mjs` | Unchanged v7 controller, projection math, vertex shader, easing |
| `src/resume/ResumeRibbonScene.ts` | Readable Three.js ribbon renderer using the v7 shader and projection |
| `src/resume/SectionExplorer.tsx` | Six section experiences |
| `src/resume/ExplorerControls.tsx` | Tabs, transition panel, film lifecycle, clipboard feedback |
| `src/resume/LiveStudy.tsx` | Lazy anatomy and motion-data renderers |
| `src/resume/explorerData.ts` | Project descriptions and skill/project mapping |
| `src/resume/explorers.css` | Section layouts and art direction |
| `public/` | Six existing films/posters, existing anatomy, and demo export |

## Verification

`npm test` includes the five retained reference-motion tests plus asset, geometry, demo-data, source-hash, and portable-build checks. Run `npm run build` first.

The browser test uses the existing agent-browser installation and a separate task session:

```powershell
$env:PYTHONUTF8='1'
python tests/browser-qa.py --url http://127.0.0.1:3049/
```

Results are in `qa/browser-results.json`. Screenshots are local QA outputs and are excluded from Git. `design-qa.md` records visual review. Browser checks do not establish clinical accuracy, physical-device performance, or identical rendering on all GPUs.

## Provenance and limits

See `docs/component-sources.md`, the retained license notices, and `baseline.json`. The v7 HTML export is preserved in the sibling `soren-motion-v7` example. No paid blocks or components with unclear source reuse terms were copied.

Résumé wording remains draft content. Military dates, email, and LinkedIn were not invented. The anatomy is adapted study geometry. KineLab motion is an existing demo export, not a validated clinical measurement. The Steppr palette control is local illustrative UI; the actual Spline scene opens through the supplied link.

The Three.js production chunk is approximately 524 kB before gzip and is lazy loaded. This build does not add a second 3D framework or include the Remotion/HyperFrames authoring runtimes in the website.
