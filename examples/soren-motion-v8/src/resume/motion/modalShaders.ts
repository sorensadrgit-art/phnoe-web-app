export const ambientVertexShader = `
varying vec2 vUv;

void main() {
  vUv = uv;
  gl_Position = vec4(position, 1.0);
}
`;

export const ambientFragmentShader = `
uniform float uTime;
uniform vec3 uAccentColor;
uniform vec2 uMouse;
uniform vec2 uResolution;
varying vec2 vUv;

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
}

float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  float a = hash(i);
  float b = hash(i + vec2(1.0, 0.0));
  float c = hash(i + vec2(0.0, 1.0));
  float d = hash(i + vec2(1.0, 1.0));
  return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

void main() {
  vec2 st = (gl_FragCoord.xy * 2.0 - uResolution) / min(uResolution.x, uResolution.y);
  vec2 mouseOffset = (uMouse - 0.5) * 0.35;

  float t = uTime * 0.15;
  float n1 = noise(st * 1.6 + vec2(t * 0.35, -t * 0.25) + mouseOffset);
  float n2 = noise(st * 3.2 - vec2(t * 0.18, t * 0.4));
  float field = smoothstep(0.3, 0.75, n1 * 0.6 + n2 * 0.4);

  // Subtle coordinate grid overlay
  vec2 grid = abs(fract(st * 10.0 - 0.5) - 0.5) / fwidth(st * 10.0);
  float line = min(grid.x, grid.y);
  float gridPattern = 1.0 - min(line, 1.0);

  // Soft cursor follow spotlight
  float distToMouse = length(vUv - uMouse);
  float mouseGlow = exp(-distToMouse * 3.8);

  vec3 baseColor = vec3(0.027, 0.039, 0.055);
  vec3 glow = uAccentColor * (field * 0.18 + mouseGlow * 0.22);
  vec3 gridLattice = uAccentColor * gridPattern * 0.05;

  vec3 finalColor = baseColor + glow + gridLattice;
  gl_FragColor = vec4(finalColor, 0.42);
}
`;
