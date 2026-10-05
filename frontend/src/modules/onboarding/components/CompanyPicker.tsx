/**
 * Pick a company, or create one. Mounted on the deal page as the buyer picker.
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
 *   company that holds it — including for a role that sees identifiers masked.
 *   The identifier is sent, never displayed back: the response
 *   carries no identifiers at all, and every such lookup is audited server-side.
 *
 * **Partial identifiers are refused by the server, so this does not offer them.**
 * The field asks for the whole value and says so; a prefix search would be a way to
 * read identifiers out of the CRM one character at a time, which is exactly what
 * the "exact only" rule exists to prevent. The component does not try to
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
 * | `NEW` | "no company matches" — and **Create buyer company** |
 *
 * `POSSIBLE_DUPLICATE` and `CONFLICT` both set `needs_a_person`, and neither
 * preselects anything — picking one for the RM is how a deal ends up attached to
 * the wrong company.
 *
 * **Creating** is offered only when the caller passes `onCreate`, and only
 * once the server has answered `NEW` — or `POSSIBLE_DUPLICATE` after the RM says none
 * of the look-alikes is the buyer: a name is never an identity, but the RM
 * must have seen them first. It creates a buyer company **outside the pipeline**
 * through the deal's buyer route, never an ordinary lead — the failure that rule exists to
 * prevent. `MATCHED` and `CONFLICT` never offer it: an identifier already names a
 * company on file, and the server would refuse a duplicate anyway.
 */

import { useMutation } from '@tanstack/react-query';
import { useState } from 'react';

import { Button, EmptySection, Input, Skeleton } from '@/components';
import { Icon } from '@/design/icons';

import { matchCompany } from '../api';
import { useExporterProfiles } from '../hooks';
import type {
  CompanyMatch,
  CompanyMatchCandidate,
  CreateBuyerCompanyRequest,
  ExporterProfileListItem,
} from '../types';

import { CreateBuyerCompanyForm } from './CreateBuyerCompanyForm';

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
  /**
   * Create the buyer as a company outside the pipeline. Rejects with the
   * server's refusal, which the form shows. Without it, nothing here creates.
   */
  onCreate?(draft: CreateBuyerCompanyRequest): Promise<unknown>;
}

export function CompanyPicker({
  onSelect,
  excludeCompanyId,
  country = 'IN',
  onCreate,
}: CompanyPickerProps) {
  const [term, setTerm] = useState('');
  const [identifierKind, setIdentifierKind] = useState<IdentifierKind>('pan');
  const [identifier, setIdentifier] = useState('');
  const [creating, setCreating] = useState(false);

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
          <Icon.search
            size={15}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-3"
          />
          <Input
            type="text"
            value={term}
            placeholder="Company name"
            className="pl-9"
            onChange={(event) => {
              setTerm(event.target.value);
              match.reset();
              setCreating(false);
            }}
            onBlur={lookUpName}
            // Enter looks the name up too: waiting for the field to lose focus left
            // the picker looking stuck to anyone who typed a name and pressed Enter.
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                lookUpName();
              }
            }}
          />
        </span>
      </label>

      <details className="rounded-lg border border-line px-3 py-2">
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
                className={`rounded-md border px-3 py-1 text-xs font-medium transition-colors ${
                  identifierKind === kind
                    ? 'border-ink bg-sunken text-ink'
                    : 'border-line text-ink-2 hover:bg-paper'
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
              setCreating(false);
            }}
          />
          <p className="text-xs text-ink-3">
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
          className="flex gap-2 rounded-lg border border-attention/40 bg-attention-tint p-3 text-sm text-ink"
        >
          <Icon.warning size={16} className="mt-0.5 shrink-0 text-attention" />
          <span>
            <span className="font-medium">These identifiers name more than one company.</span>{' '}
            {matched.reason} Check which one this buyer is before choosing.
          </span>
        </div>
      ) : null}

      {matched?.kind === 'POSSIBLE_DUPLICATE' ? (
        <p className="text-sm text-ink-2">
          <span className="font-medium text-ink">Check these first.</span> {matched.reason}
        </p>
      ) : null}

      {candidates.length > 0 ? (
        <CandidateList candidates={candidates} onSelect={onSelect} />
      ) : null}

      {onCreate && creating ? (
        <CreateBuyerCompanyForm
          initial={{
            name: trimmed,
            country,
            // The RM's own input, never a value the server sent back.
            ...(identifier.trim() ? { [identifierKind]: identifier.trim() } : {}),
          }}
          onCreate={onCreate}
          onChooseExisting={onSelect}
          onCancel={() => setCreating(false)}
        />
      ) : onCreate &&
        (matched?.kind === 'NEW' || matched?.kind === 'POSSIBLE_DUPLICATE') ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-dashed border-line px-4 py-3">
          <span className="text-sm text-ink-2">
            {matched.kind === 'NEW'
              ? 'No company on file matches. Create the buyer as a company of its own.'
              : 'None of these is the buyer? Create it as a company of its own.'}
          </span>
          <Button size="sm" variant="primary" onClick={() => setCreating(true)}>
            Create buyer company
          </Button>
        </div>
      ) : null}

      {!ready && !matched ? (
        <p className="text-xs text-ink-3">
          Type at least two characters, or search by identifier.
        </p>
      ) : query.isLoading || match.isPending ? (
        <Skeleton className="h-16 rounded-lg" />
      ) : byName.length === 0 && candidates.length === 0 && !match.isError ? (
        creating ? null : (
          <EmptySection>
            No company on file matches that.
            {onCreate && !matched ? ' Press Enter to look the name up.' : ''}
          </EmptySection>
        )
      ) : byName.length > 0 ? (
        <ul className="divide-y divide-line rounded-lg border border-line">
          {byName.map((company: ExporterProfileListItem) => (
            <li key={company.customer_id}>
              <button
                type="button"
                onClick={() => onSelect(company.customer_id)}
                className="flex w-full flex-wrap items-center justify-between gap-2 px-4 py-3 text-left transition-colors hover:bg-paper"
              >
                <span className="min-w-0">
                  <span className="font-medium text-ink">
                    {company.name ?? 'Unnamed company'}
                  </span>
                  <span className="mt-0.5 block text-xs text-ink-2">
                    {company.country ?? '—'} ·{' '}
                    {company.pipeline_status === 'NOT_IN_PIPELINE'
                      ? 'Not in pipeline'
                      : company.journey}
                  </span>
                </span>
                <span className="text-xs font-medium text-ink">Select</span>
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
    <ul className="divide-y divide-line rounded-lg border border-line" data-testid="match-candidates">
      {candidates.map((candidate) => (
        <li key={candidate.company_id}>
          <button
            type="button"
            onClick={() => onSelect(candidate.company_id)}
            className="flex w-full flex-wrap items-center justify-between gap-2 px-4 py-3 text-left transition-colors hover:bg-paper"
          >
            <span className="min-w-0">
              <span className="font-medium text-ink">
                {candidate.name ?? 'Unnamed company'}
              </span>
              <span className="mt-0.5 block text-xs text-ink-2">
                {candidate.country ?? '—'}
                {candidate.pipeline_status === 'NOT_IN_PIPELINE'
                  ? ' · Not in pipeline — exists as a buyer'
                  : ''}
              </span>
            </span>
            <span className="text-xs font-medium text-ink">Select</span>
          </button>
        </li>
      ))}
    </ul>
  );
}
