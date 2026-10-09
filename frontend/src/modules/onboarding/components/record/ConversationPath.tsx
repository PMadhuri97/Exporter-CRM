/**
 * The conversation path (frontend-plan §6.5), as in Salesforce Path:
 *
 *   [ Not contacted > Reaching out > Spoke to them > Interested > Ready now ]   [Not now]
 *
 * Every step is drawn; **only the steps the server listed in `allowed_moves` are
 * clickable** — the rest are inert, and with no moves the path is a picture of where
 * the conversation stands. Clicking a step selects it and offers *Mark as current*,
 * which asks exactly what the server says that move needs: a check-back date where
 * `check_back_required`, a reason where `reason_required` (optional otherwise).
 * *Not now* branches off — a pause, not a stage — so it is a button beside the path,
 * offered only when served. The path moves when the server answers, not before; a
 * refusal is shown in the server's words.
 *
 * Still no copy of the conversation rules: the order of the steps is the drawing,
 * not a transition table.
 */

import { useState } from 'react';
import { toast } from 'sonner';

import {
  Button,
  Input,
  Path,
  Popover,
  PopoverContent,
  PopoverTrigger,
  RequiredMark,
  Textarea,
} from '@/components';

import { useSetExporterConversation } from '../../hooks';
import type { ConversationMove, ExporterConversation } from '../../types';
import { ConversationBadge } from '../StatusBadge';

import { CONVERSATION_STATUS, CONVERSATION_TRACK } from './status';

/** Today in the browser's timezone, as the `YYYY-MM-DD` a date input takes. */
function localToday(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${now.getFullYear()}-${month}-${day}`;
}

function MoveForm({
  customerId,
  move,
  close,
}: {
  customerId: string;
  move: ConversationMove;
  close: () => void;
}) {
  const mutation = useSetExporterConversation(customerId);
  const [reason, setReason] = useState('');
  const [checkBackOn, setCheckBackOn] = useState('');
  const label = CONVERSATION_STATUS[move.to].label;

  return (
    <form
      className="space-y-3"
      onSubmit={(event) => {
        event.preventDefault();
        mutation.mutate(
          {
            conversation: move.to,
            reason: reason.trim() || null,
            // Sent only where the server asks for it: anywhere else it is refused.
            check_back_on: move.check_back_required ? checkBackOn || null : null,
          },
          {
            onSuccess: () => {
              toast.success(`Communication: ${label}`);
              close();
            },
            onError: (error) => toast.error(error.message),
          },
        );
      }}
    >
      <p className="text-body font-semibold text-ink">Move to {label}</p>
      {move.check_back_required && (
        <label className="block text-caption font-medium text-ink-2" htmlFor="conversation-check-back">
          Check back on
          <Input
            id="conversation-check-back"
            type="date"
            className="mt-1"
            value={checkBackOn}
            onChange={(event) => setCheckBackOn(event.target.value)}
            // Only stops the picker offering a past day; the server still decides.
            min={localToday()}
            required
          />
        </label>
      )}
      <label className="block text-caption font-medium text-ink-2" htmlFor="conversation-reason">
        Reason
        {move.reason_required && <RequiredMark />}
        <Textarea
          id="conversation-reason"
          className="mt-1 min-h-[4rem]"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          required={move.reason_required}
        />
      </label>
      <div className="flex justify-end gap-2">
        <Button size="sm" onClick={close}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" size="sm" loading={mutation.isPending}>
          Confirm
        </Button>
      </div>
    </form>
  );
}

const STEPS = CONVERSATION_TRACK.map((key) => ({ key, label: CONVERSATION_STATUS[key].label }));

/** A button that opens the move's form in a popover. */
function MoveButton({
  customerId,
  move,
  label,
  variant,
  onDone,
}: {
  customerId: string;
  move: ConversationMove;
  label: string;
  variant: 'primary' | 'secondary';
  onDone?: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button size="sm" variant={variant}>
          {label}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80">
        <MoveForm
          customerId={customerId}
          move={move}
          close={() => {
            setOpen(false);
            onDone?.();
          }}
        />
      </PopoverContent>
    </Popover>
  );
}

export function ConversationPath({
  customerId,
  value,
  checkBackOn,
  moves,
}: {
  customerId: string;
  value: ExporterConversation;
  checkBackOn?: string | null;
  /** Exactly what the server served. Empty: nothing on the path is a button. */
  moves: ConversationMove[];
}) {
  const [selected, setSelected] = useState<ExporterConversation | null>(null);
  const onPath = moves.filter((move) => move.to !== 'NOT_NOW').map((move) => move.to);
  const chosen = moves.find((move) => move.to === selected);
  const notNow = moves.find((move) => move.to === 'NOT_NOW');

  return (
    <div className="space-y-2" data-testid="conversation-path">
      <div className="flex flex-wrap items-center gap-3">
        <Path
          label="Communication"
          steps={STEPS}
          current={value === 'NOT_NOW' ? null : value}
          selectable={onPath}
          selected={selected}
          onSelect={(key) => setSelected((previous) => (previous === key ? null : key))}
          className="w-full flex-1 lg:w-auto lg:min-w-[28rem]"
        />
        {notNow && (
          <MoveButton customerId={customerId} move={notNow} label="Not now" variant="secondary" />
        )}
      </div>
      {(value === 'NOT_NOW' || chosen) && (
        <div className="flex flex-wrap items-center gap-2">
          {value === 'NOT_NOW' && <ConversationBadge value="NOT_NOW" checkBackOn={checkBackOn} />}
          {chosen && (
            <>
              <MoveButton
                customerId={customerId}
                move={chosen}
                label="Mark as current"
                variant="primary"
                onDone={() => setSelected(null)}
              />
              <span className="text-secondary text-ink-3">{CONVERSATION_STATUS[chosen.to].label} is selected.</span>
            </>
          )}
        </div>
      )}
    </div>
  );
}
