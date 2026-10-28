const LOCAL_HOSTS = new Set(['127.0.0.1', 'localhost', '::1', '[::1]']);

/**
 * The Windows launcher's loopback app remains the full research workspace.
 * Every other host is deliberately restricted to the synthetic web demonstration.
 */
export function resolveDeploymentSurface(hostname) {
  const host = String(hostname ?? '').trim().toLowerCase();
  return LOCAL_HOSTS.has(host) ? 'desktop' : 'web-demo';
}
