/**
 * Pick a company, or create one — **owner: Developer 3** (allocation F3, plan P4-3).
 *
 * **This is the F3 stub.** Its props are final, so Developer 2 can mount it on the
 * deal page now (task 2.4) and task 3.10 fills the body in without the mounting
 * changing.
 *
 * What 3.10 adds: `POST /companies/match`, name similarity, and the create form for
 * a buyer that is genuinely new. What this stub does: search the companies the RM can
 * already see and let them pick one. That is a real, useful control rather than a
 * placeholder — it just cannot yet find a company by PAN or GSTIN, or tell the RM
 * that the name they typed looks like one already on file.
 *
 * **Identifier disclosure is not this component's call.** It shows what the server
 * sends. BQ-2 lets a full identifier *name* a company while identifiers themselves
 * stay masked, and the open lead decision in `open-items.md` §1 bounds what 3.10's
 * match response may carry — so the search box here takes a name only, and will take
 * identifiers when the server is ready to answer for them.
 */

import { Search } from 'lucide-react';
import { useState } from 'react';

import { EmptySection, Input, Skeleton } from '@/components';

import { useExporterProfiles } from '../hooks';
import type { ExporterProfileListItem } from '../types';

export interface CompanyPickerProps {
  /** Called with `exporter_profile.customer_id` when the user picks one. */
  onSelect(companyId: string): void;
  /**
   * A company to leave out of the results — the deal's seller, so nobody picks it
   * as its own buyer (`ck_deal_buyer_is_not_the_seller` would refuse it anyway, but
   * offering the choice and then failing is worse than not offering it).
   */
  excludeCompanyId?: string;
}

export function CompanyPicker({ onSelect, excludeCompanyId }: CompanyPickerProps) {
  const [term, setTerm] = useState('');
  const trimmed = term.trim();
  // Only ask once the term is worth a query: a one-letter search returns most of the
  // database and tells the user nothing. The hook always runs, so an empty `name`
  // stands in for "not searching yet" and the results are ignored below.
  const ready = trimmed.length >= 2;
  const query = useExporterProfiles(ready ? { name: trimmed, limit: 10 } : { limit: 1 });

  const matches = ready
    ? (query.data?.profiles ?? []).filter(
        (company: ExporterProfileListItem) => company.customer_id !== excludeCompanyId,
      )
    : [];

  return (
    <div className="flex flex-col gap-3">
      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-ink">Find the company</span>
        <span className="relative">
          <Search
            size={15}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint"
          />
          <Input
            type="text"
            value={term}
            placeholder="Company name"
            className="pl-9"
            onChange={(event) => setTerm(event.target.value)}
          />
        </span>
      </label>

      {!ready ? (
        <p className="text-xs text-ink-faint">
          Type at least two characters. Searching by PAN or GSTIN arrives with the
          company match API.
        </p>
      ) : query.isLoading ? (
        <Skeleton className="h-16 rounded-lg" />
      ) : matches.length === 0 ? (
        <EmptySection>
          No company on file matches that name. Creating one from here arrives with the
          company match API.
        </EmptySection>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border">
          {matches.map((company: ExporterProfileListItem) => (
            <li key={company.customer_id}>
              <button
                type="button"
                onClick={() => onSelect(company.customer_id)}
                className="flex w-full flex-wrap items-center justify-between gap-2 px-4 py-3 text-left transition-colors hover:bg-surface-subtle"
              >
                <span className="min-w-0">
                  <span className="font-medium text-ink">
                    {company.name ?? 'Unnamed company'}
                  </span>
                  <span className="mt-0.5 block text-xs text-ink-muted">
                    {company.country ?? '—'} · {company.journey}
                  </span>
                </span>
                <span className="text-xs font-medium text-brand-600">Select</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
