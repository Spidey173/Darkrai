'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Flame, Webhook, Zap, GitBranch, ArrowRight, Github } from 'lucide-react';
import styles from '../styles/landing.module.css';

export default function Home() {
  const [authState, setAuthState] = useState<'loading' | 'authenticated' | 'guest'>('loading');

  useEffect(() => {
    fetch('/api/v1/auth/me')
      .then((res) => setAuthState(res.ok ? 'authenticated' : 'guest'))
      .catch(() => setAuthState('guest'));
  }, []);

  return (
    <div className={styles.page}>
      {/* Ambient background */}
      <div className={styles.ambientOrb1} aria-hidden="true" />
      <div className={styles.ambientOrb2} aria-hidden="true" />

      {/* Floating particles */}
      <div className={styles.particles} aria-hidden="true">
        <span className={styles.particle} />
        <span className={styles.particle} />
        <span className={styles.particle} />
        <span className={styles.particle} />
        <span className={styles.particle} />
        <span className={styles.particle} />
      </div>

      {/* ── Navbar ───────────────────────────────────── */}
      <nav className={styles.navbar} role="navigation" aria-label="Main navigation">
        <div className={styles.brand}>
          <div className={styles.brandIcon} aria-hidden="true">
            <Flame size={18} />
          </div>
          <span className={styles.brandName}>Darkrai</span>
        </div>
        <a
          href="/api/v1/auth/github/login"
          className={styles.navCta}
          aria-label="Sign in with GitHub"
        >
          <Github size={16} aria-hidden="true" />
          Sign in
        </a>
      </nav>

      {/* ── Hero ─────────────────────────────────────── */}
      <section className={styles.hero} aria-labelledby="hero-heading">
        <div className={styles.heroEyebrow}>
          <span className={styles.heroEyebrowDot} aria-hidden="true" />
          Event-Driven GitHub Automation
        </div>

        <h1 id="hero-heading" className={styles.heroHeading}>
          Automate your{' '}
          <span className={styles.heroHeadingAccent}>GitHub workflows</span>
          {' '}in seconds
        </h1>

        <p className={styles.heroDescription}>
          Connect repositories, define smart trigger rules, auto-label issues,
          post comments, and dispatch Slack alerts — all driven by live webhook events.
        </p>

        {/* Auth-aware CTA card */}
        {authState === 'loading' ? (
          <div className={styles.heroLoader} role="status" aria-label="Checking session">
            <div className={styles.loaderRing} aria-hidden="true" />
          </div>
        ) : authState === 'authenticated' ? (
          <div className={styles.heroCard}>
            <p className={styles.heroCardTitle}>Session Active</p>
            <p className={styles.heroCardSubtitle}>
              Your GitHub account is connected and ready to automate.
            </p>
            <Link href="/dashboard" className={styles.btnPrimary} aria-label="Open dashboard">
              <ArrowRight size={16} aria-hidden="true" />
              Open Dashboard
            </Link>
          </div>
        ) : (
          <div className={styles.heroCard}>
            <p className={styles.heroCardTitle}>Start Automating</p>
            <p className={styles.heroCardSubtitle}>
              Sign in with GitHub to connect your repositories and configure automation rules.
            </p>
            <a
              href="/api/v1/auth/github/login"
              className={styles.btnPrimary}
              aria-label="Sign in with GitHub"
            >
              <Github size={16} aria-hidden="true" />
              Continue with GitHub
            </a>
          </div>
        )}
      </section>

      {/* ── How It Works ─────────────────────────────── */}
      <section className={styles.howSection} aria-labelledby="how-heading">
        <span className={styles.sectionLabel}>How It Works</span>
        <h2 id="how-heading" className={styles.sectionHeading}>
          Three steps from event to action
        </h2>

        <div className={styles.howGrid} role="list">
          <article className={styles.howStep} role="listitem">
            <div className={styles.howStepNumber} aria-hidden="true">01</div>
            <div className={styles.howStepIcon} aria-hidden="true">
              <Webhook size={22} />
            </div>
            <h3 className={styles.howStepTitle}>Webhook Ingestion</h3>
            <p className={styles.howStepDesc}>
              GitHub sends signed webhook payloads to Darkrai. Every event is verified
              with HMAC-SHA256 and deduplicated before processing.
            </p>
          </article>

          <article className={styles.howStep} role="listitem">
            <div className={styles.howStepNumber} aria-hidden="true">02</div>
            <div className={styles.howStepIcon} aria-hidden="true">
              <Zap size={22} />
            </div>
            <h3 className={styles.howStepTitle}>Rule Engine</h3>
            <p className={styles.howStepDesc}>
              Each event is evaluated against your custom trigger rules — matching on
              issue titles, PR labels, keywords, or any configurable condition.
            </p>
          </article>

          <article className={styles.howStep} role="listitem">
            <div className={styles.howStepNumber} aria-hidden="true">03</div>
            <div className={styles.howStepIcon} aria-hidden="true">
              <GitBranch size={22} />
            </div>
            <h3 className={styles.howStepTitle}>Action Dispatch</h3>
            <p className={styles.howStepDesc}>
              Matched rules fire instantly — applying labels, posting comments,
              or sending Slack notifications with full audit logging.
            </p>
          </article>
        </div>
      </section>

      {/* ── Features ─────────────────────────────────── */}
      <section className={styles.featuresSection} aria-labelledby="features-heading">
        <span className={styles.sectionLabel}>Capabilities</span>
        <h2 id="features-heading" className={styles.sectionHeading}>
          Everything you need
        </h2>

        <div className={styles.featuresGrid} role="list">
          <article className={styles.featureCard} role="listitem">
            <div className={styles.featureIconWrap} aria-hidden="true">
              <Webhook size={22} />
            </div>
            <h3 className={styles.featureTitle}>Live Webhook Observability</h3>
            <p className={styles.featureDesc}>
              Monitor every inbound webhook in real time with a live event feed,
              status tracking, and expandable action audit logs.
            </p>
          </article>

          <article className={styles.featureCard} role="listitem">
            <div className={styles.featureIconWrap} aria-hidden="true">
              <Zap size={22} />
            </div>
            <h3 className={styles.featureTitle}>Flexible Rule Builder</h3>
            <p className={styles.featureDesc}>
              Configure trigger conditions per repository — match keywords, field
              values, or operators — and chain multiple actions per rule.
            </p>
          </article>

          <article className={styles.featureCard} role="listitem">
            <div className={styles.featureIconWrap} aria-hidden="true">
              <Flame size={22} />
            </div>
            <h3 className={styles.featureTitle}>Multi-Action Execution</h3>
            <p className={styles.featureDesc}>
              Trigger labels, comments, and Slack alerts from a single rule.
              All actions are idempotent and logged with detailed execution traces.
            </p>
          </article>
        </div>
      </section>

      {/* ── Footer ───────────────────────────────────── */}
      <footer className={styles.footer} role="contentinfo">
        <span className={styles.footerBrand}>Darkrai</span>
        <span className={styles.footerNote}>
          Event-driven GitHub automation platform
        </span>
      </footer>
    </div>
  );
}
