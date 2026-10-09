/**
 * The header search's field and results (frontend-plan §7.5), loaded the first time
 * the search is focused (`HeaderSearch.tsx`), so cmdk and the company search stay
 * out of the first download. Nothing is requested until someone types.
 *
 * - **Companies**: by name for every reader; by full PAN / GSTIN / IEC only for a
 *   role that may see identifiers (`useCompanyFinder` decides, and a masked role
 *   never sends an identifier — it gets a hint towards *New company*).
 * - **Pages**: the role's nav rows, from the module table — the same list the side
 *   navigation reads, so they never disagree.
 * - **Recent**: the last companies this viewer opened (per user, this browser).
 *
 * No actions: actions live on the record.
 */

import { Command } from 'cmdk';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';

import { Kbd } from '@/components';
import { Icon } from '@/design/icons';
import type { UserRole } from '@/lib/api/types';
import { countryLabel, JourneyBadge, paths, useCompanyFinder } from '@/modules/onboarding';
import { useCurrentUser } from '@/platform/auth';
import { commandKeyLabel, readRecentCompanies } from '@/platform/shell';
import { navRowsFor } from '@/routes/modules';

const ITEM =
  'flex h-9 cursor-default select-none items-center gap-3 rounded px-2.5 text-body text-ink outline-none data-[selected=true]:bg-sunken';
const GROUP =
  '[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-2.5 [&_[cmdk-group-heading]]:text-caption [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:text-ink-3';

function useDebounced<T>(value: T, delay: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return settled;
}

function matches(query: string, text: string): boolean {
  const needle = query.trim().toLowerCase();
  return !needle || text.toLowerCase().includes(needle);
}

function Hint({ children }: { children: ReactNode }) {
  return <p className="px-2.5 py-2 text-secondary text-ink-3">{children}</p>;
}

export function SearchResults({ role, close }: { role: UserRole; close: () => void }) {
  const navigate = useNavigate();
  const user = useCurrentUser();
  const [query, setQuery] = useState('');
  const settled = useDebounced(query, 200);
  const finder = useCompanyFinder(settled);
  const recent = useMemo(() => readRecentCompanies(String(user.id)), [user.id]);
  const root = useRef<HTMLDivElement>(null);
  const typing = query.trim().length > 0;
  const pages = navRowsFor(role).filter((row) => matches(query, row.label));

  // Clicking anywhere else closes the results.
  useEffect(() => {
    function onPointerDown(event: PointerEvent) {
      if (root.current && !root.current.contains(event.target as Node)) close();
    }
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [close]);

  function go(to: string) {
    close();
    navigate(to);
  }

  return (
    <div ref={root} className="relative w-full">
      <Command
        label="Search"
        shouldFilter={false}
        loop
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            event.preventDefault();
            close();
          }
        }}
      >
        <div className="flex h-8 items-center gap-2 rounded border border-accent bg-surface px-2.5 ring-1 ring-accent">
          <Icon.search size={16} className="shrink-0 text-ink-3" aria-hidden />
          <Command.Input
            autoFocus
            value={query}
            onValueChange={setQuery}
            placeholder="Search companies and pages…"
            className="h-full min-w-0 flex-1 bg-transparent text-body text-ink outline-none placeholder:text-ink-3 focus-visible:ring-0 focus-visible:ring-offset-0"
          />
          <Kbd>Esc</Kbd>
        </div>
        <Command.List className="absolute inset-x-0 top-10 z-50 max-h-[min(70vh,28rem)] overflow-y-auto rounded-xl border border-line bg-raised p-1 shadow-float">
          {typing && (
            <Command.Group heading="Companies" className={GROUP}>
              {finder.identifierHidden ? (
                <Hint>To match a company by PAN, use New company.</Hint>
              ) : query.trim().length < 2 ? (
                <Hint>Keep typing to search companies by name.</Hint>
              ) : finder.failed ? (
                <Hint>Couldn’t search companies just now.</Hint>
              ) : finder.searching && finder.companies.length === 0 ? (
                <Command.Loading>
                  <Hint>Searching…</Hint>
                </Command.Loading>
              ) : finder.companies.length === 0 ? (
                <Hint>No company matches “{settled.trim()}”.</Hint>
              ) : (
                finder.companies.map((company) => (
                  <Command.Item
                    key={company.customer_id}
                    value={`company-${company.customer_id}`}
                    onSelect={() => go(paths.company(company.customer_id))}
                    className={ITEM}
                  >
                    <Icon.company size={16} className="shrink-0 text-ink-3" aria-hidden />
                    <span className="min-w-0 flex-1 truncate">{company.name ?? 'Unnamed company'}</span>
                    {company.country && (
                      <span className="shrink-0 text-secondary text-ink-3">{countryLabel(company.country)}</span>
                    )}
                    <JourneyBadge journey={company.journey} />
                  </Command.Item>
                ))
              )}
            </Command.Group>
          )}

          {!typing && recent.length > 0 && (
            <Command.Group heading="Recent" className={GROUP}>
              {recent.map((company) => (
                <Command.Item
                  key={company.id}
                  value={`recent-${company.id}`}
                  onSelect={() => go(paths.company(company.id))}
                  className={ITEM}
                >
                  <Icon.history size={16} className="shrink-0 text-ink-3" aria-hidden />
                  <span className="min-w-0 flex-1 truncate">{company.name}</span>
                </Command.Item>
              ))}
            </Command.Group>
          )}

          {pages.length > 0 && (
            <Command.Group heading="Pages" className={GROUP} data-testid="search-pages">
              {pages.map((row) => {
                const Glyph = Icon[row.icon];
                return (
                  <Command.Item key={row.to} value={`page-${row.to}`} onSelect={() => go(row.to)} className={ITEM}>
                    <Glyph size={16} className="shrink-0 text-ink-3" aria-hidden />
                    <span className="flex-1">{row.label}</span>
                  </Command.Item>
                );
              })}
            </Command.Group>
          )}

          <p className="flex items-center gap-1.5 border-t border-line px-2.5 pb-1 pt-2 text-caption text-ink-3">
            <Kbd>/</Kbd> or <Kbd>{commandKeyLabel()}</Kbd>
            <Kbd>K</Kbd> to search from anywhere
          </p>
        </Command.List>
      </Command>
    </div>
  );
}
