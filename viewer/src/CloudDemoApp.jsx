import React from 'react';
import LiveTrackerStudio from './LiveTrackerStudio.jsx';
import './cloudDemo.css';

const features = [
  { number: '01', title: 'Interactive kinematics', description: 'Explore generated joint angles, movement phases, repetition counts and symmetry indicators.' },
  { number: '02', title: '3D motion visualization', description: 'Orbit a browser-rendered synthetic skeleton and compare layouts in real time.' },
  { number: '03', title: 'Private by design', description: 'No camera access, patient records, or research uploads in this web demonstration. Exported JSON is synthetic.' },
];

export default function CloudDemoApp() {
  return (
    <div className="kl-cloud">
      <header className="kl-topbar">
        <a className="kl-logo" href="#top" aria-label="KineLab PT home">
          <span className="kl-logo-mark" aria-hidden="true">K</span>
          <span><strong>KINELAB <em>PT</em></strong><small>MOTION SYSTEMS / WEB</small></span>
        </a>
        <div className="kl-topbar-right">
          <span className="kl-status"><span className="kl-status-dot" /> SYNTHETIC WEB DEMO</span>
          <a className="kl-top-link" href="#studio">Launch studio <span aria-hidden="true">↗</span></a>
        </div>
      </header>

      <main id="top">
        <section className="kl-hero">
          <div className="kl-hero-orbit kl-orbit-a" aria-hidden="true" />
          <div className="kl-hero-orbit kl-orbit-b" aria-hidden="true" />
          <div className="kl-hero-content">
            <div className="kl-eyebrow"><span className="kl-eyebrow-line" /> KINE LABORATORY / RESEARCH PROTOTYPE</div>
            <h1>Motion made <span>visible.</span></h1>
            <p>Explore an interactive biomechanical interface: generated movements, 3D skeletal visualization, exercise metrics and downloadable synthetic test data.</p>
            <div className="kl-hero-actions">
              <a className="kl-primary-link" href="#studio">Explore the live simulation <span aria-hidden="true">↗</span></a>
              <span className="kl-hero-caption">No account or camera required</span>
            </div>
          </div>
          <div className="kl-hero-aside" aria-hidden="true">
            <div className="kl-hero-number">03<span>D</span></div>
            <span>RESEARCH INTERFACE</span>
            <div className="kl-hero-bars"><i /><i /><i /><i /><i /><i /><i /><i /><i /></div>
          </div>
        </section>

        <div className="kl-trust-line" role="note">
          <strong>Simulation only</strong>
          <span>Animated landmarks and performance measurements are generated—not derived from your camera or validated against physical motion capture.</span>
        </div>

        <section className="kl-workspace" id="studio" aria-labelledby="kl-studio-title">
          <div className="kl-section-head">
            <div>
              <div className="kl-eyebrow">01 / INTERACTIVE WORKSPACE</div>
              <h2 id="kl-studio-title">Motion simulation studio</h2>
              <p>Switch exercises and views, inspect the synthetic 3D twin, or finish a set to export generated JSON.</p>
            </div>
            <div className="kl-section-chip">BROWSER-ONLY · NO BACKEND</div>
          </div>
          <LiveTrackerStudio demoMode />
        </section>

        <section className="kl-features" aria-label="Web demonstration capabilities">
          {features.map(feature => (
            <article className="kl-feature" key={feature.number}>
              <span className="kl-feature-index">{feature.number} / SYSTEM</span>
              <h3>{feature.title}</h3>
              <p>{feature.description}</p>
            </article>
          ))}
        </section>
        <section className="kl-desktop-note">
          <div>
            <span className="kl-eyebrow">02 / WINDOWS RESEARCH PLATFORM</span>
            <h2>Full research processing stays local.</h2>
            <p>The installed KineLab PT desktop application retains multi-camera capture, Pose2Sim, OpenSim, SQLite sessions, evidence passports and PDF reporting. Those functions are not running on Vercel.</p>
          </div>
          <div className="kl-desktop-label">LOCAL ENGINE<br /><strong>127.0.0.1</strong></div>
        </section>
      </main>
      <footer className="kl-footer">
        <span>KINELAB PT / MOTION SYSTEMS</span>
        <span>RESEARCH PROTOTYPE · CLINICAL VALIDATION UNVERIFIED</span>
      </footer>
    </div>
  );
}
