/**
 * The company's verification workspace — **owner: Developer 4B** (4b-task.md §5.10;
 * 4B-7). Rendered by Developer 4A's `BackgroundCheckPanel`, so its export and props,
 * `VerificationSection({ customerId })`, stay as they are.
 *
 * Verification results and the eight screening items are *inputs* to the background
 * check, not the decision (that is Developer 4A's). This workspace records and
 * reviews those inputs:
 *
 * - `ManualResultForm` records a manual result with evidence (a `PASSED` needs some);
 * - each `VerificationResultRow` shows provenance, evidence and the review chain,
 *   and `ReviewDialog` adds to that chain by superseding, never by editing;
 * - `ScreeningChecklist` renders the server's catalogue, with each item's history;
 * - `BankActivityPanel` says plainly that no bank feed is connected.
 *
 * What the viewer may do comes from the server's `capabilities` — this file makes no
 * role comparison.
 *
 * Developer 1, 1 October 2026:
 * - **Filters** (P2-2): All / Automated / Manual / Flagged, over served fields only.
 *   Automated is a real provider (`provenance = PROVIDER`; the RXIL stub is not, IQ-15)
 *   and says honestly that none is connected; Flagged is a `FAILED` result or a
 *   `HIGH`/`CRITICAL` risk.
 * - **Cycles** (P2-3d): the results of the current check cycle are listed as before;
 *   an earlier cycle's (after a Re-KYC / Re-KYB) stay readable, grouped by cycle and
 *   read-only. The current cycle is the server's (`current_cycle` on the standing).
 */

import { Activity, AlertTriangle, Building2, Info, ShieldCheck } from 'lucide-react';
import { useState } from 'react';

import { humanize } from '@/lib/format';

import { useBackgroundCheck, useCheckCycles, useVerificationResults } from '../hooks';
import type { VerificationResult } from '../types';

import { cycleKindLabel } from './background-check-labels';
import { BankActivityPanel } from './BankActivityPanel';
import { ManualResultForm } from './ManualResultForm';
import { ScreeningChecklist } from './ScreeningChecklist';
import { COMPANY_CHECK_TYPES } from './verification-labels';
import { VerificationResultRow } from './VerificationResultRow';

type WorkspaceTab = 'COMPANY' | 'BANK';

/** The result filters (P2-2), over fields the server serves. */
type ResultFilter = 'ALL' | 'AUTOMATED' | 'MANUAL' | 'FLAGGED';

const FILTERS: { value: ResultFilter; label: string }[] = [
  { value: 'ALL', label: 'All' },
  { value: 'AUTOMATED', label: 'Automated' },
  { value: 'MANUAL', label: 'Manual' },
  { value: 'FLAGGED', label: 'Flagged' },
];

function matchesFilter(result: VerificationResult, filter: ResultFilter): boolean {
  if (filter === 'AUTOMATED') return result.provenance === 'PROVIDER';
  if (filter === 'MANUAL') return result.provenance === 'MANUAL';
  if (filter === 'FLAGGED') {
    return (
      result.status === 'FAILED' || result.risk_level === 'HIGH' || result.risk_level === 'CRITICAL'
    );
  }
  return true;
}

function FilteredEmpty({ filter }: { filter: ResultFilter }) {
  const text =
    filter === 'AUTOMATED'
      ? 'No automated checks. No provider integration is connected, so every check is recorded by hand for now.'
      : filter === 'FLAGGED'
        ? 'No failed or high-risk checks in this cycle.'
        : 'No manual checks in this cycle.';
  return (
    <p
      data-testid="verification-filter-empty"
      className="rounded-lg border border-dashed border-border-strong bg-surface-subtle px-4 py-6 text-center text-xs text-ink-muted"
    >
      {text}
    </p>
  );
}

/** An earlier cycle's results: readable, never reviewable (P2-3d). */
function EarlierCycle({
  label,
  results,
  customerId,
  onStale,
}: {
  label: string;
  results: VerificationResult[];
  customerId: string;
  onStale: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div data-testid="earlier-cycle-results" className="mt-4">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="text-xs font-semibold text-ink"
      >
        {label} — {results.length} result{results.length === 1 ? '' : 's'}, read-only
      </button>
      {open && (
        <div className="mt-2 rounded-lg border border-border px-4 opacity-90">
          {results.map((result) => (
            <VerificationResultRow
              key={result.id}
              result={result}
              customerId={customerId}
              canReview={false}
              onStale={onStale}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * The company check types the tab advertises that have no result yet. No provider is
 * wired up for any of them; a manual result can be recorded by someone who may. Listing
 * what is missing is the honest alternative to a tab that silently shows nothing.
 */
function MissingChecks({ results }: { results: VerificationResult[] }) {
  const present = new Set(results.map((result) => result.verification_type));
  const missing = COMPANY_CHECK_TYPES.filter((type) => !present.has(type));
  if (missing.length === 0) return null;

  return (
    <div className="mt-4 rounded-lg border border-dashed border-border-strong bg-surface-subtle px-4 py-3">
      <div className="flex items-start gap-2">
        <Info size={14} className="mt-0.5 shrink-0 text-ink-faint" />
        <div className="min-w-0">
          <p className="text-xs font-medium text-ink">
            {missing.length} check {missing.length === 1 ? 'type has' : 'types have'} no result
          </p>
          <p className="mt-0.5 text-xs leading-5 text-ink-muted">
            No provider integration runs these today. They appear once a result is recorded
            by hand or a provider is connected.
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {missing.map((type) => (
              <span
                key={type}
                className="inline-flex rounded-full border border-border bg-surface px-2 py-0.5 text-[11px] font-medium text-ink-faint"
              >
                {humanize(type)}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function EmptyScreenings() {
  return (
    <div className="rounded-lg border border-dashed border-border-strong bg-surface-subtle px-4 py-8 text-center">
      <ShieldCheck className="mx-auto text-ink-faint" size={24} />
      <p className="mt-2 text-sm font-medium text-ink">No screening results yet</p>
      <p className="mx-auto mt-1 max-w-md text-xs leading-5 text-ink-muted">
        No provider integration is connected, so no company screening has run for this
        exporter. A result recorded by hand appears here.
      </p>
    </div>
  );
}

export function VerificationSection({ customerId }: { customerId: string }) {
  const query = useVerificationResults('EXPORTER', customerId);
  const [tab, setTab] = useState<WorkspaceTab>('COMPANY');
  const [recording, setRecording] = useState(false);
  const [filter, setFilter] = useState<ResultFilter>('ALL');
  const allResults = query.data?.results ?? [];
  const capabilities = query.data?.capabilities;

  // The current cycle is the server's. Until it is known (or for a company with no
  // cycle yet) every result is treated as current, as before cycles existed.
  const standing = useBackgroundCheck(customerId);
  const currentCycleId = standing.data?.current_cycle?.id ?? null;
  const inCurrentCycle = (result: VerificationResult) =>
    currentCycleId === null || !result.cycle_id || result.cycle_id === currentCycleId;
  const results = allResults.filter(inCurrentCycle);
  const earlier = allResults.filter((result) => !inCurrentCycle(result));
  const cycles = useCheckCycles(earlier.length > 0 ? customerId : undefined);
  const earlierCycles = (cycles.data?.cycles ?? [])
    .filter((cycle) => !cycle.is_current)
    .reverse()
    .map((cycle) => ({
      cycle,
      results: earlier.filter((result) => result.cycle_id === cycle.id),
    }))
    .filter((group) => group.results.length > 0);

  const shown = results.filter((result) => matchesFilter(result, filter));
  const companyResults = shown.filter((result) =>
    COMPANY_CHECK_TYPES.includes(result.verification_type),
  );
  // Every result on the company is a background-check input — a `REVIEW` or `PENDING`
  // one of any type blocks CLEAR — so one outside the screening set is listed too,
  // never dropped where nobody can see or review it.
  const otherResults = shown.filter(
    (result) => !COMPANY_CHECK_TYPES.includes(result.verification_type),
  );

  return (
    <section data-extension="screenings" className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="min-w-0 rounded-lg border border-border bg-surface p-5 shadow-card">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <ShieldCheck size={18} className="text-brand-600" />
              <h2 className="font-semibold text-ink">Screenings</h2>
            </div>
            <p className="mt-1 text-sm text-ink-muted">
              Check results, bank-monitoring signals and compliance review for this exporter.
            </p>
          </div>
          {tab === 'COMPANY' && capabilities?.can_record_result && !recording && (
            <button
              type="button"
              onClick={() => setRecording(true)}
              className="rounded-lg border border-border px-3 py-2 text-sm font-medium text-ink-muted hover:bg-surface-subtle"
            >
              Record a result
            </button>
          )}
        </div>

        {tab === 'COMPANY' && recording && capabilities?.can_record_result && (
          <ManualResultForm
            entityType="EXPORTER"
            entityReference={customerId}
            checkTypes={COMPANY_CHECK_TYPES}
            documentOwner={{ kind: 'company', id: customerId }}
            onClose={() => setRecording(false)}
          />
        )}

        <div className="mt-4 flex gap-6 border-b border-border">
          <button
            type="button"
            onClick={() => setTab('COMPANY')}
            className={`flex items-center gap-2 border-b-2 px-1 pb-3 text-sm font-medium ${tab === 'COMPANY' ? 'border-brand-500 text-brand-600' : 'border-transparent text-ink-muted hover:text-ink'}`}
          >
            <Building2 size={15} /> Company screenings{' '}
            <span className="text-xs text-ink-faint">({results.length})</span>
          </button>
          <button
            type="button"
            onClick={() => setTab('BANK')}
            className={`flex items-center gap-2 border-b-2 px-1 pb-3 text-sm font-medium ${tab === 'BANK' ? 'border-brand-500 text-brand-600' : 'border-transparent text-ink-muted hover:text-ink'}`}
          >
            <Activity size={15} /> Bank activity
          </button>
        </div>

        <div className="mt-4">
          {tab === 'BANK' ? (
            <BankActivityPanel customerId={customerId} />
          ) : query.isLoading ? (
            <div data-testid="verification-loading" className="space-y-3">
              <div className="h-20 animate-pulse rounded bg-surface-sunken" />
              <div className="h-20 animate-pulse rounded bg-surface-sunken" />
            </div>
          ) : query.isError ? (
            <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              <div className="flex items-start gap-2">
                <AlertTriangle size={16} className="mt-0.5 shrink-0" />
                <div>
                  Could not load screening results.{' '}
                  <button type="button" onClick={() => void query.refetch()} className="font-medium underline">
                    Retry
                  </button>
                </div>
              </div>
            </div>
          ) : (
            <>
              <div className="mb-3 flex flex-wrap gap-1.5" role="group" aria-label="Filter checks">
                {FILTERS.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    aria-pressed={filter === option.value}
                    onClick={() => setFilter(option.value)}
                    className={`rounded-full border px-3 py-1 text-xs font-medium ${
                      filter === option.value
                        ? 'border-ink bg-ink text-surface'
                        : 'border-border text-ink-muted hover:text-ink'
                    }`}
                  >
                    {option.label}{' '}
                    <span className="opacity-70">
                      ({results.filter((result) => matchesFilter(result, option.value)).length})
                    </span>
                  </button>
                ))}
              </div>
              {filter !== 'ALL' && shown.length === 0 ? (
                <FilteredEmpty filter={filter} />
              ) : companyResults.length === 0 && filter === 'ALL' ? (
                <EmptyScreenings />
              ) : companyResults.length === 0 ? null : (
                <div className="rounded-lg border border-border px-4">
                  {companyResults.map((result) => (
                    <VerificationResultRow
                      key={result.id}
                      result={result}
                      customerId={customerId}
                      canReview={capabilities?.can_review ?? false}
                      onStale={() => void query.refetch()}
                    />
                  ))}
                </div>
              )}
              {otherResults.length > 0 && (
                <div data-testid="other-company-checks" className="mt-4">
                  <p className="text-xs font-semibold text-ink">Other checks on this company</p>
                  <p className="mt-0.5 text-xs leading-5 text-ink-muted">
                    Recorded on this company outside the screening set. They count toward the
                    background check like any other result.
                  </p>
                  <div className="mt-2 rounded-lg border border-border px-4">
                    {otherResults.map((result) => (
                      <VerificationResultRow
                        key={result.id}
                        result={result}
                        customerId={customerId}
                        canReview={capabilities?.can_review ?? false}
                        onStale={() => void query.refetch()}
                      />
                    ))}
                  </div>
                </div>
              )}
              {filter === 'ALL' && <MissingChecks results={results} />}
              {earlierCycles.map(({ cycle, results: cycleResults }) => (
                <EarlierCycle
                  key={cycle.id}
                  label={`Cycle ${cycle.number} · ${cycleKindLabel(cycle.kind)}`}
                  results={cycleResults}
                  customerId={customerId}
                  onStale={() => void query.refetch()}
                />
              ))}
            </>
          )}
        </div>
      </div>
      <ScreeningChecklist customerId={customerId} />
    </section>
  );
}
