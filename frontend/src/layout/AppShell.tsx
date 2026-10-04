import { LogOut, Menu, PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import { Suspense, useState } from 'react';
import { Outlet } from 'react-router-dom';

import { Sheet, Skeleton } from '@/components';
import { NoWorkspaceFrame, useCan } from '@/platform/access';
import { roleShortLabel, useAuth, useCurrentUser } from '@/platform/auth';
import { ThemeToggle } from '@/platform/theme';

import { Sidebar } from './Sidebar';

const COLLAPSED_KEY = 'aner.sidebar.collapsed';

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSED_KEY) === '1';
  } catch {
    return false;
  }
}

function storeCollapsed(collapsed: boolean): void {
  try {
    window.localStorage.setItem(COLLAPSED_KEY, collapsed ? '1' : '0');
  } catch {
    // The rail's state just won't outlive this page view.
  }
}

const ICON_BUTTON =
  'flex h-8 w-8 items-center justify-center rounded-lg text-ink-faint transition-colors hover:bg-surface-sunken hover:text-ink';

function TopBar({
  collapsed,
  onToggleCollapsed,
  onOpenMenu,
}: {
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onOpenMenu: () => void;
}) {
  const user = useCurrentUser();
  const { logout } = useAuth();

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-border bg-surface px-4 sm:px-6">
      <div className="flex items-center gap-1">
        <button type="button" onClick={onOpenMenu} aria-label="Open menu" className={`${ICON_BUTTON} lg:hidden`}>
          <Menu size={18} />
        </button>
        <button
          type="button"
          onClick={onToggleCollapsed}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          className={`${ICON_BUTTON} hidden lg:flex`}
        >
          {collapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}
        </button>
      </div>
      <div className="flex items-center gap-3">
        <ThemeToggle />
        <div className="hidden text-right sm:block">
          <p className="text-sm font-medium leading-tight text-ink">{user.full_name ?? user.email}</p>
          <p className="text-xs text-ink-faint">{roleShortLabel(user.role)}</p>
        </div>
        <button type="button" onClick={() => void logout()} aria-label="Sign out" className={ICON_BUTTON}>
          <LogOut size={16} />
        </button>
      </div>
    </header>
  );
}

/** While a screen's code loads (each one is its own chunk, G7). */
function ScreenLoading() {
  return <Skeleton className="h-40 rounded-lg" />;
}

export function AppShell() {
  const { role } = useCurrentUser();
  const hasWorkspace = useCan('crm.read');
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [menuOpen, setMenuOpen] = useState(false);

  // The API user, or a role nobody listed: no rail and no CRM words (R-33, G1).
  // The routes inside are still gated; only My profile renders here.
  if (!hasWorkspace) {
    return (
      <NoWorkspaceFrame>
        <Suspense fallback={<ScreenLoading />}>
          <Outlet />
        </Suspense>
      </NoWorkspaceFrame>
    );
  }

  return (
    <div className="flex h-screen bg-surface-subtle">
      <aside className="hidden lg:flex">
        <Sidebar role={role} collapsed={collapsed} />
      </aside>
      <Sheet open={menuOpen} onOpenChange={setMenuOpen} title="Main menu">
        <Sidebar role={role} onNavigate={() => setMenuOpen(false)} />
      </Sheet>
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar
          collapsed={collapsed}
          onToggleCollapsed={() => {
            setCollapsed((current) => {
              storeCollapsed(!current);
              return !current;
            });
          }}
          onOpenMenu={() => setMenuOpen(true)}
        />
        <main className="flex-1 overflow-y-auto px-4 py-5 sm:px-6 sm:py-6">
          <div className="mx-auto max-w-[90rem]">
            <Suspense fallback={<ScreenLoading />}>
              <Outlet />
            </Suspense>
          </div>
        </main>
      </div>
    </div>
  );
}
