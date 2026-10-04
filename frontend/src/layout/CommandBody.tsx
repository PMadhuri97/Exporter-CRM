/**
 * The command bar, ⌘K / Ctrl K (frontend-plan §7.5): find a company, act on the
 * one on screen, or go to a module — only ever what this role may use.
 *
 * - **Companies**: by name for every reader; by full PAN / GSTIN / IEC only for a
 *   role that may see identifiers (`useCompanyFinder` decides, and a masked role
 *   never sends an identifier — it gets a hint towards the match flow).
 * - **On this page**: the actions the page registered with `useCommandActions`,
 *   each built from what the server served for that record.
 * - **Go to**: the role's rail rows, from the module table — the same list the rail
 *   and the `g` shortcuts read, so they never disagree.
 * - **Recent**: the last companies this viewer opened (per user, this browser).
 *
 * The bar's contents, loaded on first open (`CommandBar.tsx`), so cmdk and the
 * company search stay out of the first download; nothing is requested until someone
 * types.
 */

import { Command } from 'cmdk';
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';

import { Kbd } from '@/components';
import { Icon } from '@/design/icons';
import type { UserRole } from '@/lib/api/types';
import { JOURNEY_LABEL, JourneyDots, paths, useCompanyFinder } from '@/modules/onboarding';
import { useCurrentUser } from '@/platform/auth';
import { readRecentCompanies, useShellState } from '@/platform/shell';
import { navRowsFor } from '@/routes/modules';

const ITEM =
  'flex cursor-default select-none items-center gap-3 rounded-md px-3 py-2 text-body text-ink outline-none data-[selected=true]:bg-sunken';
const GROUP =
  '[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-3 [&_[cmdk-group-heading]]:text-caption [&_[cmdk-group-heading]]:text-ink-3';

function useDebounced<T>(value: T, delay: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return settled;
}

function matches(query: string, ...texts: (string | undefined)[]): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return texts.some((text) => text?.toLowerCase().includes(needle));
}

function Hint({ children }: { children: ReactNode }) {
  return <p className="px-3 py-2 text-secondary text-ink-3">{children}</p>;
}

export function CommandBody({ role, close }: { role: UserRole; close: () => void }) {
  const navigate = useNavigate();
  const user = useCurrentUser();
  const { actions } = useShellState();
  const [query, setQuery] = useState('');
  const settled = useDebounced(query, 200);
  const finder = useCompanyFinder(settled);
  const recent = useMemo(() => readRecentCompanies(String(user.id)), [user.id]);
  const rows = navRowsFor(role);
  const typing = query.trim().length > 0;

  function go(to: string) {
    close();
    navigate(to);
  }

  const goTo = rows.filter((row) => matches(query, row.label));
  const onPage = actions.filter((action) => matches(query, action.label, ...(action.keywords ?? [])));

  return (
    <Command label="Find or go to" shouldFilter={false} loop className="flex max-h-[min(70vh,32rem)] flex-col">
      <div className="flex items-center gap-2.5 border-b border-line px-4">
        <Icon.search size={18} className="shrink-0 text-ink-3" aria-hidden />
        <Command.Input
          value={query}
          onValueChange={setQuery}
          placeholder="Find a company, or go to…"
          className="h-12 w-full bg-transparent text-lead text-ink outline-none placeholder:text-ink-4"
        />
        <Kbd>Esc</Kbd>
      </div>
      <Command.List className="overflow-y-auto p-1.5">
        {typing && (
          <Command.Group heading="Companies" className={GROUP}>
            {finder.identifierHidden ? (
              <Hint>
                To match a company by PAN, GSTIN or IEC, use Add company or Choose buyer on a deal.
              </Hint>
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
                  <JourneyDots journey={company.journey} />
                  <span className="min-w-0 flex-1 truncate">{company.name ?? 'Unnamed company'}</span>
                  <span className="shrink-0 text-secondary text-ink-3">
                    {[company.country, JOURNEY_LABEL[company.journey]].filter(Boolean).join(' · ')}
                  </span>
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
                <Icon.history size={16} className="text-ink-3" aria-hidden />
                <span className="min-w-0 flex-1 truncate">{company.name}</span>
              </Command.Item>
            ))}
          </Command.Group>
        )}

        {onPage.length > 0 && (
          <Command.Group heading="On this page" className={GROUP}>
            {onPage.map((action) => (
              <Command.Item
                key={action.id}
                value={`action-${action.id}`}
                onSelect={() => {
                  close();
                  action.run();
                }}
                className={ITEM}
              >
                <Icon.forward size={16} className="text-ink-3" aria-hidden />
                <span className="flex-1">{action.label}</span>
                {action.shortcut && <Kbd>{action.shortcut}</Kbd>}
              </Command.Item>
            ))}
          </Command.Group>
        )}

        {goTo.length > 0 && (
          <Command.Group heading="Go to" className={GROUP} data-testid="command-go-to">
            {goTo.map((row) => {
              const Glyph = Icon[row.icon];
              return (
                <Command.Item
                  key={row.to}
                  value={`go-${row.to}`}
                  onSelect={() => go(row.to)}
                  className={ITEM}
                >
                  <Glyph size={16} className="text-ink-3" aria-hidden />
                  <span className="flex-1">{row.label}</span>
                  {row.shortcut && (
                    <span className="flex gap-0.5" aria-hidden>
                      <Kbd>g</Kbd>
                      <Kbd>{row.shortcut}</Kbd>
                    </span>
                  )}
                </Command.Item>
              );
            })}
          </Command.Group>
        )}
      </Command.List>
    </Command>
  );
}

