/**
 * A company's default payment term: what a new deal with it starts from. A deal may
 * choose another, with a reason. Only current, offered terms are listed to choose
 * from; a default that has since been retired still shows, marked so.
 */

import { toast } from 'sonner';

import { Panel, Select, Skeleton } from '@/components';

import { usePaymentTerms, useSetDefaultPaymentTerm } from '../hooks';

import { termLabel } from './payment-term-labels';

export interface DefaultPaymentTermSectionProps {
  customerId: string;
  defaultPaymentTermId: string | null | undefined;
  canEdit: boolean;
}

export function DefaultPaymentTermSection({
  customerId,
  defaultPaymentTermId,
  canEdit,
}: DefaultPaymentTermSectionProps) {
  const terms = usePaymentTerms();
  const setDefault = useSetDefaultPaymentTerm(customerId);
  const all = [...(terms.data?.terms ?? []), ...(terms.data?.history ?? [])];
  const current = all.find((term) => term.id === defaultPaymentTermId) ?? null;
  const offered = (terms.data?.terms ?? []).filter((term) => term.active);

  return (
    <Panel title="Payment terms">
      {terms.isLoading ? (
        <Skeleton className="h-9" />
      ) : canEdit ? (
        <label className="block text-caption text-ink-3">
          Default payment term
          <Select
            aria-label="Default payment term"
            className="mt-1"
            value={defaultPaymentTermId ?? ''}
            disabled={setDefault.isPending}
            onChange={(event) =>
              setDefault.mutate(event.target.value || null, {
                onSuccess: () => toast.success('Default payment term changed'),
                onError: (error) =>
                  toast.error(error instanceof Error ? error.message : 'Could not change the default'),
              })
            }
          >
            <option value="">No default</option>
            {current && !offered.some((term) => term.id === current.id) && (
              <option value={current.id}>{termLabel(current)}</option>
            )}
            {offered.map((term) => (
              <option key={term.id} value={term.id}>
                {term.label}
              </option>
            ))}
          </Select>
          <span className="mt-1 block">New deals start from this term.</span>
        </label>
      ) : (
        <p className="text-body text-ink">
          <span className="text-ink-3">Default payment term: </span>
          {termLabel(current)}
        </p>
      )}
    </Panel>
  );
}
