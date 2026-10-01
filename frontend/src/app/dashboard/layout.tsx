'use client';

import { useEffect, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import Link from 'next/link';
import { Flame, LayoutDashboard, GitFork, LogOut, User } from 'lucide-react';
import styles from '../../styles/dashboard.module.css';

interface UserProfile {
  github_username: string;
  email: string | null;
  avatar_url: string | null;
}

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/v1/auth/me')
      .then((res) => {
        if (!res.ok) {
          router.replace('/');
          return null;
        }
        return res.json();
      })
      .then((data) => {
        if (data) setUser(data);
        setLoading(false);
      })
      .catch(() => router.replace('/'));
  }, [router]);

  const handleLogout = async () => {
    try {
      const res = await fetch('/api/v1/auth/logout', { method: 'POST' });
      if (res.ok) router.replace('/');
    } catch (e) {
      console.error('Logout failed:', e);
    }
  };

  if (loading) {
    return (
      <div className={styles.loadingScreen} role="status" aria-label="Loading dashboard">
        <div className={styles.loadingRing} aria-hidden="true" />
        <span className={styles.loadingText}>Loading workspace…</span>
      </div>
    );
  }

  // Breadcrumb label logic
  const getBreadcrumb = () => {
    if (pathname === '/dashboard') return 'Overview';
    if (pathname.includes('/rules')) return 'Automation Rules';
    if (pathname.startsWith('/dashboard/repos')) return 'Repositories';
    return 'Dashboard';
  };

  const initials = user?.github_username
    ? user.github_username.slice(0, 2).toUpperCase()
    : 'CF';

  return (
    <div className={styles.shell}>
      {/* ── Sidebar ──────────────────────────────── */}
      <aside className={styles.sidebar} aria-label="Sidebar navigation">
        {/* Brand */}
        <div className={styles.sidebarBrand}>
          <div className={styles.sidebarLogo} aria-hidden="true">
            <Flame size={20} />
          </div>
          <span className={styles.sidebarBrandName}>Darkrai</span>
        </div>

        <div className={styles.sidebarDivider} aria-hidden="true" />

        {/* Nav links */}
        <nav className={styles.sidebarNav} aria-label="Primary navigation">
          <Link
            href="/dashboard"
            className={`${styles.navItem} ${pathname === '/dashboard' ? styles.navItemActive : ''}`}
            aria-current={pathname === '/dashboard' ? 'page' : undefined}
          >
            <span className={styles.navIcon} aria-hidden="true">
              <LayoutDashboard size={18} />
            </span>
            <span className={styles.navLabel}>Overview</span>
          </Link>

          <Link
            href="/dashboard/repos"
            className={`${styles.navItem} ${pathname.startsWith('/dashboard/repos') ? styles.navItemActive : ''}`}
            aria-current={pathname.startsWith('/dashboard/repos') ? 'page' : undefined}
          >
            <span className={styles.navIcon} aria-hidden="true">
              <GitFork size={18} />
            </span>
            <span className={styles.navLabel}>Repositories</span>
          </Link>
        </nav>

        {/* Footer: user + logout */}
        <div className={styles.sidebarFooter}>
          <div className={styles.sidebarDivider} style={{ marginBottom: '8px' }} aria-hidden="true" />

          <div className={styles.userRow} title={user?.github_username || ''}>
            {user?.avatar_url ? (
              <img
                src={user.avatar_url}
                alt={`${user.github_username} avatar`}
                className={styles.userAvatar}
                width={32}
                height={32}
              />
            ) : (
              <div className={styles.userAvatarPlaceholder} aria-hidden="true">
                {initials}
              </div>
            )}
            <div className={styles.userInfo}>
              <span className={styles.userName}>{user?.github_username}</span>
              <span className={styles.userHandle}>GitHub</span>
            </div>
          </div>

          <button
            className={styles.logoutBtn}
            onClick={handleLogout}
            aria-label="Sign out"
            title="Sign out"
          >
            <span className={styles.navIcon} aria-hidden="true">
              <LogOut size={16} />
            </span>
            <span className={styles.logoutLabel}>Sign out</span>
          </button>
        </div>
      </aside>

      {/* ── Main Area ─────────────────────────────── */}
      <div className={styles.mainArea}>
        {/* Topbar */}
        <header className={styles.topbar} role="banner">
          <div className={styles.breadcrumb} aria-label="Breadcrumb">
            <span className={styles.breadcrumbItem}>Darkrai</span>
            <span className={styles.breadcrumbSep} aria-hidden="true">/</span>
            <span className={styles.breadcrumbCurrent} aria-current="page">
              {getBreadcrumb()}
            </span>
          </div>

          <div className={styles.topbarRight}>
            <div className={styles.statusBadge} aria-label="System status: online">
              <span className={styles.statusDot} aria-hidden="true" />
              Online
            </div>
          </div>
        </header>

        {/* Page content */}
        <main className={styles.pageContent} id="main-content">
          {children}
        </main>
      </div>
    </div>
  );
}
