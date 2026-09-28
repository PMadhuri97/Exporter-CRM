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
 */

import { Activity, AlertTriangle, Building2, Info, ShieldCheck } from 'lucide-react';
import { useState } from 'react';

import { humanize } from '@/lib/format';

import { useVerificationResults } from '../hooks';
import type { VerificationResult } from '../types';

import { BankActivityPanel } from './BankActivityPanel';
import { ManualResultForm } from './ManualResultForm';
import { ScreeningChecklist } from './ScreeningChecklist';
import { COMPANY_CHECK_TYPES } from './verification-labels';
import { VerificationResultRow } from './VerificationResultRow';

type WorkspaceTab = 'COMPANY' | 'BANK';

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
  const results = query.data?.results ?? [];
  const capabilities = query.data?.capabilities;
  const companyResults = results.filter((result) =>
    COMPANY_CHECK_TYPES.includes(result.verification_type),
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
            <span className="text-xs text-ink-faint">({companyResults.length})</span>
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
              {companyResults.length === 0 ? (
                <EmptyScreenings />
              ) : (
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
              <MissingChecks results={results} />
            </>
          )}
        </div>
      </div>
      <ScreeningChecklist customerId={customerId} />
    </section>
  );
}
