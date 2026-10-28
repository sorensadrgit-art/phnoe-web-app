import React from 'react';
import { createRoot } from 'react-dom/client';
import { resolveDeploymentSurface } from './deploymentMode.js';
import './styles.css';
import './unified.css';

async function boot() {
  // The cloud build never bundles the local research-workspace module.
  const cloudBuild = import.meta.env.MODE === 'cloud';
  const { default: App } = cloudBuild
    ? await import('./CloudDemoApp.jsx')
    : resolveDeploymentSurface(window.location.hostname) === 'desktop'
      ? await import('./UnifiedApp.jsx')
      : await import('./CloudDemoApp.jsx');

  createRoot(document.getElementById('root')).render(
    <React.StrictMode><App /></React.StrictMode>
  );
}

boot();
