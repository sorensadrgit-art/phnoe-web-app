import gsap from 'gsap';

export interface ChoreographyOptions {
  reduced?: boolean;
  onComplete?: () => void;
}

/**
 * Orchestrates high-impact GSAP entrance animation for modal section explorer
 */
export function animateModalEntrance(
  container: HTMLElement | null,
  options: ChoreographyOptions = {}
): gsap.core.Timeline | null {
  if (!container) return null;
  const { reduced = false, onComplete } = options;

  if (reduced) {
    gsap.set(container, { opacity: 1, scale: 1, y: 0 });
    onComplete?.();
    return null;
  }

  const tl = gsap.timeline({
    onComplete: () => {
      onComplete?.();
    }
  });

  // Base shell entrance with elastic settle
  tl.fromTo(
    container,
    { opacity: 0, scale: 0.97, y: 16 },
    { opacity: 1, scale: 1, y: 0, duration: 0.52, ease: 'power3.out' }
  );

  // Staggered text choreography
  const eyebrow = container.querySelector('.ex-eyebrow');
  const h1 = container.querySelector('.ex-heading h1');
  const lead = container.querySelector('.ex-lead');
  const stage = container.querySelector('.ex-about-stage, .ex-role-visual, .ex-anatomy-stage, .ex-project-stage, .ex-workbench, .ex-contact-stage');
  const story = container.querySelector('.ex-about-story, .ex-role-story, .ex-education-story, .ex-project-story, .ex-skills-story, .ex-contact-story');

  const textGroup = [eyebrow, h1, lead].filter(Boolean);
  if (textGroup.length > 0) {
    tl.fromTo(
      textGroup,
      { opacity: 0, y: 22 },
      { opacity: 1, y: 0, duration: 0.44, stagger: 0.08, ease: 'power2.out' },
      '-=0.35'
    );
  }

  const layoutGroup = [stage, story].filter(Boolean);
  if (layoutGroup.length > 0) {
    tl.fromTo(
      layoutGroup,
      { opacity: 0, y: 18 },
      { opacity: 1, y: 0, duration: 0.48, stagger: 0.1, ease: 'power2.out' },
      '-=0.3'
    );
  }

  return tl;
}

/**
 * Orchestrates smooth, springy tab transitions
 */
export function animateTabTransition(
  outgoingPanel: HTMLElement | null,
  incomingPanel: HTMLElement | null,
  options: ChoreographyOptions = {}
): gsap.core.Timeline | null {
  const { reduced = false, onComplete } = options;

  if (reduced || !incomingPanel) {
    if (outgoingPanel) gsap.set(outgoingPanel, { display: 'none' });
    if (incomingPanel) gsap.set(incomingPanel, { display: 'block', opacity: 1, y: 0 });
    onComplete?.();
    return null;
  }

  const tl = gsap.timeline({
    onComplete: () => {
      if (outgoingPanel) gsap.set(outgoingPanel, { display: 'none' });
      onComplete?.();
    }
  });

  if (outgoingPanel) {
    tl.to(outgoingPanel, {
      opacity: 0,
      y: -10,
      duration: 0.16,
      ease: 'power2.in'
    });
  }

  tl.fromTo(
    incomingPanel,
    { opacity: 0, y: 14, display: 'block' },
    { opacity: 1, y: 0, duration: 0.36, ease: 'power3.out' },
    outgoingPanel ? '-=0.06' : 0
  );

  return tl;
}

/**
 * Kinetic character reveal for kickers and telemetry readouts
 */
export function animateKineticKicker(
  element: HTMLElement | null,
  options: ChoreographyOptions = {}
): gsap.core.Tween | null {
  if (!element) return null;
  const { reduced = false, onComplete } = options;

  if (reduced) {
    gsap.set(element, { opacity: 1, letterSpacing: '1.5px' });
    onComplete?.();
    return null;
  }

  return gsap.fromTo(
    element,
    { opacity: 0, letterSpacing: '3px' },
    { opacity: 1, letterSpacing: '1.5px', duration: 0.4, ease: 'power2.out', onComplete }
  );
}
