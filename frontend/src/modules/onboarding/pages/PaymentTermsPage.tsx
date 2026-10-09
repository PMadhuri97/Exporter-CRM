/**
 * Settings → Payment terms: the list deals and company defaults choose from.
 *
 * Each term is a code with a label, a kind (advance, LC at sight, LC usance,
 * documents against payment or acceptance, open account) and, for the kinds that run
 * for a time, a number of days. **Editing writes a new version**: a deal agreed on the
 * old wording keeps it. **Retiring** a term stops offering it; old deals still show it.
 * Only a reader who may manage settings is offered the controls (`can_edit`).
 */

import { useState } from 'react';
import { toast } from 'sonner';

import {
  Badge,
  Button,
  Card,
  ErrorState,
  Field,
  FormPanel,
  Input,
  PageHeader,
  RequiredNote,
  Select,
  Skeleton,
} from '@/components';
import { Icon } from '@/design/icons';

import { PAYMENT_KIND_LABEL, PAYMENT_KINDS_WITH_DAYS } from '../components/payment-term-labels';
import { useAddPaymentTerm, usePaymentTerms, useRevisePaymentTerm } from '../hooks';
import type { PaymentTerm } from '../types';

const KINDS = Object.keys(PAYMENT_KIND_LABEL);

function TermForm({ editing, onDone }: { editing?: PaymentTerm; onDone: () => void }) {
  const add = useAddPaymentTerm();
  const revise = useRevisePaymentTerm();
  const [code, setCode] = useState(editing?.code ?? '');
  const [label, setLabel] = useState(editing?.label ?? '');
  const [kind, setKind] = useState(editing?.kind ?? 'ADVANCE');
  const [days, setDays] = useState(editing?.days ? String(editing.days) : '');
  const needsDays = PAYMENT_KINDS_WITH_DAYS.has(kind);
  const ready = label.trim() && code.trim() && (!needsDays || Number(days) > 0);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!ready) return;
    const dayCount = needsDays ? Number(days) : null;
    try {
      if (editing) {
        await revise.mutateAsync({
          code: editing.code,
          body: { label: label.trim(), kind, days: dayCount },
        });
        toast.success('Payment term changed — deals keep the wording they were agreed on');
      } else {
        await add.mutateAsync({ code: code.trim().toUpperCase(), label: label.trim(), kind, days: dayCount });
        toast.success('Payment term added');
      }
      onDone();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not save the term');
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <RequiredNote />
      <Field label="Code" htmlFor="term-code" required hint="Letters, digits and _; it never changes.">
        <Input id="term-code" value={code} disabled={Boolean(editing)} onChange={(e) => setCode(e.target.value)} />
      </Field>
      <Field label="Label" htmlFor="term-label" required>
        <Input id="term-label" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. DA 90 days" />
      </Field>
      <Field label="Kind" htmlFor="term-kind" required>
        <Select id="term-kind" value={kind} onChange={(e) => setKind(e.target.value)}>
          {KINDS.map((value) => (
            <option key={value} value={value}>
              {PAYMENT_KIND_LABEL[value]}
            </option>
          ))}
        </Select>
      </Field>
      {needsDays && (
        <Field label="Days" htmlFor="term-days" required>
          <Input id="term-days" type="number" min={1} value={days} onChange={(e) => setDays(e.target.value)} />
        </Field>
      )}
      <div className="flex justify-end gap-2 border-t border-line pt-4">
        <Button onClick={onDone}>Cancel</Button>
        <Button type="submit" variant="primary" disabled={!ready} loading={add.isPending || revise.isPending}>
          Save term
        </Button>
      </div>
    </form>
  );
}

export function PaymentTermsPage() {
  const query = usePaymentTerms();
  const revise = useRevisePaymentTerm();
  const [form, setForm] = useState<{ editing?: PaymentTerm } | null>(null);
  const terms = query.data?.terms ?? [];
  const canEdit = query.data?.can_edit ?? false;

  async function setActive(term: PaymentTerm, active: boolean) {
    try {
      await revise.mutateAsync({ code: term.code, body: { active } });
      toast.success(active ? 'Payment term offered again' : 'Payment term retired');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not change the term');
    }
  }

  return (
    <div className="max-w-reading">
      <PageHeader
        as="h2"
        title="Payment terms"
        actions={
          canEdit && (
            <Button variant="primary" onClick={() => setForm({})}>
              <Icon.add size={15} aria-hidden />
              Add a term
            </Button>
          )
        }
      />
      {form && (
        <FormPanel title={form.editing ? `Change ${form.editing.label}` : 'Add a payment term'} onClose={() => setForm(null)}>
          <TermForm editing={form.editing} onDone={() => setForm(null)} />
        </FormPanel>
      )}
      {query.isError ? (
        <ErrorState title="Couldn't load the payment terms." onRetry={() => void query.refetch()} />
      ) : query.isLoading ? (
        <div className="space-y-2" aria-hidden>
          <Skeleton className="h-12" />
          <Skeleton className="h-12" />
        </div>
      ) : (
        <Card title="Terms" as="h3" flush>
          <ul className="divide-y divide-line">
            {terms.map((term) => (
              <li key={term.id} data-testid="payment-term-row" className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                <div className="min-w-0">
                  <p className="flex flex-wrap items-center gap-2">
                    <span className={term.active ? 'font-medium text-ink' : 'font-medium text-ink-3'}>{term.label}</span>
                    {!term.active && <Badge tone="neutral">Retired</Badge>}
                  </p>
                  <p className="text-caption text-ink-3">
                    {PAYMENT_KIND_LABEL[term.kind] ?? term.kind}
                    {term.days ? ` · ${term.days} days` : ''} · {term.code} · version {term.version}
                  </p>
                </div>
                {canEdit && (
                  <div className="flex gap-2">
                    {term.active && (
                      <Button size="sm" variant="subtle" onClick={() => setForm({ editing: term })}>
                        <Icon.edit size={14} /> Change
                      </Button>
                    )}
                    <Button size="sm" variant="subtle" disabled={revise.isPending} onClick={() => void setActive(term, !term.active)}>
                      {term.active ? 'Retire' : 'Offer again'}
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
