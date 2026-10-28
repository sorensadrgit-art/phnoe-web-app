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
