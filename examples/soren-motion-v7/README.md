# SOREN — Motion Exhibits v7

The latest résumé copy: six independent silent motion films on the curved WebGL ribbon, with mobile posters and reduced-motion fallbacks. The About, Experience, Education and Projects films use Remotion and Three.js; Skills and Contact retain their distinct HyperFrames designs.

## Open

Download `index.html` and open it in a modern browser. This file embeds the complete runtime, six MP4 films and six posters; it needs no installation or build. The earlier v4 copy remains in `../soren-motion-v4/`.

## Editable projects

- `resume-films-v7/`: six separate HyperFrames projects, videos, posters, gallery, asset credits and design QA.
- `section-motion/`: editable Remotion compositions, original anatomy study asset, existing KineLab demo data and the pinned dependency lockfile.
- `premium-films-v7-verification.json`: the 29 local browser/media checks.
- `premium-films-v7-design-comparison.jpg`: approved concepts beside the refined rendered frames.

To edit and render the four refined films, run these commands inside `section-motion` with Node.js installed:

```sh
npm ci
npm run dev -- --no-open
node render-premium.mjs --render
```

The renderer updates the matching films in `../resume-films-v7/`. Each HyperFrames folder can be opened independently with its pinned `npm run dev` command. The collection can be previewed from `resume-films-v7` with `npx --yes hyperframes@0.8.211 preview --background`.

The self-contained `index.html` is a release snapshot. The integration scripts are provided as the original workspace build/QA reference; their owner-specific paths and v4 baseline requirement are documented in `resume-films-v7/DELIVERY.md`.

## Credits and limits

Read `resume-films-v7/ASSET-CREDITS.md` for BodyParts3D attribution, adaptations and the KineLab screenshot/demo sources. The demo motion JSON matches the sample already tracked in this repository. No participant recordings, calibration captures, credentials or environment files are added.

Local playback, mobile, reduced-motion and resize checks passed. Physical-device GPU performance, clinical accuracy and exhaustive accessibility acceptance remain unverified. The patched authoring toolchain has a documented Zod version-pin warning; the exported HTML and videos do not contain that dependency. This commit does not deploy or merge the example into the KineLab application.
