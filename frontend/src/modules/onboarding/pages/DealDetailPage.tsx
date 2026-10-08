/**
 * One deal: its stage, its buyer, its paperwork and its history.
 *
 * **The stage moves this page offers come from the server.** `allowed_stage_moves`
 * is what *this* deal may do next for *this* user (§7.5, deal contract §4.1), so
 * there is no copy of the stage graph in here and an illegal move is not offerable
 * rather than rejected after a click.
 *
 * **A blocked handover is explained, not offered.** When the handover guard is unmet
 * the move is absent from that list and `handover_blocked_reason` says why. Showing
 * the reason beats a button that returns 409.
 */

import { useState, type ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';
import { toast } from 'sonner';

import {
  Button,
  Card,
  ConfirmDialog,
  DetailRow,
  EmptyLine,
  ErrorState,
  Field,
  FormPanel,
  Input,
  Panel,
  RecordHeader,
  SidePanel,
  Skeleton,
  Textarea,
  type RecordAction,
  type RecordField,
} from '@/components';
import { Icon } from '@/design/icons';
import { formatDateTime, humanize } from '@/lib/format';
import { useCan } from '@/platform/access';

import {
  BuyerChecks,
  CompanyPicker,
  DealHistory,
  DealStageChip,
  InvoicingBranchPicker,
  PartyCard,
  HandoverChecklist,
  RecordDealOutcomeForm,
  DocumentsByCategory,
  DealStagePath,
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
        <p className="text-caption text-ink-3">
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
 * What the lending team was given.
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
      className="rounded border border-line bg-surface p-5"
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
      <p className="mt-3 text-caption text-ink-2">
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

/**
 * The deal's stage moves as header actions (frontend-plan §8.6), exactly the server's
 * `allowed_stage_moves`. *Hand over* is the primary action and keeps its confirmation
 * (it is terminal and announces the deal to the lending team); *Withdraw* asks for
 * its reason in a side panel before anything is sent.
 */
function useStageMoves({
  dealId,
  customerId,
  moves,
}: {
  dealId: string;
  customerId?: string;
  moves: { to_stage: DealStage; reason_required: boolean }[];
}): { actions: RecordAction[]; dialogs: ReactNode } {
  const mutation = useTransitionDealStage(dealId, customerId);
  const [pending, setPending] = useState<DealStage | null>(null);
  const [reason, setReason] = useState('');
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

  // Hand over first (the primary action), then the forward moves, then withdraw.
  const order: DealStage[] = ['HANDED_OVER', 'GATHERING_PAPERWORK', 'OPEN', 'WITHDRAWN'];
  const actions: RecordAction[] = [...moves]
    .sort((x, y) => order.indexOf(x.to_stage) - order.indexOf(y.to_stage))
    .map((entry) => ({
      label: STAGE_ACTION_LABEL[entry.to_stage],
      onSelect: () => choose(entry),
      destructive: entry.to_stage === 'WITHDRAWN',
      loading: mutation.isPending && !confirmingHandover && pending === null,
    }));

  const dialogs = (
    <>
      <SidePanel
        open={pending !== null}
        onOpenChange={(open) => {
          if (!open) setPending(null);
        }}
        title="Withdraw deal"
        description="A withdrawn deal stays on record and cannot be reopened."
        submitLabel="Withdraw deal"
        onSubmit={() => {
          if (pending !== null && reason.trim()) void move(pending, reason.trim());
        }}
        pending={mutation.isPending}
        submitDisabled={reason.trim() === ''}
      >
        <label htmlFor="stage-reason" className="block text-caption text-ink-3">
          Why is this deal being withdrawn?
          <Textarea
            id="stage-reason"
            className="mt-1"
            value={reason}
            rows={3}
            required
            onChange={(event) => setReason(event.target.value)}
          />
        </label>
      </SidePanel>
      <ConfirmDialog
        open={confirmingHandover}
        onOpenChange={setConfirmingHandover}
        title="Hand this deal to the lending team?"
        description="This cannot be undone. The deal and its documents are announced to them as they stand now."
        confirmLabel="Hand over"
        onConfirm={() => void move('HANDED_OVER')}
        loading={mutation.isPending}
      />
    </>
  );

  return { actions, dialogs };
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
  // Which paperwork a handover needs, marked on the document list (readable by every reader).
  const requiredDocuments = useDealRequiredDocuments();
  const upload = useUploadDealDocument(dealId ?? '');
  const [editingBuyer, setEditingBuyer] = useState(false);
  const [pickingCompany, setPickingCompany] = useState(false);
  // Task 2.4's write: the same `PUT /deals/{id}/buyer` route, in its company form.
  const setBuyerCompany = useSetDealBuyer(dealId ?? '', deal?.company_id);
  // The payment-outcome write. Separate state because it is a different question from the deal's
  // own: the deal is finished, and this is about what happened to the money.
  const [recordingOutcome, setRecordingOutcome] = useState(false);

  // Header actions: the served stage moves, for staff only. A read-only role is
  // given no moves and no reason, so the record reads as a record.
  const stageMoves = useStageMoves({
    dealId: dealId ?? '',
    customerId: deal?.company_id,
    moves: isStaff ? (deal?.allowed_stage_moves ?? []) : [],
  });

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

  const buyerName = deal.buyer_company?.name ?? deal.buyer?.name ?? null;
  const buyerCountry = deal.buyer_company?.country ?? deal.buyer?.country ?? null;
  const fields: RecordField[] = [
    { label: 'Stage', value: <DealStageChip stage={deal.stage} /> },
    { label: 'Opened', value: formatDateTime(deal.created_at) },
  ];
  if (deal.handed_over_at) fields.push({ label: 'Handed over', value: formatDateTime(deal.handed_over_at) });
  if (deal.withdrawal_reason) fields.push({ label: 'Withdrawn because', value: deal.withdrawal_reason });

  return (
    <div>
      <RecordHeader
        breadcrumbs={[
          { label: 'Companies', to: paths.companies },
          ...(companyName ? [{ label: companyName, to: paths.company(deal.company_id, 'deals') }] : []),
          { label: deal.reference ?? 'Deal' },
        ]}
        objectType="Deal"
        title={deal.reference ?? 'Deal'}
        meta={
          <>
            {companyName ?? 'The seller'} → {buyerName ? `${buyerName}${buyerCountry ? ` (${buyerCountry})` : ''}` : 'no buyer yet'}
          </>
        }
        fields={fields}
        actions={stageMoves.actions}
        path={
          <DealStagePath stage={deal.stage} />
        }
      />
      {stageMoves.dialogs}

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_22.5rem]">
        <div className="flex min-w-0 flex-col gap-4">
          {/* The guard's verdict (frontend-plan §6.11): the server's sentence verbatim,
              a checklist once structured conditions are served. Staff only: Developer
              is sent no reason. */}
          {isStaff && deal.handover_blocked_reason && (
            <Card as="h2" title="Handover readiness">
              <HandoverChecklist blockedReason={deal.handover_blocked_reason} />
            </Card>
          )}

          {/* The two parties, side by side — a problem stays with the party it belongs
              to (architecture). The guard reads the seller's background check and the
              buyer's sanctions and AML, and each card shows its own. */}
          <section aria-label="Parties">
            <div className="grid gap-4 lg:grid-cols-2 lg:items-start">
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
                  className="flex min-w-0 flex-col gap-3 rounded border border-line bg-surface p-4"
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
                      {/* Choosing the company is the way in; it is set once,
                          so a second choice is a 409. */}
                      <Button size="sm" variant="primary" onClick={() => setPickingCompany(true)}>
                        Choose buyer company
                      </Button>
                      {/* The legacy `deal_buyer` form: kept while deals written before the
                          buyer migration still have one (it is where such a deal's
                          sanctions and AML are recorded). Retires with the legacy buyer. */}
                      <Button size="sm" variant="subtle" onClick={() => setEditingBuyer(true)}>
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
                  // Create the buyer as a company outside the pipeline and name it,
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
          </section>

          {/* Checks on a **legacy** buyer row only, demoted under its own
              label: once a buyer company is named its checks live on that company.
              Staff only: DEVELOPER is refused the verification routes. */}
          {isStaff && deal.buyer && !deal.buyer_company && (
            <section aria-label="Legacy buyer record" className="space-y-2">
              <p className="flex items-center gap-2 text-caption text-ink-3">
                <Icon.history size={14} aria-hidden />
                Legacy buyer record — kept until this deal's buyer is a company
              </p>
              <BuyerChecks dealId={deal.id} dealBuyerId={deal.buyer.id} />
            </section>
          )}

          {/* What these two companies have traded before, on a deal with a
              buyer company only: a legacy buyer row has no second company to pair with. */}
          {deal.buyer_company && (
            <Panel
              title="Trade between these two"
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

          {/* What the lending team was given, once it exists: a sealed receipt. */}
          {deal.handover_snapshot && <HandoverSnapshot snapshot={deal.handover_snapshot} />}

          <Panel title="Paperwork">
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
                <Link to={paths.dealRequiredDocuments} className="font-semibold text-accent underline-offset-2 hover:underline">
                  Required documents
                </Link>
                .
              </p>
            )}
            <DocumentsByCategory
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

        <aside aria-label="History" className="min-w-0">
          <Panel title="History">
            <DealHistory dealId={deal.id} compact />
          </Panel>
        </aside>
      </div>
    </div>
  );
}
