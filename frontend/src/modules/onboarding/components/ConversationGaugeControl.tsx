/**
 * Move the conversation gauge — **owner: Developer 3A** (L3-03, L3-04a).
 *
 * Shows exactly the moves the server listed for this user and this company
 * (`allowed_moves`), and asks for a reason and a check-back date exactly where the
 * server says each is required. **There is no copy of the conversation rules
 * here**: no value list, no transition table, no "NOT_NOW needs a date" — a role
 * that may not move the gauge gets no moves and sees no buttons, and anything the
 * server refuses is shown as the server worded it.
 *
 * That is architecture §7.5 taken literally: the frontend fetches the allowed
 * moves rather than keeping a hand-copied table. The same shape as
 * `MarkerControl.tsx`, which does it for the marker.
 *
 * Labels come from `humanize()` rather than a label map, for the same reason: a map
 * is a copy of the value list, and it would have to be edited in lockstep with the
 * enum. `NOT_CONTACTED` reads as "Not contacted", which is what it should say.
 */

import { CalendarClock } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { Button, Input, Textarea } from '@/components';
import { humanize } from '@/lib/format';

import { useSetExporterConversation } from '../hooks';
import type { ConversationMove } from '../types';

/** Today in the browser's timezone, as the `YYYY-MM-DD` a date input takes. */
function localToday(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${now.getFullYear()}-${month}-${day}`;
}

interface ConversationGaugeControlProps {
  customerId: string;
  /** Exactly what the server served. Empty means "no moves for you" — this
   * component never works out why, and never fills the gap itself. */
  moves: ConversationMove[];
}

export function ConversationGaugeControl({
  customerId,
  moves,
}: ConversationGaugeControlProps) {
  const mutation = useSetExporterConversation(customerId);
  const [pending, setPending] = useState<ConversationMove | null>(null);
  const [reason, setReason] = useState('');
  const [checkBackOn, setCheckBackOn] = useState('');

  if (moves.length === 0) return null;

  const reset = () => {
    setPending(null);
    setReason('');
    setCheckBackOn('');
  };

  if (pending) {
    // A move that needs nothing still goes through this step. Confirming is
    // cheap, and a one-click gauge change that lands in the permanent history
    // log is not what an operator wants from a mis-click.
    const submit = (event: React.FormEvent) => {
      event.preventDefault();
      mutation.mutate(
        {
          conversation: pending.to,
          reason: reason.trim() || null,
          // Sent only where the server asks for it. Sending it anywhere else is
          // refused (not ignored), which is the server's rule and not this
          // component's to soften.
          check_back_on: pending.check_back_required ? checkBackOn || null : null,
        },
        {
          onSuccess: () => {
            toast.success(`Conversation: ${humanize(pending.to)}`);
            reset();
          },
          onError: (error) => toast.error(error.message),
        },
      );
    };

    return (
      <form
        onSubmit={submit}
        className="flex w-full max-w-md flex-col gap-2 rounded-lg border border-border bg-surface p-3 shadow-card"
        data-extension="conversation-move-form"
      >
        <p className="text-sm font-medium text-ink">Move to {humanize(pending.to)}</p>

        {pending.check_back_required && (
          <label className="text-xs font-medium text-ink-muted" htmlFor="conversation-check-back">
            Check back on
            <Input
              id="conversation-check-back"
              type="date"
              className="mt-1"
              value={checkBackOn}
              onChange={(event) => setCheckBackOn(event.target.value)}
              // Only stops the picker offering a past day; the server still decides
              // (it judges "today" in UTC) and its refusal is shown as worded.
              min={localToday()}
              required
            />
          </label>
        )}

        <label className="text-xs font-medium text-ink-muted" htmlFor="conversation-reason">
          Reason{pending.reason_required ? '' : ' (optional)'}
          <Textarea
            id="conversation-reason"
            className="mt-1 min-h-[4rem]"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            required={pending.reason_required}
          />
        </label>

        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={reset}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" size="sm" loading={mutation.isPending}>
            Confirm
          </Button>
        </div>
      </form>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2" data-extension="conversation-moves">
      <span className="mr-1 text-sm text-ink-muted">Move to:</span>
      {moves.map((move) => (
        <Button key={move.to} size="sm" onClick={() => setPending(move)}>
          {humanize(move.to)}
          {move.check_back_required && <CalendarClock size={13} className="text-ink-faint" />}
        </Button>
      ))}
    </div>
  );
}
