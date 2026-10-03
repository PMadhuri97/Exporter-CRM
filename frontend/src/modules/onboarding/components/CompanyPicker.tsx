/**
 * Pick a company, or create one — **owner: Developer 3** (allocation task 3.10,
 * plan P4-3). Mounted on the deal page by Developer 2's task 2.4.
 *
 * Two ways to find a company, because an RM has one of two things in hand:
 *
 * * **A name.** Searches the companies this role can already see
 *   (`GET /exporters?name=`), and additionally asks `POST /companies/match`, which
 *   is the only thing that can say "a company already on file is named this,
 *   ignoring punctuation and legal form". That is worth saying loudly: the whole
 *   point of this control is that an RM stops creating a second record for a buyer
 *   we already have.
 * * **A full identifier.** A complete PAN, GSTIN or registration number names the
 *   company that holds it — including for a role that sees identifiers masked
 *   (decision BQ-2). The identifier is sent, never displayed back: the response
 *   carries no identifiers at all, and every such lookup is audited server-side.
 *
 * **Partial identifiers are refused by the server, so this does not offer them.**
 * The field asks for the whole value and says so; a prefix search would be a way to
 * read identifiers out of the CRM one character at a time, which is exactly what
 * BQ-2's "exact only" rule exists to prevent. The component does not try to
 * validate formats itself — the server owns that, and a client-side regex that
 * disagreed with it would refuse values the CRM accepts.
 *
 * What the four answers mean on screen:
 *
 * | `kind` | Shown as |
 * |---|---|
 * | `MATCHED` | one company, ready to select |
 * | `POSSIBLE_DUPLICATE` | "check these first" — candidates, nothing preselected |
 * | `CONFLICT` | a warning naming every company involved; the RM decides |
 * | `NEW` | "no company matches", and creating one is still elsewhere |
 *
 * `POSSIBLE_DUPLICATE` and `CONFLICT` both set `needs_a_person`, and neither
 * preselects anything — picking one for the RM is how a deal ends up attached to
 * the wrong company (decision IQ-8).
 *
 * **Creating a company from here is deliberately still absent.** It needs the
 * buyer-create path (Developer 2's task 2.6 uses the same
 * `CompanyDirectory.create_buyer_company`), and a create button that made an
 * ordinary `IN_PIPELINE` lead instead of a `NOT_IN_PIPELINE` buyer company would
 * quietly inflate the sales pipeline — the precise failure P4-2 exists to prevent.
 * So it says where creating lives rather than offering a button that does the wrong
 * thing.
 */

import { useMutation } from '@tanstack/react-query';
import { AlertTriangle, Search } from 'lucide-react';
import { useState } from 'react';

import { Button, EmptySection, Input, Skeleton } from '@/components';

import { matchCompany } from '../api';
import { useExporterProfiles } from '../hooks';
import type {
  CompanyMatch,
  CompanyMatchCandidate,
  ExporterProfileListItem,
} from '../types';

/** Which identifier the RM is holding. */
type IdentifierKind = 'pan' | 'gstin' | 'registration_number';

const IDENTIFIER_LABEL: Record<IdentifierKind, string> = {
  pan: 'PAN',
  gstin: 'GSTIN',
  registration_number: 'Registration number',
};

const IDENTIFIER_HINT: Record<IdentifierKind, string> = {
  pan: 'The complete 10-character PAN',
  gstin: 'The complete 15-character GSTIN',
  registration_number: "The complete number, as the company's own registrar issued it",
};

export interface CompanyPickerProps {
  /** Called with `exporter_profile.customer_id` when the user picks one. */
  onSelect(companyId: string): void;
  /**
   * A company to leave out of the results — the deal's seller, so nobody picks it
   * as its own buyer (`ck_deal_buyer_is_not_the_seller` would refuse it anyway, but
   * offering the choice and then failing is worse than not offering it).
   */
  excludeCompanyId?: string;
  /**
   * The country to match a registration number within, and the one sent with a
   * name search. Defaults to `IN`. A registration number is only unique per
   * country, so matching one without a country would be meaningless.
   */
  country?: string;
}

export function CompanyPicker({
  onSelect,
  excludeCompanyId,
  country = 'IN',
}: CompanyPickerProps) {
  const [term, setTerm] = useState('');
  const [identifierKind, setIdentifierKind] = useState<IdentifierKind>('pan');
  const [identifier, setIdentifier] = useState('');

  const trimmed = term.trim();
  // Only ask once the term is worth a query: a one-letter search returns most of the
  // database and tells the user nothing. The hook always runs, so an empty `name`
  // stands in for "not searching yet" and the results are ignored below.
  const ready = trimmed.length >= 2;
  const query = useExporterProfiles(ready ? { name: trimmed, limit: 10 } : { limit: 1 });

  const match = useMutation({ mutationFn: matchCompany });
  // Cleared whenever the name changes, so a stale identifier answer can never sit
  // under a different search and look like its result.
  const matched: CompanyMatch | undefined = match.data;

  const byName = ready
    ? (query.data?.profiles ?? []).filter(
        (company: ExporterProfileListItem) => company.customer_id !== excludeCompanyId,
      )
    : [];

  const candidates = (matched?.candidates ?? []).filter(
    (candidate) => candidate.company_id !== excludeCompanyId,
  );

  function lookUpIdentifier() {
    const value = identifier.trim();
    if (!value) return;
    match.mutate({
      // `name` is required by the server even with an identifier: a MATCHED answer
      // naming a company that looks nothing like what the RM typed is the signal
      // something is wrong, and the name is what makes that visible.
      name: trimmed || value,
      country,
      [identifierKind]: value,
    });
  }

  function lookUpName() {
    if (!ready) return;
    match.mutate({ name: trimmed, country });
  }

  return (
    <div className="flex flex-col gap-4">
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
            onChange={(event) => {
              setTerm(event.target.value);
              match.reset();
            }}
            onBlur={lookUpName}
          />
        </span>
      </label>

      <details className="rounded-lg border border-border px-3 py-2">
        <summary className="cursor-pointer text-sm font-medium text-ink">
          Search by identifier
        </summary>
        <div className="mt-3 flex flex-col gap-2">
          <div className="flex flex-wrap gap-2">
            {(Object.keys(IDENTIFIER_LABEL) as IdentifierKind[]).map((kind) => (
              <button
                key={kind}
                type="button"
                aria-pressed={identifierKind === kind}
                onClick={() => {
                  setIdentifierKind(kind);
                  match.reset();
                }}
                className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                  identifierKind === kind
                    ? 'border-brand-600 bg-brand-50 text-brand-700'
                    : 'border-border text-ink-muted hover:bg-surface-subtle'
                }`}
              >
                {IDENTIFIER_LABEL[kind]}
              </button>
            ))}
          </div>
          <Input
            type="text"
            value={identifier}
            aria-label={IDENTIFIER_LABEL[identifierKind]}
            placeholder={IDENTIFIER_LABEL[identifierKind]}
            onChange={(event) => {
              setIdentifier(event.target.value);
              match.reset();
            }}
          />
          <p className="text-xs text-ink-faint">
            {IDENTIFIER_HINT[identifierKind]}. Partial values are not accepted, and
            the identifier is never shown back to you.
          </p>
          <Button
            variant="secondary"
            onClick={lookUpIdentifier}
            disabled={!identifier.trim() || match.isPending}
          >
            Look up
          </Button>
        </div>
      </details>

      {match.isError ? (
        <EmptySection>
          {/* The server words every refusal — a partial identifier, a masked value
              sent back — and this shows it rather than guessing at the rule. */}
          That search was refused. Send the complete identifier, or search by name.
        </EmptySection>
      ) : null}

      {matched?.kind === 'CONFLICT' ? (
        <div
          role="alert"
          className="flex gap-2 rounded-lg border border-status-review/40 bg-status-review/10 p-3 text-sm text-ink"
        >
          <AlertTriangle size={16} className="mt-0.5 shrink-0 text-status-review" />
          <span>
            <span className="font-medium">These identifiers name more than one company.</span>{' '}
            {matched.reason} Check which one this buyer is before choosing.
          </span>
        </div>
      ) : null}

      {matched?.kind === 'POSSIBLE_DUPLICATE' ? (
        <p className="text-sm text-ink-muted">
          <span className="font-medium text-ink">Check these first.</span> {matched.reason}
        </p>
      ) : null}

      {candidates.length > 0 ? (
        <CandidateList candidates={candidates} onSelect={onSelect} />
      ) : null}

      {!ready && !matched ? (
        <p className="text-xs text-ink-faint">
          Type at least two characters, or search by identifier.
        </p>
      ) : query.isLoading || match.isPending ? (
        <Skeleton className="h-16 rounded-lg" />
      ) : byName.length === 0 && candidates.length === 0 && !match.isError ? (
        <EmptySection>
          No company on file matches that. Creating a buyer company from here arrives
          with the buyer migration.
        </EmptySection>
      ) : byName.length > 0 ? (
        <ul className="divide-y divide-border rounded-lg border border-border">
          {byName.map((company: ExporterProfileListItem) => (
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
                    {company.country ?? '—'} ·{' '}
                    {company.pipeline_status === 'NOT_IN_PIPELINE'
                      ? 'Not in pipeline'
                      : company.journey}
                  </span>
                </span>
                <span className="text-xs font-medium text-brand-600">Select</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function CandidateList({
  candidates,
  onSelect,
}: {
  candidates: CompanyMatchCandidate[];
  onSelect(companyId: string): void;
}) {
  return (
    <ul className="divide-y divide-border rounded-lg border border-border" data-testid="match-candidates">
      {candidates.map((candidate) => (
        <li key={candidate.company_id}>
          <button
            type="button"
            onClick={() => onSelect(candidate.company_id)}
            className="flex w-full flex-wrap items-center justify-between gap-2 px-4 py-3 text-left transition-colors hover:bg-surface-subtle"
          >
            <span className="min-w-0">
              <span className="font-medium text-ink">
                {candidate.name ?? 'Unnamed company'}
              </span>
              <span className="mt-0.5 block text-xs text-ink-muted">
                {candidate.country ?? '—'}
                {candidate.pipeline_status === 'NOT_IN_PIPELINE'
                  ? ' · Not in pipeline — exists as a buyer'
                  : ''}
              </span>
            </span>
            <span className="text-xs font-medium text-brand-600">Select</span>
          </button>
        </li>
      ))}
    </ul>
  );
}
