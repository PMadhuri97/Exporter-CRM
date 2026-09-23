import { format } from 'date-fns';
import {
  Activity,
  AlertTriangle,
  Building2,
  ChevronDown,
  ChevronUp,
  CircleDashed,
  Info,
  Landmark,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import { toast } from 'sonner';

import { ApiError } from '@/lib/api/errors';
import { useCurrentUser } from '@/platform/auth';

import {
  useBankActivity,
  useReviewVerification,
  useScreeningReview,
  useTriggerVerification,
  useUpdateScreeningReviewItem,
  useVerificationResults,
} from '../hooks';
import type {
  ScreeningChecklistStatus,
  VerificationResult,
  VerificationReviewStatus,
  VerificationType,
} from '../types';

const COMPANY_CHECK_TYPES: VerificationType[] = [
  'KYB',
  'COMPANY_REGISTRY',
  'GST',
  'IEC',
  'UBO',
  'AML',
  'CFT',
  'SANCTIONS',
  'PEP',
  'ADVERSE_MEDIA',
];

const STUB_RUN_TYPES: VerificationType[] = ['KYB', 'AML', 'SANCTIONS'];

type WorkspaceTab = 'COMPANY' | 'BANK';

interface ChecklistItem {
  id: string;
  label: string;
  section: 'Company checks' | 'Volume and activity' | 'EDD' | 'Exception';
}

const CHECKLIST_ITEMS: ChecklistItem[] = [
  { id: 'website-reviewed', section: 'Company checks', label: 'Has the website been reviewed?' },
  { id: 'address-physical', section: 'Company checks', label: 'Is the registered address a physical business address?' },
  { id: 'business-consistency', section: 'Company checks', label: 'Does the declared business activity make sense for the exporter?' },
  { id: 'payment-purpose', section: 'Volume and activity', label: 'Does expected payment and trading activity fit the business?' },
  { id: 'bank-statements-reviewed', section: 'EDD', label: 'Have bank statements / bank-linked activity been reviewed?' },
  { id: 'suspicious-bank-indicators', section: 'EDD', label: 'Were suspicious bank activity indicators investigated?' },
  { id: 'exception-approval', section: 'Exception', label: 'If an exception exists, has it been formally approved?' },
  { id: 'exception-evidence', section: 'Exception', label: 'Has supporting evidence for the exception been attached?' },
];

const CHECKLIST_SECTIONS: ChecklistItem['section'][] = [
  'Company checks',
  'Volume and activity',
  'EDD',
  'Exception',
];

function humanize(value: string): string {
  return value
    .toLowerCase()
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—';
  return format(new Date(value), 'dd MMM yyyy, HH:mm');
}

function chipClasses(value: string): string {
  // CRITICAL is a solid fill rather than another tinted pill: it has to read
  // as a different *class* of signal at a glance, not as a slightly darker
  // HIGH. Risk banding is meant to be scannable without reading the label.
  if (value === 'CRITICAL') return 'bg-red-600 text-white';
  if (['PASSED', 'LOW', 'ACCEPTED', 'CLOSED'].includes(value)) return 'bg-emerald-50 text-emerald-700';
  if (['FAILED', 'HIGH', 'REJECTED'].includes(value)) return 'bg-red-50 text-red-700';
  if (['REVIEW', 'MEDIUM', 'ESCALATED', 'NEEDS_REVIEW', 'OPEN'].includes(value)) return 'bg-amber-50 text-amber-700';
  return 'bg-surface-sunken text-ink-muted';
}

function Chip({ value }: { value: string }) {
  return <span className={`inline-flex rounded-full px-2 py-1 text-xs font-medium ${chipClasses(value)}`}>{humanize(value)}</span>;
}

/**
 * A placeholder row created by `runAvailableChecks` rather than by a provider.
 *
 * These carry `normalized_result.stub === true` and no `provider_reference`,
 * and they can never resolve: `ManualEntryAdapter.get_verification_status`
 * raises, and with no provider reference there is nothing to poll anyway. They
 * exist only to show which checks a real integration would populate.
 */
function isStubResult(result: VerificationResult): boolean {
  const normalized = result.normalized_result as { stub?: unknown } | null | undefined;
  return normalized?.stub === true && !result.provider_reference;
}

/**
 * Whether a compliance officer may record a decision on this result.
 *
 * A PENDING check has not produced a finding yet, so there is nothing to
 * accept or reject — and because the backend makes a recorded review immutable
 * by database trigger, accepting one is unrecoverable. Stub rows are PENDING
 * forever, which is the case this guard primarily exists for.
 */
function isReviewable(result: VerificationResult): boolean {
  return result.status !== 'PENDING';
}

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Render `reviewed_by` for a human.
 *
 * This field is moving from a display string to the reviewer's user id. There
 * is no endpoint that resolves a user id to a name — `/me` only ever returns
 * the caller — so a foreign id cannot be turned into a name client-side. The
 * current user's own id is resolvable without any backend change, which covers
 * the common "did I already review this?" case; anything else is labelled as
 * an unresolved id rather than dumped raw, so an officer is never shown a bare
 * UUID where a name used to be.
 *
 * Remove the UUID branch once a user-lookup endpoint exists — see this
 * ticket's report for the exact shape needed.
 */
function formatReviewer(
  value: string | null | undefined,
  currentUser: { id?: string; full_name?: string | null; email?: string },
): string {
  if (!value) return '—';
  if (currentUser.id && value === currentUser.id) {
    return `${currentUser.full_name?.trim() || currentUser.email || 'You'} (you)`;
  }
  if (UUID_PATTERN.test(value)) return `Unresolved user · ${value.slice(0, 8)}…`;
  return value;
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function ReviewChecklist({ customerId }: { customerId: string }) {
  const user = useCurrentUser();
  const query = useScreeningReview(customerId);
  const mutation = useUpdateScreeningReviewItem(customerId);
  const canReview = user.role === 'COMPLIANCE' || user.role === 'ADMIN';
  const serverItems = query.data?.items ?? [];
  const byKey = new Map(serverItems.map((item) => [item.item_key, item]));
  const completed = CHECKLIST_ITEMS.filter(
    (item) => (byKey.get(item.id)?.status ?? 'NEEDS_REVIEW') !== 'NEEDS_REVIEW',
  ).length;
  // Rows the server persisted under a key this build does not know about —
  // an older or newer checklist revision, or a key written by another client.
  // Iterating CHECKLIST_ITEMS alone would fetch these and silently drop them,
  // leaving a decision that exists in the database invisible to the officer
  // reviewing the case. Read-only: this build cannot know what they mean.
  const knownKeys = new Set(CHECKLIST_ITEMS.map((item) => item.id));
  const unrecognised = serverItems.filter((item) => !knownKeys.has(item.item_key));

  async function save(itemKey: string, status: ScreeningChecklistStatus, comment: string | null) {
    try {
      await mutation.mutateAsync({ itemKey, status, comment });
      toast.success('Review item saved');
    } catch (error) {
      toast.error(errorMessage(error, 'Could not save review item'));
    }
  }

  return (
    <aside className="rounded-lg border border-border bg-surface shadow-card">
      <div className="border-b border-border px-4 py-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="font-semibold text-ink">Review checklist</h3>
            <p className="mt-0.5 text-xs text-ink-muted">
              {completed}/{CHECKLIST_ITEMS.length} items reviewed
              {unrecognised.length > 0 && ` · ${unrecognised.length} unrecognised`}
            </p>
          </div>
          <span className="rounded-full bg-emerald-50 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-emerald-700">Persisted</span>
        </div>
        <p className="mt-3 rounded-md bg-surface-subtle px-3 py-2 text-xs leading-5 text-ink-faint">
          Decisions and comments are stored in the backend with reviewer and timestamp.
        </p>
      </div>

      <div className="max-h-[720px] space-y-4 overflow-y-auto p-4">
        {query.isLoading ? (
          <div className="h-32 animate-pulse rounded bg-surface-sunken" />
        ) : query.isError ? (
          <div className="rounded-md border border-red-200 bg-red-50 p-3 text-xs text-red-700">
            Could not load checklist. <button type="button" className="underline" onClick={() => void query.refetch()}>Retry</button>
          </div>
        ) : (
          CHECKLIST_SECTIONS.map((section) => (
            <div key={section}>
              <p className="mb-2 text-xs font-semibold text-ink">{section}</p>
              <div className="space-y-2">
                {CHECKLIST_ITEMS.filter((item) => item.section === section).map((item) => {
                  const saved = byKey.get(item.id);
                  const status = saved?.status ?? 'NEEDS_REVIEW';
                  return (
                    <ChecklistCard
                      // Stable: keying on the saved values remounted every
                      // card whenever any one of them saved, throwing away
                      // unsaved text in the others. The card reconciles
                      // server changes itself — see its body.
                      key={item.id}
                      item={item}
                      initialStatus={status}
                      initialComment={saved?.comment ?? ''}
                      disabled={!canReview || mutation.isPending}
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
            <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-amber-700">
              <AlertTriangle size={13} /> Unrecognised items
            </p>
            <p className="mb-2 text-[11px] leading-5 text-ink-muted">
              Stored against this exporter under a key this version of the checklist does not define. Shown read-only so a persisted decision is never hidden.
            </p>
            <div className="space-y-2">
              {unrecognised.map((item) => (
                <div key={item.id} className="rounded-lg border border-dashed border-amber-300 bg-amber-50/40 px-3 py-2.5">
                  <p className="break-all font-mono text-[11px] text-ink">{item.item_key}</p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-2">
                    <Chip value={item.status} />
                    <span className="text-[11px] text-ink-faint">{formatDateTime(item.reviewed_at)}</span>
                  </div>
                  {item.comment && <p className="mt-1.5 text-xs leading-5 text-ink-muted">{item.comment}</p>}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}

function ChecklistCard({
  item,
  initialStatus,
  initialComment,
  disabled,
  onSave,
}: {
  item: ChecklistItem;
  initialStatus: ScreeningChecklistStatus;
  initialComment: string;
  disabled: boolean;
  onSave: (itemKey: string, status: ScreeningChecklistStatus, comment: string | null) => Promise<void>;
}) {
  const [status, setStatus] = useState(initialStatus);
  const [comment, setComment] = useState(initialComment);

  // This card used to be remounted (via its React key) to pick up a newly
  // saved value, which also wiped every *other* card's unsaved comment. With
  // a stable key the reset has to be explicit: when the server values this
  // card was last synced from change — its own save landing, or a refetch —
  // adopt them. Adjusting state during render rather than in an effect is the
  // documented pattern for this; React re-renders immediately without
  // committing the intermediate UI, and no other card is touched.
  const [syncedFrom, setSyncedFrom] = useState({
    status: initialStatus,
    comment: initialComment,
  });
  if (syncedFrom.status !== initialStatus || syncedFrom.comment !== initialComment) {
    setSyncedFrom({ status: initialStatus, comment: initialComment });
    setStatus(initialStatus);
    setComment(initialComment);
  }

  const dirty = status !== initialStatus || comment !== initialComment;

  return (
    <div className="rounded-lg border border-border bg-surface-subtle px-3 py-2.5">
      <p className="text-xs leading-5 text-ink-muted">{item.label}</p>
      <select
        aria-label={`${item.label} status`}
        className="mt-2 w-full rounded-md border border-border bg-surface px-2 py-1.5 text-xs text-ink outline-none focus:border-brand-500 disabled:opacity-60"
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
        className="mt-2 min-h-16 w-full resize-y rounded-md border border-border bg-surface px-2 py-1.5 text-xs text-ink outline-none focus:border-brand-500 disabled:opacity-60"
        placeholder="Add review comment (optional)"
        value={comment}
        disabled={disabled}
        onChange={(event) => setComment(event.target.value)}
      />
      {dirty && !disabled && (
        <div className="mt-2 flex justify-end">
          <button
            type="button"
            onClick={() => void onSave(item.id, status, comment.trim() || null)}
            className="rounded-md bg-ink px-2.5 py-1.5 text-xs font-medium text-white"
          >
            Save
          </button>
        </div>
      )}
    </div>
  );
}

function ReviewActions({ result, customerId }: { result: VerificationResult; customerId: string }) {
  const user = useCurrentUser();
  const mutation = useReviewVerification('EXPORTER', customerId);
  const canReview = user.role === 'COMPLIANCE' || user.role === 'ADMIN';
  if (!canReview || result.review_status) return null;

  // Gated on `status`, not just `review_status`. A recorded review is made
  // immutable by a database trigger, so accepting a check that never ran is
  // unrecoverable — and stub rows sit at PENDING permanently.
  if (!isReviewable(result)) {
    return (
      <div className="mt-3 flex items-start gap-2 border-t border-border pt-3 text-xs text-ink-faint">
        <Info size={14} className="mt-0.5 shrink-0" />
        <span>
          {isStubResult(result)
            ? 'Placeholder record — no provider ran this check, so it cannot be reviewed. Connect a provider integration to enable a compliance decision.'
            : 'This check has not returned a result yet. A compliance decision can be recorded once it resolves.'}
        </span>
      </div>
    );
  }

  async function review(status: VerificationReviewStatus) {
    try {
      await mutation.mutateAsync({
        verificationResultId: result.id,
        // `reviewed_by` is deliberately not sent: the backend now derives the
        // reviewer from the authenticated session (`current_user.id`), and
        // `RecordReviewRequest` is `extra="forbid"` — sending it would be a
        // 422. The server-assigned id is what comes back on the result and is
        // rendered through `formatReviewer`.
        payload: { review_status: status },
      });
      toast.success(`Screening ${humanize(status).toLowerCase()}`);
    } catch (error) {
      toast.error(errorMessage(error, 'Could not record review'));
    }
  }

  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-3">
      <span className="mr-1 text-xs font-medium text-ink-faint">Compliance decision</span>
      {(['ACCEPTED', 'REJECTED', 'ESCALATED'] as VerificationReviewStatus[]).map((status) => (
        <button key={status} type="button" disabled={mutation.isPending} onClick={() => void review(status)} className="rounded-lg border border-border px-2.5 py-1.5 text-xs font-medium text-ink-muted hover:bg-surface-subtle disabled:opacity-50">
          {humanize(status)}
        </button>
      ))}
    </div>
  );
}

function ScreeningRow({ result, customerId }: { result: VerificationResult; customerId: string }) {
  const user = useCurrentUser();
  const [expanded, setExpanded] = useState(false);
  const normalized = useMemo(() => JSON.stringify(result.normalized_result, null, 2), [result.normalized_result]);
  const stub = isStubResult(result);
  return (
    <div className={`border-b border-border py-4 last:border-b-0 ${stub ? 'opacity-70' : ''}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-ink">{humanize(result.verification_type)}</span>
            {stub ? (
              // Deliberately not the neutral PENDING chip a real in-flight
              // check gets: a placeholder and a check that is genuinely
              // running are different things and must not look alike.
              <span className="inline-flex items-center gap-1 rounded-full border border-dashed border-border-strong bg-surface-sunken px-2 py-1 text-xs font-medium text-ink-faint">
                <CircleDashed size={12} /> Not run
              </span>
            ) : (
              <Chip value={result.status} />
            )}
            {result.risk_level && <Chip value={result.risk_level} />}
            {result.review_status && <Chip value={result.review_status} />}
          </div>
          <p className="mt-1 text-xs text-ink-faint">
            {stub ? 'Placeholder · no provider integration' : `Source: ${result.provider}`} · {formatDateTime(result.performed_at)}
          </p>
        </div>
        <button type="button" onClick={() => setExpanded((value) => !value)} className="inline-flex items-center gap-1 text-xs font-medium text-ink-muted hover:text-ink">
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          {expanded ? 'Hide details' : 'View details'}
        </button>
      </div>
      {expanded && (
        <div className="mt-3 grid gap-3 rounded-lg bg-surface-subtle p-3 text-xs md:grid-cols-2">
          <div><span className="text-ink-faint">Provider reference</span><p className="mt-0.5 break-all text-ink">{result.provider_reference ?? '—'}</p></div>
          <div><span className="text-ink-faint">Valid until</span><p className="mt-0.5 text-ink">{formatDateTime(result.valid_until)}</p></div>
          <div><span className="text-ink-faint">Evidence reference</span><p className="mt-0.5 break-all text-ink">{result.evidence_reference ?? '—'}</p></div>
          <div><span className="text-ink-faint">Reviewed by</span><p className="mt-0.5 break-all text-ink">{formatReviewer(result.reviewed_by, user)}</p></div>
          <div className="md:col-span-2"><span className="text-ink-faint">Provider result</span><pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded border border-border bg-surface p-3 text-[11px] leading-5 text-ink">{normalized}</pre></div>
        </div>
      )}
      <ReviewActions result={result} customerId={customerId} />
    </div>
  );
}

/**
 * The company check types the tab advertises but nothing in the product can
 * currently produce.
 *
 * `COMPANY_CHECK_TYPES` is what the Company tab is scoped to; `STUB_RUN_TYPES`
 * is the subset the dev placeholder generator knows how to create. Everything
 * in the difference has no route to existence at all — no provider is wired
 * up for it. Listing them is the honest alternative to a tab that silently
 * shows nothing where a check was expected.
 */
function UnavailableChecks({ results }: { results: VerificationResult[] }) {
  const present = new Set(results.map((result) => result.verification_type));
  const unavailable = COMPANY_CHECK_TYPES.filter(
    (type) => !present.has(type) && !STUB_RUN_TYPES.includes(type),
  );
  if (unavailable.length === 0) return null;

  return (
    <div className="mt-4 rounded-lg border border-dashed border-border-strong bg-surface-subtle px-4 py-3">
      <div className="flex items-start gap-2">
        <Info size={14} className="mt-0.5 shrink-0 text-ink-faint" />
        <div className="min-w-0">
          <p className="text-xs font-medium text-ink">
            {unavailable.length} check {unavailable.length === 1 ? 'type has' : 'types have'} no provider integration
          </p>
          <p className="mt-0.5 text-xs leading-5 text-ink-muted">
            These are part of the company screening set but cannot be run today — nothing in the product creates them. They will populate once a provider is connected.
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {unavailable.map((type) => (
              <span key={type} className="inline-flex rounded-full border border-border bg-surface px-2 py-0.5 text-[11px] font-medium text-ink-faint">
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
      <p className="mx-auto mt-1 max-w-md text-xs leading-5 text-ink-muted">No provider integration is connected, so no company screening has run for this exporter yet. Results will appear here once a provider is configured.</p>
    </div>
  );
}

function BankActivityPanel({ customerId }: { customerId: string }) {
  const query = useBankActivity(customerId);
  const data = query.data;
  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-border bg-surface-subtle p-4">
        <div className="flex items-start gap-3">
          <div className="rounded-lg bg-surface p-2 text-brand-600 shadow-sm"><Landmark size={18} /></div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-semibold text-ink">Bank-linked activity</h3>
              <span className="rounded-full bg-blue-50 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-blue-700">E9 contract ready</span>
            </div>
            <p className="mt-1 text-sm leading-6 text-ink-muted">Surepass / Finpass-style suspicious-activity findings now have a persisted backend contract. Until a provider feed is connected, the API returns a valid empty state rather than fake alerts.</p>
          </div>
        </div>
      </div>

      {query.isLoading ? (
        <div className="h-24 animate-pulse rounded bg-surface-sunken" />
      ) : query.isError ? (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">Could not load bank activity. <button type="button" className="underline" onClick={() => void query.refetch()}>Retry</button></div>
      ) : (
        <>
          <div className="grid gap-3 md:grid-cols-3">
            {[
              ['Connected accounts', String(data?.connected_accounts ?? 0)],
              ['Last bank sync', formatDateTime(data?.last_synced_at)],
              ['Open suspicious activity flags', String(data?.open_findings ?? 0)],
            ].map(([label, value]) => (
              <div key={label} className="rounded-lg border border-border p-4"><p className="text-xs text-ink-faint">{label}</p><p className="mt-1 text-lg font-semibold text-ink">{value}</p></div>
            ))}
          </div>
          {(data?.findings.length ?? 0) === 0 ? (
            <div className="rounded-lg border border-dashed border-border-strong px-4 py-8 text-center">
              <p className="text-sm font-medium text-ink">No bank activity findings</p>
              <p className="mt-1 text-xs text-ink-muted">No provider feed has reported suspicious activity for this exporter.</p>
            </div>
          ) : (
            <div className="rounded-lg border border-border px-4">
              {data!.findings.map((finding) => (
                <div key={finding.id} className="border-b border-border py-4 last:border-0">
                  <div className="flex flex-wrap items-center gap-2"><span className="font-medium text-ink">{finding.title}</span><Chip value={finding.risk_level} /><Chip value={finding.status} /></div>
                  <p className="mt-1 text-xs text-ink-faint">{finding.provider} · {humanize(finding.finding_type)} · {formatDateTime(finding.detected_at)}</p>
                  {finding.description && <p className="mt-2 text-sm text-ink-muted">{finding.description}</p>}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

export function VerificationSection({ customerId }: { customerId: string }) {
  const user = useCurrentUser();
  // Triggering a verification is compliance-only on the backend (403 otherwise).
  const canTrigger = user.role === 'COMPLIANCE' || user.role === 'ADMIN';
  const query = useVerificationResults('EXPORTER', customerId);
  const triggerMutation = useTriggerVerification('EXPORTER', customerId);
  const [tab, setTab] = useState<WorkspaceTab>('COMPANY');
  const results = query.data?.results ?? [];
  const companyResults = results.filter((result) => result.verification_type !== 'BANK_ACCOUNT' && COMPANY_CHECK_TYPES.includes(result.verification_type));

  async function runAvailableChecks() {
    const existingTypes = new Set(results.map((result) => result.verification_type));
    const checksToCreate = STUB_RUN_TYPES.filter((verificationType) => !existingTypes.has(verificationType));
    if (checksToCreate.length === 0) {
      toast.info('Available company checks already have screening records');
      return;
    }
    try {
      for (const verificationType of checksToCreate) {
        await triggerMutation.mutateAsync({
          verification_type: verificationType,
          provider: 'manual',
          payload: {
            status: 'PENDING',
            normalized_result: { stub: true, message: 'Provider integration not configured. Pending record created by the screening workspace.' },
          },
        });
      }
      toast.success(`${checksToCreate.length} pending screening ${checksToCreate.length === 1 ? 'record' : 'records'} created`);
    } catch (error) {
      toast.error(errorMessage(error, 'Could not initialize screening checks'));
    }
  }

  return (
    <section data-extension="screenings" className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="min-w-0 rounded-lg border border-border bg-surface p-5 shadow-card">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div><div className="flex items-center gap-2"><ShieldCheck size={18} className="text-brand-600" /><h2 className="font-semibold text-ink">Screenings</h2></div><p className="mt-1 text-sm text-ink-muted">Provider results, bank-monitoring signals and compliance review for this exporter.</p></div>
          {/* TASK: this control creates rows that are terminal at PENDING
              forever — no provider runs, and they can never resolve. It is
              therefore dev-only and labelled as a placeholder generator, so it
              cannot be mistaken for working screening in a demo. Triggering is
              also COMPLIANCE/ADMIN-only on the backend (403 otherwise). */}
          {import.meta.env.DEV && canTrigger && (
            <button
              type="button"
              disabled={triggerMutation.isPending}
              onClick={() => void runAvailableChecks()}
              title="Developer tool: inserts placeholder PENDING rows. No provider is contacted."
              className="inline-flex items-center gap-1.5 rounded-lg border border-dashed border-border-strong bg-surface-subtle px-3 py-2 text-sm font-medium text-ink-muted hover:bg-surface-sunken disabled:cursor-not-allowed disabled:opacity-50"
            >
              {triggerMutation.isPending ? <RefreshCw size={15} className="animate-spin" /> : <CircleDashed size={15} />}
              {triggerMutation.isPending ? 'Creating placeholders…' : 'Create placeholder records (dev)'}
            </button>
          )}
        </div>

        <div className="mt-4 flex gap-6 border-b border-border">
          <button type="button" onClick={() => setTab('COMPANY')} className={`flex items-center gap-2 border-b-2 px-1 pb-3 text-sm font-medium ${tab === 'COMPANY' ? 'border-brand-500 text-brand-600' : 'border-transparent text-ink-muted hover:text-ink'}`}><Building2 size={15} /> Company screenings <span className="text-xs text-ink-faint">({companyResults.length})</span></button>
          <button type="button" onClick={() => setTab('BANK')} className={`flex items-center gap-2 border-b-2 px-1 pb-3 text-sm font-medium ${tab === 'BANK' ? 'border-brand-500 text-brand-600' : 'border-transparent text-ink-muted hover:text-ink'}`}><Activity size={15} /> Bank activity</button>
        </div>

        <div className="mt-4">
          {tab === 'BANK' ? (
            <BankActivityPanel customerId={customerId} />
          ) : query.isLoading ? (
            <div className="space-y-3"><div className="h-20 animate-pulse rounded bg-surface-sunken" /><div className="h-20 animate-pulse rounded bg-surface-sunken" /></div>
          ) : query.isError ? (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"><div className="flex items-start gap-2"><AlertTriangle size={16} className="mt-0.5 shrink-0" /><div>Could not load screening results. <button type="button" onClick={() => void query.refetch()} className="font-medium underline">Retry</button></div></div></div>
          ) : (
            <>
              {companyResults.length === 0 ? (
                <EmptyScreenings />
              ) : (
                <div className="rounded-lg border border-border px-4">{companyResults.map((result) => <ScreeningRow key={result.id} result={result} customerId={customerId} />)}</div>
              )}
              <UnavailableChecks results={results} />
            </>
          )}
        </div>
      </div>
      <ReviewChecklist customerId={customerId} />
    </section>
  );
}
