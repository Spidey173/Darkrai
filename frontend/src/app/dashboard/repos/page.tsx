'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import {
  GitBranch,
  Settings,
  Plus,
  Loader2,
  Link2,
  Trash2,
  RefreshCw,
} from 'lucide-react';
import styles from '../../../styles/dashboard.module.css';

interface ConnectedRepo {
  id: string;
  github_repo_id: number;
  name: string;
  owner: string;
  full_name: string;
  is_active: boolean;
  webhook_id: number | null;
  slack_webhook_url: string | null;
}

interface GitHubRepoOption {
  github_repo_id: number;
  name: string;
  owner: string;
  full_name: string;
  description: string | null;
  private: boolean;
}

export default function ReposPage() {
  const [connectedRepos, setConnectedRepos] = useState<ConnectedRepo[]>([]);
  const [availableRepos, setAvailableRepos] = useState<GitHubRepoOption[]>([]);
  const [activeTab, setActiveTab] = useState<'connected' | 'add'>('connected');

  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');

  const [selectedRepoIndex, setSelectedRepoIndex] = useState<number>(-1);
  const [slackWebhookUrl, setSlackWebhookUrl] = useState('');

  const fetchRepos = async () => {
    try {
      const res = await fetch('/api/v1/repos');
      if (res.ok) {
        const data = await res.json();
        setConnectedRepos(data);
      }
    } catch (e) {
      console.error('Failed to load connected repositories:', e);
    }
  };

  const fetchAvailableGitHubRepos = async () => {
    try {
      const res = await fetch('/api/v1/repos/github');
      if (res.ok) {
        const data = await res.json();
        setAvailableRepos(data);
      }
    } catch (e) {
      console.error('Failed to load GitHub repositories:', e);
    }
  };

  useEffect(() => {
    const init = async () => {
      setLoading(true);
      await fetchRepos();
      setLoading(false);
    };
    init();
  }, []);

  const handleTabChange = async (tab: 'connected' | 'add') => {
    setActiveTab(tab);
    if (tab === 'add' && availableRepos.length === 0) {
      setSyncing(true);
      await fetchAvailableGitHubRepos();
      setSyncing(false);
    }
  };

  const handleConnectRepo = async (e: React.FormEvent) => {
    e.preventDefault();
    if (selectedRepoIndex < 0) {
      setErrorMsg('Please select a repository.');
      return;
    }
    setErrorMsg('');
    setSubmitting(true);
    const target = availableRepos[selectedRepoIndex];

    try {
      const res = await fetch('/api/v1/repos/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          github_repo_id: target.github_repo_id,
          name: target.name,
          owner: target.owner,
          full_name: target.full_name,
          slack_webhook_url: slackWebhookUrl || null,
        }),
      });

      if (res.ok) {
        setSlackWebhookUrl('');
        setSelectedRepoIndex(-1);
        await fetchRepos();
        setActiveTab('connected');
      } else {
        const data = await res.json();
        setErrorMsg(data.detail || 'Failed to connect repository.');
      }
    } catch {
      setErrorMsg('Network error occurred.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleToggleWebhook = async (id: string, currentlyActive: boolean) => {
    const endpoint = `/api/v1/repos/${id}/${currentlyActive ? 'disable' : 'enable'}`;
    // Optimistic update
    setConnectedRepos((prev) =>
      prev.map((r) => (r.id === id ? { ...r, is_active: !currentlyActive } : r))
    );
    try {
      const res = await fetch(endpoint, { method: 'POST' });
      if (!res.ok) {
        setConnectedRepos((prev) =>
          prev.map((r) => (r.id === id ? { ...r, is_active: currentlyActive } : r))
        );
        const data = await res.json();
        alert(data.detail || 'Action failed');
      } else {
        await fetchRepos();
      }
    } catch {
      setConnectedRepos((prev) =>
        prev.map((r) => (r.id === id ? { ...r, is_active: currentlyActive } : r))
      );
    }
  };

  const handleDisconnectRepo = async (id: string) => {
    if (!confirm('Disconnect this repository? All webhook automations will stop.')) return;
    try {
      const res = await fetch(`/api/v1/repos/${id}`, { method: 'DELETE' });
      if (res.ok) {
        await fetchRepos();
      } else {
        const data = await res.json();
        alert(data.detail || 'Failed to disconnect.');
      }
    } catch {
      alert('Network error occurred.');
    }
  };

  if (loading) {
    return (
      <div role="status" aria-label="Loading repositories">
        <div className={styles.pageHeader}>
          <div className={styles.pageHeaderLeft}>
            <div className={`${styles.skeletonLine}`} style={{ height: '28px', width: '160px', marginBottom: '8px' }} />
            <div className={`${styles.skeletonLine}`} style={{ height: '16px', width: '240px' }} />
          </div>
        </div>
        <div className={styles.repoGrid} style={{ padding: '0' }}>
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className={styles.skeletonCard} />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div>
      {/* ── Page header ──────────────────────────── */}
      <div className={styles.pageHeader}>
        <div className={styles.pageHeaderLeft}>
          <h1 className={styles.pageTitle}>Repositories</h1>
          <p className={styles.pageSubtitle}>
            {connectedRepos.length} connected · manage webhooks and automation rules
          </p>
        </div>
        <button
          className={`${styles.btn} ${styles.btnGhost}`}
          onClick={() => handleTabChange('add')}
          aria-label="Add repository"
        >
          <Plus size={15} aria-hidden="true" />
          Add Repository
        </button>
      </div>

      {/* ── Tabs ─────────────────────────────────── */}
      <div className={styles.tabs} role="tablist" aria-label="Repository sections">
        <button
          className={`${styles.tab} ${activeTab === 'connected' ? styles.tabActive : ''}`}
          onClick={() => handleTabChange('connected')}
          role="tab"
          aria-selected={activeTab === 'connected'}
          aria-controls="connected-panel"
          id="connected-tab"
        >
          Connected ({connectedRepos.length})
        </button>
        <button
          className={`${styles.tab} ${activeTab === 'add' ? styles.tabActive : ''}`}
          onClick={() => handleTabChange('add')}
          role="tab"
          aria-selected={activeTab === 'add'}
          aria-controls="add-panel"
          id="add-tab"
        >
          Add Repository
        </button>
      </div>

      {/* ── Connected tab ────────────────────────── */}
      <div
        id="connected-panel"
        role="tabpanel"
        aria-labelledby="connected-tab"
        hidden={activeTab !== 'connected'}
        style={{ marginTop: '20px' }}
      >
        {connectedRepos.length === 0 ? (
          <div className={styles.sectionCard}>
            <div className={styles.emptyState}>
              <div className={styles.emptyIcon} aria-hidden="true">
                <GitBranch size={28} />
              </div>
              <p className={styles.emptyTitle}>No repositories connected</p>
              <p className={styles.emptyDesc}>
                Add your first GitHub repository to start configuring webhook automation rules.
              </p>
              <button
                className={`${styles.btn} ${styles.btnPrimary}`}
                onClick={() => handleTabChange('add')}
              >
                <Plus size={15} aria-hidden="true" />
                Connect Repository
              </button>
            </div>
          </div>
        ) : (
          <div className={styles.repoGrid} style={{ padding: '0' }} role="list" aria-label="Connected repositories">
            {connectedRepos.map((repo, i) => (
              <article
                key={repo.id}
                className={styles.repoCard}
                style={{ animationDelay: `${i * 0.05}s` }}
                role="listitem"
              >
                <div className={styles.repoCardTop}>
                  <h2 className={styles.repoName}>
                    <GitBranch size={16} aria-hidden="true" style={{ color: 'var(--text-ghost)', flexShrink: 0 }} />
                    {repo.name}
                  </h2>
                  <p className={styles.repoOwner}>{repo.owner}</p>
                  {repo.slack_webhook_url && (
                    <span className={styles.slackBadge} aria-label="Slack connected">
                      <Link2 size={11} aria-hidden="true" />
                      Slack
                    </span>
                  )}
                </div>

                <div className={styles.repoCardDivider} aria-hidden="true" />

                {/* Status toggle */}
                <div className={styles.repoStatus}>
                  <div className={styles.repoStatusLabel}>
                    <span
                      className={`${styles.repoStatusText} ${
                        repo.is_active
                          ? styles.repoStatusTextActive
                          : styles.repoStatusTextInactive
                      }`}
                    >
                      {repo.is_active ? 'Monitoring Active' : 'Inactive'}
                    </span>
                    <span className={styles.repoStatusSub}>Webhook status</span>
                  </div>
                  <label className={styles.toggle} title={repo.is_active ? 'Disable webhook' : 'Enable webhook'}>
                    <input
                      type="checkbox"
                      checked={repo.is_active}
                      onChange={() => handleToggleWebhook(repo.id, repo.is_active)}
                      aria-label={`Toggle webhook for ${repo.name}`}
                    />
                    <span className={styles.toggleSlider} />
                  </label>
                </div>

                {/* Action buttons */}
                <div className={styles.repoActions}>
                  <Link
                    href={`/dashboard/repos/${repo.id}/rules`}
                    className={`${styles.btn} ${styles.btnGhost}`}
                    style={{ flex: 1 }}
                    aria-label={`Manage rules for ${repo.name}`}
                  >
                    <Settings size={14} aria-hidden="true" />
                    Rules
                  </Link>
                  <button
                    className={`${styles.btn} ${styles.btnDanger} ${styles.btnIconOnly}`}
                    onClick={() => handleDisconnectRepo(repo.id)}
                    aria-label={`Disconnect ${repo.name}`}
                    title="Disconnect repository"
                  >
                    <Trash2 size={14} aria-hidden="true" />
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </div>

      {/* ── Add Repository tab ───────────────────── */}
      <div
        id="add-panel"
        role="tabpanel"
        aria-labelledby="add-tab"
        hidden={activeTab !== 'add'}
        style={{ marginTop: '20px' }}
      >
        <div className={`${styles.formPanel} ${styles.connectSection}`}>
          <h2 className={styles.formPanelTitle}>Connect a Repository</h2>

          {errorMsg && (
            <div className={styles.alertError} role="alert">{errorMsg}</div>
          )}

          <form onSubmit={handleConnectRepo} noValidate>
            <div className={styles.formGroup}>
              <label htmlFor="repo-select" className={styles.formLabel}>
                GitHub Repository
              </label>
              {syncing ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--text-muted)', fontSize: '0.875rem' }}>
                  <Loader2 size={16} style={{ animation: 'spin 0.8s linear infinite' }} aria-hidden="true" />
                  Loading your repositories…
                </div>
              ) : (
                <select
                  id="repo-select"
                  className={styles.select}
                  value={selectedRepoIndex}
                  onChange={(e) => setSelectedRepoIndex(Number(e.target.value))}
                  aria-required="true"
                >
                  <option value={-1} disabled>Select a repository…</option>
                  {availableRepos.map((repo, idx) => (
                    <option key={repo.github_repo_id} value={idx}>
                      {repo.full_name}{repo.private ? ' (Private)' : ' (Public)'}
                    </option>
                  ))}
                </select>
              )}
              {!syncing && availableRepos.length === 0 && (
                <button
                  type="button"
                  className={`${styles.btn} ${styles.btnGhost}`}
                  onClick={async () => {
                    setSyncing(true);
                    await fetchAvailableGitHubRepos();
                    setSyncing(false);
                  }}
                  style={{ width: 'fit-content' }}
                >
                  <RefreshCw size={14} aria-hidden="true" />
                  Load Repositories
                </button>
              )}
            </div>

            <div className={styles.formSectionDivider} aria-hidden="true" />
            <p className={styles.formSectionTitle}>Optional Integrations</p>

            <div className={styles.formGroup}>
              <label htmlFor="slack-url" className={styles.formLabel}>
                Slack Incoming Webhook URL
              </label>
              <input
                id="slack-url"
                type="url"
                className={styles.input}
                placeholder="https://hooks.slack.com/services/…"
                value={slackWebhookUrl}
                onChange={(e) => setSlackWebhookUrl(e.target.value)}
                aria-describedby="slack-url-hint"
              />
              <span id="slack-url-hint" className={styles.formHint}>
                Provide a Slack incoming webhook to enable Slack alert actions.
              </span>
            </div>

            <button
              type="submit"
              className={`${styles.btn} ${styles.btnPrimary} ${styles.btnFull} ${styles.btnLg}`}
              disabled={submitting}
              aria-busy={submitting}
            >
              {submitting ? (
                <>
                  <Loader2 size={16} style={{ animation: 'spin 0.8s linear infinite' }} aria-hidden="true" />
                  Connecting…
                </>
              ) : (
                <>
                  <Plus size={16} aria-hidden="true" />
                  Save & Enable Repository
                </>
              )}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
