import React, { useEffect, useRef } from 'react';
import gsap from 'gsap';

export interface MotionGraphicTypeProps {
  text: string;
  kicker?: string;
  variant?: 'stagger' | 'wave' | 'telemetry-scramble';
  reduced?: boolean;
  className?: string;
  as?: 'h1' | 'h2' | 'h3' | 'div';
}

export function MotionGraphicType({
  text,
  kicker,
  variant = 'stagger',
  reduced = false,
  className = '',
  as = 'h1'
}: MotionGraphicTypeProps): React.JSX.Element {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const prefersReducedMotion = reduced || window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReducedMotion || !containerRef.current) {
      return;
    }

    const chars = containerRef.current.querySelectorAll<HTMLElement>('.ex-kinetic-char');
    if (!chars.length) return;

    const ctx = gsap.context(() => {
      if (variant === 'telemetry-scramble') {
        gsap.fromTo(
          chars,
          { opacity: 0, y: 14, filter: 'blur(6px)' },
          {
            opacity: 1,
            y: 0,
            filter: 'blur(0px)',
            duration: 0.45,
            ease: 'steps(6)',
            stagger: 0.018
          }
        );
      } else if (variant === 'wave') {
        gsap.fromTo(
          chars,
          { opacity: 0, y: 22, rotateY: 35 },
          {
            opacity: 1,
            y: 0,
            rotateY: 0,
            duration: 0.7,
            ease: 'sine.out',
            stagger: {
              each: 0.025,
              from: 'center'
            }
          }
        );
      } else {
        // default: stagger
        gsap.fromTo(
          chars,
          { opacity: 0, y: 20, rotateX: -30, filter: 'blur(4px)' },
          {
            opacity: 1,
            y: 0,
            rotateX: 0,
            filter: 'blur(0px)',
            duration: 0.6,
            ease: 'power3.out',
            stagger: 0.02
          }
        );
      }
    }, containerRef);

    return () => {
      ctx.revert();
    };
  }, [text, variant, reduced]);

  const Tag = as;
  const accessibleLabel = kicker ? `${kicker} - ${text}` : text;
  const chars = Array.from(text);

  return (
    <div className={`ex-kinetic-title-wrap ${className}`} ref={containerRef}>
      {kicker && (
        <span className="ex-kinetic-kicker">
          <span className="ex-kicker-caret">[</span>
          {kicker}
          <span className="ex-kicker-caret">]</span>
        </span>
      )}
      <Tag
        className="ex-kinetic-title"
        aria-label={accessibleLabel}
        data-variant={variant}
      >
        <span aria-hidden="true" className="ex-kinetic-chars-wrapper">
          {chars.map((char, index) => (
            <span
              key={`${char}-${index}`}
              className="ex-kinetic-char"
              data-char={char}
            >
              {char === ' ' ? '\u00A0' : char}
            </span>
          ))}
        </span>
      </Tag>
    </div>
  );
}
