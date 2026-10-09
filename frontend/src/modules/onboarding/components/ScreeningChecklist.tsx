/**
 * The compliance screening checklist (verification-and-screening.md §5, §9), with
 * evidence and cycles.
 *
 * Rendered from the server: the items, their labels, sections and order come from
 * `catalogue` (the one backend catalogue, `SCREENING_CATALOGUE_ITEMS`), and whether
 * the viewer may record a decision from `capabilities.can_record_decision`. This file
 * keeps no copy of either. Each item's full history opens beneath it.
 *
 * Screening is a compliance list inside the background check. It is not
 * qualification, and not a gauge (architecture §5.5).
 *
 * Since 1 October 2026:
 * - **Evidence**: each answer shows the evidence it was given (`EvidenceList`),
 *   and a new answer may carry some — the company's scanned-clean documents or an
 *   http(s) link. Optional. Answers are append-only, so evidence belongs to the
 *   answer it was given with; a new answer starts with none attached.
 * - **Cycles**: the list is one check cycle's — the current one, where answers
 *   are recorded; an earlier one, read-only, when chosen. Whether the viewer may record
 *   still comes only from `capabilities`, which the server sets false on earlier cycles.
 * - The catalogue is seven items since `website-reviewed` was retired.
 */

import { useState } from 'react';
import { toast } from 'sonner';

import { Icon } from '@/design/icons';
import { ApiError } from '@/lib/api/errors';
import { formatDate, formatDateTime } from '@/lib/format';

import {
  useCheckCycles,
  useCompanyAddresses,
  useCompanyDocuments,
  useScreeningReview,
  useUpdateScreeningReviewItem,
} from '../hooks';
import type {
  ScreeningCatalogueItem,
  ScreeningChecklistStatus,
  VerificationEvidenceRef,
  VerificationEvidenceRefStored,
} from '../types';

import { addressLine } from './address-labels';
import { cycleKindLabel } from './background-check-labels';
import { EvidenceList } from './EvidenceList';
import { ScreeningItemHistory } from './ScreeningItemHistory';
import { isWebLink } from './verification-labels';
import { VerificationStatusChip } from './VerificationStatusChip';

/** Which cycle the checklist shows; the current one unless the viewer picks another. */
function CyclePicker({
  customerId,
  currentNumber,
  value,
  onChange,
}: {
  customerId: string;
  currentNumber: number;
  value: string | undefined;
  onChange: (cycleId: string | undefined) => void;
}) {
  // Fetched only when there is an earlier cycle to show (the current number is > 1).
  const cycles = useCheckCycles(currentNumber > 1 ? customerId : undefined);
  const options = cycles.data?.cycles ?? [];
  if (options.length < 2) return null;
  return (
    <label className="mt-2 flex items-center gap-2 text-caption text-ink-2">
      Cycle
      <select
        aria-label="Check cycle"
        className="rounded-md border border-line bg-surface px-2 py-1 text-caption text-ink"
        value={value ?? ''}
        onChange={(event) => onChange(event.target.value || undefined)}
      >
        {[...options].reverse().map((cycle) => (
          <option key={cycle.id} value={cycle.is_current ? '' : cycle.id}>
            {`Cycle ${cycle.number} · ${cycleKindLabel(cycle.kind)}${cycle.is_current ? ' (current)' : ''}`}
          </option>
        ))}
      </select>
    </label>
  );
}

export function ScreeningChecklist({ customerId }: { customerId: string }) {
  const [cycleId, setCycleId] = useState<string | undefined>(undefined);
  const query = useScreeningReview(customerId, cycleId);
  const mutation = useUpdateScreeningReviewItem(customerId);
  const catalogue = query.data?.catalogue ?? [];
  const canRecord = query.data?.capabilities.can_record_decision ?? false;
  const serverItems = query.data?.items ?? [];
  const byKey = new Map(serverItems.map((item) => [item.item_key, item]));
  const completed = catalogue.filter(
    (item) => (byKey.get(item.key)?.status ?? 'NEEDS_REVIEW') !== 'NEEDS_REVIEW',
  ).length;
  // Sections in the order the catalogue first uses them.
  const sections = [...new Set(catalogue.map((item) => item.section))];
  // Rows persisted under a key the catalogue no longer (or not yet) defines — an
  // older checklist revision, or a key written before keys were validated. Listing
  // only the catalogue would fetch these and silently drop them, hiding a decision
  // that exists in the database. Read-only: nothing here knows what they mean.
  const knownKeys = new Set(catalogue.map((item) => item.key));
  const unrecognised = serverItems.filter((item) => !knownKeys.has(item.item_key));

  const cycle = query.data?.cycle ?? null;
  const isCurrentCycle = cycle?.is_current ?? true;

  async function save(
    itemKey: string,
    status: ScreeningChecklistStatus,
    comment: string | null,
    evidenceRefs: VerificationEvidenceRef[],
  ): Promise<boolean> {
    try {
      await mutation.mutateAsync({ itemKey, status, comment, evidenceRefs });
      toast.success('Review item saved');
      return true;
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : 'Could not save review item');
      return false;
    }
  }

  return (
    <aside
      data-testid="screening-checklist"
      className="rounded-lg border border-line bg-surface"
    >
      <div className="border-b border-line px-4 py-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="font-semibold text-ink">Review checklist</h3>
            {!query.isLoading && !query.isError && (
              <p className="mt-0.5 text-caption text-ink-2">
                {completed}/{catalogue.length} items reviewed
                {unrecognised.length > 0 && ` · ${unrecognised.length} unrecognised`}
              </p>
            )}
          </div>
        </div>
        {cycle && (
          <p data-testid="screening-cycle" className="mt-2 text-caption text-ink-2">
            Cycle {cycle.number} · {cycleKindLabel(cycle.kind)} · started {formatDate(cycle.started_at)}
            {!isCurrentCycle && ' · earlier cycle, read-only'}
          </p>
        )}
        {cycle && (
          <CyclePicker
            customerId={customerId}
            currentNumber={isCurrentCycle ? cycle.number : cycle.number + 1}
            value={cycleId}
            onChange={setCycleId}
          />
        )}
        <p className="mt-3 rounded-md bg-paper px-3 py-2 text-caption leading-5 text-ink-3">
          Decisions and comments are stored with reviewer and timestamp; every earlier
          decision stays in each item&apos;s history.
        </p>
      </div>

      <div className="max-h-[720px] space-y-4 overflow-y-auto p-4">
        {query.isLoading ? (
          <div className="h-32 animate-pulse rounded bg-sunken" />
        ) : query.isError ? (
          <div role="alert" className="rounded-md border border-negative/30 bg-negative-tint p-3 text-caption text-negative">
            Could not load checklist.{' '}
            <button type="button" className="underline" onClick={() => void query.refetch()}>
              Retry
            </button>
          </div>
        ) : (
          sections.map((section) => (
            <div key={section} data-testid="screening-section">
              <p className="mb-2 text-caption font-semibold text-ink">{section}</p>
              <div className="space-y-2">
                {catalogue
                  .filter((item) => item.section === section)
                  .map((item) => {
                    const saved = byKey.get(item.key);
                    return (
                      <ChecklistCard
                        // Stable: keying on the saved values remounted every card
                        // whenever any one of them saved, throwing away unsaved text
                        // in the others. The card reconciles server changes itself.
                        // A different cycle is a different list, so it remounts.
                        key={`${cycleId ?? 'current'}:${item.key}`}
                        customerId={customerId}
                        item={item}
                        initialStatus={saved?.status ?? 'NEEDS_REVIEW'}
                        initialComment={saved?.comment ?? ''}
                        savedEvidence={saved?.evidence_refs ?? []}
                        canRecord={canRecord}
                        busy={mutation.isPending}
                        onSave={save}
                      />
                    );
                  })}
              </div>
            </div>
          ))
        )}

        {!query.isLoading && !query.isError && unrecognised.length > 0 && (
          <div>
            <p className="mb-2 flex items-center gap-1.5 text-caption font-semibold text-attention">
              <Icon.warning size={13} /> Unrecognised items
            </p>
            <p className="mb-2 text-[11px] leading-5 text-ink-2">
              Stored against this exporter under a key the checklist does not define. Shown
              read-only so a persisted decision is never hidden.
            </p>
            <div className="space-y-2">
              {unrecognised.map((item) => (
                <div
                  key={item.id}
                  data-testid="unrecognised-item"
                  className="rounded-lg border border-dashed border-attention/30 bg-attention-tint px-3 py-2.5"
                >
                  <p className="break-all text-[11px] text-ink">{item.item_key}</p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-2">
                    <VerificationStatusChip value={item.status} />
                    <span className="text-[11px] text-ink-3">
                      {formatDateTime(item.reviewed_at)}
                    </span>
                  </div>
                  {item.comment && (
                    <p className="mt-1.5 text-caption leading-5 text-ink-2">{item.comment}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}

/**
 * Evidence for the answer about to be recorded: the company's scanned-clean documents
 * and an optional http(s) link. Mounted only when opened, so the documents are fetched
 * only then. The server checks the same rules (and ownership) again.
 */
function EvidencePicker({
  customerId,
  refs,
  onChange,
  disabled,
}: {
  customerId: string;
  refs: VerificationEvidenceRef[];
  onChange: (refs: VerificationEvidenceRef[]) => void;
  disabled: boolean;
}) {
  const documents = useCompanyDocuments(customerId);
  const [link, setLink] = useState('');
  const [error, setError] = useState<string | null>(null);
  const available = (documents.data?.documents ?? []).filter(
    (document) => document.scan_status === 'AVAILABLE',
  );
  const chosen = new Set(refs.filter((ref) => ref.type === 'document').map((ref) => ref.ref));

  function toggle(documentId: string) {
    onChange(
      chosen.has(documentId)
        ? refs.filter((ref) => !(ref.type === 'document' && ref.ref === documentId))
        : [...refs, { type: 'document', ref: documentId }],
    );
  }

  function addLink() {
    const value = link.trim();
    if (!isWebLink(value)) {
      setError('The link must start with http:// or https://.');
      return;
    }
    setError(null);
    onChange([...refs, { type: 'url', ref: value }]);
    setLink('');
  }

  return (
    <div data-testid="screening-evidence-picker" className="mt-2 rounded-md border border-line p-2">
      {documents.isLoading ? (
        <p className="text-[11px] text-ink-3">Loading documents…</p>
      ) : available.length === 0 ? (
        <p className="text-[11px] text-ink-3">No scanned-clean documents to attach.</p>
      ) : (
        <div className="space-y-1">
          {available.map((document) => (
            <label key={document.id} className="flex items-center gap-2 text-[11px] text-ink">
              <input
                type="checkbox"
                checked={chosen.has(document.id)}
                disabled={disabled}
                onChange={() => toggle(document.id)}
              />
              {document.file_name}
            </label>
          ))}
        </div>
      )}
      <div className="mt-2 flex gap-2">
        <input
          aria-label="Evidence link"
          type="url"
          className="w-full rounded-md border border-line bg-surface px-2 py-1 text-[11px] text-ink"
          placeholder="https://…"
          value={link}
          disabled={disabled}
          onChange={(event) => setLink(event.target.value)}
        />
        <button
          type="button"
          className="rounded-md border border-line px-2 py-1 text-[11px] text-ink-2"
          disabled={disabled || !link.trim()}
          onClick={addLink}
        >
          Add link
        </button>
      </div>
      {refs.some((ref) => ref.type === 'url') && (
        <ul className="mt-1 space-y-0.5 text-[11px] text-ink-2">
          {refs
            .filter((ref) => ref.type === 'url')
            .map((ref) => (
              <li key={ref.ref} className="break-all">
                {ref.ref}
              </li>
            ))}
        </ul>
      )}
      {error && (
        <p role="alert" className="mt-1 text-[11px] text-negative">
          {error}
        </p>
      )}
    </div>
  );
}

/** The checklist question about the registered address, which shows that address. */
const REGISTERED_ADDRESS_ITEM = 'address-physical';

/** The company's default registered address, beside the question asked about it. */
function RegisteredAddress({ customerId }: { customerId: string }) {
  const query = useCompanyAddresses(customerId);
  if (!query.data) return null;
  const registered = query.data.addresses.find(
    (address) => address.is_active && address.is_default && address.address_type === 'REGISTERED',
  );
  return (
    <p className="mt-1 text-caption text-ink" data-testid="registered-address">
      {registered ? addressLine(registered) : 'No registered address recorded.'}
      {query.data.registered_changed_since_clear && (
        <span className="ml-1 font-medium text-attention">Changed since last Clear</span>
      )}
    </p>
  );
}

function ChecklistCard({
  customerId,
  item,
  initialStatus,
  initialComment,
  savedEvidence,
  canRecord,
  busy,
  onSave,
}: {
  customerId: string;
  item: ScreeningCatalogueItem;
  initialStatus: ScreeningChecklistStatus;
  initialComment: string;
  savedEvidence: VerificationEvidenceRefStored[];
  canRecord: boolean;
  busy: boolean;
  onSave: (
    itemKey: string,
    status: ScreeningChecklistStatus,
    comment: string | null,
    evidenceRefs: VerificationEvidenceRef[],
  ) => Promise<boolean>;
}) {
  const [status, setStatus] = useState(initialStatus);
  const [comment, setComment] = useState(initialComment);
  const [refs, setRefs] = useState<VerificationEvidenceRef[]>([]);
  const [attaching, setAttaching] = useState(false);

  // With a stable key, adopting a newly saved value has to be explicit: when the
  // server values this card was last synced from change — its own save landing, or a
  // refetch — take them. Adjusting state during render is the documented pattern;
  // no other card is touched.
  const [syncedFrom, setSyncedFrom] = useState({
    status: initialStatus,
    comment: initialComment,
  });
  if (syncedFrom.status !== initialStatus || syncedFrom.comment !== initialComment) {
    setSyncedFrom({ status: initialStatus, comment: initialComment });
    setStatus(initialStatus);
    setComment(initialComment);
  }

  const disabled = !canRecord || busy;
  const dirty = status !== initialStatus || comment !== initialComment || refs.length > 0;

  async function save() {
    const saved = await onSave(item.key, status, comment.trim() || null, refs);
    if (saved) {
      setRefs([]);
      setAttaching(false);
    }
  }

  return (
    <div
      data-testid="screening-item"
      data-item-key={item.key}
      className="rounded-lg border border-line bg-paper px-3 py-2.5"
    >
      <p className="text-caption leading-5 text-ink-2">{item.label}</p>
      {item.key === REGISTERED_ADDRESS_ITEM && <RegisteredAddress customerId={customerId} />}
      <select
        aria-label={`${item.label} status`}
        className="mt-2 w-full rounded-md border border-line bg-surface px-2 py-1.5 text-caption text-ink outline-none focus:border-accent disabled:opacity-60"
        value={status}
        disabled={disabled}
        onChange={(event) => setStatus(event.target.value as ScreeningChecklistStatus)}
      >
        <option value="NEEDS_REVIEW">Needs review</option>
        <option value="PASSED">Passed</option>
        <option value="FAILED">Failed</option>
        <option value="EXEMPT">Exempt</option>
      </select>
      <textarea
        aria-label={`${item.label} comment`}
        className="mt-2 min-h-16 w-full resize-y rounded-md border border-line bg-surface px-2 py-1.5 text-caption text-ink outline-none focus:border-accent disabled:opacity-60"
        placeholder={canRecord ? 'Add a review comment' : undefined}
        value={comment}
        disabled={disabled}
        onChange={(event) => setComment(event.target.value)}
      />
      <EvidenceList note={null} refs={savedEvidence} />
      {canRecord && !attaching && (
        <button
          type="button"
          className="mt-2 text-[11px] font-medium text-ink hover:underline disabled:opacity-50"
          disabled={disabled}
          onClick={() => setAttaching(true)}
        >
          Attach evidence
        </button>
      )}
      {canRecord && attaching && (
        <EvidencePicker
          customerId={customerId}
          refs={refs}
          onChange={setRefs}
          disabled={disabled}
        />
      )}
      {dirty && !disabled && (
        <div className="mt-2 flex justify-end">
          <button
            type="button"
            onClick={() => void save()}
            className="rounded-md bg-accent-solid px-2.5 py-1.5 text-caption font-medium text-white"
          >
            Save
          </button>
        </div>
      )}
      <ScreeningItemHistory customerId={customerId} itemKey={item.key} label={item.label} />
    </div>
  );
}
