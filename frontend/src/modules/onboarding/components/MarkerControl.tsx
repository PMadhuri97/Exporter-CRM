/**
 * Pause, end or resume a relationship — **owner: Developer 2** (L2-08).
 *
 * Shows exactly the moves the server listed for this user and this company
 * (`allowed_marker_moves`) and asks for a reason exactly where the server says
 * one is required. There is no copy of the marker rules here: a role that may
 * not set markers gets no moves and sees nothing, and anything the server
 * refuses is shown as it said it.
 */

import { useState } from 'react';
import { toast } from 'sonner';

import { MARKER_ACTION_LABEL } from '../constants';
import { useSetExporterMarker } from '../hooks';
import type { ExporterMarker, MarkerMove } from '../types';

interface MarkerControlProps {
  customerId: string;
  moves: MarkerMove[];
}

export function MarkerControl({ customerId, moves }: MarkerControlProps) {
  const mutation = useSetExporterMarker(customerId);
  const [pending, setPending] = useState<MarkerMove | null>(null);
  const [reason, setReason] = useState('');

  if (moves.length === 0) return null;

  const submit = (to: ExporterMarker, withReason: string | null) => {
    mutation.mutate(
      { marker: to, reason: withReason },
      {
        onSuccess: () => {
          toast.success(`${MARKER_ACTION_LABEL[to]}: done`);
          setPending(null);
          setReason('');
        },
        onError: (error) => toast.error(error.message),
      },
    );
  };

  if (pending) {
    return (
      <form
        className="flex w-full max-w-md flex-col gap-2 rounded-lg border border-border bg-surface p-3 shadow-card"
        onSubmit={(e) => {
          e.preventDefault();
          submit(pending.to, reason.trim() || null);
        }}
      >
        <label className="text-sm font-medium text-ink" htmlFor="marker-reason">
          {MARKER_ACTION_LABEL[pending.to]} — reason
          {pending.reason_required ? '' : ' (optional)'}
        </label>
        <textarea
          id="marker-reason"
          className="input min-h-[4rem]"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          required={pending.reason_required}
        />
        <div className="flex justify-end gap-2">
          <button
            type="button"
            className="rounded-lg px-3 py-1.5 text-sm text-ink-muted hover:bg-surface-sunken"
            onClick={() => {
              setPending(null);
              setReason('');
            }}
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={mutation.isPending}
            className="rounded-lg bg-ink px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          >
            Confirm
          </button>
        </div>
      </form>
    );
  }

  return (
    <div className="flex flex-wrap gap-2">
      {moves.map((move) => (
        <button
          key={move.to}
          type="button"
          onClick={() => setPending(move)}
          className="rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-ink hover:bg-surface-subtle"
        >
          {MARKER_ACTION_LABEL[move.to]}
        </button>
      ))}
    </div>
  );
}
