/**
 * Choose one company by name: a search field that lists matches under it, and, once
 * one is chosen, the company's name with a way to clear it.
 *
 * Used where a company is a **value** — the Deals page's company filter and
 * *New deal*'s seller — not where one is being identified for the first time. That
 * is `CompanyPicker`'s job, with identifier lookups and duplicate checks; this
 * searches only the companies this role can already see (`GET /exporters?name=`).
 *
 * `unavailable` lets a caller show a company without letting it be chosen, with the
 * reason in place: *New deal* lists a lead greyed out with "Leads can't have deals
 * yet" rather than leaving it out, so a missing company is never a mystery.
 *
 * A value can arrive with only its id — a shared link to a filtered list — so the
 * name is fetched for it when the caller does not already have it.
 */

import { useId, useState, type KeyboardEvent } from 'react';

import { Input, Skeleton } from '@/components';
import { Icon } from '@/design/icons';
import { cn } from '@/lib/cn';

import { useExporterProfileDetail, useExporterProfiles } from '../hooks';
import type { ExporterProfileListItem } from '../types';

export interface CompanySearchSelectProps {
  /** `exporter_profile.customer_id`, or `null` for none chosen. */
  value: string | null;
  onChange(companyId: string | null, company?: ExporterProfileListItem): void;
  /** Names the field for assistive tech, and is its visible label unless `hideLabel`. */
  label: string;
  hideLabel?: boolean;
  placeholder?: string;
  /** Why this company cannot be chosen here, or `null` when it can. */
  unavailable?(company: ExporterProfileListItem): string | null;
  /** The facts line under each match. Defaults to the country. */
  describe?(company: ExporterProfileListItem): string | null;
  className?: string;
}

const MIN_TERM = 2;

export function CompanySearchSelect({
  value,
  onChange,
  label,
  hideLabel = false,
  placeholder = 'Search companies',
  unavailable,
  describe = (company) => company.country,
  className,
}: CompanySearchSelectProps) {
  const id = useId();
  const listId = `${id}-results`;
  const [term, setTerm] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  // The name of the company chosen here, so it shows without a second request.
  const [chosen, setChosen] = useState<{ id: string; name: string | null } | null>(null);

  const known = chosen && chosen.id === value ? chosen.name : undefined;
  const detail = useExporterProfileDetail(value && known === undefined ? value : undefined);

  const trimmed = term.trim();
  const searching = trimmed.length >= MIN_TERM;
  const query = useExporterProfiles(searching ? { name: trimmed, limit: 10 } : { limit: 1 });
  // The list query keeps its previous answer on screen while the next one loads. That
  // answer may be the one-row request made while not searching, which is not a match
  // for anything — offered here, a quick click would choose a company nobody searched
  // for. So only a name search's own answer is shown: the current one once it arrives,
  // and the last search's until then, so the list does not flicker as you type.
  const fresh = searching && query.data && !query.isPlaceholderData ? query.data.profiles : null;
  const [lastSearch, setLastSearch] = useState<ExporterProfileListItem[] | null>(null);
  if (fresh && fresh !== lastSearch) setLastSearch(fresh);
  if (!searching && lastSearch !== null) setLastSearch(null);
  const results = searching ? (fresh ?? lastSearch ?? []) : [];
  const loading = searching && fresh === null && lastSearch === null && !query.isError;

  function choose(company: ExporterProfileListItem) {
    if (unavailable?.(company)) return;
    setChosen({ id: company.customer_id, name: company.name });
    setTerm('');
    setOpen(false);
    onChange(company.customer_id, company);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (!results.length) return;
      setOpen(true);
      const step = event.key === 'ArrowDown' ? 1 : -1;
      setActive((current) => (current + step + results.length) % results.length);
    } else if (event.key === 'Enter') {
      if (open && results[active]) {
        event.preventDefault();
        choose(results[active]);
      }
    } else if (event.key === 'Escape') {
      setOpen(false);
    }
  }

  const labelEl = (
    <label htmlFor={id} className={hideLabel ? 'sr-only' : 'mb-1 block text-caption font-medium text-ink-2'}>
      {label}
    </label>
  );

  if (value) {
    const name = known !== undefined ? known : detail.data?.name;
    return (
      <div className={className}>
        {!hideLabel && <span className="mb-1 block text-caption font-medium text-ink-2">{label}</span>}
        <div className="input flex items-center justify-between gap-2" data-testid="company-select-value">
          <span className="flex min-w-0 items-center gap-2">
            <Icon.company size={16} className="shrink-0 text-ink-3" aria-hidden />
            {detail.isLoading && known === undefined ? (
              <Skeleton className="h-4 w-32" />
            ) : (
              <span className="truncate text-ink">{name ?? 'Unnamed company'}</span>
            )}
          </span>
          <button
            type="button"
            onClick={() => {
              setChosen(null);
              onChange(null);
            }}
            className="-mr-1 flex h-6 w-6 shrink-0 items-center justify-center rounded text-ink-3 hover:bg-sunken hover:text-ink"
            aria-label={`Clear ${label.toLowerCase()}`}
          >
            <Icon.close size={14} aria-hidden />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={cn('relative', className)}>
      {labelEl}
      <span className="relative block">
        <Icon.search
          size={15}
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-3"
          aria-hidden
        />
        <Input
          id={id}
          type="text"
          role="combobox"
          autoComplete="off"
          aria-expanded={open && searching}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={open && results[active] ? `${listId}-${active}` : undefined}
          value={term}
          placeholder={placeholder}
          className="w-full pl-9"
          onChange={(event) => {
            setTerm(event.target.value);
            setActive(0);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          // Late enough that a click on a result lands first.
          onBlur={() => window.setTimeout(() => setOpen(false), 150)}
          onKeyDown={onKeyDown}
        />
      </span>
      {open && searching && (
        <div className="absolute left-0 right-0 top-full z-30 mt-1 overflow-hidden rounded border border-line bg-surface shadow-float">
          {loading ? (
            <div className="p-3">
              <Skeleton className="h-4 w-40" />
            </div>
          ) : results.length === 0 ? (
            <p className="px-3 py-2.5 text-secondary text-ink-3">No company matches that name.</p>
          ) : (
            <ul id={listId} role="listbox" aria-label={label} className="max-h-72 overflow-y-auto py-1">
              {results.map((company, index) => {
                const reason = unavailable?.(company) ?? null;
                const facts = describe(company);
                return (
                  <li
                    key={company.customer_id}
                    id={`${listId}-${index}`}
                    role="option"
                    aria-selected={index === active}
                    aria-disabled={reason ? true : undefined}
                    // Keep focus in the field, so the list does not close before the click.
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => choose(company)}
                    onMouseEnter={() => setActive(index)}
                    className={cn(
                      'px-3 py-2',
                      reason ? 'cursor-not-allowed' : 'cursor-pointer',
                      index === active && !reason && 'bg-sunken',
                    )}
                  >
                    <span className={cn('block truncate text-body', reason ? 'text-ink-3' : 'text-ink')}>
                      {company.name ?? 'Unnamed company'}
                    </span>
                    {(reason || facts) && (
                      <span className="block truncate text-caption text-ink-3">
                        {[facts, reason].filter(Boolean).join(' · ')}
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
      {open && !searching && trimmed.length > 0 && (
        <p className="absolute left-0 right-0 top-full z-30 mt-1 rounded border border-line bg-surface px-3 py-2.5 text-secondary text-ink-3 shadow-float">
          Type at least {MIN_TERM} characters.
        </p>
      )}
    </div>
  );
}
