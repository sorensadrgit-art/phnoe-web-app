# SOREN Living Resume — Reference Motion v4

A self-contained copy of the SOREN portfolio demo, with six embedded generated images and its complete browser runtime.

## Open

Download `index.html` and open it in a modern browser. No installation or build is required. Desktop supports the curved WebGL carousel, wheel inertia, drag release, hover dent and section transitions. Mobile and reduced-motion settings use the existing fallbacks.

## Motion source and checks

`reference-motion.mjs` contains the readable motion equations and controller used to produce this copy. They are already embedded in `index.html`; this file is provided for inspection and mathematical tests. Editing it alone does not rebuild the bundled HTML.

Run the mathematical checks with Node.js:

```sh
node --test examples/soren-motion-v4/reference-motion.test.mjs
```

The original local acceptance run passed five mathematical tests, 22 browser checks and a native pointer drag check. See `verification.json` for measured wheel-trajectory comparisons and scope limits. Physical-device GPU performance and exact frame parity across devices remain unverified.

This directory is an independent portfolio example. It contains no participant recordings, calibration captures, downloaded models, credentials or service configuration. The repository's motion-capture application is unaffected.
