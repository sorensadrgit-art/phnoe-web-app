export interface ResumeBlock {
  label: string;
  value: string;
  /** Optional public-facing link. Only use verified/user-provided destinations. */
  href?: string;
}

export interface ResumeSection {
  id: string;
  number: string;
  title: string;
  summary: string;
  lead: string;
  image: string;
  imageFocus: string;
  blocks: ResumeBlock[];
}

/** Asymmetric gallery stations: preserve all six cards inside the desktop viewport. */
export const carouselPositions = [-2.2, -1.25, 0, 0.98, 1.82, 2.48] as const;

/**
 * EDITORIAL DRAFT — READ BEFORE PUBLICATION
 *
 * Education/role: based on prior user-supplied and connected context, requiring final owner approval.
 * Projects: bounded descriptions of work, not claims of published commercial results.
 * Values/focus: proposed first-person copy, not independent verification of personal opinions.
 * Contact: approved project links only; no guessed email or LinkedIn accounts.
 *
 * Update the content here without changing navigation, 3D motion, or other components.
 */
export const resumeSections: ResumeSection[] = [
  {
    id: 'about',
    number: '01',
    title: 'ABOUT ME',
    summary: 'Movement science meets creative engineering.',
    lead: 'Exploring the intersection of human movement, intelligent systems, and immersive digital design.',
    image: import.meta.env.BASE_URL + 'media/about-poster.png',
    imageFocus: 'center',
    blocks: [
      {
        label: 'MY BACKGROUND',
        value: 'I am an Arcadia University Doctor of Physical Therapy student and creative developer drawn to motion-driven digital experiences.'
      },
      {
        label: 'WHAT I VALUE',
        value: 'I aim for clear thinking, human-centered design, meaningful interaction, and motion that serves a purpose.'
      },
      {
        label: 'WHERE I FOCUS',
        value: 'Biomechanics, interactive 3D, WebGL, pose analysis, and AI-assisted systems connect many of my experiments.'
      },
      {
        label: 'CURRENT DIRECTION',
        value: 'I am developing movement-focused prototypes while progressing through physical therapy education.'
      }
    ]
  },
  {
    id: 'experience',
    number: '02',
    title: 'EXPERIENCE',
    summary: 'Education, service, design, and exploration.',
    lead: 'A multidisciplinary background spanning physical therapy education, technology, and hands-on prototyping.',
    image: import.meta.env.BASE_URL + 'media/experience-poster.png',
    imageFocus: 'center',
    blocks: [
      {
        label: 'GRADUATE ASSISTANT',
        value: 'Hybrid Lab Graduate Assistant at Arcadia University, supporting orientation and immersion activities for the Hybrid DPT program.'
      },
      {
        label: 'CREATIVE DEVELOPMENT',
        value: 'Building and exploring responsive React interfaces, cinematic GSAP animations, WebGL scenes, and reusable design systems.'
      },
      {
        label: 'MILITARY EXPERIENCE',
        value: 'U.S. Army service background. Specific assignments, responsibilities, and service dates will be added after résumé review.'
      },
      {
        label: 'CLINICAL EDUCATION',
        value: 'Doctoral studies in movement assessment, clinical reasoning, therapeutic exercise, and systems review at the student level.'
      }
    ]
  },
  {
    id: 'education',
    number: '03',
    title: 'EDUCATION',
    summary: 'Learning to understand movement.',
    lead: 'Clinical foundations and creative technology inform how I approach complex problems.',
    image: import.meta.env.BASE_URL + 'media/education-poster.png',
    imageFocus: 'center',
    blocks: [
      {
        label: 'DPT PROGRAM',
        value: 'Doctor of Physical Therapy — in progress. Hybrid DPT Class of 2028.'
      },
      {
        label: 'UNIVERSITY',
        value: 'Arcadia University. Graduate-level training in physical therapy with a hybrid learning format.'
      },
      {
        label: 'ACADEMIC INTERESTS',
        value: 'Biomechanics, exercise prescription, cardiopulmonary systems, and evidence-informed movement analysis.'
      },
      {
        label: 'INDEPENDENT LEARNING',
        value: 'Exploring Three.js, Spline, GSAP, creative coding, and AI-agent engineering alongside DPT coursework.'
      }
    ]
  },
  {
    id: 'projects',
    number: '04',
    title: 'PROJECTS',
    summary: 'Movement, code, and experiments.',
    lead: 'Selected technical explorations, from camera-based motion analysis to intelligent creative tools.',
    image: import.meta.env.BASE_URL + 'media/projects-poster.png',
    imageFocus: 'center',
    blocks: [
      {
        label: 'KINELAB PT',
        value: 'KineLab PT is a dual-camera movement-analysis prototype using ordinary cameras, pose estimation, and 3D visualization; physical accuracy remains unverified.'
      },
      {
        label: 'SOREN MCP V3',
        value: 'SOREN MCP V3 explores source-grounded coding agents, tool orchestration, and planning workflows for software builds.'
      },
      {
        label: 'STEPPR / SPLINE',
        value: 'Steppr is a Spline 3D room study with Day/Night lighting and configured first-person navigation; usability testing remains ongoing.',
        href: 'https://app.spline.design/file/a087c1a8-3639-41cd-bdcd-3da0a3343377'
      },
      {
        label: 'LIVING RÉSUMÉ',
        value: 'This portfolio experiment brings together curved Three.js cards, React interfaces, GSAP transitions, and accessible content navigation.'
      }
    ]
  },
  {
    id: 'skills',
    number: '05',
    title: 'SKILLS',
    summary: 'Design, engineering, and movement.',
    lead: 'A cross-disciplinary toolkit for creating thoughtful, technically ambitious experiences.',
    image: import.meta.env.BASE_URL + 'media/skills-poster.png',
    imageFocus: 'center',
    blocks: [
      {
        label: 'WEB ENGINEERING',
        value: 'React, Next.js, Vite, TypeScript, Tailwind CSS, responsive interfaces, and component-based development.'
      },
      {
        label: 'MOTION DESIGN',
        value: 'GSAP, ScrollTrigger, Framer Motion, kinetic transitions, animation choreography, and microinteractions.'
      },
      {
        label: '3D & CREATIVE TECH',
        value: 'Three.js, React Three Fiber, Spline, Blender, WebGL, and real-time visual prototyping.'
      },
      {
        label: 'MOVEMENT & AI',
        value: 'Student-level biomechanics, pose analysis, computer vision experiments, Python, and AI-assisted engineering.'
      }
    ]
  },
  {
    id: 'contact',
    number: '06',
    title: 'CONTACT',
    summary: 'Explore the work. Start a conversation.',
    lead: 'Interested in human movement, creative engineering, and what we can build at their intersection?',
    image: import.meta.env.BASE_URL + 'media/contact-poster.png',
    imageFocus: 'center',
    blocks: [
      {
        label: 'GITHUB',
        value: 'Explore code, prototypes, and ongoing agent-system experiments.',
        href: 'https://github.com/sorensadrgit-art'
      },
      {
        label: 'SPLINE PROJECT',
        value: 'Explore the Steppr room, a 3D environment and interaction study.',
        href: 'https://app.spline.design/file/a087c1a8-3639-41cd-bdcd-3da0a3343377'
      },
      {
        label: 'EMAIL — ADD LATER',
        value: 'A public professional email has not been added to this draft. Confirm an address before publishing.'
      },
      {
        label: 'LINKEDIN — ADD LATER',
        value: 'Confirm the correct LinkedIn profile and add its link when ready to share this résumé.'
      }
    ]
  }
];

export function getSectionIndexFromHash(hash: string): number {
  const id = hash.replace(/^#/, '').split('?')[0].toLowerCase().trim();
  if (!id) return -1;
  return resumeSections.findIndex(section => section.id === id);
}

export function stepIndex(index: number, delta: number, length: number): number {
  if (!Number.isFinite(index) || !Number.isFinite(delta) || length <= 0) return 0;
  return ((Math.trunc(index) + Math.trunc(delta)) % length + length) % length;
}
