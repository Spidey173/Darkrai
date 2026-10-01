'use client';

import { useEffect, useState } from 'react';
import { useRouter, useParams } from 'next/navigation';
import { ArrowLeft, Trash2, ShieldAlert, Plus, Info } from 'lucide-react';
import styles from '../../../../../styles/dashboard.module.css';

interface Rule {
  id: string;
  name: string;
  event_type: string;
  conditions: {
    field: string;
    operator: string;
    value: string;
  };
  actions: Array<{
    type: string;
    value: string;
  }>;
  is_active: boolean;
}

export default function RulesPage() {
  const router = useRouter();
  const params = useParams();
  const repoId = params.id as string;

  const [rules, setRules] = useState<Rule[]>([]);
  const [loading, setLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState('');

  // Form state
  const [name, setName] = useState('');
  const [eventType, setEventType] = useState('issues');
  const [keyword, setKeyword] = useState('');

  const [enableLabel, setEnableLabel] = useState(false);
  const [labelText, setLabelText] = useState('bug');

  const [enableComment, setEnableComment] = useState(false);
  const [commentText, setCommentText] = useState(
    'Thank you for reporting. The bot has logged this item.'
  );

  const [enableSlack, setEnableSlack] = useState(false);
  const [slackText, setSlackText] = useState(
    'Issue #{number} opened in {repo}: *{title}*'
  );

  const fetchRules = async () => {
    try {
      const res = await fetch(`/api/v1/repos/${repoId}/rules`);
      if (res.ok) {
        const data = await res.json();
        setRules(data);
      }
    } catch (e) {
      console.error('Failed to fetch rules:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRules();
  }, [repoId]);

  const handleToggleRule = async (ruleId: string) => {
    setRules((prev) =>
      prev.map((r) => (r.id === ruleId ? { ...r, is_active: !r.is_active } : r))
    );
    try {
      const res = await fetch(`/api/v1/rules/${ruleId}/toggle`, { method: 'PATCH' });
      if (!res.ok) await fetchRules();
    } catch {
      await fetchRules();
    }
  };

  const handleDeleteRule = async (ruleId: string) => {
    if (!confirm('Delete this automation rule?')) return;
    try {
      const res = await fetch(`/api/v1/rules/${ruleId}`, { method: 'DELETE' });
      if (res.ok) setRules((prev) => prev.filter((r) => r.id !== ruleId));
    } catch (e) {
      console.error('Delete rule failed:', e);
    }
  };

  const handleCreateRule = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !keyword.trim()) {
      setErrorMsg('Rule name and condition keyword are required.');
      return;
    }
    if (!enableLabel && !enableComment && !enableSlack) {
      setErrorMsg('Configure at least one action (label, comment, or Slack).');
      return;
    }
    setErrorMsg('');

    const conditions = { field: 'title', operator: 'contains', value: keyword };
    const actions: Array<{ type: string; value: string }> = [];
    if (enableLabel && labelText) actions.push({ type: 'add_label', value: labelText });
    if (enableComment && commentText) actions.push({ type: 'create_comment', value: commentText });
    if (enableSlack && slackText) actions.push({ type: 'send_slack', value: slackText });

    try {
      const res = await fetch(`/api/v1/repos/${repoId}/rules`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, event_type: eventType, conditions, actions }),
      });

      if (res.ok) {
        setName('');
        setKeyword('');
        setEnableLabel(false);
        setEnableComment(false);
        setEnableSlack(false);
        await fetchRules();
      } else {
        const data = await res.json();
        setErrorMsg(data.detail || 'Failed to create rule.');
      }
    } catch {
      setErrorMsg('Failed to save rule.');
    }
  };

  const getActionLabel = (type: string): string => {
    switch (type) {
      case 'add_label':     return 'Label';
      case 'create_comment': return 'Comment';
      case 'send_slack':    return 'Slack';
      default: return type.replace(/_/g, ' ');
    }
  };

  if (loading) {
    return (
      <div role="status" aria-label="Loading rules">
        <button className={styles.backBtn} disabled>
          <ArrowLeft size={14} aria-hidden="true" />
          Back
        </button>
        <div className={styles.twoCol}>
          {[0, 1].map((i) => (
            <div key={i} className={styles.skeletonCard} style={{ height: '200px' }} />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div>
      {/* ── Back button ──────────────────────────── */}
      <button
        className={styles.backBtn}
        onClick={() => router.push('/dashboard/repos')}
        aria-label="Back to repositories"
      >
        <ArrowLeft size={14} aria-hidden="true" />
        Repositories
      </button>

      {/* ── Page header ──────────────────────────── */}
      <div className={styles.pageHeader}>
        <div className={styles.pageHeaderLeft}>
          <h1 className={styles.pageTitle}>Automation Rules</h1>
          <p className={styles.pageSubtitle}>
            {rules.length} rule{rules.length !== 1 ? 's' : ''} configured for this repository
          </p>
        </div>
      </div>

      {/* ── Two column layout ────────────────────── */}
      <div className={styles.twoCol}>

        {/* ── Rules list ──────────────────────────── */}
        <section aria-labelledby="rules-list-title">
          <div className={styles.sectionCard}>
            <div className={styles.sectionHead}>
              <h2 id="rules-list-title" className={styles.sectionTitle}>
                Configured Rules
              </h2>
              <span className={styles.sectionSubtitle}>{rules.length} total</span>
            </div>

            {rules.length === 0 ? (
              <div className={styles.emptyState}>
                <div className={styles.emptyIcon} aria-hidden="true">
                  <ShieldAlert size={26} />
                </div>
                <p className={styles.emptyTitle}>No rules yet</p>
                <p className={styles.emptyDesc}>
                  Use the form to create your first automation rule.
                </p>
              </div>
            ) : (
              <div style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '10px' }} role="list" aria-label="Automation rules">
                {rules.map((rule, i) => (
                  <article
                    key={rule.id}
                    className={`${styles.ruleCard} ${!rule.is_active ? styles.ruleCardInactive : ''}`}
                    style={{ animationDelay: `${i * 0.05}s` }}
                    role="listitem"
                  >
                    <div className={styles.ruleCardTop}>
                      <h3 className={styles.ruleName}>{rule.name}</h3>
                      <div className={styles.ruleControls}>
                        {/* Toggle */}
                        <label
                          className={styles.togglePill}
                          title={rule.is_active ? 'Disable rule' : 'Enable rule'}
                        >
                          <input
                            type="checkbox"
                            checked={rule.is_active}
                            onChange={() => handleToggleRule(rule.id)}
                            aria-label={`Toggle rule "${rule.name}"`}
                          />
                          <span className={styles.togglePillSlider} />
                        </label>
                        {/* Delete */}
                        <button
                          className={`${styles.btn} ${styles.btnDanger} ${styles.btnIconOnly}`}
                          onClick={() => handleDeleteRule(rule.id)}
                          aria-label={`Delete rule "${rule.name}"`}
                        >
                          <Trash2 size={13} aria-hidden="true" />
                        </button>
                      </div>
                    </div>

                    <p className={styles.ruleCondition}>
                      When{' '}
                      <span className={styles.ruleConditionCode}>{rule.event_type}</span>
                      {' '}title contains{' '}
                      <span className={styles.ruleConditionCode}>
                        &ldquo;{rule.conditions.value}&rdquo;
                      </span>
                    </p>

                    <div className={styles.ruleChips} aria-label="Actions">
                      {rule.actions.map((act, idx) => (
                        <span key={idx} className={styles.ruleChip}>
                          {getActionLabel(act.type)}
                        </span>
                      ))}
                    </div>
                  </article>
                ))}
              </div>
            )}
          </div>
        </section>

        {/* ── Create rule form ─────────────────────── */}
        <section aria-labelledby="create-rule-title">
          <div className={styles.formPanel}>
            <h2 id="create-rule-title" className={styles.formPanelTitle}>
              Create Automation Rule
            </h2>

            {errorMsg && (
              <div className={styles.alertError} role="alert">{errorMsg}</div>
            )}

            <form onSubmit={handleCreateRule} noValidate>
              {/* Rule name */}
              <div className={styles.formGroup}>
                <label htmlFor="rule-name" className={styles.formLabel}>Rule Name</label>
                <input
                  id="rule-name"
                  type="text"
                  className={styles.input}
                  placeholder="e.g. Auto tag bug reports"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  aria-required="true"
                />
              </div>

              {/* Event type */}
              <div className={styles.formGroup}>
                <label htmlFor="event-type" className={styles.formLabel}>Event Source</label>
                <select
                  id="event-type"
                  className={styles.select}
                  value={eventType}
                  onChange={(e) => setEventType(e.target.value)}
                >
                  <option value="issues">GitHub Issues</option>
                  <option value="pull_request">GitHub Pull Requests</option>
                </select>
              </div>

              {/* Keyword condition */}
              <div className={styles.formGroup}>
                <label htmlFor="keyword" className={styles.formLabel}>
                  If Title Contains Keyword
                </label>
                <input
                  id="keyword"
                  type="text"
                  className={styles.input}
                  placeholder="e.g. bug, fix, critical"
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                  aria-required="true"
                  aria-describedby="keyword-hint"
                />
                <span id="keyword-hint" className={styles.formHint}>
                  Case-insensitive. Partial matching supported.
                </span>
              </div>

              <div className={styles.formSectionDivider} aria-hidden="true" />
              <p className={styles.formSectionTitle}>Then Execute</p>

              {/* Label action */}
              <div className={`${styles.actionBlock} ${enableLabel ? styles.actionBlockActive : ''}`}>
                <label className={styles.actionCheckLabel}>
                  <input
                    type="checkbox"
                    className={styles.actionCheckInput}
                    checked={enableLabel}
                    onChange={(e) => setEnableLabel(e.target.checked)}
                    aria-controls="label-input"
                  />
                  Apply Label to Issue / PR
                </label>
                {enableLabel && (
                  <div className={styles.actionExpand} id="label-input">
                    <input
                      type="text"
                      className={styles.input}
                      placeholder="Label name, e.g. bug"
                      value={labelText}
                      onChange={(e) => setLabelText(e.target.value)}
                      aria-label="Label text"
                    />
                  </div>
                )}
              </div>

              {/* Comment action */}
              <div className={`${styles.actionBlock} ${enableComment ? styles.actionBlockActive : ''}`}>
                <label className={styles.actionCheckLabel}>
                  <input
                    type="checkbox"
                    className={styles.actionCheckInput}
                    checked={enableComment}
                    onChange={(e) => setEnableComment(e.target.checked)}
                    aria-controls="comment-input"
                  />
                  Post Comment
                </label>
                {enableComment && (
                  <div className={styles.actionExpand} id="comment-input">
                    <textarea
                      className={styles.textarea}
                      value={commentText}
                      onChange={(e) => setCommentText(e.target.value)}
                      aria-label="Comment text"
                    />
                  </div>
                )}
              </div>

              {/* Slack action */}
              <div className={`${styles.actionBlock} ${enableSlack ? styles.actionBlockActive : ''}`} style={{ marginBottom: '24px' }}>
                <label className={styles.actionCheckLabel}>
                  <input
                    type="checkbox"
                    className={styles.actionCheckInput}
                    checked={enableSlack}
                    onChange={(e) => setEnableSlack(e.target.checked)}
                    aria-controls="slack-input"
                  />
                  Send Slack Notification
                </label>
                {enableSlack && (
                  <div className={styles.actionExpand} id="slack-input">
                    <textarea
                      className={styles.textarea}
                      value={slackText}
                      onChange={(e) => setSlackText(e.target.value)}
                      aria-label="Slack message template"
                      style={{ marginBottom: '8px' }}
                    />
                    <div style={{ display: 'flex', alignItems: 'flex-start', gap: '6px', color: 'var(--text-ghost)', fontSize: '0.75rem', lineHeight: '1.5' }}>
                      <Info size={12} style={{ flexShrink: 0, marginTop: '2px' }} aria-hidden="true" />
                      <span>
                        Supports{' '}
                        <code style={{ fontFamily: 'monospace', color: 'var(--ember)' }}>{'{number}'}</code>,{' '}
                        <code style={{ fontFamily: 'monospace', color: 'var(--ember)' }}>{'{title}'}</code>,{' '}
                        <code style={{ fontFamily: 'monospace', color: 'var(--ember)' }}>{'{repo}'}</code>
                      </span>
                    </div>
                  </div>
                )}
              </div>

              <button
                type="submit"
                className={`${styles.btn} ${styles.btnPrimary} ${styles.btnFull} ${styles.btnLg}`}
              >
                <Plus size={16} aria-hidden="true" />
                Save Rule
              </button>
            </form>
          </div>
        </section>

      </div>
    </div>
  );
}
