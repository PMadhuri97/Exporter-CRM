/**
 * One deal: its stage, its buyer, its paperwork and its history — **owner:
 * Developer 3B** (L3-11b).
 *
 * **The stage moves this page offers come from the server.** `allowed_stage_moves`
 * is what *this* deal may do next for *this* user (§7.5, deal contract §4.1), so
 * there is no copy of the stage graph in here and an illegal move is not offerable
 * rather than rejected after a click.
 *
 * **A blocked handover is explained, not offered.** When the A5 guard is unmet the
 * move is absent from that list and `handover_blocked_reason` says why — until
 * Developer 4's background check exists, always. Showing the reason beats a
 * button that returns 409.
 */

import { Handshake, Upload } from 'lucide-react';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { toast } from 'sonner';

import {
  Button,
  ConfirmDialog,
  DetailRow,
  EmptySection,
  ErrorState,
  Field,
  FormPanel,
  Input,
  PageHeader,
  Panel,
  Skeleton,
  Textarea,
} from '@/components';
import { formatDateTime, humanize } from '@/lib/format';
import { isAdminRole, isStaffRole, useCurrentUser } from '@/platform/auth';
import { canReveal } from '@/platform/mask';

import {
  BuyerChecks,
  DealHistory,
  DealStageChip,
  DocumentList,
  DocumentUpload,
} from '../components';
import {
  useDeal,
  useDealDocuments,
  useExporterProfileDetail,
  useSetDealBuyer,
  useTransitionDealStage,
  useUploadDealDocument,
} from '../hooks';
import { paths } from '../paths';
import type { DealStage, SetDealBuyerRequest } from '../types';

const STAGE_ACTION_LABEL: Record<DealStage, string> = {
  OPEN: 'Reopen',
  GATHERING_PAPERWORK: 'Start gathering paperwork',
  HANDED_OVER: 'Hand over to lending',
  WITHDRAWN: 'Withdraw',
};

/** The buyer fields the server masks for OPERATIONS and DEVELOPER. */
const MASKED_BUYER_FIELDS = ['registration_number', 'tax_id', 'contact_email', 'contact_phone'] as const;
type MaskedBuyerField = (typeof MASKED_BUYER_FIELDS)[number];

function BuyerForm({
  dealId,
  customerId,
  initial,
  revealIdentifiers,
  onClose,
}: {
  dealId: string;
  customerId?: string;
  initial: SetDealBuyerRequest | null;
  /** COMPLIANCE and ADMIN receive the buyer in full; every other role receives
   * the masked fields masked. */
  revealIdentifiers: boolean;
  onClose: () => void;
}) {
  const mutation = useSetDealBuyer(dealId, customerId);
  // A role that sees masked values starts those fields empty rather than holding
  // bullets it could send back (the server refuses them). Left empty they are
  // left out of the request, which keeps the stored value; typed, they replace it.
  const [form, setForm] = useState<SetDealBuyerRequest>(() => {
    const start = initial ?? { name: '', country: '' };
    if (revealIdentifiers || initial === null) return start;
    const cleared = { ...start };
    for (const key of MASKED_BUYER_FIELDS) cleared[key] = null;
    return cleared;
  });
  const hidden = (key: keyof SetDealBuyerRequest): key is MaskedBuyerField =>
    !revealIdentifiers && initial !== null && (MASKED_BUYER_FIELDS as readonly string[]).includes(key);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const request: SetDealBuyerRequest = {
      ...form,
      name: form.name.trim(),
      country: form.country.trim().toUpperCase(),
    };
    for (const key of MASKED_BUYER_FIELDS) {
      if (hidden(key) && !form[key]?.trim()) delete request[key];
    }
    try {
      await mutation.mutateAsync(request);
      toast.success('Buyer saved');
      onClose();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not save the buyer');
    }
  }

  const field = (key: keyof SetDealBuyerRequest, label: string, required = false) => (
    <Field label={label} htmlFor={`buyer-${key}`} required={required}>
      <Input
        id={`buyer-${key}`}
        type="text"
        required={required}
        placeholder={hidden(key) ? 'Hidden — type to replace' : undefined}
        value={(form[key] as string | null) ?? ''}
        onChange={(event) => setForm({ ...form, [key]: event.target.value })}
      />
    </Field>
  );

  return (
    <FormPanel title={initial ? 'Edit buyer' : 'Add buyer'} onClose={onClose}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <div className="grid gap-3 sm:grid-cols-2">
          {field('name', 'Buyer name', true)}
          {field('country', 'Country (ISO code)', true)}
          {field('registration_number', 'Registration number')}
          {field('tax_id', 'Tax identifier')}
          {field('contact_email', 'Contact email')}
          {field('contact_phone', 'Contact phone')}
        </div>
        <p className="text-xs text-ink-faint">
          One buyer per deal. Saving replaces the details rather than adding a second
          buyer — a handover names one buyer, so two would be ambiguous.
        </p>
        <div className="flex justify-end">
          <Button
            type="submit"
            variant="primary"
            disabled={form.name.trim() === '' || form.country.trim().length !== 2}
            loading={mutation.isPending}
          >
            Save buyer
          </Button>
        </div>
      </form>
    </FormPanel>
  );
}

/** What the handover snapshot's `snapshot_source` means, in words. */
const SNAPSHOT_SOURCE_LABEL: Record<string, string> = {
  taken_at_handover: 'Recorded at the moment of the handover.',
  backfilled_from_deal_buyer:
    'Reconstructed from the records that existed: this deal was handed over before snapshots were kept.',
};

/**
 * What the lending team was given (plan P2-7).
 *
 * Read-only, always: the snapshot is set once and the database refuses to change
 * it, so there is nothing to offer here but the record. The buyer's identifiers
 * arrive already masked for the roles that may not see them — the server masks,
 * never the browser.
 */
function HandoverSnapshot({ snapshot }: { snapshot: Record<string, unknown> }) {
  const buyer = (snapshot.buyer ?? null) as Record<string, string | null> | null;
  // `null` in a backfilled snapshot means no record of the paperwork survived —
  // "not recorded", which must not read as "none".
  const documentIds = Array.isArray(snapshot.document_ids) ? snapshot.document_ids : null;
  const source = typeof snapshot.snapshot_source === 'string' ? snapshot.snapshot_source : '';

  return (
    <Panel
      title="What was handed over"
      description="The buyer and the paperwork as they stood when this deal went to the lending team. This record does not change."
    >
      {buyer ? (
        <dl className="grid gap-x-8 sm:grid-cols-2">
          <DetailRow label="Buyer">{buyer.name ?? '—'}</DetailRow>
          <DetailRow label="Country">{buyer.country ?? '—'}</DetailRow>
          <DetailRow label="Registration number">{buyer.registration_number ?? '—'}</DetailRow>
          <DetailRow label="Tax identifier">{buyer.tax_id ?? '—'}</DetailRow>
          <DetailRow label="Contact email">{buyer.contact_email ?? '—'}</DetailRow>
          <DetailRow label="Contact phone">{buyer.contact_phone ?? '—'}</DetailRow>
        </dl>
      ) : (
        <EmptySection>
          This handover's buyer is no longer on record. The snapshot was reconstructed
          after the fact and the buyer row had already gone.
        </EmptySection>
      )}
      <p className="mt-3 text-xs text-ink-muted">
        {documentIds === null
          ? 'Which documents were included was not recorded.'
          : documentIds.length === 1
            ? '1 document was included.'
            : `${documentIds.length} documents were included.`}{' '}
        <span className="text-ink-faint">{SNAPSHOT_SOURCE_LABEL[source] ?? ''}</span>
      </p>
    </Panel>
  );
}

function StageMoves({
  dealId,
  customerId,
  moves,
  blockedReason,
}: {
  dealId: string;
  customerId?: string;
  moves: { to_stage: DealStage; reason_required: boolean }[];
  blockedReason: string | null;
}) {
  const mutation = useTransitionDealStage(dealId, customerId);
  const [pending, setPending] = useState<DealStage | null>(null);
  const [reason, setReason] = useState('');
  // `HANDED_OVER` is terminal and announces the deal to the lending team, so it
  // is the one move worth a confirmation. A withdrawal already asks for a reason,
  // which is its own deliberate step.
  const [confirmingHandover, setConfirmingHandover] = useState(false);

  async function move(toStage: DealStage, withReason?: string) {
    try {
      await mutation.mutateAsync({
        to_stage: toStage,
        ...(withReason ? { reason: withReason } : {}),
      });
      toast.success(`Deal moved to ${humanize(toStage).toLowerCase()}`);
      setPending(null);
      setReason('');
      setConfirmingHandover(false);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not move the deal');
    }
  }

  const choose = (entry: { to_stage: DealStage; reason_required: boolean }) => {
    if (entry.to_stage === 'HANDED_OVER') setConfirmingHandover(true);
    else if (entry.reason_required) setPending(entry.to_stage);
    else void move(entry.to_stage);
  };

  return (
    <div className="flex flex-col gap-3">
      {moves.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {moves.map((entry) => (
            <Button
              key={entry.to_stage}
              size="sm"
              variant={
                entry.to_stage === 'HANDED_OVER'
                  ? 'primary'
                  : entry.to_stage === 'WITHDRAWN'
                    ? 'ghost'
                    : 'secondary'
              }
              onClick={() => choose(entry)}
              disabled={mutation.isPending}
            >
              {STAGE_ACTION_LABEL[entry.to_stage]}
            </Button>
          ))}
        </div>
      )}

      {/* A move that needs a reason asks for it before submitting, rather than
          showing a 422 afterwards. */}
      {pending !== null && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void move(pending, reason.trim());
          }}
          className="flex flex-col gap-2 rounded-lg border border-border bg-surface-subtle p-3"
        >
          <label htmlFor="stage-reason" className="text-xs font-medium text-ink-muted">
            Why is this deal being withdrawn?
          </label>
          <Textarea
            id="stage-reason"
            value={reason}
            rows={2}
            required
            onChange={(event) => setReason(event.target.value)}
          />
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="ghost" onClick={() => setPending(null)}>
              Cancel
            </Button>
            <Button
              type="submit"
              size="sm"
              variant="danger"
              disabled={reason.trim() === ''}
              loading={mutation.isPending}
            >
              Withdraw deal
            </Button>
          </div>
        </form>
      )}

      {blockedReason !== null && (
        <p className="rounded-lg border border-status-review/30 bg-status-review/10 px-3 py-2 text-sm text-ink">
          <span className="font-medium">Not ready to hand over:</span>{' '}
          <span className="text-ink-muted">{blockedReason}</span>
        </p>
      )}

      <ConfirmDialog
        open={confirmingHandover}
        onOpenChange={setConfirmingHandover}
        title="Hand this deal to the lending team?"
        description="This cannot be undone. The deal and its documents are announced to them as they stand now."
        confirmLabel="Hand over"
        onConfirm={() => void move('HANDED_OVER')}
        loading={mutation.isPending}
      />
    </div>
  );
}

export function DealDetailPage() {
  const { dealId } = useParams<{ dealId: string }>();
  const user = useCurrentUser();
  const isStaff = isStaffRole(user.role);

  const { data: deal, isLoading, isError, refetch } = useDeal(dealId);
  const company = useExporterProfileDetail(deal?.company_id);
  // A handed-over deal's paperwork is what the lending team was given, and a
  // withdrawn deal's is history: the server refuses both an upload and a buyer edit
  // on a terminal deal, so neither control is offered.
  const isClosed = deal?.stage === 'HANDED_OVER' || deal?.stage === 'WITHDRAWN';
  const documents = useDealDocuments(dealId);
  const upload = useUploadDealDocument(dealId ?? '');
  const [editingBuyer, setEditingBuyer] = useState(false);
  const [uploading, setUploading] = useState(false);

  if (isLoading) {
    return (
      <div className="space-y-5">
        <Skeleton className="h-8 w-72" />
        <Skeleton className="h-40 rounded-lg" />
      </div>
    );
  }
  if (isError || deal === undefined) {
    return <ErrorState title="Could not load that deal." onRetry={() => void refetch()} />;
  }

  const companyName = company.data?.name;

  return (
    <div>
      <PageHeader
        back={{
          to: paths.company(deal.company_id, 'deals'),
          label: companyName ? `${companyName} · Deals` : 'Back to the company',
        }}
        title={
          <span className="inline-flex items-center gap-2">
            <Handshake size={18} className="text-ink-faint" />
            {deal.reference}
          </span>
        }
        meta={<DealStageChip stage={deal.stage} />}
        description={`Opened ${formatDateTime(deal.created_at)}`}
      />

      <div className="grid gap-5 xl:grid-cols-[1.4fr_1fr]">
        <div className="space-y-5">
          <Panel title="Stage" description="Where this deal is, and where it may go next.">
            {(deal.handed_over_at || deal.withdrawal_reason) && (
              <dl className="mb-3">
                {deal.handed_over_at && (
                  <DetailRow label="Handed over at">{formatDateTime(deal.handed_over_at)}</DetailRow>
                )}
                {deal.withdrawal_reason && (
                  <DetailRow label="Withdrawn because">{deal.withdrawal_reason}</DetailRow>
                )}
              </dl>
            )}
            {isStaff ? (
              <StageMoves
                dealId={deal.id}
                customerId={deal.company_id}
                moves={deal.allowed_stage_moves}
                blockedReason={deal.handover_blocked_reason}
              />
            ) : (
              <p className="text-sm text-ink-muted">Stage changes are made by staff.</p>
            )}
            {isStaff && deal.allowed_stage_moves.length === 0 && deal.handover_blocked_reason === null && (
              <p className="text-sm text-ink-muted">This deal is closed; its stage no longer moves.</p>
            )}
          </Panel>

          <Panel
            title="Buyer"
            description="Who this company is selling to. Checks about a buyer are recorded against the buyer, never against the company."
            actions={
              isStaff &&
              !editingBuyer &&
              !isClosed && (
                <Button size="sm" onClick={() => setEditingBuyer(true)}>
                  {deal.buyer ? 'Edit buyer' : 'Add buyer'}
                </Button>
              )
            }
          >
            {editingBuyer && (
              <BuyerForm
                dealId={deal.id}
                customerId={deal.company_id}
                initial={
                  deal.buyer
                    ? {
                        name: deal.buyer.name,
                        country: deal.buyer.country,
                        registration_number: deal.buyer.registration_number,
                        tax_id: deal.buyer.tax_id,
                        contact_email: deal.buyer.contact_email,
                        contact_phone: deal.buyer.contact_phone,
                      }
                    : null
                }
                revealIdentifiers={canReveal(user.role)}
                onClose={() => setEditingBuyer(false)}
              />
            )}

            {/* The buyer as a company record, once one is recorded (P4-4). It is
                the authority when both it and the legacy row are present, so it
                reads first. `null` on every deal until the buyer migration. */}
            {deal.buyer_company && (
              <dl className="mb-3 grid gap-x-8 border-b border-border pb-3 sm:grid-cols-2">
                <DetailRow label="Buyer company">
                  <Link
                    to={paths.company(deal.buyer_company.company_id)}
                    className="font-medium text-brand-600 hover:underline"
                  >
                    {deal.buyer_company.name ?? 'Unnamed company'}
                  </Link>
                </DetailRow>
                <DetailRow label="Country">{deal.buyer_company.country ?? '—'}</DetailRow>
                <DetailRow label="PAN">{deal.buyer_company.pan ?? '—'}</DetailRow>
                <DetailRow label="CIN">{deal.buyer_company.cin ?? '—'}</DetailRow>
              </dl>
            )}

            {deal.buyer ? (
              <dl className="grid gap-x-8 sm:grid-cols-2">
                <DetailRow label="Name">{deal.buyer.name}</DetailRow>
                <DetailRow label="Country">{deal.buyer.country}</DetailRow>
                <DetailRow label="Registration number">{deal.buyer.registration_number ?? '—'}</DetailRow>
                <DetailRow label="Tax identifier">{deal.buyer.tax_id ?? '—'}</DetailRow>
                <DetailRow label="Contact email">{deal.buyer.contact_email ?? '—'}</DetailRow>
                <DetailRow label="Contact phone">{deal.buyer.contact_phone ?? '—'}</DetailRow>
              </dl>
            ) : (
              !editingBuyer &&
              !deal.buyer_company && (
                <EmptySection>No buyer recorded yet. A deal cannot be handed over without one.</EmptySection>
              )
            )}
          </Panel>

          {/* What the lending team was given (P2-7). Shown only once it exists,
              which is only on a handed-over deal: a snapshot is a record of an
              event, so there is nothing to show before the event. */}
          {deal.handover_snapshot && <HandoverSnapshot snapshot={deal.handover_snapshot} />}

          {/* Checks on the buyer (decision 9: they attach to the buyer, never the
              company). Staff only: DEVELOPER is refused the verification routes (D8).
              Whether recording is offered is the server's `capabilities` — closed on
              a HANDED_OVER or WITHDRAWN deal (D17). */}
          {isStaff && deal.buyer && <BuyerChecks dealId={deal.id} dealBuyerId={deal.buyer.id} />}

          <Panel
            title="Paperwork"
            description="Documents for this deal. These are the ones a handover tells the lending team about."
            actions={
              isStaff &&
              !isClosed &&
              !uploading && (
                <Button size="sm" onClick={() => setUploading(true)}>
                  <Upload size={14} />
                  Upload a document
                </Button>
              )
            }
          >
            {uploading && (
              <FormPanel title="Upload a document" onClose={() => setUploading(false)}>
                <DocumentUpload
                  owner="DEAL"
                  isUploading={upload.isPending}
                  onUpload={(input) => upload.mutateAsync(input)}
                  onDone={() => setUploading(false)}
                />
              </FormPanel>
            )}

            {isClosed && (
              <p className="mb-3 rounded-lg border border-border bg-surface-subtle px-3 py-2 text-xs text-ink-muted">
                {deal.stage === 'HANDED_OVER'
                  ? 'This deal has been handed over. Its paperwork is what the lending team was given, so nothing more can be added.'
                  : 'This deal was withdrawn. Its paperwork is kept as a record and nothing more can be added.'}
              </p>
            )}

            {/* Where the handover's paperwork rule lives, for the one role that
                can change it. The rule itself is served with the refusal reason,
                so everyone else already sees *what* is missing; only an
                administrator has anywhere to go from here. */}
            {isAdminRole(user.role) && !isClosed && (
              <p className="mb-3 text-xs text-ink-faint">
                Which categories a handover needs is set in{' '}
                <Link
                  to={paths.dealRequiredDocuments}
                  className="text-brand-600 hover:underline"
                >
                  Required documents
                </Link>
                .
              </p>
            )}
            <DocumentList
              documents={documents.data?.documents ?? []}
              isLoading={documents.isLoading}
              emptyMessage="No documents on this deal yet."
            />
          </Panel>
        </div>

        <Panel title="History" description="Every change to this deal, newest first.">
          <DealHistory dealId={deal.id} />
        </Panel>
      </div>
    </div>
  );
}
