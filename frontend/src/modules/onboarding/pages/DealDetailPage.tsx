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

import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { toast } from 'sonner';

import {
  Button,
  ConfirmDialog,
  DetailRow,
  EmptyLine,
  ErrorState,
  Field,
  FormPanel,
  Input,
  Panel,
  Skeleton,
  Textarea,
} from '@/components';
import { Icon } from '@/design/icons';
import { formatDateTime, humanize } from '@/lib/format';
import { useCan } from '@/platform/access';
import { useCrumbs } from '@/platform/shell';

import {
  BuyerChecks,
  CompanyPicker,
  DealHistory,
  InvoicingBranchPicker,
  PartyCard,
  Preflight,
  RecordDealOutcomeForm,
  Shelf,
  StageRoute,
  TradeHistoryPanel,
} from '../components';
import {
  useDeal,
  useDealDocuments,
  useDealRequiredDocuments,
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

/**
 * `SetDealBuyerRequest`'s legacy form. The generated type is one shape for both forms,
 * so every field in it is optional; in this form `name` and `country` are required
 * together, and `buyer_company_id` belongs to the other form.
 */
type LegacyBuyerRequest = Omit<SetDealBuyerRequest, 'buyer_company_id' | 'name' | 'country'> & {
  name: string;
  country: string;
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
  initial: LegacyBuyerRequest | null;
  /** COMPLIANCE and ADMIN receive the buyer in full; every other role receives
   * the masked fields masked. */
  revealIdentifiers: boolean;
  onClose: () => void;
}) {
  const mutation = useSetDealBuyer(dealId, customerId);
  // A role that sees masked values starts those fields empty rather than holding
  // bullets it could send back (the server refuses them). Left empty they are
  // left out of the request, which keeps the stored value; typed, they replace it.
  const [form, setForm] = useState<LegacyBuyerRequest>(() => {
    const start = initial ?? { name: '', country: '' };
    if (revealIdentifiers || initial === null) return start;
    const cleared = { ...start };
    for (const key of MASKED_BUYER_FIELDS) cleared[key] = null;
    return cleared;
  });
  const hidden = (key: keyof LegacyBuyerRequest): key is MaskedBuyerField =>
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

  const field = (key: keyof LegacyBuyerRequest, label: string, required = false) => (
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
        <p className="text-xs text-ink-3">
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
      className="rounded-xl border-[3px] border-double border-line-strong bg-surface p-5"
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
        <EmptyLine>
          This handover's buyer is no longer on record. The snapshot was reconstructed
          after the fact and the buyer row had already gone.
        </EmptyLine>
      )}
      <p className="mt-3 text-xs text-ink-2">
        {documentIds === null
          ? 'Which documents were included was not recorded.'
          : documentIds.length === 1
            ? '1 document was included.'
            : `${documentIds.length} documents were included.`}{' '}
        <span className="text-ink-3">{SNAPSHOT_SOURCE_LABEL[source] ?? ''}</span>
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
                    ? 'quiet'
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
          className="flex flex-col gap-2 rounded-lg border border-line bg-paper p-3"
        >
          <label htmlFor="stage-reason" className="text-xs font-medium text-ink-2">
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
            <Button size="sm" variant="quiet" onClick={() => setPending(null)}>
              Cancel
            </Button>
            <Button
              type="submit"
              size="sm"
              variant="destructive"
              disabled={reason.trim() === ''}
              loading={mutation.isPending}
            >
              Withdraw deal
            </Button>
          </div>
        </form>
      )}

      {/* The guard's verdict, verbatim (frontend-plan §6.4); a checklist once A3 lands. */}
      <Preflight blockedReason={blockedReason} />

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
  const isStaff = useCan('crm.write');
  const canReveal = useCan('identifiers.reveal');
  const canSetRequiredDocuments = useCan('settings.requiredDocuments');

  const { data: deal, isLoading, isError, refetch } = useDeal(dealId);
  const company = useExporterProfileDetail(deal?.company_id);
  // A handed-over deal's paperwork is what the lending team was given, and a
  // withdrawn deal's is history: the server refuses both an upload and a buyer edit
  // on a terminal deal, so neither control is offered.
  const isClosed = deal?.stage === 'HANDED_OVER' || deal?.stage === 'WITHDRAWN';
  const documents = useDealDocuments(dealId);
  // Which paperwork a handover needs, to mark it on the shelf (readable by every reader).
  const requiredDocuments = useDealRequiredDocuments();
  const upload = useUploadDealDocument(dealId ?? '');
  const [editingBuyer, setEditingBuyer] = useState(false);
  const [pickingCompany, setPickingCompany] = useState(false);
  // Task 2.4's write: the same `PUT /deals/{id}/buyer` route, in its company form.
  const setBuyerCompany = useSetDealBuyer(dealId ?? '', deal?.company_id);
  // P5-6's write. Separate state because it is a different question from the deal's
  // own: the deal is finished, and this is about what happened to the money.
  const [recordingOutcome, setRecordingOutcome] = useState(false);

  // The trail (R-33 Phase 2): Companies / the seller / its deals / this deal.
  const seller = company.data?.name;
  useCrumbs([
    { label: 'Companies', to: paths.companies },
    ...(deal && seller ? [{ label: seller, to: paths.company(deal.company_id, 'deals') }] : []),
    ...(deal ? [{ label: deal.reference ?? 'Deal' }] : []),
  ]);

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
    <div className="grid gap-10 2xl:grid-cols-[minmax(0,1fr)_24rem]">
      <div className="min-w-0 max-w-reading space-y-8">
        <header>
          <h1 className="font-display text-display-lg text-ink">{deal.reference}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2">
            <StageRoute stage={deal.stage} />
            <span className="text-secondary text-ink-3">Opened {formatDateTime(deal.created_at)}</span>
          </div>
        </header>

        <Panel title="Stage" description="Where this deal may go next — only the moves the server offers.">
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
          {/* Staff see the moves and, when the guard says no, why (the pre-flight). A
              read-only role is given no moves and no reason (D8), so the record reads
              as a record, with no line saying what it cannot do. */}
          {isStaff && (
            <StageMoves
              dealId={deal.id}
              customerId={deal.company_id}
              moves={deal.allowed_stage_moves}
              blockedReason={deal.handover_blocked_reason}
            />
          )}
          {isStaff && deal.allowed_stage_moves.length === 0 && deal.handover_blocked_reason === null && (
            <p className="text-body text-ink-2">This deal is closed; its stage no longer moves.</p>
          )}
        </Panel>

        {/* The two parties, side by side — a problem stays with the party it belongs
            to (architecture). The guard reads the seller's background check and the
            buyer's sanctions and AML (decision BQ-4), and each card shows its own. */}
        <Panel title="Parties" description="Who is selling, and who is buying. A buyer is a company record of its own; its checks are recorded against it and read back from it.">
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] lg:items-start">
            <PartyCard
              role="Seller company"
              companyId={deal.company_id}
              name={companyName ?? 'The seller'}
              country={company.data?.country}
              journey={company.data?.journey}
              qualification={company.data?.qualification}
              marker={company.data?.marker}
            >
              {/* Which of the seller's GST branches this deal is invoiced from (task
                  2.8): the guard asks for it whenever the seller has an active
                  registration, and this is the only place it is recorded. */}
              <div className="border-t border-line pt-3">
                <p className="mb-1.5 text-caption text-ink-3">Invoicing branch</p>
                <InvoicingBranchPicker
                  dealId={deal.id}
                  sellerId={deal.company_id}
                  recordedId={deal.seller_gst_registration_id}
                  canEdit={isStaff}
                  closed={isClosed}
                />
              </div>
            </PartyCard>

            <Icon.forward size={20} className="hidden self-center text-ink-3 lg:block" aria-hidden />

            {deal.buyer_company ? (
              <PartyCard
                role="Buyer company"
                companyId={deal.buyer_company.company_id}
                name={deal.buyer_company.name ?? 'Unnamed company'}
                country={deal.buyer_company.country}
              >
                {/* Served masked for a role that may not see them; shown as served. */}
                <dl className="flex flex-wrap gap-x-5 gap-y-1 text-secondary">
                  <div className="flex gap-1.5">
                    <dt className="text-ink-3">PAN</dt>
                    <dd className="data text-ink">{deal.buyer_company.pan ?? '—'}</dd>
                  </div>
                  <div className="flex gap-1.5">
                    <dt className="text-ink-3">CIN</dt>
                    <dd className="data text-ink">{deal.buyer_company.cin ?? '—'}</dd>
                  </div>
                </dl>
                <p className="text-caption text-ink-3">Chosen once — a deal pointed at the wrong buyer is withdrawn and reopened.</p>
              </PartyCard>
            ) : (
              <div
                role="group"
                aria-label="Buyer"
                className="flex min-w-0 flex-col gap-3 rounded-xl border border-dashed border-line-strong p-4"
              >
                <p className="text-caption text-ink-3">Buyer</p>
                {deal.buyer ? (
                  <dl>
                    <DetailRow label="Name">{deal.buyer.name}</DetailRow>
                    <DetailRow label="Country">{deal.buyer.country}</DetailRow>
                    <DetailRow label="Registration number">{deal.buyer.registration_number ?? '—'}</DetailRow>
                    <DetailRow label="Tax identifier">{deal.buyer.tax_id ?? '—'}</DetailRow>
                    <DetailRow label="Contact email">{deal.buyer.contact_email ?? '—'}</DetailRow>
                    <DetailRow label="Contact phone">{deal.buyer.contact_phone ?? '—'}</DetailRow>
                  </dl>
                ) : (
                  <EmptyLine>No buyer recorded yet. A deal cannot be handed over without one.</EmptyLine>
                )}
                {isStaff && !isClosed && (
                  <div className="flex flex-wrap gap-2">
                    {/* Choosing the company is the way in (task 2.4); it is set once,
                        so a second choice is a 409. */}
                    <Button size="sm" variant="primary" onClick={() => setPickingCompany(true)}>
                      Choose buyer company
                    </Button>
                    {/* The legacy `deal_buyer` form: kept while deals written before the
                        buyer migration still have one (it is where such a deal's
                        sanctions and AML are recorded). Retires with P4-10. */}
                    <Button size="sm" variant="quiet" onClick={() => setEditingBuyer(true)}>
                      {deal.buyer ? 'Edit buyer details' : 'Record details instead'}
                    </Button>
                  </div>
                )}
              </div>
            )}
          </div>

          {pickingCompany && (
            <FormPanel title="Choose the buyer" onClose={() => setPickingCompany(false)}>
              <CompanyPicker
                // The seller cannot be its own buyer (`ck_deal_buyer_is_not_the_seller`).
                excludeCompanyId={deal.company_id}
                // R-24: create the buyer as a company outside the pipeline and name it,
                // in one request. A refusal is shown inside the form.
                onCreate={async (draft) => {
                  await setBuyerCompany.mutateAsync({ create: draft });
                  setPickingCompany(false);
                  toast.success('Buyer company created');
                }}
                onSelect={(companyId) => {
                  setBuyerCompany.mutate(
                    { buyer_company_id: companyId },
                    {
                      onSuccess: () => {
                        setPickingCompany(false);
                        toast.success('Buyer company recorded');
                      },
                      onError: (error) =>
                        toast.error(
                          error instanceof Error ? error.message : 'Could not record the buyer company',
                        ),
                    },
                  );
                }}
              />
            </FormPanel>
          )}
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
              revealIdentifiers={canReveal}
              onClose={() => setEditingBuyer(false)}
            />
          )}
        </Panel>

        {/* Checks on a **legacy** buyer row only (task 2.4), demoted under its own
            label: once a buyer company is named its checks live on that company.
            Staff only: DEVELOPER is refused the verification routes (D8). */}
        {isStaff && deal.buyer && !deal.buyer_company && (
          <section aria-label="Legacy buyer record" className="space-y-2">
            <p className="flex items-center gap-2 text-caption text-ink-3">
              <Icon.history size={14} aria-hidden />
              Legacy buyer record — kept until this deal's buyer is a company (P4-10)
            </p>
            <BuyerChecks dealId={deal.id} dealBuyerId={deal.buyer.id} />
          </section>
        )}

        {/* What these two companies have traded before (task 2.11), on a deal with a
            buyer company only: a legacy buyer row has no second company to pair with. */}
        {deal.buyer_company && (
          <Panel
            title="Trade between these two"
            description="What these two companies have invoiced each other before, and how it was settled. Never totalled; each amount stays in its own currency."
            actions={
              // After the handover, staff only: the server refuses an outcome before it
              // (409 DEAL_NOT_HANDED_OVER). DEVELOPER reads and writes nothing.
              isStaff &&
              deal.stage === 'HANDED_OVER' &&
              !recordingOutcome && (
                <Button size="sm" onClick={() => setRecordingOutcome(true)}>
                  Record outcome
                </Button>
              )
            }
          >
            <TradeHistoryPanel sellerId={deal.company_id} buyerId={deal.buyer_company.company_id} dealId={deal.id} />
            {recordingOutcome && (
              <RecordDealOutcomeForm
                dealId={deal.id}
                sellerId={deal.company_id}
                buyerId={deal.buyer_company.company_id}
                onClose={() => setRecordingOutcome(false)}
              />
            )}
          </Panel>
        )}

        {/* What the lending team was given (P2-7), once it exists: a sealed receipt. */}
        {deal.handover_snapshot && <HandoverSnapshot snapshot={deal.handover_snapshot} />}

        <Panel
          title="Paperwork"
          description="Documents for this deal — the ones a handover tells the lending team about. The categories a handover needs are marked."
        >
          {isClosed && (
            <p className="mb-3 text-secondary text-ink-3">
              {deal.stage === 'HANDED_OVER'
                ? 'This deal has been handed over. Its paperwork is what the lending team was given, so nothing more can be added.'
                : 'This deal was withdrawn. Its paperwork is kept as a record and nothing more can be added.'}
            </p>
          )}
          {/* Where the paperwork rule lives, for the one role that can change it. */}
          {canSetRequiredDocuments && !isClosed && (
            <p className="mb-3 text-secondary text-ink-3">
              Which categories a handover needs is set in{' '}
              <Link to={paths.dealRequiredDocuments} className="text-ink underline underline-offset-[3px]">
                Required documents
              </Link>
              .
            </p>
          )}
          <Shelf
            documents={documents.data?.documents ?? []}
            isLoading={documents.isLoading}
            emptyMessage="No documents on this deal yet."
            required={(requiredDocuments.data?.requirements ?? [])
              .filter((rule) => rule.active)
              .map((rule) => ({
                category: rule.category,
                documentType: rule.document_type,
                label: humanize(rule.document_type ?? rule.category),
              }))}
            upload={
              isStaff && !isClosed
                ? {
                    owner: 'DEAL',
                    isUploading: upload.isPending,
                    onUpload: (input) => upload.mutateAsync(input),
                  }
                : undefined
            }
          />
        </Panel>
      </div>

      <aside className="min-w-0 2xl:border-l 2xl:border-line 2xl:pl-8">
        <Panel title="Ledger" description="Every change to this deal, newest first.">
          <DealHistory dealId={deal.id} />
        </Panel>
      </aside>
    </div>
  );
}
