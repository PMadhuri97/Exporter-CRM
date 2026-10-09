/**
 * Pause, end or resume a relationship.
 *
 * Shows exactly the moves the server listed for this user and this company
 * (`allowed_marker_moves`) and asks for a reason exactly where the server says
 * one is required. There is no copy of the marker rules here: a role that may
 * not set markers gets no moves and sees nothing, and anything the server
 * refuses is shown as it said it.
 *
 * The buttons sit in the company page's header, so the reason is asked for in
 * a dialog rather than a form that would push the header open.
 */

import { useState } from 'react';
import { toast } from 'sonner';

import { Button, Dialog, RequiredMark, Textarea } from '@/components';

import { MARKER_ACTION_LABEL } from '../constants';
import { useSetExporterMarker } from '../hooks';
import type { MarkerMove } from '../types';

interface MarkerControlProps {
  customerId: string;
  moves: MarkerMove[];
}

const CONSEQUENCE: Record<MarkerMove['to'], string> = {
  NONE: 'The relationship goes back to normal working lists.',
  PAUSED: 'The company stays in lists, badged as paused. Reversible.',
  ENDED: 'The company leaves default working lists but stays searchable. Reversible.',
};

export function MarkerControl({ customerId, moves }: MarkerControlProps) {
  const mutation = useSetExporterMarker(customerId);
  const [pending, setPending] = useState<MarkerMove | null>(null);
  const [reason, setReason] = useState('');

  if (moves.length === 0) return null;

  const close = () => {
    setPending(null);
    setReason('');
  };

  const submit = () => {
    if (!pending) return;
    mutation.mutate(
      { marker: pending.to, reason: reason.trim() || null },
      {
        onSuccess: () => {
          toast.success(`${MARKER_ACTION_LABEL[pending.to]}: done`);
          close();
        },
        onError: (error) => toast.error(error.message),
      },
    );
  };

  return (
    <>
      <div className="flex flex-wrap gap-2">
        {moves.map((move) => (
          <Button
            key={move.to}
            size="sm"
            variant={move.to === 'ENDED' ? 'subtle' : 'secondary'}
            onClick={() => setPending(move)}
          >
            {MARKER_ACTION_LABEL[move.to]}
          </Button>
        ))}
      </div>

      <Dialog
        open={pending !== null}
        onOpenChange={(open) => {
          if (!open) close();
        }}
        title={pending ? MARKER_ACTION_LABEL[pending.to] : ''}
        description={pending ? CONSEQUENCE[pending.to] : undefined}
      >
        {pending && (
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              submit();
            }}
          >
            <label className="block text-body font-medium text-ink" htmlFor="marker-reason">
              Reason
              {pending.reason_required && <RequiredMark />}
            </label>
            <Textarea
              id="marker-reason"
              className="-mt-2 min-h-[5rem]"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              required={pending.reason_required}
            />
            <div className="flex justify-end gap-2">
              <Button variant="subtle" onClick={close}>
                Cancel
              </Button>
              <Button
                type="submit"
                variant={pending.to === 'ENDED' ? 'destructive' : 'primary'}
                loading={mutation.isPending}
              >
                Confirm
              </Button>
            </div>
          </form>
        )}
      </Dialog>
    </>
  );
}
