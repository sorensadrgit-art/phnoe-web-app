/**
 * Custom GLSL Shader Material for Kinematic Arc Telemetry Ribbon
 * Visualizes dynamic curvature vector connecting robotic manipulator to anatomical joint.
 */

export const KinematicArcShader = {
  uniforms: {
    uTime: { value: 0 },
    uProgress: { value: 0 },
    uAccentColor: { value: [0.22, 0.74, 0.97] }, // Cyan telemetry
    uAmberColor: { value: [0.96, 0.62, 0.18] },  // Amber warning/peak
    uGlowIntensity: { value: 1.8 }
  },

  vertexShader: `
    attribute vec3 position;
    attribute vec2 uv;
    uniform mat4 modelViewMatrix;
    uniform mat4 projectionMatrix;
    uniform float uTime;
    uniform float uProgress;

    varying vec2 vUv;
    varying float vPulse;

    void main() {
      vUv = uv;
      vec3 pos = position;
      // Slight aerodynamic harmonic displacement along ribbon normal
      float pulse = sin(uv.x * 12.0 - uTime * 4.0) * 0.008 * smoothstep(0.0, 0.5, uv.x);
      pos.y += pulse;
      vPulse = pulse;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(pos, 1.0);
    }
  `,

  fragmentShader: `
    precision highp float;
    uniform float uTime;
    uniform float uProgress;
    uniform vec3 uAccentColor;
    uniform vec3 uAmberColor;
    uniform float uGlowIntensity;

    varying vec2 vUv;
    varying float vPulse;

    void main() {
      // Longitudinal dash sequence
      float dash = sin(vUv.x * 40.0 - uTime * 6.0);
      float dashAlpha = smoothstep(-0.2, 0.4, dash);

      // Edge glow falloff across ribbon width (vUv.y)
      float edgeDist = abs(vUv.y - 0.5) * 2.0;
      float edgeGlow = pow(1.0 - edgeDist, 2.8) * uGlowIntensity;

      // Color transition from cyan baseline to amber high-flexion threshold
      vec3 color = mix(uAccentColor, uAmberColor, clamp(uProgress * 1.2 - 0.2, 0.0, 1.0));

      // Active head marker on telemetry ribbon
      float headMarker = smoothstep(0.04, 0.0, abs(vUv.x - uProgress));
      vec3 finalColor = color + vec3(headMarker * 1.2);

      float alpha = (edgeGlow * 0.75 + dashAlpha * 0.35 + headMarker) * (1.0 - edgeDist * 0.4);
      gl_FragColor = vec4(finalColor, clamp(alpha, 0.0, 0.95));
    }
  `
};
