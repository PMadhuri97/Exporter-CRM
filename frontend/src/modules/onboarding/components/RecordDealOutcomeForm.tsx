/**
 * Record how a handed-over deal was paid.
 *
 * The one write trade history needs on the deal page, and the reason the panel beside
 * it is not read-only. `POST /deals/{id}/payment-outcome` does three things in one
 * request — find or create the relationship, create the deal's invoice if it has none,
 * append the outcome — so this form asks for the invoice only when the deal has none.
 *
 * What the shape of the form is saying:
 *
 * - **The four invoice fields are all-or-nothing**, which the server also enforces: an
 *   invoice with a number but no amount is not an invoice. Once one exists they are
 *   gone from the form, because its identity is frozen and sending them again is
 *   refused (422 `TRADE_INVOICE_ALREADY_RECORDED`) rather than treated as an edit.
 * - **A correction is a new outcome**, not an edit. When the invoice already carries
 *   one, this form sends `supersedes_outcome_id` for it — the current head, which is
 *   the only thing the server accepts — and the old outcome stays visible, marked
 *   superseded. Nothing here can change what was recorded before.
 * - **`UNKNOWN` is offered as an answer**, deliberately. A relationship manager may
 *   know an invoice exists without knowing whether it was paid, and recording that is
 *   more useful than recording nothing.
 * - **`PROVEN` needs something to rest on.** Checked here to save a round trip; the
 *   server checks it too and its wording is what is shown.
 * - **`amount_paid` is a string**, as the amount is: money is `Numeric` server-side and
 *   a parsed number would round it. Nothing here does arithmetic on it.
 *
 * It is not a deal stage and says so on screen: the deal is closed and stays closed.
 */

import { useState } from 'react';
import { toast } from 'sonner';

import { Skeleton } from '@/components';
import { ApiError } from '@/lib/api/errors';

import {
  useRecordDealPaymentOutcome,
  useTradeRelationship,
  useTradeRelationshipForPair,
} from '../hooks';
import type { TradePaymentStatus, TradeProofStatus } from '../types';

const FIELD =
  'mt-1 w-full rounded-md border border-line bg-surface px-2 py-1.5 text-caption text-ink outline-none focus:border-accent disabled:opacity-60';
const SECONDARY_BUTTON =
  'rounded-lg border border-line px-2.5 py-1.5 text-caption font-medium text-ink-2 hover:bg-paper disabled:opacity-50';
const PRIMARY_BUTTON =
  'rounded-md bg-accent-solid px-2.5 py-1.5 text-caption font-medium text-white disabled:opacity-50';

const PAYMENT_STATUSES: { value: TradePaymentStatus; label: string }[] = [
  { value: 'PAID', label: 'Paid' },
  { value: 'PARTIAL', label: 'Part paid' },
  { value: 'UNPAID', label: 'Unpaid' },
  { value: 'DISPUTED', label: 'Disputed' },
  // Last, and worded as an answer rather than a gap.
  { value: 'UNKNOWN', label: 'Not known' },
];

const PROOF_STATUSES: { value: TradeProofStatus; label: string }[] = [
  { value: 'CLAIMED', label: 'Claimed — nobody has shown proof yet' },
  { value: 'PROVEN', label: 'Proven — we have seen evidence' },
];

export interface RecordDealOutcomeFormProps {
  dealId: string;
  /** The deal's own company. */
  sellerId: string;
  /** The deal's buyer **company** — this form is not offered for a legacy buyer row. */
  buyerId: string;
  onClose: () => void;
}

export function RecordDealOutcomeForm({
  dealId,
  sellerId,
  buyerId,
  onClose,
}: RecordDealOutcomeFormProps) {
  const mutation = useRecordDealPaymentOutcome(dealId);
  // Whether to ask for the invoice is a question about what the deal already has, so
  // it is read rather than guessed: the pair's relationship, then this deal's invoice
  // within it. Both are cache hits — the panel beside this form just asked for them.
  const pair = useTradeRelationshipForPair(sellerId, buyerId);
  const detail = useTradeRelationship(pair.data?.id);
  const invoice = (detail.data?.invoices ?? []).find((row) => row.deal_id === dealId);
  const head = invoice?.current_outcome ?? null;

  const [paymentStatus, setPaymentStatus] = useState<TradePaymentStatus | ''>('');
  const [proofStatus, setProofStatus] = useState<TradeProofStatus>('CLAIMED');
  const [amountPaid, setAmountPaid] = useState('');
  const [note, setNote] = useState('');
  const [invoiceNumber, setInvoiceNumber] = useState('');
  const [invoiceDate, setInvoiceDate] = useState('');
  const [amount, setAmount] = useState('');
  const [currency, setCurrency] = useState('USD');
  const [error, setError] = useState<string | null>(null);

  // Whether the deal has an invoice is **not known** until both reads have landed, and
  // a form that guessed would flicker: the first version computed this from
  // `!detail.isLoading`, so the invoice fields appeared, vanished while the second
  // request was in flight, and came back. Nothing is rendered until the answer is
  // settled, and then it does not change.
  const deciding = pair.isLoading || (Boolean(pair.data) && !detail.isSuccess && !detail.isError);
  const needsInvoice = invoice === undefined;

  async function submit() {
    setError(null);
    if (!paymentStatus) {
      setError('Choose what happened to the invoice.');
      return;
    }
    const trimmedNote = note.trim();
    if (proofStatus === 'PROVEN' && !trimmedNote) {
      setError('A proven outcome needs a note saying what was seen.');
      return;
    }
    if (needsInvoice) {
      // All four or none, which is what the server accepts.
      const given = [invoiceNumber.trim(), invoiceDate, amount.trim(), currency.trim()];
      if (given.some((value) => !value)) {
        setError('This deal has no invoice yet, so give its number, date, amount and currency.');
        return;
      }
    }
    try {
      await mutation.mutateAsync({
        payment_status: paymentStatus,
        proof_status: proofStatus,
        amount_paid: amountPaid.trim() || null,
        evidence_note: trimmedNote || null,
        // A correction names the outcome it replaces. The server refuses anything but
        // the current head, so sending the head is the only correct thing to send.
        supersedes_outcome_id: head?.id ?? null,
        ...(needsInvoice
          ? {
              invoice_number: invoiceNumber.trim(),
              invoice_date: invoiceDate,
              amount: amount.trim(),
              currency: currency.trim().toUpperCase(),
            }
          : {}),
      });
      toast.success(head ? 'Outcome corrected' : 'Outcome recorded');
      onClose();
    } catch (caught) {
      // The server's words: 409 if the deal is not handed over or its buyer is not a
      // company, 422 if the invoice details clash with one already recorded.
      setError(caught instanceof ApiError ? caught.message : 'Could not record the outcome.');
    }
  }

  if (deciding) {
    return (
      <div
        data-testid="record-deal-outcome-form"
        className="mt-4 rounded-lg border border-line p-4 text-caption"
      >
        <Skeleton className="h-24 rounded" />
      </div>
    );
  }

  return (
    <div
      data-testid="record-deal-outcome-form"
      className="mt-4 rounded-lg border border-line p-4 text-caption"
    >
      <p className="font-medium text-ink">
        {head ? 'Correct the outcome' : 'Record how this was paid'}
      </p>
      <p className="mt-0.5 text-ink-3">
        {head
          ? 'The outcome recorded now replaces the current one, which stays visible as superseded.'
          : 'A fact about the trade, not a change to the deal — the deal stays handed over.'}
      </p>

      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <label className="block text-ink-3">
          What happened
          <select
            aria-label="What happened"
            className={FIELD}
            value={paymentStatus}
            disabled={mutation.isPending}
            onChange={(event) => setPaymentStatus(event.target.value as TradePaymentStatus | '')}
          >
            <option value="">Choose…</option>
            {PAYMENT_STATUSES.map(({ value, label }) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-ink-3">
          Proof
          <select
            aria-label="Proof"
            className={FIELD}
            value={proofStatus}
            disabled={mutation.isPending}
            onChange={(event) => setProofStatus(event.target.value as TradeProofStatus)}
          >
            {PROOF_STATUSES.map(({ value, label }) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-ink-3">
          Amount paid
          <input
            aria-label="Amount paid"
            className={FIELD}
            value={amountPaid}
            placeholder="e.g. 12400.00"
            disabled={mutation.isPending}
            onChange={(event) => setAmountPaid(event.target.value)}
          />
        </label>
      </div>

      {needsInvoice && (
        <fieldset className="mt-3 rounded-md border border-line p-3">
          <legend className="px-1 text-ink-3">
            This deal has no invoice yet — record it
          </legend>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block text-ink-3">
              Invoice number
              <input
                aria-label="Invoice number"
                className={FIELD}
                value={invoiceNumber}
                disabled={mutation.isPending}
                onChange={(event) => setInvoiceNumber(event.target.value)}
              />
            </label>
            <label className="block text-ink-3">
              Invoice date
              <input
                aria-label="Invoice date"
                type="date"
                className={FIELD}
                value={invoiceDate}
                disabled={mutation.isPending}
                onChange={(event) => setInvoiceDate(event.target.value)}
              />
            </label>
            <label className="block text-ink-3">
              Amount
              <input
                aria-label="Amount"
                className={FIELD}
                value={amount}
                placeholder="e.g. 18400.00"
                disabled={mutation.isPending}
                onChange={(event) => setAmount(event.target.value)}
              />
            </label>
            <label className="block text-ink-3">
              Currency
              <input
                aria-label="Currency"
                className={FIELD}
                value={currency}
                maxLength={3}
                disabled={mutation.isPending}
                onChange={(event) => setCurrency(event.target.value)}
              />
            </label>
          </div>
          <p className="mt-2 text-ink-3">
            {/* Said here because the record cannot be edited afterwards. */}
            An invoice's number, date, amount and currency are frozen once recorded. A
            mistake is corrected by recording the right invoice, not by changing this one.
          </p>
        </fieldset>
      )}

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
          {head ? 'Record correction' : 'Record outcome'}
        </button>
      </div>
    </div>
  );
}
