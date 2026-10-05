/**
 * Search in the app header (frontend-plan §7.5): companies and pages, never actions.
 * `/` or Ctrl+K focuses it from anywhere (`useGlobalShortcuts`).
 *
 * At rest it is a plain field-shaped button, so the first download carries no search
 * code; opening it swaps in the real field and its results (`SearchResults.tsx`,
 * loaded on first use and prefetched once the shell is idle).
 */

import { lazy, Suspense, useEffect, useRef } from 'react';

import { Kbd } from '@/components';
import { Icon } from '@/design/icons';
import type { UserRole } from '@/lib/api/types';
import { commandKeyLabel } from '@/platform/shell';

const loadResults = () => import('./SearchResults');
const SearchResults = lazy(() => loadResults().then((m) => ({ default: m.SearchResults })));

/** The field at rest: a button, so Tab, Enter and a click open the real field. */
function Field({ onOpen, inert = false }: { onOpen?: () => void; inert?: boolean }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      tabIndex={inert ? -1 : undefined}
      aria-label="Search companies and pages"
      aria-keyshortcuts="/ Control+K Meta+K"
      data-search-trigger
      className="flex h-8 w-full items-center gap-2 rounded border border-line-strong bg-surface px-2.5 text-left text-body text-ink-3 transition-colors duration-quick hover:border-ink-2"
    >
      <Icon.search size={16} className="shrink-0" aria-hidden />
      <span className="min-w-0 flex-1 truncate">Search companies and pages…</span>
      <span className="hidden items-center gap-0.5 sm:flex" aria-hidden>
        <Kbd>{commandKeyLabel()}</Kbd>
        <Kbd>K</Kbd>
      </span>
    </button>
  );
}

export function HeaderSearch({
  role,
  open,
  onOpenChange,
}: {
  role: UserRole;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const wrapper = useRef<HTMLDivElement>(null);
  const wasOpen = useRef(open);

  // Fetch the results' code while the viewer is still reading the page.
  useEffect(() => {
    const idle = window.requestIdleCallback ?? ((run: () => void) => window.setTimeout(run, 1500));
    idle(() => void loadResults());
  }, []);

  // Closing hands focus back to the field, unless the viewer has moved on to
  // something else (a result opened a page, or they clicked elsewhere).
  useEffect(() => {
    if (wasOpen.current && !open) {
      const active = document.activeElement;
      if (!active || active === document.body) {
        wrapper.current?.querySelector<HTMLButtonElement>('[data-search-trigger]')?.focus({ preventScroll: true });
      }
    }
    wasOpen.current = open;
  }, [open]);

  return (
    <div ref={wrapper} role="search" className="w-full max-w-xl">
      {open ? (
        <Suspense fallback={<Field inert />}>
          <SearchResults role={role} close={() => onOpenChange(false)} />
        </Suspense>
      ) : (
        <Field onOpen={() => onOpenChange(true)} />
      )}
    </div>
  );
}
