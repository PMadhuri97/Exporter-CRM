/**
 * The shell (frontend-plan §7.1): the app header across the top, the side navigation
 * on the left, and the page. Under 1024px the navigation is a drawer. The page's
 * breadcrumbs (`useCrumbs`) sit at the top of the page, where enterprise apps put
 * them. The header, the navigation, search's *Pages* and the router all read the
 * module table, so a role is offered the same modules in every one of them.
 */

import { Suspense, useState } from 'react';
import { Outlet } from 'react-router-dom';

import { Breadcrumbs, Skeleton } from '@/components';
import { NoWorkspaceFrame, useCan } from '@/platform/access';
import { useCurrentUser } from '@/platform/auth';
import { ShellProvider, useShellState } from '@/platform/shell';

import { AppHeader } from './AppHeader';
import { ShortcutList } from './ShortcutList';
import { NavDrawer, SideNav } from './SideNav';
import { useGlobalShortcuts } from './useGlobalShortcuts';

/** While a screen's code loads (each one is its own chunk): shaped, not a spinner. */
function ScreenLoading() {
  return (
    <div className="space-y-3" aria-hidden>
      <Skeleton className="h-7 w-72" />
      <Skeleton className="h-4 w-96 max-w-full" />
      <Skeleton className="mt-6 h-40" />
    </div>
  );
}

function PageCrumbs() {
  const { crumbs } = useShellState();
  if (!crumbs || crumbs.length < 2) return null;
  return <Breadcrumbs items={crumbs} className="mb-3" />;
}

function Workspace() {
  const { role } = useCurrentUser();
  const [searchOpen, setSearchOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);

  useGlobalShortcuts({
    openSearch: () => setSearchOpen(true),
    openShortcuts: () => setShortcutsOpen(true),
  });

  return (
    <div className="flex h-screen flex-col bg-paper">
      <AppHeader
        role={role}
        searchOpen={searchOpen}
        onSearchOpenChange={setSearchOpen}
        onOpenNav={() => setNavOpen(true)}
      />
      <div className="flex min-h-0 flex-1">
        <SideNav role={role} />
        <main className="min-w-0 flex-1 overflow-y-auto px-4 pb-10 pt-4 md:px-6 md:pt-5">
          <div className="mx-auto max-w-[100rem]">
            <PageCrumbs />
            <Suspense fallback={<ScreenLoading />}>
              <Outlet />
            </Suspense>
          </div>
        </main>
      </div>
      <NavDrawer role={role} open={navOpen} onOpenChange={setNavOpen} />
      <ShortcutList open={shortcutsOpen} onOpenChange={setShortcutsOpen} />
    </div>
  );
}

export function AppShell() {
  const hasWorkspace = useCan('crm.read');

  // The API user, or a role nobody listed: no navigation and no CRM words.
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
    <ShellProvider>
      <Workspace />
    </ShellProvider>
  );
}
