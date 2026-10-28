export interface LuxuryTokens {
  palette: { ink: string; paper: string; typeInk: string; amber: string; teal: string; terracotta: string; sage: string; alpineBlue: string };
  gallery: { idleCardHeightSvH: number; cardAspect: number; cardGapPx: number; arcDepthFactor: number; pullbackFactor: number };
  focus: { widthVw: number; heightSvH: number; sideCardDepthFactor: number };
  motion: { lerp60Hz: number; hoverMs: number; openMs: number; closeMs: number };
  light: { stageIntensity: number; accentIntensity: number };
}

export const luxuryTokens: LuxuryTokens = {
  palette: { ink:'#080f12', paper:'#f3ede3', typeInk:'#242724', amber:'#d8a363', teal:'#347b83', terracotta:'#b77558', sage:'#748a69', alpineBlue:'#7fafc7' },
  gallery: { idleCardHeightSvH:39, cardAspect:1.70, cardGapPx:10, arcDepthFactor:.22, pullbackFactor:1.14 },
  focus: { widthVw:62, heightSvH:68, sideCardDepthFactor:.24 },
  motion: { lerp60Hz:.10, hoverMs:220, openMs:900, closeMs:650 },
  light: { stageIntensity:.42, accentIntensity:.30 }
};

export const sectionAccents = ['amber','terracotta','alpineBlue','amber','sage','teal'] as const;

export interface CyberneticTokens {
  palette: {
    obsidian: string;
    panelBg: string;
    panelBorder: string;
    specularRim: string;
    textPrimary: string;
    textSecondary: string;
    textMuted: string;
    emeraldBio: string;
    solarAmber: string;
    synapticCyan: string;
    cobaltCyber: string;
    neonViolet: string;
    hyperPlatinum: string;
  };
  glows: {
    emerald: string;
    amber: string;
    cyan: string;
    cobalt: string;
    violet: string;
    platinum: string;
  };
  typography: {
    display: string;
    body: string;
    mono: string;
  };
}

export const cyberneticTokens: CyberneticTokens = {
  palette: {
    obsidian: '#070a0e',
    panelBg: 'rgba(10, 13, 16, 0.82)',
    panelBorder: 'rgba(255, 255, 255, 0.12)',
    specularRim: 'rgba(255, 255, 255, 0.22)',
    textPrimary: '#f5f6fa',
    textSecondary: '#a4b0be',
    textMuted: '#57606f',
    emeraldBio: '#00f5a0',
    solarAmber: '#ff9f43',
    synapticCyan: '#00d2d3',
    cobaltCyber: '#3867d6',
    neonViolet: '#a55eea',
    hyperPlatinum: '#f5f6fa'
  },
  glows: {
    emerald: 'rgba(0, 245, 160, 0.35)',
    amber: 'rgba(255, 159, 67, 0.35)',
    cyan: 'rgba(0, 210, 211, 0.35)',
    cobalt: 'rgba(56, 103, 214, 0.35)',
    violet: 'rgba(165, 94, 234, 0.35)',
    platinum: 'rgba(245, 246, 250, 0.25)'
  },
  typography: {
    display: "'Syne', -apple-system, BlinkMacSystemFont, sans-serif",
    body: "'Space Grotesk', -apple-system, BlinkMacSystemFont, sans-serif",
    mono: "'JetBrains Mono', Consolas, monospace"
  }
};
