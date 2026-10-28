import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type PointerEvent } from 'react';
import gsap from 'gsap';
import { useInertialTrack } from './useInertialTrack';
import type { ResumeRibbonScene } from './ResumeRibbonScene';
import { carouselPositions, getSectionIndexFromHash, resumeSections, stepIndex } from './resumeData';
import { luxuryTokens, sectionAccents } from './luxuryTokens';
import {SectionExplorer} from './SectionExplorer';
import {flightEase} from './reference-motion.mjs';
import './legacy.css';
import './explorers.css';

const count = resumeSections.length;
const initialFocus = 0;

function useReducedMotion() {
  const [reduced, setReduced] = useState(() =>
    typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setReduced(query.matches);
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  return reduced;
}

export function ResumeExperience() {
  const [focusedIndex, setFocusedIndex] = useState(initialFocus);
  const [openId, setOpenId] = useState<string | null>(null);
  const [indexOpen, setIndexOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [initialProject, setInitialProject] = useState('kinelab');
  const [displayMode, setDisplayMode] = useState<'featured' | 'full'>('featured');
  const [isDragging, setIsDragging] = useState(false);
  const reduced = useReducedMotion();
  const [introDone, setIntroDone] = useState(() => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const appRef = useRef<HTMLDivElement>(null);
  const [desktopGl, setDesktopGl] = useState(() => typeof window !== 'undefined' && window.innerWidth >= 900);
  const [glReady, setGlReady] = useState(false);
  const glCanvasRef = useRef<HTMLCanvasElement>(null);
  const glSceneRef = useRef<ResumeRibbonScene | null>(null);
  const latestView = useRef({ focusedIndex, isDetailOpen: Boolean(openId) });
  latestView.current = { focusedIndex, isDetailOpen: Boolean(openId || indexOpen || profileOpen) };
  const detailRef = useRef<HTMLDivElement>(null);
  const closingRef = useRef<gsap.core.Tween | null>(null);
  const pointerStart = useRef<{x:number,y:number}|null>(null);
  const hasDragged = useRef(false);
  const suppressClickUntil = useRef(0);
  const returnFocus = useRef<string>('about');
  const returnControl = useRef<HTMLElement | null>(null);
  const focusRaf = useRef<number | null>(null);
  const modalOpen = Boolean(openId || indexOpen || profileOpen);

  const { trackRef, goTo: trackGoTo, wheel: trackWheel, drag: trackDrag } = useInertialTrack({
    count, initialIndex: initialFocus, reduced, detailOpen: modalOpen,
    onSelected: (index:number) => {
      if (!latestView.current.isDetailOpen) setFocusedIndex(index);
    },
    onFrame: (speed:number) => glSceneRef.current?.setMotionSpeed(speed)
  });

  const activeSection = openId ? resumeSections.find(item => item.id === openId) : null;

  useEffect(() => {
    if (reduced || !appRef.current) {
      setIntroDone(true);
      return;
    }
    const root = appRef.current;
    const bars = root.querySelectorAll('.sr-intro-bar');
    const backdrop = root.querySelector('.sr-intro');
    const surfaces = [root.querySelector('.sr-stage'), root.querySelector('.sr-ribbon-canvas')].filter(Boolean);
    const tl = gsap.timeline({
      onComplete: () => setIntroDone(true)
    });
    tl.set(bars,{autoAlpha:0},0);tl.set(surfaces,{opacity:1},0);
    tl.to(backdrop,{autoAlpha:0,duration:.3,ease:'power1.out'},.85);
    tl.set(surfaces,{clearProps:'opacity'},3.2);
    return () => { tl.kill(); gsap.set(surfaces,{clearProps:'opacity'}); };
  }, [reduced]);

  useEffect(() => {
    const onSize = () => setDesktopGl(window.innerWidth >= 900);
    window.addEventListener('resize', onSize, { passive: true });
    return () => {
      window.removeEventListener('resize', onSize);
      if (focusRaf.current !== null) cancelAnimationFrame(focusRaf.current);
    };
  }, []);

  useEffect(() => {
    if (!desktopGl || reduced || !glCanvasRef.current) {
      setGlReady(false);
      return;
    }
    let alive = true;
    let renderer: ResumeRibbonScene | null = null;

    import('./ResumeRibbonScene').then(async ({ ResumeRibbonScene }) => {
      if (!alive || !glCanvasRef.current) return;
      renderer = new ResumeRibbonScene(glCanvasRef.current, resumeSections, ready => { if (alive) setGlReady(ready); });
      glSceneRef.current = renderer;
      const ready = await renderer.initialize();
      if (alive && ready) {
        renderer.update(latestView.current.focusedIndex, latestView.current.isDetailOpen);
        setGlReady(true);
      }
    }).catch(error => {
      if (alive) console.warn('Curved ribbon unavailable; CSS cards remain visible.', error);
    });

    return () => {
      alive = false;
      renderer?.dispose();
      if (glSceneRef.current === renderer) glSceneRef.current = null;
    };
    // Renderer lifetime is determined by device capability, not the current section.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [desktopGl, reduced]);

  useEffect(() => {
    glSceneRef.current?.update(focusedIndex, modalOpen);
  }, [focusedIndex, modalOpen]);

  const closePanels = useCallback(() => {
    if (closingRef.current) return;
    const finish = () => {
      closingRef.current = null;
      setOpenId(null);
      setIndexOpen(false);
      setProfileOpen(false);

      setDisplayMode('featured');
      if (window.location.hash) {
        window.history.pushState(null, '', window.location.pathname + window.location.search);
      }
      if (focusRaf.current !== null) cancelAnimationFrame(focusRaf.current);
      focusRaf.current = window.requestAnimationFrame(() => {
        focusRaf.current = null;
        const button = document.querySelector<HTMLButtonElement>('[data-resume-card="' + returnFocus.current + '"]');
        const target = returnControl.current?.isConnected ? returnControl.current : button;
        target?.focus({ preventScroll: true });
      });
    };
    const sheet = detailRef.current;
    if (openId && sheet && !reduced) {
      const card = document.querySelector<HTMLElement>('[data-resume-card="' + openId + '"]');
      const source = card?.getBoundingClientRect();
      const dest = sheet.getBoundingClientRect();
      closingRef.current = gsap.to(sheet, {
        transformOrigin: '50% 50%',
        x: source ? source.left + source.width/2 - (dest.left + dest.width/2) : 0,
        y: source ? source.top + source.height/2 - (dest.top + dest.height/2) : 25,
        scaleX: source ? Math.min(1, source.width/dest.width) : .8,
        scaleY: source ? Math.min(1, source.height/dest.height) : .62,
        opacity: 0, duration: 1, ease: flightEase,
        onComplete: finish
      });
    } else {
      finish();
    }
  }, [openId, reduced]);

  const openSection = useCallback((index: number, project = 'kinelab') => {
    const section = resumeSections[index];
    if (!section) return;
    if (focusRaf.current !== null) {
      cancelAnimationFrame(focusRaf.current);
      focusRaf.current = null;
    }
    if (!modalOpen) {
      const current = document.activeElement as HTMLElement | null;
      returnControl.current = current?.closest('[data-resume-clone]') || current === document.body ? null : current;
    }
    closingRef.current?.kill();
    closingRef.current = null;
    returnFocus.current = section.id;
    setInitialProject(project);
    setFocusedIndex(index);
    trackGoTo(index);
    setOpenId(section.id);

    setIndexOpen(false);
    setProfileOpen(false);
    setDisplayMode('featured');
    if (window.location.hash !== '#' + section.id) {
      window.history.pushState(null, '', '#' + section.id);
    }
  }, [trackGoTo, modalOpen]);

  const toggleIndex = useCallback(() => {
    const next = !indexOpen;
    setOpenId(null);
    setProfileOpen(false);
    setIndexOpen(next);
    setDisplayMode(next ? 'full' : 'featured');
    if (window.location.hash) window.history.pushState(null, '', window.location.pathname + window.location.search);
  }, [indexOpen]);

  const goToFocus = useCallback((direction: number) => {
    if (focusRaf.current !== null) {
      cancelAnimationFrame(focusRaf.current);
      focusRaf.current = null;
    }
    const next = stepIndex(focusedIndex, direction, count);
    returnFocus.current = resumeSections[next].id;
    returnControl.current = null;
    setFocusedIndex(next);
    trackGoTo(next);
  }, [focusedIndex, trackGoTo]);

  useEffect(() => {
    const readHash = (event?: Event) => {
      closingRef.current?.kill();
      closingRef.current = null;

      setIndexOpen(false);
      setProfileOpen(false);
      setDisplayMode('featured');
      const index = getSectionIndexFromHash(window.location.hash);
      if (index >= 0) {
        if (focusRaf.current !== null) {
          cancelAnimationFrame(focusRaf.current);
          focusRaf.current = null;
        }
        setFocusedIndex(index);
        trackGoTo(index);
        setInitialProject('kinelab');
        setOpenId(resumeSections[index].id);
      } else {
        setOpenId(null);
        if (event) {
          if (focusRaf.current !== null) cancelAnimationFrame(focusRaf.current);
          focusRaf.current = window.requestAnimationFrame(() => {
            focusRaf.current = null;
            const source = returnControl.current?.isConnected ? returnControl.current : document.querySelector<HTMLElement>('[data-resume-card="'+returnFocus.current+'"]');
            source?.focus({preventScroll:true});
          });
        }
      }
    };
    readHash();
    window.addEventListener('popstate', readHash);
    window.addEventListener('hashchange', readHash);
    return () => {
      window.removeEventListener('popstate', readHash);
      window.removeEventListener('hashchange', readHash);
    };
  }, [trackGoTo]);

  useLayoutEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        if (openId || profileOpen || indexOpen) closePanels();
        return;
      }
      if (indexOpen || profileOpen) return;
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
      if (event.target instanceof HTMLElement && event.target.closest('[role="tablist"], select, [role="slider"], [data-local-keys]' )) return;
      if (event.key === 'ArrowRight' && !event.altKey && !event.ctrlKey) {
        event.preventDefault();
        if (openId) openSection(stepIndex(focusedIndex, 1, count));
        else goToFocus(1);
      } else if (event.key === 'ArrowLeft' && !event.altKey && !event.ctrlKey) {
        event.preventDefault();
        if (openId) openSection(stepIndex(focusedIndex, -1, count));
        else goToFocus(-1);
      }
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [closePanels, focusedIndex, goToFocus, indexOpen, openId, openSection, profileOpen]);

  useEffect(() => {
    if (!openId || !detailRef.current) return;
    const sheet = detailRef.current;
    const copy = sheet.querySelectorAll('.ex-heading');
    gsap.set([sheet,...copy], {clearProps:'transform,opacity'});
    sheet.focus({ preventScroll: true });
    if (reduced) return;
    const source = document.querySelector<HTMLElement>('[data-resume-card="' + openId + '"]');
    const from = source?.getBoundingClientRect();
    const to = sheet.getBoundingClientRect();
    const dx = from ? from.left + from.width/2 - (to.left + to.width/2) : 0;
    const dy = from ? from.top + from.height/2 - (to.top + to.height/2) : 22;
    const scaleX = from ? Math.min(1, from.width/to.width) : .86;
    const scaleY = from ? Math.min(1, from.height/to.height) : .62;
    const timeline = gsap.timeline();
    timeline.fromTo(sheet, {
      transformOrigin: '50% 50%', x: dx, y: dy,
      scaleX, scaleY, opacity: .84, rotateZ: .5
    }, {
      x:0, y:0, scaleX:1, scaleY:1, opacity:1, rotateZ:0,
      duration: 1, ease: flightEase,
      clearProps:'transform,opacity'
    });
    timeline.fromTo(copy, { opacity:0, y:25 }, {
      opacity:1, y:0, duration:1.1, stagger:.075,
      ease:'expo.out', clearProps:'opacity,transform'
    }, .35);
    return () => { timeline.kill(); gsap.set([sheet,...copy],{clearProps:'transform,opacity'}); };
  }, [openId, reduced]);

  useEffect(() => () => { closingRef.current?.kill(); }, []);

  useEffect(() => {
    if (!openId && !indexOpen && !profileOpen) return;
    const dialog = document.querySelector<HTMLElement>('.sr-detail[role="dialog"], .sr-index-overlay[role="dialog"], .sr-profile-overlay[role="dialog"]');
    if (!dialog) return;
    if (!openId) dialog.focus({ preventScroll: true });

    const trapTab = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return;
      const focusables = Array.from(dialog.querySelectorAll<HTMLElement>(
        'button:not([disabled]), a[href], input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      )).filter(el => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden');
      if (!focusables.length) {
        event.preventDefault();
        dialog.focus({ preventScroll: true });
        return;
      }
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const current = document.activeElement;
      if (event.shiftKey && (current === first || current === dialog)) {
        event.preventDefault();
        last.focus({ preventScroll: true });
      } else if (!event.shiftKey && current === last) {
        event.preventDefault();
        first.focus({ preventScroll: true });
      } else if (!dialog.contains(current)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus({ preventScroll: true });
      }
    };
    document.addEventListener('keydown', trapTab, true);
    return () => document.removeEventListener('keydown', trapTab, true);
  }, [openId, indexOpen, profileOpen]);

  const onStageDown = (event: PointerEvent<HTMLDivElement>) => {
    if (openId || indexOpen || profileOpen || window.innerWidth <= 720) return;
    pointerStart.current = { x: event.clientX, y: event.clientY };
    hasDragged.current = false;
    setIsDragging(false);
    trackDrag(0, 'start');
  };
  const onStageMove = (event: PointerEvent<HTMLDivElement>) => {
    const start = pointerStart.current;
    if (!start || window.innerWidth <= 720) return;
    const dx = event.clientX - start.x;
    if (Math.abs(dx) > 9) {
      hasDragged.current = true;
      suppressClickUntil.current = Date.now() + 1000;
      if (!event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.setPointerCapture(event.pointerId);
      if (!isDragging) setIsDragging(true);
      trackDrag(dx, 'move');
    }
  };
  const onStageUp = (event: PointerEvent<HTMLDivElement>) => {
    const start = pointerStart.current;
    pointerStart.current = null;
    setIsDragging(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    if (!start || window.innerWidth <= 720) return;
    const dx = event.clientX - start.x;
    if (Math.abs(dx) > 10 && Math.abs(dx) > Math.abs(event.clientY - start.y)) {
      hasDragged.current = true;
      suppressClickUntil.current = Date.now() + 1000;
      trackDrag(dx, 'end');
      setTimeout(() => { hasDragged.current = false; }, 800);
    } else {
      trackDrag(0, 'end');
    }
  };
  const onStageWheel = (event: React.WheelEvent<HTMLDivElement>) => {
    if (openId || indexOpen || profileOpen || window.innerWidth <= 720) return;
    if(event.ctrlKey)return;
    if(Math.abs(event.deltaX)+Math.abs(event.deltaY)>.2)trackWheel({deltaX:event.deltaX,deltaY:event.deltaY,deltaMode:event.deltaMode,timeStamp:event.timeStamp});
  };

  return (
    <div ref={appRef} data-intro-complete={introDone ? 'true' : 'false'} style={{
      ...Object.fromEntries(Object.entries(luxuryTokens.palette).map(([key,value]) => ['--'+key.replace(/[A-Z]/g,c=>'-'+c.toLowerCase()),value])),
      '--ribbon-height': `min(${luxuryTokens.gallery.idleCardHeightSvH}svh, 880px)`,
      '--ribbon-aspect': luxuryTokens.gallery.cardAspect,
      '--ribbon-gap': `${luxuryTokens.gallery.cardGapPx}px`,
      '--focus-width': `${luxuryTokens.focus.widthVw}vw`,
      '--focus-height': `${luxuryTokens.focus.heightSvH}svh`,
      '--hover-time': `${luxuryTokens.motion.hoverMs}ms`,
      '--stage-intensity': luxuryTokens.light.stageIntensity,
      '--section-accent': luxuryTokens.palette[sectionAccents[focusedIndex]]
    } as CSSProperties} className={'sr-app' + (activeSection ? ' sr-has-detail' : '') + (indexOpen ? ' sr-has-index' : '') + (!introDone ? ' sr-intro-active' : '') + (glReady && desktopGl && !reduced ? ' sr-webgl-ready' : '')}>
      <div className="sr-ambient" aria-hidden="true" />
      <div className="sr-intro" aria-hidden="true">
        <span className="sr-intro-bar" />
        <span className="sr-intro-bar" />
        <span className="sr-intro-bar" />
      </div>
      <div className="sr-floor" aria-hidden="true" />
      <canvas ref={glCanvasRef} className="sr-ribbon-canvas" data-resume-ribbon
        aria-hidden="true" tabIndex={-1} />

      <header className="sr-header" inert={modalOpen} aria-hidden={modalOpen || undefined} onClickCapture={event => { if (!modalOpen) returnControl.current = (event.target as HTMLElement).closest('button'); }}>
        <button className="sr-identity" type="button" onClick={closePanels} aria-label="Return to résumé overview">
          <span className="sr-brand-dot" />
          <span className="sr-brand-content">
            <span className="sr-brand-name">Soren Sadr</span>
            <span className="sr-brand-role">STUDENT PHYSICAL THERAPIST / DESIGN ENGINEER</span>
          </span>
        </button>

        <nav className="sr-mode" aria-label="Resume views">
          <button type="button" title="Browse the interactive gallery" aria-pressed={displayMode === 'featured'} className={displayMode === 'featured' ? 'is-on' : ''}
            onClick={() => { closePanels(); setDisplayMode('featured'); }}>
            Featured
          </button>
          <span className="sr-mode-line" aria-hidden="true"><span /></span>
          <button type="button" title="View all six résumé topics" aria-pressed={displayMode === 'full'} className={displayMode === 'full' ? 'is-on' : ''}
            onClick={() => { setDisplayMode('full'); setIndexOpen(true); setOpenId(null); setProfileOpen(false); if (window.location.hash) window.history.pushState(null, '', window.location.pathname + window.location.search); }}>
            Full
          </button>
        </nav>

        <div className="sr-header-right">
          <button type="button" className="sr-pill" aria-expanded={profileOpen} onClick={() => {
            setProfileOpen(value => !value); setIndexOpen(false); setOpenId(null); if (window.location.hash) window.history.pushState(null, '', window.location.pathname + window.location.search);
          }}>
            <span aria-hidden="true" className="sr-person-icon"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"><circle cx="12" cy="7" r="3.3"/><path d="M5.5 21v-2.6a6.5 6.5 0 0 1 13 0V21"/></svg></span> Profile
          </button>
          <button type="button" className="sr-pill" aria-expanded={indexOpen} onClick={toggleIndex}>
            <span aria-hidden="true" className="sr-grid-icon">⠿</span> Index
          </button>
        </div>
      </header>

      <div className="sr-stage" onPointerDown={onStageDown} onPointerMove={onStageMove}
        onPointerUp={onStageUp} onPointerCancel={() => { pointerStart.current = null; hasDragged.current = false; setIsDragging(false); }}
        onClickCapture={(e) => {
          if (hasDragged.current || Date.now() < suppressClickUntil.current) {
            e.preventDefault();
            e.stopPropagation();
          }
        }}
        onWheel={onStageWheel} inert={modalOpen} aria-hidden={modalOpen || undefined} aria-label="Interactive résumé carousel">
        <div className="sr-ribbon-track" ref={trackRef}>
        {[0,1,2].flatMap(cycle => resumeSections.map((section, index) => {
          const offset = carouselPositions[index] - carouselPositions[openId ? 2 : focusedIndex];
          const canonical = cycle === 1;
          const openOffset = [-1.95, -1.3, -0.45, 0.45, 1.92, 2.65][index];
          const abs = Math.abs(offset);
          const style = {
            '--offset': String(offset),
            '--open-offset': String(openOffset),
            '--rotation': String(-offset * 9) + 'deg',
            '--scale': String(Math.max(0.72, 1 - abs * 0.095)),
            '--depth': String(-abs * 50) + 'px',
            zIndex: 20 - abs
          } as CSSProperties;
          return (
            <button key={cycle+'-'+section.id} type="button"
              data-resume-card={canonical ? section.id : undefined}
              data-resume-visual={cycle+'-'+index}
              data-resume-clone={canonical ? undefined : 'true'}
              tabIndex={canonical ? 0 : -1}
              aria-hidden={canonical ? undefined : true}
              className={'sr-card' + (canonical && index === focusedIndex ? ' is-focused' : '') + (isDragging ? ' is-dragging' : '')}
              style={style} aria-label={'Open ' + section.title + ' section'}
              onPointerEnter={() => glSceneRef.current?.setHovered(index, true)}
              onPointerLeave={() => glSceneRef.current?.setHovered(index, false)}
              onFocus={() => { if (canonical && !openId) { setFocusedIndex(index); trackGoTo(index); } }}
              onClick={() => { if (!hasDragged.current && Date.now() > suppressClickUntil.current) openSection(index); }}>
              <span className="sr-card-top">
                <span>{section.number}</span>
                <span className="sr-card-arrow" aria-hidden="true">↗</span>
              </span>
              <span className="sr-card-copy">
                <span className="sr-card-title">{section.title}</span>
                <span className="sr-card-subtitle">{section.summary}</span>
              </span>
              <span className="sr-card-art" aria-hidden="true">
                <img src={section.image} alt="" draggable={false} loading={desktopGl || index<2 ? 'eager' : 'lazy'} onError={e=>{e.currentTarget.hidden=true;}} style={{ objectPosition: section.imageFocus }} />
              </span>
            </button>
          );
        }))}
        </div>
      </div>

      {activeSection && <div className="sr-focus-arc" aria-hidden="true">
        {[-2,-1,1,2].map(offset => {
          const preview=resumeSections[stepIndex(focusedIndex,offset,count)];
          return <figure key={offset} className="sr-focus-preview" data-focus-preview={preview.id}
            style={{'--preview-side':Math.sign(offset),'--preview-rank':Math.abs(offset)} as CSSProperties}>
            <img src={preview.image} alt="" onError={e=>{e.currentTarget.hidden=true;}}/>
            <figcaption><span>{preview.number}</span><strong>{preview.title}</strong></figcaption>
          </figure>;
        })}
      </div>}

      {!openId && !indexOpen && !profileOpen && (
        <div className="sr-stage-actions" aria-label="Carousel controls">
          <button type="button" className="sr-stage-arrow" aria-label="Previous topic" onClick={() => goToFocus(-1)}>←</button>
          <span className="sr-stage-hint">Drag, scroll, or use arrows to explore</span>
          <button type="button" className="sr-stage-arrow" aria-label="Next topic" onClick={() => goToFocus(1)}>→</button>
        </div>
      )}

      {activeSection && (
        <div className="sr-detail-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) closePanels(); }}>
          <section ref={detailRef} className={'sr-detail sr-explorer'} role="dialog" aria-modal="true"
            aria-label={activeSection.title} tabIndex={-1} data-open-section={activeSection.id}>
            <button type="button" className="sr-detail-close" onClick={closePanels} aria-label="Close section">×</button>
            <SectionExplorer key={activeSection.id} section={activeSection} reduced={reduced} initialProject={initialProject} onNavigate={(id,project)=>openSection(resumeSections.findIndex(s=>s.id===id),project)}/>
            <nav className="sr-section-nav" aria-label="Section navigation">
              <button type="button" aria-label="Previous section" onClick={()=>openSection(stepIndex(focusedIndex,-1,count))}>← Previous</button>
              <button type="button" aria-label="Back to gallery" onClick={closePanels}>Back to gallery</button>
              <button type="button" aria-label="Next section" onClick={()=>openSection(stepIndex(focusedIndex,1,count))}>Next →</button>
            </nav>
          </section>
        </div>
      )}

      {indexOpen && (
        <div className="sr-index-overlay" role="dialog" aria-modal="true" aria-label="Complete resume index" tabIndex={-1}>
          <div className="sr-index-top"><span>EXPLORE / RESUME INDEX</span>
            <button type="button" aria-label="Close index" onClick={closePanels}>Close ×</button>
          </div>
          <div className="sr-index-list">
            {resumeSections.map((section,index) => (
              <button type="button" key={section.id} className="sr-index-row" onClick={() => openSection(index)}>
                <span>{section.number}</span><strong>{section.title}</strong><span>↗</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {profileOpen && (
        <div className="sr-profile-overlay" role="dialog" aria-modal="true" aria-label="Profile overview" tabIndex={-1}>
          <button type="button" className="sr-profile-close" onClick={closePanels}>Close ×</button>
          <p className="sr-profile-label">PROFILE / A LIVING RÉSUMÉ</p>
          <h2>Soren Sadr</h2>
          <p className="sr-profile-text">Student Physical Therapist / Design Engineer</p>
          <p className="sr-profile-placeholder">{resumeSections[0].lead} My work connects DPT education, creative engineering, and movement-based digital experiments.</p>
          <button type="button" className="sr-profile-action" onClick={() => openSection(0)}>Read About Me <span aria-hidden="true">↗</span></button>
          <button type="button" className="sr-profile-action" onClick={() => openSection(5)}>Get in Touch <span aria-hidden="true">↗</span></button>
        </div>
      )}

      <nav className="sr-timeline" aria-label="Resume sections" inert={modalOpen} aria-hidden={modalOpen || undefined}>
        <ol>
          {resumeSections.map((section,index) => (
            <li key={section.id}>
              <button type="button" className={'sr-timeline-link' + (focusedIndex === index ? ' is-current' : '')}
                aria-current={focusedIndex === index ? 'step' : undefined}
                aria-label={'Open ' + section.title}
                onClick={() => openSection(index)}>
                <span className="sr-timeline-number">{section.number}</span>
                <span className="sr-timeline-name">{section.title}</span>
                <span className="sr-timeline-node" aria-hidden="true" />
              </button>
            </li>
          ))}
        </ol>
      </nav>
    </div>
  );
}
