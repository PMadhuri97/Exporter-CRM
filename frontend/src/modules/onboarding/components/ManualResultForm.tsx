/**
 * Record a manual verification result (verification-and-screening.md §3, §9).
 *
 * A person records what they checked, with its real outcome and what it rests on:
 *
 * - `provider` is always `manual`. The route accepts nothing else, and the form
 *   offers no choice, so nobody can record a result as RXIL's.
 * - Outcomes are `PASSED`, `FAILED` and `REVIEW`. `PENDING` is never offered: nothing
 *   would ever resolve a manual pending result (§8).
 * - A `PASSED` needs evidence — a note, a document or a link. Checked here to
 *   save a round trip; the server checks it too, and its refusal is shown as worded.
 * - Only documents the subject owns and that are `AVAILABLE` are offered: nothing
 *   else can be opened, and the server refuses it.
 *
 * Shared by the company workspace (company documents) and `BuyerChecks` (the buyer's
 * deal documents). The caller shows it only when `capabilities.can_record_result`.
 */

import { useState } from 'react';
import { toast } from 'sonner';

import { ApiError } from '@/lib/api/errors';
import { humanize } from '@/lib/format';

import { useCompanyDocuments, useDealDocuments, useTriggerVerification } from '../hooks';
import type {
  VerificationEntityType,
  VerificationEvidenceRef,
  VerificationResultStatus,
  VerificationRiskLevel,
  VerificationType,
} from '../types';

import { isWebLink, MANUAL_OUTCOMES, RISK_LEVELS, verificationTypeLabel } from './verification-labels';

const FIELD =
  'mt-1 w-full rounded-md border border-line bg-surface px-2 py-1.5 text-caption text-ink outline-none focus:border-accent disabled:opacity-60';
const SECONDARY_BUTTON =
  'rounded-lg border border-line px-2.5 py-1.5 text-caption font-medium text-ink-2 hover:bg-paper disabled:opacity-50';
const PRIMARY_BUTTON =
  'rounded-md bg-accent-solid px-2.5 py-1.5 text-caption font-medium text-white disabled:opacity-50';

/** Whose documents may be evidence: the company's, or the buyer's deal's. */
export type EvidenceDocumentOwner = { kind: 'company' | 'deal'; id: string };

export function ManualResultForm({
  entityType,
  entityReference,
  checkTypes,
  documentOwner,
  onClose,
}: {
  entityType: VerificationEntityType;
  entityReference: string;
  checkTypes: VerificationType[];
  documentOwner: EvidenceDocumentOwner;
  onClose: () => void;
}) {
  const mutation = useTriggerVerification(entityType, entityReference);
  const companyDocuments = useCompanyDocuments(
    documentOwner.kind === 'company' ? documentOwner.id : undefined,
  );
  const dealDocuments = useDealDocuments(
    documentOwner.kind === 'deal' ? documentOwner.id : undefined,
  );
  const documents = documentOwner.kind === 'company' ? companyDocuments : dealDocuments;

  const [verificationType, setVerificationType] = useState<VerificationType>(
    checkTypes[0] ?? 'KYB',
  );
  const [outcome, setOutcome] = useState<VerificationResultStatus | ''>('');
  const [risk, setRisk] = useState<VerificationRiskLevel | ''>('');
  const [note, setNote] = useState('');
  const [documentIds, setDocumentIds] = useState<string[]>([]);
  const [url, setUrl] = useState('');
  const [error, setError] = useState<string | null>(null);

  // Only a document that can be opened can be evidence; the server refuses the rest.
  const available = (documents.data?.documents ?? []).filter(
    (document) => document.scan_status === 'AVAILABLE',
  );

  function toggleDocument(id: string) {
    setDocumentIds((current) =>
      current.includes(id) ? current.filter((value) => value !== id) : [...current, id],
    );
  }

  async function submit() {
    setError(null);
    if (!outcome) {
      setError('Choose an outcome.');
      return;
    }
    const refs: VerificationEvidenceRef[] = documentIds.map((id) => ({ type: 'document', ref: id }));
    const link = url.trim();
    // Other staff open this as a link, so only http(s) is accepted; the server refuses
    // anything else too.
    if (link && !isWebLink(link)) {
      setError('The evidence link must start with http:// or https://.');
      return;
    }
    if (link) refs.push({ type: 'url', ref: link });
    const trimmedNote = note.trim();
    // A manual PASSED needs a note or at least one reference.
    if (outcome === 'PASSED' && !trimmedNote && refs.length === 0) {
      setError('A passed check needs evidence: a note, a document or a link.');
      return;
    }
    try {
      await mutation.mutateAsync({
        verification_type: verificationType,
        provider: 'manual',
        payload: { status: outcome, ...(risk ? { risk_level: risk } : {}) },
        evidence_note: trimmedNote || null,
        evidence_refs: refs,
      });
      toast.success('Check recorded');
      onClose();
    } catch (caught) {
      // The server's words: a 422 on evidence, or a 409 DEAL_CLOSED on a buyer.
      setError(caught instanceof ApiError ? caught.message : 'Could not record the check.');
    }
  }

  return (
    <div
      data-testid="manual-result-form"
      className="mt-4 rounded-lg border border-line p-4 text-caption"
    >
      <p className="font-medium text-ink">Record a manual result</p>
      <p className="mt-0.5 text-ink-3">Recorded as a manual check by you.</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <label className="block text-ink-3">
          Check
          <select
            aria-label="Check"
            className={FIELD}
            value={verificationType}
            disabled={mutation.isPending}
            onChange={(event) => setVerificationType(event.target.value as VerificationType)}
          >
            {checkTypes.map((type) => (
              <option key={type} value={type}>
                {verificationTypeLabel(type)}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-ink-3">
          Outcome
          <select
            aria-label="Outcome"
            className={FIELD}
            value={outcome}
            disabled={mutation.isPending}
            onChange={(event) => setOutcome(event.target.value as VerificationResultStatus | '')}
          >
            <option value="">Choose…</option>
            {MANUAL_OUTCOMES.map((value) => (
              <option key={value} value={value}>
                {humanize(value)}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-ink-3">
          Risk (optional)
          <select
            aria-label="Risk"
            className={FIELD}
            value={risk}
            disabled={mutation.isPending}
            onChange={(event) => setRisk(event.target.value as VerificationRiskLevel | '')}
          >
            <option value="">None</option>
            {RISK_LEVELS.map((value) => (
              <option key={value} value={value}>
                {humanize(value)}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label className="mt-3 block text-ink-3">
        Evidence note
        <textarea
          aria-label="Evidence note"
          className={`${FIELD} min-h-16 resize-y`}
          value={note}
          disabled={mutation.isPending}
          onChange={(event) => setNote(event.target.value)}
        />
      </label>
      <fieldset className="mt-3">
        <legend className="text-ink-3">
          Evidence documents from this {documentOwner.kind === 'deal' ? 'deal' : 'company'}
        </legend>
        {documents.isLoading ? (
          <p className="mt-1 text-ink-3">Loading documents…</p>
        ) : documents.isError ? (
          <p className="mt-1 text-ink-3">Documents could not be loaded.</p>
        ) : available.length === 0 ? (
          <p className="mt-1 text-ink-3">No scanned-clean documents to attach.</p>
        ) : (
          <div className="mt-1 space-y-1">
            {available.map((document) => (
              <label key={document.id} className="flex items-center gap-2 text-ink">
                <input
                  type="checkbox"
                  checked={documentIds.includes(document.id)}
                  disabled={mutation.isPending}
                  onChange={() => toggleDocument(document.id)}
                />
                {document.file_name}
              </label>
            ))}
          </div>
        )}
      </fieldset>
      <label className="mt-3 block text-ink-3">
        Evidence link (optional)
        <input
          aria-label="Evidence link"
          type="url"
          className={FIELD}
          value={url}
          disabled={mutation.isPending}
          onChange={(event) => setUrl(event.target.value)}
        />
      </label>
      {error && (
        <p role="alert" className="mt-2 text-negative">
          {error}
        </p>
      )}
      <div className="mt-3 flex justify-end gap-2">
        <button type="button" className={SECONDARY_BUTTON} onClick={onClose}>
          Cancel
        </button>
        <button
          type="button"
          className={PRIMARY_BUTTON}
          disabled={mutation.isPending}
          onClick={() => void submit()}
        >
          Record check
        </button>
      </div>
    </div>
  );
}
